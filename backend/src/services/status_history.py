import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.instance_status_history import InstanceStatusHistory

# Reference window for the uptime calculation.
_UPTIME_WINDOW = timedelta(days=30)


def record_status_change(
    db: Session, instance: DatabaseInstance, new_status: InstanceStatus
) -> None:
    """
    Applies the status change to the instance AND records the transition in the history.

    Does NOT commit on purpose: every call site already commits right after, so
    the history row goes into the same transaction as the status change — if it
    rolls back, both disappear together (atomicity).

    Should only be called when the status actually changes; the call sites already
    ensure this (valid transitions or `if status != X` guards), so we don't filter
    here — that would hide a no-op that would signal a bug in the caller.
    """
    instance.status = new_status
    db.add(InstanceStatusHistory(instance_id=instance.id, status=new_status))


def _uptime_from_rows(
    rows: list[InstanceStatusHistory],
    created_at: datetime,
    now: datetime,
) -> float | None:
    """
    Computes the % of time spent RUNNING in the window [max(now - 30d, created_at), now].

    `rows`: history of ONE instance ordered by changed_at ASC. Empty → None
    (instance predates tracking — better to show "—" than fabricate 0/100%).

    The status in effect at the start of the window is that of the last record with
    changed_at <= window_start (carry-in), allowing windows that begin in the middle
    of a RUNNING period for instances older than 30 days.
    """
    if not rows:
        return None

    window_start = max(now - _UPTIME_WINDOW, created_at)
    total = (now - window_start).total_seconds()
    if total <= 0:
        return None

    # Carry-in: status active at window_start.
    current = rows[0].status
    for row in rows:
        if row.changed_at <= window_start:
            current = row.status
        else:
            break

    running_seconds = 0.0
    cursor = window_start
    for row in rows:
        if row.changed_at <= window_start:
            continue
        if row.changed_at >= now:
            break
        if current == InstanceStatus.RUNNING:
            running_seconds += (row.changed_at - cursor).total_seconds()
        cursor = row.changed_at
        current = row.status

    # Final segment: from the last boundary to now.
    if current == InstanceStatus.RUNNING:
        running_seconds += (now - cursor).total_seconds()

    return round(running_seconds / total * 100, 2)


def get_instance_uptime_pct(
    db: Session, instance: DatabaseInstance
) -> float | None:
    """Uptime (% RUNNING over the last 30 days) of a single instance."""
    rows = (
        db.query(InstanceStatusHistory)
        .filter(InstanceStatusHistory.instance_id == instance.id)
        .order_by(InstanceStatusHistory.changed_at.asc())
        .all()
    )
    return _uptime_from_rows(rows, instance.created_at, datetime.now(timezone.utc))


def get_uptime_pct_by_instance(
    db: Session, instances: list[DatabaseInstance]
) -> dict[uuid.UUID, float]:
    """
    30-day uptime for several instances at once.

    A single query brings back the history of all of them; grouping and the
    per-instance calculation happen in Python (portfolio scale — few instances; no
    need for a view/cache). An instance with no history is left OUT of the dict, so
    the caller shows "—" instead of fabricating 0/100%.
    """
    if not instances:
        return {}

    rows = (
        db.query(InstanceStatusHistory)
        .filter(InstanceStatusHistory.instance_id.in_([i.id for i in instances]))
        .order_by(InstanceStatusHistory.changed_at.asc())
        .all()
    )

    by_instance: dict[uuid.UUID, list[InstanceStatusHistory]] = {}
    for row in rows:
        by_instance.setdefault(row.instance_id, []).append(row)

    now = datetime.now(timezone.utc)
    return {
        inst.id: pct
        for inst in instances
        if (
            pct := _uptime_from_rows(by_instance.get(inst.id, []), inst.created_at, now)
        )
        is not None
    }


def get_fleet_uptime_pct(
    db: Session, company_id: uuid.UUID | None = None
) -> float | None:
    """
    Fleet-wide average uptime: simple average of per-instance uptime (not deleted),
    scoped by company. None if no instance has history yet.
    """
    inst_q = db.query(DatabaseInstance).filter(DatabaseInstance.deleted_at.is_(None))
    if company_id is not None:
        inst_q = inst_q.filter(DatabaseInstance.company_id == company_id)
    instances = inst_q.all()

    pcts = list(get_uptime_pct_by_instance(db, instances).values())
    if not pcts:
        return None
    return round(sum(pcts) / len(pcts), 2)
