import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse, urlunparse

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from src.core.encryption import decrypt_value, encrypt_value
from src.core.scoping import scope_instance_query, visible_company_id
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.user import User
from src.schemas.instance import InstanceCreate, InstanceUpdate
from src.services.provisioning import get_provisioner
from src.services.status_history import record_status_change

logger = logging.getLogger(__name__)

VALID_TRANSITIONS: dict[InstanceStatus, list[InstanceStatus]] = {
    InstanceStatus.PENDING: [InstanceStatus.PROVISIONING, InstanceStatus.FAILED],
    InstanceStatus.PROVISIONING: [InstanceStatus.RUNNING, InstanceStatus.FAILED],
    InstanceStatus.RUNNING: [InstanceStatus.STOPPED, InstanceStatus.DELETING, InstanceStatus.FAILED],
    InstanceStatus.STOPPED: [InstanceStatus.RUNNING, InstanceStatus.DELETING, InstanceStatus.FAILED],
    InstanceStatus.DELETING: [InstanceStatus.DELETED, InstanceStatus.FAILED],
    InstanceStatus.DELETED: [],
    InstanceStatus.FAILED: [InstanceStatus.PENDING, InstanceStatus.DELETED],
}


def sync_connection_port(instance: DatabaseInstance, new_port: int) -> None:
    """
    Resyncs the port and the encrypted connection_uri after a restart.

    Used both by transition_status (manual start) and by the status_poller
    (automatic reconciliation after a Docker restart).

    Ports dynamically published by Docker are NOT preserved across
    stop/start — each start can get a new port. Without this, the saved
    connection_uri would point to the old port and metrics/backups would break.

    Decrypts the URI, swaps only the port, and re-encrypts. db_password stays
    in memory only for the duration of this function.
    """
    instance.port = new_port
    if instance.connection_uri:
        parsed = urlparse(decrypt_value(instance.connection_uri))
        netloc = f"{parsed.username}:{parsed.password}@{parsed.hostname}:{new_port}"
        new_uri = urlunparse(
            (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
        )
        instance.connection_uri = encrypt_value(new_uri)


def reconcile_connection_port(db: Session, instance: DatabaseInstance) -> bool:
    """
    Resyncs the port with whatever the provisioner publishes NOW, if they diverge.

    The status_poller already reconciles every 30s, but at startup all background
    loops come up together: a scheduled backup that's already due can run on the first
    cycle and arrive before the first reconciliation, using the port from the previous
    boot — Docker republishes ports when containers restart. pg_dump fails
    with "connection refused", writes a FAILED Backup, and the schedule advances, so
    the overdue-backup alert stays open until the next cron window.

    Called before operations that depend on connection_uri and can't
    wait for the poller's 30s. Best-effort: a failure querying the provisioner just
    returns False, letting the operation proceed with what's in the database.

    Returns True if the port changed.
    """
    try:
        port = get_provisioner().get_port(instance.id)
    except Exception as exc:  # noqa: BLE001 — best-effort, the operation proceeds
        logger.warning(
            "Could not check the port of instance %s: %s", instance.id, exc
        )
        return False

    if port is None or port == instance.port:
        return False

    logger.info(
        "Instance %s: port diverged (db=%s, docker=%s) — resyncing",
        instance.id,
        instance.port,
        port,
    )
    sync_connection_port(instance, port)
    db.commit()
    return True


def get_instance_by_id(
    db: Session, instance_id: uuid.UUID, current_user: User
) -> Optional[DatabaseInstance]:
    query = db.query(DatabaseInstance).filter(
        DatabaseInstance.id == instance_id,
        DatabaseInstance.deleted_at.is_(None),
    )
    return scope_instance_query(query, current_user).first()


def list_instances(db: Session, current_user: User) -> list[DatabaseInstance]:
    query = db.query(DatabaseInstance).filter(DatabaseInstance.deleted_at.is_(None))
    return (
        scope_instance_query(query, current_user)
        .order_by(DatabaseInstance.created_at.desc())
        .all()
    )


async def create_instance(
    db: Session, data: InstanceCreate, current_user: User
) -> DatabaseInstance:
    """
    Creates a DatabaseInstance record and provisions a real PostgreSQL container.

    Full flow:
    1. Create the record in the database with PENDING status (visible to the operator immediately)
    2. Transition to PROVISIONING and commit (the poller knows to ignore this state)
    3. Run the provisioner in a thread pool — the Docker API + psycopg are blocking
       (asyncio.to_thread avoids blocking the event loop during the ~10-30s setup)
    4. On success: populate host/port/db_name/db_user, encrypt connection_uri with
       Fernet and store it, mark RUNNING
    5. On failure: mark FAILED, raise HTTP 503

    Why asyncio.to_thread()?
    provisioner.create() polls for up to 90s waiting for PostgreSQL to start.
    If it ran directly on a sync route, it would block uvicorn's single worker
    thread for that entire time, preventing any other request from being
    served. With to_thread(), the work goes to the OS thread pool and the
    event loop stays free.
    """
    instance = DatabaseInstance(
        name=data.name,
        engine_version=data.engine_version,
        cpu=data.cpu,
        memory_mb=data.memory_mb,
        storage_gb=data.storage_gb,
        region=data.region,
        environment=data.environment,
        notes=data.notes,
        status=InstanceStatus.PENDING,
        # The instance is born in the company the creator is CURRENTLY LOOKING AT, which
        # is what visible_company_id resolves: their own company for a regular user, the
        # workspace picked in the switcher (X-Company-Id) for a superuser. Using
        # current_user.company_id instead would file every superuser-created instance
        # under NULL — invisible in the very workspace that was on screen when it was
        # created, and reachable only from the "All companies" view.
        company_id=visible_company_id(current_user),
    )
    db.add(instance)
    db.commit()
    db.refresh(instance)

    # Seed the history with the initial status (instance.id already exists after the
    # refresh) so the uptime calculation has a starting point from creation onward.
    record_status_change(db, instance, InstanceStatus.PENDING)

    # Mark as PROVISIONING before calling the provisioner
    record_status_change(db, instance, InstanceStatus.PROVISIONING)
    db.commit()

    provisioner = get_provisioner()
    try:
        result = await asyncio.to_thread(
            provisioner.create,
            instance.id,
            instance.engine_version,
            instance.memory_mb,
            instance.cpu,
        )
    except Exception as exc:
        record_status_change(db, instance, InstanceStatus.FAILED)
        db.commit()
        # Logs the detail internally; the client only gets a generic message —
        # str(exc) could expose Docker hostnames/ports/errors.
        logger.error("Provisioning failed for instance %s: %s", instance.id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provisioning failed. See server logs for details.",
        ) from exc

    # Build the connection URI and encrypt it with Fernet before persisting.
    # db_password exists ONLY in this scope — after the commit it's collected
    # by the GC and never again accessible to the application's code.
    connection_uri = (
        f"postgresql://{result.db_user}:{result.db_password}"
        f"@{result.host}:{result.port}/{result.db_name}"
    )

    instance.host = result.host
    instance.port = result.port
    instance.db_name = result.db_name
    instance.db_user = result.db_user
    instance.connection_uri = encrypt_value(connection_uri)
    record_status_change(db, instance, InstanceStatus.RUNNING)
    db.commit()
    db.refresh(instance)
    return instance


def update_instance(
    db: Session,
    instance: DatabaseInstance,
    data: InstanceUpdate,
) -> DatabaseInstance:
    if instance.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot update a deleted instance",
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(instance, field, value)

    db.commit()
    db.refresh(instance)
    return instance


async def transition_status(
    db: Session,
    instance: DatabaseInstance,
    new_status: InstanceStatus,
) -> DatabaseInstance:
    """
    Validates and applies a status transition, calling the provisioner for
    start/stop operations.

    The provisioner is invoked only for RUNNING ↔ STOPPED:
    - RUNNING → STOPPED: provisioner.stop() — gracefully stops the Docker container
    - STOPPED → RUNNING: provisioner.start() — restarts the existing container

    Other transitions (→ FAILED, → DELETING) only update the status in the database,
    without interacting with Docker. DELETING→DELETED is exclusive to soft_delete_instance.
    """
    allowed = VALID_TRANSITIONS.get(instance.status, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot transition from '{instance.status.value}' "
                f"to '{new_status.value}'. "
                f"Allowed: {[s.value for s in allowed] or 'none'}"
            ),
        )

    provisioner = get_provisioner()

    if instance.status == InstanceStatus.RUNNING and new_status == InstanceStatus.STOPPED:
        try:
            await asyncio.to_thread(provisioner.stop, instance.id)
        except Exception as exc:
            record_status_change(db, instance, InstanceStatus.FAILED)
            db.commit()
            logger.error("Failed to stop instance %s: %s", instance.id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to stop the instance. See server logs for details.",
            ) from exc

    elif instance.status == InstanceStatus.STOPPED and new_status == InstanceStatus.RUNNING:
        try:
            new_port = await asyncio.to_thread(provisioner.start, instance.id)
        except Exception as exc:
            record_status_change(db, instance, InstanceStatus.FAILED)
            db.commit()
            logger.error("Failed to start instance %s: %s", instance.id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to start the instance. See server logs for details.",
            ) from exc
        # Docker can publish a different port on each start — resyncs
        # the port and connection_uri so metrics/backups stay valid.
        sync_connection_port(instance, new_port)

    record_status_change(db, instance, new_status)
    db.commit()
    db.refresh(instance)
    return instance


