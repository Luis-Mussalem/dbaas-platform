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
# Mapeamento de ações auditáveis
#
# Cada entrada: (método HTTP, regex do path, nome da ação, resource_type,
#                número do grupo de captura para resource_id — ou None)
#
# O regex captura o resource_id diretamente do path, sem precisar parsear
# o body do request. Grupo 1 = primeiro UUID no path, grupo 2 = segundo.
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
    Decodifica o JWT do header Authorization para extrair o user_id.

    Não levanta exceções: se o token está ausente, expirado ou inválido,
    retorna None silenciosamente. O middleware nunca deve rejeitar um
    request — só observa e registra o que passou.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth.split(" ", 1)[1]
    else:
        # Frontend autentica via cookie HttpOnly (sem header Authorization).
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
    Resolve o company_id a ser gravado no audit log.

    Espelha a semântica de visible_company_id (core/scoping.py):
    - usuário comum → sua company_id;
    - superuser → UUID do header X-Company-Id (None se ausente/inválido);
    - usuário desconhecido (login/register, user_id=None) → None.
    NULL-company fica visível só ao superuser-sem-header, sem vazar entre tenants.
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
    Grava uma entrada no audit log com sessão própria.

    Por que SessionLocal() em vez de Depends(get_db)?
    O middleware não participa do ciclo de Depends do FastAPI — ele executa
    fora do contexto de um handler. Criar uma sessão própria isola a escrita
    do ciclo de vida da sessão do request: mesmo que a sessão do handler
    seja revertida, o audit log é persistido.

    Erros de escrita são absorvidos: o log não pode interromper a resposta.
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
        logger.error("Falha ao gravar audit log [%s/%s]: %s", action, resource_type, exc)
        db.rollback()
    finally:
        db.close()


class AuditMiddleware(BaseHTTPMiddleware):
    """
    Registra ações auditáveis automaticamente, sem tocar no código de negócio.

    Funciona em três etapas por request:
    1. Deixa o handler processar o request normalmente (call_next).
    2. Se o response for 4xx/5xx (ação falhou), não registra nada.
    3. Se o response for 2xx, verifica se o path+método corresponde a uma
       das ações na tabela _AUDIT_ACTIONS e, se sim, grava o audit log.

    Apenas respostas bem-sucedidas (< 400) geram entradas no log.
    Uma tentativa de login com senha errada não gera audit log de "login" —
    o login não aconteceu.
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

            # _write_log é I/O síncrono (SessionLocal); em thread para não
            # bloquear o event loop durante a escrita do audit log.
            await asyncio.to_thread(
                _write_log,
                action, resource_type, resource_id,
                user_id, ip_address, details, active_company_header,
            )
            break

        return response
