import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.dependencies import get_current_user, get_db, get_instance_or_404, get_instance_if_running
from src.models.maintenance import MaintenanceSchedule
from src.models.user import User
from src.schemas.maintenance import (
    ConfigRecommendationsResponse,
    MaintenanceScheduleCreate,
    MaintenanceScheduleRead,
    MaintenanceTaskCreate,
    MaintenanceTaskRead,
)
from src.services import maintenance as svc

router = APIRouter(prefix="/instances", tags=["Maintenance"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_schedule(
    schedule_id: uuid.UUID,
    instance_id: uuid.UUID,
    db: Session,
) -> MaintenanceSchedule:
    """Returns the schedule or 404."""
    schedule = (
        db.query(MaintenanceSchedule)
        .filter(
            MaintenanceSchedule.id == schedule_id,
            MaintenanceSchedule.instance_id == instance_id,
        )
        .first()
    )
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance schedule not found",
        )
    return schedule


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/{instance_id}/maintenance/run",
    response_model=MaintenanceTaskRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a manual maintenance task",
)
def run_maintenance(
    instance_id: uuid.UUID,
    data: MaintenanceTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Runs a maintenance task immediately on the instance.

    - **VACUUM** / **ANALYZE** / **REINDEX**: optionally on a specific table
    - **VACUUM_FULL**: `target_table` is required (exclusive lock — never on the whole database)
    - **KILL_IDLE** / **KILL_LONG**: `target_table` is ignored (they operate on connections)

    Requires the instance to be `RUNNING`.
    """
    instance = get_instance_if_running(instance_id, db, current_user)
    try:
        return svc.run_task(db, instance, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )


@router.get(
    "/{instance_id}/maintenance",
    response_model=list[MaintenanceTaskRead],
    summary="Maintenance task history",
)
def list_maintenance_history(
    instance_id: uuid.UUID,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns the history of the instance's most recent maintenance tasks.
    Ordered by `scheduled_at` descending.
    """
    get_instance_or_404(instance_id, db, current_user)
    return svc.get_task_history(db, instance_id, limit=limit)


@router.post(
    "/{instance_id}/maintenance/schedules",
    response_model=MaintenanceScheduleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a maintenance schedule",
)
def create_schedule(
    instance_id: uuid.UUID,
    data: MaintenanceScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Creates a recurring maintenance schedule with a cron expression.

    `cron_expression` example:
    - `"0 3 * * 0"` — every Monday at 3:00 UTC
    - `"30 1 * * *"` — every day at 01:30 UTC

    `VACUUM_FULL` cannot be scheduled automatically (it uses an exclusive lock).
    Run it manually via `POST /maintenance/run`.
    """
    get_instance_or_404(instance_id, db, current_user)
    return svc.create_schedule(db, instance_id, data)


@router.get(
    "/{instance_id}/maintenance/schedules",
    response_model=list[MaintenanceScheduleRead],
    summary="List maintenance schedules",
)
def list_schedules(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns all of the instance's maintenance schedules."""
    get_instance_or_404(instance_id, db, current_user)
    return svc.list_schedules(db, instance_id)


@router.delete(
    "/{instance_id}/maintenance/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a maintenance schedule",
)
def delete_schedule(
    instance_id: uuid.UUID,
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently deletes a maintenance schedule."""
    get_instance_or_404(instance_id, db, current_user)
    schedule = _require_schedule(schedule_id, instance_id, db)
    svc.delete_schedule(db, schedule)


@router.get(
    "/{instance_id}/config-recommendations",
    response_model=ConfigRecommendationsResponse,
    summary="PostgreSQL configuration recommendations",
)
def get_config_recommendations(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns PostgreSQL parameter recommendations based on the instance's resources.

    Computed offline — doesn't require a connection to the database.
    Works even when the instance is `STOPPED`.

    The formulas follow the recommendations from [wiki.postgresql.org](https://wiki.postgresql.org/wiki/Tuning_Your_PostgreSQL_Server)
    and from pgTune for OLTP workloads.
    """
    instance = get_instance_or_404(instance_id, db, current_user)
    return svc.get_config_recommendations(instance)
