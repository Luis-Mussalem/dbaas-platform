import asyncio
import logging
import re
import uuid
from typing import Optional

from fastapi import Request, Response
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.config import settings
from src.core.database import SessionLocal

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Auditable action mapping
#
# Each entry: (HTTP method, path regex, action name, resource_type,
#              capture group number for resource_id — or None)
#
# The regex captures the resource_id directly from the path, without needing to parse
# the request body. Group 1 = first UUID in the path, group 2 = second.
# ─────────────────────────────────────────────────────────────────────────────
_AUDIT_ACTIONS = [
    ("POST",   re.compile(r"^/api/v1/auth/register$"),                          "register",                "user",            None),
    ("POST",   re.compile(r"^/api/v1/auth/login$"),                             "login",                   "auth",            None),
    ("POST",   re.compile(r"^/api/v1/auth/logout$"),                            "logout",                  "auth",            None),
    ("POST",   re.compile(r"^/api/v1/instances$"),                              "instance_created",        "instance",        None),
    ("PATCH",  re.compile(r"^/api/v1/instances/([^/]+)/status$"),               "instance_status_changed", "instance",        1),
    ("DELETE", re.compile(r"^/api/v1/instances/([^/]+)$"),                      "instance_deleted",        "instance",        1),
    ("POST",   re.compile(r"^/api/v1/instances/([^/]+)/backups$"),              "backup_created",          "backup",          1),
    ("POST",   re.compile(r"^/api/v1/backups/([^/]+)/restore$"),                "restore_initiated",       "backup",          1),
    ("POST",   re.compile(r"^/api/v1/instances/([^/]+)/schedules$"),            "schedule_created",        "backup_schedule", 1),
    ("DELETE", re.compile(r"^/api/v1/instances/([^/]+)/schedules/([^/]+)$"),    "schedule_deleted",        "backup_schedule", 2),
    ("POST",   re.compile(r"^/api/v1/instances/([^/]+)/maintenance/run$"),      "maintenance_run",         "maintenance",     1),
]


def _extract_user_id(request: Request) -> Optional[uuid.UUID]:
    """
    Decodes the JWT from the Authorization header to extract the user_id.

    Raises no exceptions: if the token is missing, expired, or invalid,
    silently returns None. The middleware must never reject a
    request — it only observes and records what went through.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth.split(" ", 1)[1]
    else:
        # Frontend authenticates via an HttpOnly cookie (no Authorization header).
        token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        raw_id = payload.get("sub")
        return uuid.UUID(raw_id) if raw_id else None
    except (JWTError, ValueError):
        return None


def _resolve_company_id(
    db,
    user_id: Optional[uuid.UUID],
    active_company_header: Optional[str],
) -> Optional[uuid.UUID]:
    """
    Resolves the company_id to be recorded in the audit log.

    Mirrors the semantics of visible_company_id (core/scoping.py):
    - regular user → their company_id;
    - superuser → UUID from the X-Company-Id header (None if missing/invalid);
    - unknown user (login/register, user_id=None) → None.
    NULL-company is only visible to a superuser-without-header, without leaking across tenants.
    """
    if user_id is None:
        return None
    from src.models.user import User
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None
    if user.is_superuser:
        if not active_company_header:
            return None
        try:
            return uuid.UUID(active_company_header)
        except ValueError:
            return None
    return user.company_id


def _write_log(
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    user_id: Optional[uuid.UUID],
    ip_address: Optional[str],
    details: dict,
    active_company_header: Optional[str] = None,
) -> None:
    """
    Writes an entry to the audit log with its own session.

    Why SessionLocal() instead of Depends(get_db)?
    The middleware doesn't participate in FastAPI's Depends cycle — it runs
    outside a handler's context. Creating its own session isolates the write
    from the request's session lifecycle: even if the handler's session
    is rolled back, the audit log is persisted.

    Write errors are swallowed: the log must not interrupt the response.
    """
    from src.models.audit_log import AuditLog

    db = SessionLocal()
    try:
        company_id = _resolve_company_id(db, user_id, active_company_header)
        db.add(AuditLog(
            user_id=user_id,
            company_id=company_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
        ))
        db.commit()
    except Exception as exc:
        logger.error("Failed to write audit log [%s/%s]: %s", action, resource_type, exc)
        db.rollback()
    finally:
        db.close()


class AuditMiddleware(BaseHTTPMiddleware):
    """
    Automatically records auditable actions, without touching business code.

    Works in three steps per request:
    1. Lets the handler process the request normally (call_next).
    2. If the response is 4xx/5xx (action failed), records nothing.
    3. If the response is 2xx, checks whether the path+method matches one
       of the actions in the _AUDIT_ACTIONS table and, if so, writes the audit log.

    Only successful responses (< 400) generate log entries.
    A login attempt with the wrong password does not generate a "login" audit log —
    the login didn't happen.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        if response.status_code >= 400:
            return response

        path = request.url.path
        method = request.method

        for req_method, pattern, action, resource_type, id_group in _AUDIT_ACTIONS:
            if method != req_method:
                continue
            match = pattern.match(path)
            if not match:
                continue

            resource_id = match.group(id_group) if id_group else None
            user_id = _extract_user_id(request)
            active_company_header = request.headers.get("X-Company-Id")
            ip_address = request.client.host if request.client else None
            details = {"method": method, "path": path, "status": response.status_code}

            # _write_log is synchronous I/O (SessionLocal); run in a thread so it doesn't
            # block the event loop while writing the audit log.
            await asyncio.to_thread(
                _write_log,
                action, resource_type, resource_id,
                user_id, ip_address, details, active_company_header,
            )
            break

        return response
