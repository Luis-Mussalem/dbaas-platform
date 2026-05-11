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
    if not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1]
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


def _write_log(
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    user_id: Optional[uuid.UUID],
    ip_address: Optional[str],
    details: dict,
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
        db.add(AuditLog(
            user_id=user_id,
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
            ip_address = request.client.host if request.client else None
            details = {"method": method, "path": path, "status": response.status_code}

            _write_log(action, resource_type, resource_id, user_id, ip_address, details)
            break

        return response
