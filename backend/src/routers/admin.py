import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.models.user import User
from src.schemas.admin import AuditLogRead, DashboardResponse
from src.services import admin as admin_service

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Visão consolidada da saúde da plataforma.

    Retorna:
    - Total de instâncias e contagem por status
    - Alertas ativos (não resolvidos)
    - Backups nas últimas 24h (total e falhos)
    - Tarefas de manutenção pendentes ou em execução
    """
    return admin_service.get_dashboard(db)


@router.get("/audit-log", response_model=list[AuditLogRead])
def get_audit_log(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None, description="Filtrar por ação (ex: login, backup_created)"),
    resource_type: str | None = Query(None, description="Filtrar por tipo de recurso (ex: instance, backup)"),
    user_id: uuid.UUID | None = Query(None, description="Filtrar por usuário"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Histórico de ações auditadas na plataforma.

    Ordenado por timestamp decrescente (mais recente primeiro).
    Suporta filtros por action, resource_type e user_id.
    Paginação via limit e offset.
    """
    return admin_service.list_audit_logs(
        db,
        limit=limit,
        offset=offset,
        action=action,
        resource_type=resource_type,
        user_id=user_id,
    )
