import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.database import get_db
from src.core.scoping import scope_instance_query, is_company_admin
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.user import User
from src.services.auth import is_token_blacklisted

# auto_error=False: sem header Authorization não levanta 401 na hora —
# get_current_user tenta o cookie HttpOnly "access_token" antes de rejeitar.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def _read_active_company(request: Request, user: User) -> uuid.UUID | None:
    """
    Empresa-ativa do superuser, lida do header X-Company-Id (Stage B).

    Só o superuser pode "vestir" uma empresa; para o usuário comum o header é
    ignorado (ele fica preso à própria empresa). Header ausente/ inválido = None
    (superuser vê todas).
    """
    if not user.is_superuser:
        return None
    raw = request.headers.get("X-Company-Id")
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Header Authorization tem precedência (API clients, Swagger, testes);
    # o cookie HttpOnly é o caminho do frontend (não exposto a XSS).
    if token is None:
        token = request.cookies.get("access_token")
    if token is None:
        raise credentials_exception

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

    # Stage B: anexa a empresa-ativa (atributo transiente, não é coluna do User).
    # O scoping (core/scoping.py) lê isto para filtrar os dados do superuser.
    user.active_company_id = _read_active_company(request, user)
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


def get_current_company_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Exige que o usuário autenticado seja superuser ou admin de uma empresa.

    Reusa get_current_user e adiciona a checagem de rol (role). O serviço
    é responsável por validar se o admin gerencia de fato o recurso-alvo
    (defense in depth). Este dependência apenas comprova "você é admin em
    algum lugar".
    """
    if not is_company_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


def get_instance_or_404(
    instance_id: uuid.UUID, db: Session, current_user: User
) -> DatabaseInstance:
    # Scoping multi-tenant: usuário comum só acha instâncias da própria empresa;
    # uma instância de outra empresa vira 404 (mesma resposta de "não existe" —
    # não vaza que ela existe). Superuser passa direto (vê todas).
    query = db.query(DatabaseInstance).filter(
        DatabaseInstance.id == instance_id,
        DatabaseInstance.deleted_at.is_(None),
    )
    instance = scope_instance_query(query, current_user).first()
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instance not found",
        )
    return instance


def get_instance_if_running(
    instance_id: uuid.UUID, db: Session, current_user: User
) -> DatabaseInstance:
    instance = get_instance_or_404(instance_id, db, current_user)
    if instance.status != InstanceStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Instance is not RUNNING (current status: {instance.status.value})",
        )
    return instance