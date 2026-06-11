import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.core.audit_middleware import AuditMiddleware
from src.core.config import settings
from src.core.rate_limit import limiter
from src.routers import admin, alerts, auth, backups, companies, health, instances, maintenance, metrics, users
from src.services.alert_evaluator import alert_evaluation_loop
from src.services.backup_scheduler import backup_scheduling_loop
from src.services.maintenance_scheduler import maintenance_scheduling_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gerencia o ciclo de vida da aplicação (startup e shutdown).

    Por que substituir @app.on_event?
    O decorador @app.on_event("startup/shutdown") foi depreciado no FastAPI 0.93+.
    O padrão atual é um único context manager assíncrono que usa 'yield' para
    separar o código de inicialização (antes do yield) do de encerramento (após).
    Isso garante que o shutdown sempre executa, mesmo em caso de erro no startup.

    O que acontece no startup:
    1. get_provisioner() — abre conexão com o daemon Docker via socket Unix.
       Se o Docker não estiver rodando, a aplicação falha imediatamente com
       mensagem clara (fail fast), em vez de falhar silenciosamente no primeiro
       request de provisionamento.
    2. status_polling_loop — inicia a task de background que monitora containers.

    O que acontece no shutdown:
    1. stop_event.set() — sinaliza ao poller para sair do loop graciosamente.
    2. await poller_task — aguarda a task terminar antes de encerrar.
       Isso garante que nenhum commit de banco fica no meio ao fechar.
    """
    # --- STARTUP ---
    from src.services.provisioning import get_provisioner
    from src.services.provisioning.status_poller import status_polling_loop
    from src.services.metrics_poller import metrics_polling_loop

    logger.info("Conectando ao daemon Docker...")
    try:
        get_provisioner()  # Inicializa via lru_cache — falha rápido se Docker indisponível
        logger.info("Docker disponível. Provisioner pronto.")
    except Exception as exc:
        raise RuntimeError(
            f"Não foi possível conectar ao Docker. "
            f"Certifique-se de que o Docker Engine está rodando. Erro: {exc}"
        ) from exc

    stop_event = asyncio.Event()
    poller_task = asyncio.create_task(status_polling_loop(stop_event))
    logger.info("Status poller iniciado.")

    metrics_stop_event = asyncio.Event()
    metrics_poller_task = asyncio.create_task(
        metrics_polling_loop(metrics_stop_event)
    )
    logger.info("Metrics poller iniciado.")

    backup_stop_event = asyncio.Event()
    backup_scheduler_task = asyncio.create_task(
        backup_scheduling_loop(backup_stop_event)
    )
    logger.info("Backup scheduler iniciado.")

    maintenance_stop_event = asyncio.Event()
    maintenance_scheduler_task = asyncio.create_task(
        maintenance_scheduling_loop(maintenance_stop_event)
    )
    logger.info("Maintenance scheduler iniciado.")

    alert_stop_event = asyncio.Event()
    alert_evaluator_task = asyncio.create_task(
        alert_evaluation_loop(alert_stop_event)
    )
    logger.info("Alert evaluator iniciado.")

    yield  # Aplicação em execução — processando requests

    # --- SHUTDOWN ---
    logger.info("Encerrando pollers...")
    stop_event.set()
    metrics_stop_event.set()
    backup_stop_event.set()
    maintenance_stop_event.set()
    alert_stop_event.set()
    await poller_task
    await metrics_poller_task
    await backup_scheduler_task
    await maintenance_scheduler_task
    await alert_evaluator_task
    logger.info("Encerramento concluído.")


# Descrição exibida no topo do /docs (Swagger UI) e /redoc.
# Mantida genérica e reutilizável — sem credenciais, clientes ou dados reais.
API_DESCRIPTION = """
Plataforma de gestão de bancos PostgreSQL — provisionamento, monitoramento,
automação e proteção de dados (DBA-as-a-Service).

**Pilares:** Monitoramento · Backup & Recovery · Manutenção Automática · Alertas Proativos

Todas as rotas de domínio ficam sob `/api/v1/`. O `GET /health` permanece na
raiz para probes de infraestrutura e load balancers.
A maioria dos endpoints exige autenticação via Bearer JWT (`POST /api/v1/auth/login`).
"""

# Ordem e descrição das tags no /docs. O FastAPI renderiza os grupos na ordem
# desta lista — do fluxo de acesso (auth) ao painel administrativo.
openapi_tags = [
    {"name": "Health", "description": "Liveness/readiness da API e conectividade com o banco da plataforma."},
    {"name": "Authentication", "description": "Registro, login, refresh e logout. Emite e revoga tokens JWT."},
    {"name": "Users", "description": "Gestão self-service da conta do usuário autenticado."},
    {"name": "Companies", "description": "Empresas (multi-tenant). Restrito ao superusuário da plataforma."},
    {"name": "Instances", "description": "Ciclo de vida das instâncias de banco: criar, iniciar, parar e remover."},
    {"name": "Monitoring", "description": "Métricas, health, slow queries, locks, índices e bloat por instância."},
    {"name": "Backups", "description": "Backups lógicos (pg_dump) e físicos (pg_basebackup), restore e agendamento."},
    {"name": "Maintenance", "description": "VACUUM, ANALYZE, REINDEX, gestão de conexões e recomendações de tuning."},
    {"name": "Alerts", "description": "Regras de alerta, avaliação automática e histórico de eventos."},
    {"name": "Administration", "description": "Visão consolidada da plataforma e trilha de auditoria."},
]

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=API_DESCRIPTION,
    openapi_tags=openapi_tags,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# AuditMiddleware adicionado por último = mais interno na cadeia.
# Executa depois que o handler já processou o request e a resposta está pronta.
# Assim, só grava ações que o handler confirmou como bem-sucedidas (2xx).
app.add_middleware(AuditMiddleware)


@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


app.include_router(health.router)

# Todas as rotas de domínio ficam sob /api/v1/.
# health.router permanece na raiz — load balancers e probes de infra
# fazem GET /health diretamente, sem conhecer a versão da API.
api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(auth.router)
api_v1.include_router(users.router)
api_v1.include_router(companies.router)
api_v1.include_router(instances.router)
api_v1.include_router(metrics.router)
api_v1.include_router(backups.router)
api_v1.include_router(maintenance.router)
api_v1.include_router(alerts.router)
api_v1.include_router(admin.router)
app.include_router(api_v1)