import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.rate_limit import limiter
from src.core.security import create_access_token, create_refresh_token
from src.models.user import User
from src.schemas.user import UserCreate, UserRead
from src.services.auth import (
    authenticate_user,
    blacklist_token,
    is_token_blacklisted,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


def _set_auth_cookies(response: Response, request: Request, access: str, refresh: str) -> None:
    """
    Grava os tokens em cookies HttpOnly — inacessíveis a JavaScript (anti-XSS).

    O corpo JSON com os tokens é mantido nos endpoints (Swagger, API clients e
    testes usam o header Authorization); o frontend usa só os cookies.
    """
    secure = request.url.scheme == "https"
    response.set_cookie(
        "access_token",
        access,
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    response.set_cookie(
        "refresh_token",
        refresh,
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
def register(request: Request, data: UserCreate, db: Session = Depends(get_db)):
    if not settings.REGISTRATION_ENABLED:
        user_count = db.query(User).count()
        if user_count > 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Registration is disabled",
            )
    return register_user(db, data)


@router.post("/login")
@limiter.limit("5/minute")
def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    _set_auth_cookies(response, request, access_token, refresh_token)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/refresh")
@limiter.limit("10/minute")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    # Header Authorization (API clients) tem precedência; cookie HttpOnly
    # é o caminho do frontend.
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    else:
        token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
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

        if user_id is None or token_type != "refresh" or jti is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    if is_token_blacklisted(db, jti):
        raise credentials_exception

    user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if user is None or not user.is_active:
        raise credentials_exception

    # Blacklist the consumed refresh token (token rotation — prevent reuse)
    ref_expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    blacklist_token(db, jti, "refresh", uuid.UUID(user_id), ref_expires_at)

    new_access_token = create_access_token({"sub": str(user.id)})
    new_refresh_token = create_refresh_token({"sub": str(user.id)})
    _set_auth_cookies(response, request, new_access_token, new_refresh_token)
    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    body: LogoutRequest = LogoutRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    else:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        jti = payload["jti"]
        token_type = payload["type"]
        exp = payload["exp"]
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
    except (JWTError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    blacklist_token(db, jti, token_type, current_user.id, expires_at)

    # Refresh token do corpo (API clients) ou do cookie (frontend).
    refresh_token = body.refresh_token or request.cookies.get("refresh_token")
    if refresh_token:
        try:
            ref_payload = jwt.decode(
                refresh_token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            ref_jti = ref_payload["jti"]
            ref_type = ref_payload["type"]
            ref_exp = ref_payload["exp"]
            if ref_type == "refresh":
                ref_expires_at = datetime.fromtimestamp(ref_exp, tz=timezone.utc)
                blacklist_token(db, ref_jti, ref_type, current_user.id, ref_expires_at)
        except (JWTError, KeyError):
            pass

    _clear_auth_cookies(response)
    return {"detail": "Successfully logged out"}


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)):
    return current_user