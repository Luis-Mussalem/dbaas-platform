import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.dependencies import get_current_company_admin, get_current_user
from src.core.scoping import assert_can_manage_target, is_company_admin
from src.models.user import User
from src.schemas.user import (
    UserAdminCreate,
    UserAdminUpdate,
    UserListItem,
    UserRead,
    UserUpdate,
)
from src.services.auth import get_user_by_id
from src.services.user import (
    create_user_admin,
    list_users,
    update_user_admin,
    update_user_self,
)

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=list[UserListItem])
def list_users_admin(
    company_id: Optional[uuid.UUID] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_company_admin),
):
    return list_users(db, acting_user=current_user, company_id=company_id)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user_admin_endpoint(
    data: UserAdminCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_company_admin),
):
    return create_user_admin(db, data, acting_user=current_user)


@router.patch("/{user_id}/admin", response_model=UserRead)
def update_user_admin_endpoint(
    user_id: uuid.UUID,
    data: UserAdminUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_company_admin),
):
    return update_user_admin(db, user_id, data, acting_user=current_user)


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Reads one user.

    Object-level authorization, in three steps:
    - your own record: always readable;
    - superuser: reads anyone;
    - company admin: reads employees of their OWN company — the same set they can
      already list via `GET /users` and edit via `PATCH /users/{id}/admin`. Denying
      it here was an inconsistency, not a protection: an admin could change a
      colleague's role but got 403 fetching that colleague by id.

    Anyone else gets 403 — without this, any authenticated user could read
    another's record by UUID (IDOR).
    """
    if current_user.id != user_id:
        if not is_company_admin(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed to view another user",
            )
        target = get_user_by_id(db, user_id)
        if not target:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        # 404 (not 403) for a target outside the admin's reach — same posture as
        # the rest of the tenant boundary: don't confirm that the user exists.
        assert_can_manage_target(current_user, target)
        return target

    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Updates the authenticated user's own account (email and/or password).

    Only the account's owner may call it — an admin changing someone else's
    credentials goes through `PATCH /users/{id}/admin` instead. Changing either
    field requires `current_password`; see the UserUpdate schema for the rationale.
    """
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to update another user",
        )

    return update_user_self(
        db,
        current_user,
        email=data.email,
        password=data.password,
        current_password=data.current_password,
    )