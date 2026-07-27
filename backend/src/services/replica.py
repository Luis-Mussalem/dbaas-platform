import asyncio
import logging
import uuid
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from src.core.encryption import decrypt_value, encrypt_value
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.replica import Replica, ReplicationState
from src.models.user import User
from src.services.provisioning import get_provisioner
from src.services.status_history import record_status_change

logger = logging.getLogger(__name__)


def _attach_replica_instance(db: Session, replica: Replica) -> Replica:
    """
    Attaches the standby DatabaseInstance to the Replica object (transient attribute).

    Replica has no relationship with the instance (plain UUID columns, same
    pattern as Backup); ReplicaRead reads `replica_instance` via from_attributes.
    """
    replica.replica_instance = (
        db.query(DatabaseInstance)
        .filter(DatabaseInstance.id == replica.replica_instance_id)
        .first()
    )
    return replica


def list_replicas(db: Session, primary_instance_id: uuid.UUID) -> list[Replica]:
    replicas = (
        db.query(Replica)
        .filter(Replica.primary_instance_id == primary_instance_id)
        .order_by(Replica.created_at.desc())
        .all()
    )
    for replica in replicas:
        _attach_replica_instance(db, replica)
    return replicas


def get_replica(db: Session, replica_id: uuid.UUID) -> Replica | None:
    replica = db.query(Replica).filter(Replica.id == replica_id).first()
    if replica:
        _attach_replica_instance(db, replica)
    return replica


async def create_replica(
    db: Session, primary: DatabaseInstance, current_user: User
) -> Replica:
    """
    Creates a streaming standby from a RUNNING primary instance.

    Mirrors instance.create_instance's flow: creates a companion DatabaseInstance
    (the replica is a real member of the fleet), provisions the standby via
    pg_basebackup in a thread pool, and links the two through a Replica row.

    The replica is a PHYSICAL copy of the primary → it inherits database/role/password; we decrypt
    the primary's connection_uri to reuse those credentials in the standby's URI.
    """
    if not primary.connection_uri:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Primary has no connection URI — cannot replicate",
        )

    parsed = urlparse(decrypt_value(primary.connection_uri))
    db_user = parsed.username or ""
    db_password = parsed.password or ""
    db_name = (parsed.path or "/").lstrip("/")

    # Companion instance that represents the standby in the fleet (status/port/metrics).
    replica_instance = DatabaseInstance(
        name=f"{primary.name} (replica)",
        engine_version=primary.engine_version,
        cpu=primary.cpu,
        memory_mb=primary.memory_mb,
        storage_gb=primary.storage_gb,
        region=primary.region,
        environment=primary.environment,
        status=InstanceStatus.PENDING,
        company_id=primary.company_id,
    )
    db.add(replica_instance)
    db.commit()
    db.refresh(replica_instance)
    record_status_change(db, replica_instance, InstanceStatus.PENDING)
    record_status_change(db, replica_instance, InstanceStatus.PROVISIONING)

    replica = Replica(
        primary_instance_id=primary.id,
        replica_instance_id=replica_instance.id,
        replication_state=ReplicationState.PROVISIONING,
    )
    db.add(replica)
    db.commit()
    db.refresh(replica)

    provisioner = get_provisioner()
    try:
        result = await asyncio.to_thread(
            provisioner.create_replica,
            replica_instance.id,
            primary.id,
            primary.engine_version,
            db_name,
            db_user,
            db_password,
            primary.memory_mb,
            primary.cpu,
        )
    except Exception as exc:
        record_status_change(db, replica_instance, InstanceStatus.FAILED)
        replica.replication_state = ReplicationState.FAILED
        replica.error_message = "Replica provisioning failed. See server logs."
        db.commit()
        logger.error("Replica provisioning failed for primary %s: %s", primary.id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Replica provisioning failed. See server logs for details.",
        ) from exc

    connection_uri = (
        f"postgresql://{result.db_user}:{result.db_password}"
        f"@{result.host}:{result.port}/{result.db_name}"
    )
    replica_instance.host = result.host
    replica_instance.port = result.port
    replica_instance.db_name = result.db_name
    replica_instance.db_user = result.db_user
    replica_instance.connection_uri = encrypt_value(connection_uri)
    record_status_change(db, replica_instance, InstanceStatus.RUNNING)

    # STREAMING is optimistic; the replication_poller confirms/corrects it on the next cycle.
    replica.replication_state = ReplicationState.STREAMING
    replica.error_message = None
    db.commit()
    db.refresh(replica)
    return _attach_replica_instance(db, replica)


async def promote_replica(
    db: Session, replica: Replica, current_user: User
) -> Replica:
    """
    Promotes the standby to a standalone primary (manual failover, pg_promote()).

    After promotion, the standby stops applying WAL and accepts writes; the
    replication link becomes PROMOTED (ended). The companion instance stays RUNNING.
    """
    if replica.replication_state == ReplicationState.PROMOTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Replica is already promoted",
        )

    provisioner = get_provisioner()
    try:
        await asyncio.to_thread(provisioner.promote_replica, replica.replica_instance_id)
    except Exception as exc:
        logger.error("Failed to promote replica %s: %s", replica.id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to promote the replica. See server logs for details.",
        ) from exc

    replica.replication_state = ReplicationState.PROMOTED
    replica.lag_bytes = None
    replica.lag_seconds = None
    db.commit()
    db.refresh(replica)
    return _attach_replica_instance(db, replica)
