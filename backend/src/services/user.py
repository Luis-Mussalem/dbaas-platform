import uuid
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.core.security import hash_password
from src.models.user import User
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


def list_users(db: Session, company_id: Optional[uuid.UUID] = None) -> list[User]:
    q = db.query(User)
    if company_id is not None:
        q = q.filter(User.company_id == company_id)
    return q.order_by(User.email).all()


def create_user_admin(db: Session, data: UserAdminCreate) -> User:
    if get_user_by_email(db, data.email):
        raise HTTPException(status_code=400, detail="Email already registered")

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

    # Lockout guards — only check when the field is explicitly sent.
    # last-superuser runs first: it's the stronger system-level constraint,
    # and self-lockout is not meaningful when there's only one superuser left.
    if updates.get("is_active") is False or updates.get("is_superuser") is False:
        if user.is_superuser:
            _guard_last_superuser(db, user_id)
        _guard_self_lockout(acting_user, user_id)

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
