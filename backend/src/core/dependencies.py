import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.database import get_db
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.user import User
from src.services.auth import is_token_blacklisted

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id: str | None = payload.get("sub")
        token_type: str | None = payload.get("type")
        jti: str | None = payload.get("jti")

        if user_id is None or token_type != "access" or jti is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    if is_token_blacklisted(db, jti):
        raise credentials_exception

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_uuid).first()
    if user is None or not user.is_active:
        raise credentials_exception

    return user


def get_current_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Exige que o usuário autenticado seja superuser (admin da plataforma).

    Reusa get_current_user (autenticação) e adiciona a checagem de papel.
    Primeiro ponto onde is_superuser passa a ser efetivamente verificado —
    base para o multi-tenant: só o superuser enxerga/gerencia todas as empresas.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser privileges required",
        )
    return current_user


def get_instance_or_404(instance_id: uuid.UUID, db: Session) -> DatabaseInstance:
    instance = (
        db.query(DatabaseInstance)
        .filter(
            DatabaseInstance.id == instance_id,
            DatabaseInstance.deleted_at.is_(None),
        )
        .first()
    )
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instance not found",
        )
    return instance


def get_instance_if_running(instance_id: uuid.UUID, db: Session) -> DatabaseInstance:
    instance = get_instance_or_404(instance_id, db)
    if instance.status != InstanceStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Instance is not RUNNING (current status: {instance.status.value})",
        )
    return instance