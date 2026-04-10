import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.schemas.instance import InstanceCreate, InstanceUpdate

VALID_TRANSITIONS: dict[InstanceStatus, list[InstanceStatus]] = {
    InstanceStatus.PENDING: [InstanceStatus.PROVISIONING, InstanceStatus.FAILED],
    InstanceStatus.PROVISIONING: [InstanceStatus.RUNNING, InstanceStatus.FAILED],
    InstanceStatus.RUNNING: [InstanceStatus.STOPPED, InstanceStatus.DELETING, InstanceStatus.FAILED],
    InstanceStatus.STOPPED: [InstanceStatus.RUNNING, InstanceStatus.DELETING, InstanceStatus.FAILED],
    InstanceStatus.DELETING: [InstanceStatus.DELETED, InstanceStatus.FAILED],
    InstanceStatus.DELETED: [],
    InstanceStatus.FAILED: [InstanceStatus.PENDING, InstanceStatus.DELETED],
}


def get_instance_by_id(db: Session, instance_id: uuid.UUID) -> Optional[DatabaseInstance]:
    return (
        db.query(DatabaseInstance)
        .filter(
            DatabaseInstance.id == instance_id,
            DatabaseInstance.deleted_at.is_(None),
        )
        .first()
    )


def list_instances(db: Session) -> list[DatabaseInstance]:
    return (
        db.query(DatabaseInstance)
        .filter(DatabaseInstance.deleted_at.is_(None))
        .order_by(DatabaseInstance.created_at.desc())
        .all()
    )


def create_instance(db: Session, data: InstanceCreate) -> DatabaseInstance:
    instance = DatabaseInstance(
        name=data.name,
        engine_version=data.engine_version,
        cpu=data.cpu,
        memory_mb=data.memory_mb,
        storage_gb=data.storage_gb,
        notes=data.notes,
        status=InstanceStatus.PENDING,
    )
    db.add(instance)
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


def transition_status(
    db: Session,
    instance: DatabaseInstance,
    new_status: InstanceStatus,
) -> DatabaseInstance:
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

    instance.status = new_status
    db.commit()
    db.refresh(instance)
    return instance


def soft_delete_instance(db: Session, instance: DatabaseInstance) -> DatabaseInstance:
    from datetime import datetime, timezone

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

    instance.deleted_at = datetime.now(timezone.utc)
    instance.status = InstanceStatus.DELETED
    db.commit()
    db.refresh(instance)
    return instance

