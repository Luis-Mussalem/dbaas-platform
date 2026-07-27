import asyncio
import logging
from datetime import datetime, timezone

from src.core.database import SessionLocal
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.maintenance import MaintenanceSchedule, TaskType
from src.schemas.maintenance import MaintenanceTaskCreate

logger = logging.getLogger(__name__)

# Interval in seconds between each scheduler cycle
_SCHEDULER_INTERVAL_SECONDS = 60

# VACUUM_FULL cannot be scheduled automatically:
# it requires an exclusive lock on the table — would block reads and writes.
# Should only be run manually via POST /maintenance/run with a
# planned maintenance window and an explicit target_table.
_UNSCHEDULABLE = {TaskType.VACUUM_FULL}


def poll_schedules_once() -> None:
    """
    Checks which MaintenanceSchedules should run now.

    Dispatch strategy:
    1. Fetch all active schedules whose next_run_at <= now
    2. For each schedule: advance next_run_at BEFORE executing
       (avoids re-dispatch if execution takes longer than _SCHEDULER_INTERVAL_SECONDS)
    3. Check whether the instance is RUNNING (skip if STOPPED/FAILED/DELETED)
    4. Execute the task (blocking — runs in a thread via asyncio.to_thread)

    Why advance next_run_at before executing?
    If we advanced it afterward, and the task takes 2 minutes (REINDEX on a large table),
    the poller's next cycle (60s) would find the same schedule with next_run_at
    still in the past and dispatch it again — duplicating the execution.
    Advancing beforehand guarantees concurrent schedules never duplicate.

    Why check InstanceStatus.RUNNING?
    VACUUM/REINDEX on a stopped container would result in a ConnectionError and a FAILED task.
    More importantly: if the instance is STOPPED, maintenance doesn't make sense —
    we simply skip it and the schedule stays scheduled for its next time.

    Why synchronous?
    This function is called via asyncio.to_thread() — it can do
    blocking operations (SQL + psycopg) without blocking the HTTP requests' event loop.
    """
    from src.services.maintenance import advance_schedule, run_task

    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        due_schedules = (
            db.query(MaintenanceSchedule)
            .join(
                DatabaseInstance,
                MaintenanceSchedule.instance_id == DatabaseInstance.id,
            )
            .filter(
                MaintenanceSchedule.is_active.is_(True),
                MaintenanceSchedule.next_run_at <= now,
                MaintenanceSchedule.task_type.notin_(list(_UNSCHEDULABLE)),
                DatabaseInstance.status == InstanceStatus.RUNNING,
                DatabaseInstance.deleted_at.is_(None),
            )
            .all()
        )

        for schedule in due_schedules:
            # Advance next_run_at BEFORE executing
            advance_schedule(db, schedule)

            instance = (
                db.query(DatabaseInstance)
                .filter(DatabaseInstance.id == schedule.instance_id)
                .first()
            )
            if instance is None:
                logger.warning(
                    "Schedule %s has no matching instance — skipping",
                    schedule.id,
                )
                continue

            task_data = MaintenanceTaskCreate(
                task_type=schedule.task_type,
                target_table=None,  # automatic schedules never have a target_table
            )

            try:
                task = run_task(db, instance, task_data)
                logger.info(
                    "Scheduled maintenance executed: schedule=%s instance=%s "
                    "task_type=%s task_id=%s status=%s",
                    schedule.id,
                    instance.id,
                    schedule.task_type.value,
                    task.id,
                    task.status.value,
                )
            except Exception as exc:
                logger.error(
                    "Error running scheduled maintenance: schedule=%s instance=%s "
                    "task_type=%s error=%s",
                    schedule.id,
                    instance.id,
                    schedule.task_type.value,
                    exc,
                )

    except Exception as exc:
        logger.error("Error in maintenance scheduler cycle: %s", exc)
    finally:
        db.close()


async def maintenance_scheduling_loop(stop_event: asyncio.Event) -> None:
    """
    Async loop of the maintenance scheduler.

    Uses the same pattern as the other pollers (status_poller, metrics_poller,
    backup_scheduler): asyncio.to_thread() so it doesn't block the event loop,
    asyncio.wait_for() for a safety timeout.

    The timeout (180s) is larger than _SCHEDULER_INTERVAL_SECONDS (60s) to give
    margin for REINDEX on large tables, while still avoiding a stuck schedule
    blocking all subsequent ones indefinitely.

    stop_event comes from FastAPI's lifespan — it's set on shutdown to
    end the loop gracefully.
    """
    logger.info("Maintenance scheduling loop started")
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(
                asyncio.to_thread(poll_schedules_once),
                timeout=180.0,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Maintenance scheduler cycle exceeded the 180s timeout"
            )
        except Exception as exc:
            logger.error("Unexpected exception in maintenance scheduling loop: %s", exc)

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=_SCHEDULER_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            pass

    logger.info("Maintenance scheduling loop stopped")
