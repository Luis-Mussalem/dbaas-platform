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


def get_dashboard(
    db: Session, company_id: uuid.UUID | None = None
) -> DashboardResponse:
    # company_id None = superuser (sem filtro). Caso contrário todos os agregados
    # ficam restritos às instâncias daquela empresa; recursos derivados (alertas,
    # backups, manutenção) são filtrados via JOIN à instância dona.

    # Instâncias agrupadas por status (exceto deletadas por soft delete)
    inst_q = db.query(DatabaseInstance.status, func.count(DatabaseInstance.id)).filter(
        DatabaseInstance.deleted_at.is_(None)
    )
    if company_id is not None:
        inst_q = inst_q.filter(DatabaseInstance.company_id == company_id)
    rows = inst_q.group_by(DatabaseInstance.status).all()
    instances_by_status = {status.value: count for status, count in rows}
    total_instances = sum(instances_by_status.values())

    # Alertas ativos (sem resolved_at)
    alerts_q = db.query(func.count(AlertEvent.id)).filter(AlertEvent.resolved_at.is_(None))
    if company_id is not None:
        alerts_q = alerts_q.join(
            DatabaseInstance, AlertEvent.instance_id == DatabaseInstance.id
        ).filter(DatabaseInstance.company_id == company_id)
    active_alerts = alerts_q.scalar() or 0

    # Backups nas últimas 24h
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

    # Tarefas de manutenção pendentes ou em execução
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
    # TODO(PHASE 11 — Audit scoping): ainda NÃO escopado por empresa. Escopar aqui
    # é não-trivial: eventos de sistema (login/register) têm user_id NULL e o
    # resource_id aponta para tipos variados (instance/backup/auth). Fica como item
    # próprio do RBAC/Audit scoping, separado do scoping de instâncias da Stage A.
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
