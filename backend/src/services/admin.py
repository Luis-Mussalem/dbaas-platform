import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.alert import AlertEvent
from src.models.audit_log import AuditLog
from src.models.backup import Backup, BackupStatus
from src.models.database_instance import DatabaseInstance
from src.models.maintenance import MaintenanceTask, TaskStatus
from src.schemas.admin import DashboardResponse


def write_audit_log(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    user_id: uuid.UUID | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
    )
    db.add(entry)
    db.commit()


def get_dashboard(db: Session) -> DashboardResponse:
    # Instâncias agrupadas por status (exceto deletadas por soft delete)
    rows = (
        db.query(DatabaseInstance.status, func.count(DatabaseInstance.id))
        .filter(DatabaseInstance.deleted_at.is_(None))
        .group_by(DatabaseInstance.status)
        .all()
    )
    instances_by_status = {status.value: count for status, count in rows}
    total_instances = sum(instances_by_status.values())

    # Alertas ativos (sem resolved_at)
    active_alerts = (
        db.query(func.count(AlertEvent.id))
        .filter(AlertEvent.resolved_at.is_(None))
        .scalar()
    ) or 0

    # Backups nas últimas 24h
    since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    backups_last_24h = (
        db.query(func.count(Backup.id))
        .filter(Backup.created_at >= since)
        .filter(Backup.status != BackupStatus.DELETED)
        .scalar()
    ) or 0

    failed_backups_last_24h = (
        db.query(func.count(Backup.id))
        .filter(Backup.created_at >= since)
        .filter(Backup.status == BackupStatus.FAILED)
        .scalar()
    ) or 0

    # Tarefas de manutenção pendentes ou em execução
    pending_maintenance_tasks = (
        db.query(func.count(MaintenanceTask.id))
        .filter(MaintenanceTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]))
        .scalar()
    ) or 0

    return DashboardResponse(
        total_instances=total_instances,
        instances_by_status=instances_by_status,
        active_alerts=active_alerts,
        backups_last_24h=backups_last_24h,
        failed_backups_last_24h=failed_backups_last_24h,
        pending_maintenance_tasks=pending_maintenance_tasks,
    )


def list_audit_logs(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    resource_type: str | None = None,
    user_id: uuid.UUID | None = None,
) -> list[AuditLog]:
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    return (
        query.order_by(AuditLog.timestamp.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
