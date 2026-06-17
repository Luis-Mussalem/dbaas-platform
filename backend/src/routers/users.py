import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.dependencies import get_current_superuser, get_current_user
from src.core.security import hash_password
from src.models.user import User
from src.schemas.user import UserAdminCreate, UserAdminUpdate, UserRead, UserUpdate
from src.services.auth import get_user_by_id
from src.services.user import (
    create_user_admin,
    list_users,
    update_user_admin,
)

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=list[UserRead])
def list_users_admin(
    company_id: Optional[uuid.UUID] = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_superuser),
):
    return list_users(db, company_id=company_id)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user_admin_endpoint(
    data: UserAdminCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_superuser),
):
    return create_user_admin(db, data)


@router.patch("/{user_id}/admin", response_model=UserRead)
def update_user_admin_endpoint(
    user_id: uuid.UUID,
    data: UserAdminUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    return update_user_admin(db, user_id, data, acting_user=current_user)


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Object-level authorization: um usuário só pode ler o próprio registro.
    # O superuser (admin da plataforma) pode ler qualquer um. Sem esta checagem,
    # qualquer usuário autenticado leria os dados de outro pelo UUID (IDOR).
    if current_user.id != user_id and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to view another user",
        )

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
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to update another user",
        )

    if data.email is not None:
        current_user.email = data.email
    if data.password is not None:
        current_user.hashed_password = hash_password(data.password)

    db.commit()
    db.refresh(current_user)
    return current_user