async def soft_delete_instance(db: Session, instance: DatabaseInstance) -> DatabaseInstance:
    """
    Removes an instance from active use with full container cleanup.

    Flow:
    1. Validate preconditions (not deleted, not running)
    2. Transition to DELETING and commit (the poller ignores this state)
    3. Call provisioner.delete() — removes the Docker container (idempotent)
    4. Finalize: mark deleted_at + status DELETED

    provisioner.delete() is idempotent: if the container doesn't exist (e.g. it was
    removed manually), it doesn't raise an error — it just continues.
    """
    if instance.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Instance is already deleted",
        )
    if instance.status == InstanceStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a running instance. Stop it first.",
        )

    record_status_change(db, instance, InstanceStatus.DELETING)
    db.commit()

    provisioner = get_provisioner()
    try:
        await asyncio.to_thread(provisioner.delete, instance.id)
    except Exception as exc:
        record_status_change(db, instance, InstanceStatus.FAILED)
        db.commit()
        logger.error("Failed to remove container for instance %s: %s", instance.id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to remove the instance container. See server logs for details.",
        ) from exc

    instance.deleted_at = datetime.now(timezone.utc)
    record_status_change(db, instance, InstanceStatus.DELETED)
    db.commit()
    db.refresh(instance)
    return instance

