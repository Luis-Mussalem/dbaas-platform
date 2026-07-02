import uuid
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.scoping import assert_can_manage_target
from src.core.security import hash_password
from src.models.audit_log import AuditLog
from src.models.user import User, UserRole
from src.schemas.user import UserAdminCreate, UserAdminUpdate
from src.services.auth import get_user_by_email, get_user_by_id
from src.services.company import get_company_by_id


def _guard_self_lockout(acting_user: User, target_user_id: uuid.UUID) -> None:
    if acting_user.id == target_user_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot deactivate or demote your own account",
        )


def _guard_last_superuser(db: Session, target_user_id: uuid.UUID) -> None:
    active_superusers = (
        db.query(User)
        .filter(User.is_superuser.is_(True), User.is_active.is_(True))
        .count()
    )
    if active_superusers <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot deactivate or demote the last active superuser",
        )


def _guard_last_company_admin(db: Session, target_user: User) -> None:
    """Bloqueia demover/desativar o último admin ativo de uma empresa."""
    if target_user.company_id is None:
        return
    active_admins = (
        db.query(User)
        .filter(
            User.company_id == target_user.company_id,
            User.role == UserRole.ADMIN,
            User.is_active.is_(True),
        )
        .count()
    )
    if active_admins <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot deactivate or demote the last active admin of this company",
        )


def list_users(
    db: Session, acting_user: User, company_id: Optional[uuid.UUID] = None
) -> list[User]:
    """Lista usuários, com scoping automático para company admins."""
    q = db.query(User)
    if not acting_user.is_superuser:
        q = q.filter(User.company_id == acting_user.company_id)
    elif company_id is not None:
        q = q.filter(User.company_id == company_id)
    users = q.order_by(User.email).all()

    # "Última atividade" = MAX(timestamp) por usuário em audit_logs. Uma query
    # agregada só para os user_ids já escopados (sem N+1, sem tocar audit_logs de
    # outra empresa). Setado como atributo transiente lido por UserListItem.
    user_ids = [u.id for u in users]
    if user_ids:
        last_seen = dict(
            db.query(AuditLog.user_id, func.max(AuditLog.timestamp))
            .filter(AuditLog.user_id.in_(user_ids))
            .group_by(AuditLog.user_id)
            .all()
        )
        for u in users:
            u.last_activity = last_seen.get(u.id)
    return users


def create_user_admin(db: Session, data: UserAdminCreate, acting_user: User) -> User:
    if get_user_by_email(db, data.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    # Company admin guards — antes de permitir criar qualquer coisa
    if not acting_user.is_superuser:
        if acting_user.company_id is None:
            raise HTTPException(status_code=403, detail="Admin has no company")
        if data.is_superuser:
            raise HTTPException(status_code=403, detail="Cannot create superusers")
        if data.company_id is not None and data.company_id != acting_user.company_id:
            raise HTTPException(status_code=403, detail="Cannot create users in another company")
        data.company_id = acting_user.company_id

    if not data.is_superuser and data.company_id is None:
        raise HTTPException(
            status_code=400,
            detail="company_id is required for non-superuser accounts",
        )

    if data.company_id is not None and get_company_by_id(db, data.company_id) is None:
        raise HTTPException(status_code=400, detail="Company not found")

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        company_id=data.company_id,
        is_superuser=data.is_superuser,
        role=data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_admin(
    db: Session,
    user_id: uuid.UUID,
    data: UserAdminUpdate,
    acting_user: User,
) -> User:
    user = get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    updates = data.model_dump(exclude_unset=True)

    # Company admin guards — before any other check
    if not acting_user.is_superuser:
        assert_can_manage_target(acting_user, user)
        if "is_superuser" in updates:
            raise HTTPException(status_code=403, detail="Cannot modify superuser flag")
        if "company_id" in updates and updates["company_id"] != acting_user.company_id:
            raise HTTPException(status_code=403, detail="Cannot move user to another company")

    # Lockout guards — only check when the field is explicitly sent.
    # last-superuser runs first: it's the stronger system-level constraint,
    # and self-lockout is not meaningful when there's only one superuser left.
    if updates.get("is_active") is False or updates.get("is_superuser") is False:
        if user.is_superuser:
            _guard_last_superuser(db, user_id)
        _guard_self_lockout(acting_user, user_id)

    # Guard last company admin — when demoting or deactivating a company admin
    if user.role == UserRole.ADMIN and user.company_id is not None:
        if (updates.get("is_active") is False or
            (updates.get("role") is not None and updates["role"] != UserRole.ADMIN)):
            _guard_last_company_admin(db, user)

    if "email" in updates and updates["email"] != user.email:
        if get_user_by_email(db, updates["email"]):
            raise HTTPException(status_code=400, detail="Email already registered")

    if "company_id" in updates and updates["company_id"] is not None:
        if get_company_by_id(db, updates["company_id"]) is None:
            raise HTTPException(status_code=400, detail="Company not found")

    for field, value in updates.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


def deactivate_user(db: Session, user_id: uuid.UUID, acting_user: User) -> User:
    data = UserAdminUpdate(is_active=False)
    return update_user_admin(db, user_id, data, acting_user)
