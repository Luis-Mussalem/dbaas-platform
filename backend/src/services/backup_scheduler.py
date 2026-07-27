import asyncio
import logging
from datetime import datetime, timezone

from src.core.database import SessionLocal
from src.models.backup import BackupSchedule, BackupStrategy, BackupType
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.services.backup import (
    advance_schedule,
    apply_retention,
    create_logical_backup,
    create_physical_backup,
)
from src.services.instance import reconcile_connection_port

logger = logging.getLogger(__name__)


def poll_schedules_once() -> None:
    """
    Checks all active BackupSchedules with next_run_at <= now.
    For each one, runs the backup and advances the schedule to its next run.

    Why sync with SessionLocal() directly (and not Depends(get_db))?
    This code runs outside a FastAPI request context. There's no way to use
    FastAPI's dependency injection here. We create and close the session manually.

    Why catch Exception per schedule instead of letting it propagate?
    If one instance's backup fails (instance offline, disk full, etc.),
    the poller must keep checking the other instances. A single failure must not
    take down the backups of the rest.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        due_schedules = (
            db.query(BackupSchedule)
            .filter(
                BackupSchedule.is_active.is_(True),
                BackupSchedule.next_run_at.isnot(None),
                BackupSchedule.next_run_at <= now,
            )
            .all()
        )

        if not due_schedules:
            return

        logger.info("Backup scheduler: %d schedule(s) due for execution", len(due_schedules))

        for schedule in due_schedules:
            # Check whether the instance exists and is RUNNING
            instance = (
                db.query(DatabaseInstance)
                .filter(
                    DatabaseInstance.id == schedule.instance_id,
                    DatabaseInstance.status == InstanceStatus.RUNNING,
                    DatabaseInstance.deleted_at.is_(None),
                    DatabaseInstance.connection_uri.isnot(None),
                )
                .first()
            )

            if not instance:
                logger.warning(
                    "Schedule %s: instance %s not found or not RUNNING — skipping",
                    schedule.id,
                    schedule.instance_id,
                )
                # Still advances the schedule so it doesn't keep retrying repeatedly
                advance_schedule(db, schedule)
                continue

            # Docker republishes ports when containers restart; a backup that
            # comes due at boot can run ahead of the status_poller and fail on a
            # dead port. Checking beforehand only costs one call to the Docker API.
            reconcile_connection_port(db, instance)

            try:
                if schedule.strategy == BackupStrategy.LOGICAL:
                    create_logical_backup(
                        db,
                        instance,
                        backup_type=BackupType.SCHEDULED,
                        retention_days=schedule.retention_days,
                    )
                elif schedule.strategy == BackupStrategy.PHYSICAL:
                    create_physical_backup(
                        db,
                        instance,
                        backup_type=BackupType.SCHEDULED,
                        retention_days=schedule.retention_days,
                    )

                # Apply retention after each scheduled backup
                removed = apply_retention(db, instance.id)
                if removed > 0:
                    logger.info(
                        "Retention removed %d expired backups for instance %s",
                        removed,
                        instance.id,
                    )

            except Exception as exc:
                logger.exception(
                    "Backup schedule %s for instance %s failed: %s",
                    schedule.id,
                    instance.id,
                    exc,
                )
            finally:
                # Always advance the schedule, even on failure,
                # to avoid retrying again on the next 60s cycle
                advance_schedule(db, schedule)

    finally:
        db.close()


async def backup_scheduling_loop(stop_event: asyncio.Event) -> None:
    """
    Async loop that runs poll_schedules_once() every 60 seconds.

    Why asyncio.to_thread()?
    poll_schedules_once() is synchronous (sync SQLAlchemy + subprocess). Running it
    directly on the event loop would block all requests during execution.
    asyncio.to_thread() moves the execution to a thread pool, freeing the event loop.

    Why asyncio.wait_for(stop_event.wait(), timeout=60)?
    Lets the loop be interrupted immediately when the API shuts down,
    without waiting for the next 60s cycle. The TimeoutError is caught and treated as
    "continue the loop".
    """
    logger.info("Backup scheduling loop started (interval: 60s)")
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(poll_schedules_once)
        except Exception as exc:
            logger.exception("Unexpected error in backup scheduling loop: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
    logger.info("Backup scheduling loop stopped")
