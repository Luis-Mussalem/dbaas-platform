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

# auto_error=False: without an Authorization header it doesn't raise 401 right away —
# get_current_user tries the HttpOnly "access_token" cookie before rejecting.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def _read_active_company(request: Request, user: User) -> uuid.UUID | None:
    """
    Superuser's active company, read from the X-Company-Id header (Stage B).

    Only the superuser can "wear" a company; for a regular user the header is
    ignored (they're stuck with their own company). Missing/invalid header = None
    (superuser sees all).
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

    # The Authorization header takes precedence (API clients, Swagger, tests);
    # the HttpOnly cookie is the frontend's path (not exposed to XSS).
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

    # Stage B: attaches the active company (transient attribute, not a User column).
    # scoping (core/scoping.py) reads this to filter the superuser's data.
    user.active_company_id = _read_active_company(request, user)
    return user


def get_current_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Requires the authenticated user to be a superuser (platform admin).

    Reuses get_current_user (authentication) and adds the role check.
    First point where is_superuser is actually verified —
    the foundation for multi-tenancy: only the superuser sees/manages all companies.
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
    Requires the authenticated user to be a superuser or the admin of a company.

    This is the platform's write gate. The permission model has exactly one rule:

        **members observe, admins operate.**

    Every endpoint that CHANGES state — provisioning, starting and stopping,
    deleting, backing up and restoring, scheduling, maintenance, replication,
    alert rules, employee management — depends on this. Everything that only
    READS — metrics, health, logs, schema, slow queries, the fleet summary, the
    dashboard, and the SQL console (SELECT-only by construction) — depends on
    ``get_current_user`` and is open to every member of the company.

    Drawing the line at "does it mutate?" rather than per-endpoint judgement is
    deliberate: a `member` who could restore a backup would be able to overwrite
    the whole database with an old dump, and one who could delete an instance
    could destroy production — while an "obviously harmless" exception list is
    exactly the kind of thing that rots as endpoints are added. A member who
    needs to act asks an admin, which is what the role is for.

    Note the split of responsibilities: this dependency only proves "you are an
    admin SOMEWHERE". Proving the admin may touch this PARTICULAR resource is the
    scoping layer's job — ``get_instance_or_404`` (company filter) for instances
    and ``assert_can_manage_target`` for users — and both still run. Defense in
    depth: neither check alone is sufficient.
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
    # Multi-tenant scoping: a regular user can only find instances of their own company;
    # an instance from another company becomes 404 (same response as "doesn't exist" —
    # doesn't leak that it exists). Superuser passes through (sees all).
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