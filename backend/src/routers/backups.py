import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.dependencies import get_current_user, get_db, get_instance_or_404, get_instance_if_running
from src.models.backup import BackupStatus, BackupStrategy
from src.models.user import User
from src.schemas.backup import (
    BackupRead,
    BackupRequest,
    BackupScheduleCreate,
    BackupScheduleRead,
    BackupScheduleUpdate,
)
from src.services.backup import (
    create_logical_backup,
    create_physical_backup,
    create_schedule,
    delete_backup_record,
    delete_schedule,
    get_backup_by_id,
    get_schedule_by_id,
    list_backups,
    list_schedules,
    restore_logical_backup,
    update_schedule,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Backups"])


# ---------------------------------------------------------------------------
# Backup endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/instances/{instance_id}/backups",
    response_model=BackupRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_backup(
    instance_id: uuid.UUID,
    data: BackupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Triggers a manual backup for the specified instance.

    strategy=logical: pg_dump (custom format) — fast, portable, allows selective restore.
    strategy=physical: pg_basebackup — full backup of the data files, the basis for PITR.

    The instance must be in RUNNING status.
    Blocking operation — waits for the backup to complete before returning.
    For large databases, this can take several minutes.
    """
    instance = get_instance_if_running(instance_id, db, current_user)

    if not instance.connection_uri:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Instance has no connection URI — cannot backup",
        )

    try:
        if data.strategy == BackupStrategy.LOGICAL:
            backup = await asyncio.to_thread(
                create_logical_backup, db, instance
            )
        else:
            backup = await asyncio.to_thread(
                create_physical_backup, db, instance
            )
    except RuntimeError as exc:
        # str(exc) carries pg_dump/pg_basebackup stderr (host, port, internal
        # messages) — it stays only in the server log; the client gets a generic message.
        logger.error("Backup failed for instance %s: %s", instance_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Backup operation failed. Check server logs for details.",
        ) from exc

    return backup


@router.get(
    "/instances/{instance_id}/backups",
    response_model=list[BackupRead],
)
def list_instance_backups(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lists all non-deleted backups of an instance, most recent first.
    """
    get_instance_or_404(instance_id, db, current_user)
    return list_backups(db, instance_id)


@router.get(
    "/backups/{backup_id}",
    response_model=BackupRead,
)
def get_backup(
    backup_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns the details of a specific backup."""
    backup = get_backup_by_id(db, backup_id)
    if not backup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup not found",
        )
    # Scoping by company: if the owning instance is not visible to the user, 404.
    get_instance_or_404(backup.instance_id, db, current_user)
    return backup


@router.delete(
    "/backups/{backup_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_backup(
    backup_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Removes a backup: deletes the physical file and marks the record as DELETED.
    The record stays in the database for audit purposes.
    """
    backup = get_backup_by_id(db, backup_id)
    if not backup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup not found",
        )
    # Scoping by company: owning instance not visible to the user → 404.
    get_instance_or_404(backup.instance_id, db, current_user)
    if backup.status == BackupStatus.DELETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Backup is already deleted",
        )
    delete_backup_record(db, backup)


@router.post(
    "/backups/{backup_id}/restore",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def restore_backup(
    backup_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Restores a logical backup (pg_restore) onto the source instance.

    WARNING: destructive operation — all current data in the database is replaced
    with the backup's contents. Confirm you have the right backup before running this.

    Only backups with strategy=logical and status=completed can be restored.
    The instance must be in RUNNING status.
    """
    backup = get_backup_by_id(db, backup_id)
    if not backup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup not found",
        )

    if backup.status != BackupStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot restore backup with status '{backup.status}'",
        )

    if backup.strategy != BackupStrategy.LOGICAL:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only logical backups can be restored via this endpoint",
        )

    # get_instance_if_running already scopes by company: a backup from another company → 404.
    instance = get_instance_if_running(backup.instance_id, db, current_user)

    try:
        await asyncio.to_thread(restore_logical_backup, db, backup, instance)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        # Same reason as create_backup: the real error (file path, pg_restore
        # stderr) goes to the log; the client only gets a generic message.
        logger.error("Restore failed for backup %s: %s", backup_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Restore operation failed. Check server logs for details.",
        ) from exc


# ---------------------------------------------------------------------------
# Schedule endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/instances/{instance_id}/schedules",
    response_model=BackupScheduleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_backup_schedule(
    instance_id: uuid.UUID,
    data: BackupScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Creates an automatic backup schedule for the instance.
    The cron expression is validated before saving.
    next_run_at is computed automatically.
    """
    get_instance_or_404(instance_id, db, current_user)
    return create_schedule(db, instance_id, data)


@router.get(
    "/instances/{instance_id}/schedules",
    response_model=list[BackupScheduleRead],
)
def list_backup_schedules(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lists all backup schedules for an instance."""
    get_instance_or_404(instance_id, db, current_user)
    return list_schedules(db, instance_id)


@router.patch(
    "/instances/{instance_id}/schedules/{schedule_id}",
    response_model=BackupScheduleRead,
)
def update_backup_schedule(
    instance_id: uuid.UUID,
    schedule_id: uuid.UUID,
    data: BackupScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Updates an existing schedule.
    If the cron expression changes, next_run_at is recomputed automatically.
    If is_active is turned off, next_run_at is cleared (pauses the schedule).
    """
    get_instance_or_404(instance_id, db, current_user)
    schedule = get_schedule_by_id(db, schedule_id)
    if not schedule or schedule.instance_id != instance_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Schedule not found",
        )
    return update_schedule(db, schedule, data)


@router.delete(
    "/instances/{instance_id}/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_backup_schedule(
    instance_id: uuid.UUID,
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Removes a backup schedule. Backups already created are not affected."""
    get_instance_or_404(instance_id, db, current_user)
    schedule = get_schedule_by_id(db, schedule_id)
    if not schedule or schedule.instance_id != instance_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Schedule not found",
        )
    delete_schedule(db, schedule)
