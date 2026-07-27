import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.dependencies import get_current_company_admin, get_current_user
from src.core.scoping import visible_company_id
from src.models.user import User
from src.schemas.admin import AuditLogRead, DashboardResponse
from src.services import admin as admin_service

router = APIRouter(prefix="/admin", tags=["Administration"])


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Consolidated view of the platform's health.

    Returns:
    - Total instances and count by status
    - Active (unresolved) alerts
    - Backups in the last 24h (total and failed)
    - Pending or running maintenance tasks
    """
    return admin_service.get_dashboard(db, company_id=visible_company_id(current_user))


@router.get("/audit-log", response_model=list[AuditLogRead])
def get_audit_log(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None, description="Filter by action (e.g.: login, backup_created)"),
    resource_type: str | None = Query(None, description="Filter by resource type (e.g.: instance, backup)"),
    user_id: uuid.UUID | None = Query(None, description="Filter by user"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_company_admin),
):
    """
    History of audited actions on the platform.

    Ordered by timestamp descending (most recent first).
    Supports filters by action, resource_type, and user_id.
    Paginated via limit and offset.
    Access restricted to company-admin and superuser.
    """
    return admin_service.list_audit_logs(
        db,
        limit=limit,
        offset=offset,
        action=action,
        resource_type=resource_type,
        user_id=user_id,
        company_id=visible_company_id(current_user),
    )
