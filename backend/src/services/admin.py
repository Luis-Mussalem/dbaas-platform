import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.alert import AlertEvent
from src.models.audit_log import AuditLog
from src.models.backup import Backup, BackupStatus
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.maintenance import MaintenanceTask, TaskStatus
from src.models.user import User
from src.schemas.admin import DashboardResponse
from src.services import fleet_summary, status_history


def _running_instance_ids(
    db: Session, company_id: uuid.UUID | None
) -> list[uuid.UUID]:
    """IDs of RUNNING instances in scope (basis for the throughput/latency KPIs)."""
    q = db.query(DatabaseInstance.id).filter(
        DatabaseInstance.status == InstanceStatus.RUNNING,
        DatabaseInstance.deleted_at.is_(None),
    )
    if company_id is not None:
        q = q.filter(DatabaseInstance.company_id == company_id)
    return [row[0] for row in q.all()]


def _compute_fleet_queries_per_second(
    db: Session, company_id: uuid.UUID | None
) -> float:
    """Real fleet throughput: sum of commit rates per RUNNING instance."""
    instance_ids = _running_instance_ids(db, company_id)
    rates = fleet_summary.queries_per_second_by_instance(db, instance_ids)
    return round(sum(rates.values()), 2)


def _compute_fleet_p95_latency(
    db: Session, company_id: uuid.UUID | None
) -> float | None:
    """
    Fleet average P95 latency: average of the latest p95_query_latency_ms of each
    RUNNING instance that has the metric. None if none has it (shows "—").
    """
    instance_ids = _running_instance_ids(db, company_id)
    values = list(
        fleet_summary.latest_metric_by_instance(
            db, instance_ids, "p95_query_latency_ms"
        ).values()
    )
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def write_audit_log(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    user_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    entry = AuditLog(
        user_id=user_id,
        company_id=company_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
    )
    db.add(entry)
    db.commit()


def get_dashboard(
    db: Session, company_id: uuid.UUID | None = None
) -> DashboardResponse:
    # company_id None = superuser (no filter). Otherwise all aggregates
    # are restricted to that company's instances; derived resources (alerts,
    # backups, maintenance) are filtered via a JOIN to the owning instance.

    # Instances grouped by status (excluding soft-deleted ones)
    inst_q = db.query(DatabaseInstance.status, func.count(DatabaseInstance.id)).filter(
        DatabaseInstance.deleted_at.is_(None)
    )
    if company_id is not None:
        inst_q = inst_q.filter(DatabaseInstance.company_id == company_id)
    rows = inst_q.group_by(DatabaseInstance.status).all()
    instances_by_status = {status.value: count for status, count in rows}
    total_instances = sum(instances_by_status.values())

    # Active alerts (no resolved_at)
    alerts_q = db.query(func.count(AlertEvent.id)).filter(AlertEvent.resolved_at.is_(None))
    if company_id is not None:
        alerts_q = alerts_q.join(
            DatabaseInstance, AlertEvent.instance_id == DatabaseInstance.id
        ).filter(DatabaseInstance.company_id == company_id)
    active_alerts = alerts_q.scalar() or 0

    # Backups in the last 24h
    since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    backups_q = (
        db.query(func.count(Backup.id))
        .filter(Backup.created_at >= since)
        .filter(Backup.status != BackupStatus.DELETED)
    )
    failed_q = (
        db.query(func.count(Backup.id))
        .filter(Backup.created_at >= since)
        .filter(Backup.status == BackupStatus.FAILED)
    )
    if company_id is not None:
        backups_q = backups_q.join(
            DatabaseInstance, Backup.instance_id == DatabaseInstance.id
        ).filter(DatabaseInstance.company_id == company_id)
        failed_q = failed_q.join(
            DatabaseInstance, Backup.instance_id == DatabaseInstance.id
        ).filter(DatabaseInstance.company_id == company_id)
    backups_last_24h = backups_q.scalar() or 0
    failed_backups_last_24h = failed_q.scalar() or 0

    # Pending or running maintenance tasks
    maint_q = db.query(func.count(MaintenanceTask.id)).filter(
        MaintenanceTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING])
    )
    if company_id is not None:
        maint_q = maint_q.join(
            DatabaseInstance, MaintenanceTask.instance_id == DatabaseInstance.id
        ).filter(DatabaseInstance.company_id == company_id)
    pending_maintenance_tasks = maint_q.scalar() or 0

    return DashboardResponse(
        total_instances=total_instances,
        instances_by_status=instances_by_status,
        active_alerts=active_alerts,
        backups_last_24h=backups_last_24h,
        failed_backups_last_24h=failed_backups_last_24h,
        pending_maintenance_tasks=pending_maintenance_tasks,
        queries_per_second=_compute_fleet_queries_per_second(db, company_id),
        p95_latency_ms=_compute_fleet_p95_latency(db, company_id),
        fleet_uptime_pct=status_history.get_fleet_uptime_pct(db, company_id),
    )


def list_audit_logs(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    resource_type: str | None = None,
    user_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
) -> list[AuditLog]:
    # LEFT JOIN on users to bring back the actor's email too (AuditLog only stores the
    # user_id). outerjoin: actions with no user (login, background) and already-
    # deleted users keep the row, with email = None.
    query = db.query(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id)
    if company_id is not None:
        query = query.filter(AuditLog.company_id == company_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    # Tiebreak by id: with LIMIT/OFFSET, ordering by timestamp alone isn't
    # deterministic when two entries land on the same instant — Postgres
    # can return them in different orders across pages, and then a row
    # shows up twice while another disappears. id has no temporal meaning;
    # it's there only to make the order stable.
    rows = (
        query.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    # Attaches the email as a transient attribute for AuditLogRead (from_attributes).
    logs: list[AuditLog] = []
    for log, email in rows:
        log.user_email = email
        logs.append(log)
    return logs
