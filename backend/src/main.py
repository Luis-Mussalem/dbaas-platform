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
from src.routers import admin, alerts, auth, backups, companies, demo, health, instances, maintenance, metrics, query, replicas, users
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
    from src.services.replication_poller import replication_polling_loop

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

    replication_stop_event = asyncio.Event()
    replication_poller_task = asyncio.create_task(
        replication_polling_loop(replication_stop_event)
    )
    logger.info("Replication poller iniciado.")

    # Modo demo: o diretor do roteiro + o gerador de carga. Ambos ficam ociosos
    # até o usuário clicar em "Simular uso" — no boot, a frota é 100% real.
    demo_stop_event = asyncio.Event()
    demo_tasks: list[asyncio.Task] = []
    if settings.DEMO_MODE:
        from src.services.demo_simulation import simulation_loop
        from src.services.workload_simulator import workload_loop

        demo_tasks = [
            asyncio.create_task(simulation_loop(demo_stop_event)),
            asyncio.create_task(workload_loop(demo_stop_event)),
        ]
        logger.info("Demo mode ativo: diretor da simulação e gerador de carga prontos.")

    yield  # Aplicação em execução — processando requests

    # --- SHUTDOWN ---
    logger.info("Encerrando pollers...")
    stop_event.set()
    metrics_stop_event.set()
    backup_stop_event.set()
    maintenance_stop_event.set()
    alert_stop_event.set()
    replication_stop_event.set()
    demo_stop_event.set()
    await poller_task
    await metrics_poller_task
    await backup_scheduler_task
    await maintenance_scheduler_task
    await alert_evaluator_task
    await replication_poller_task
    for task in demo_tasks:
        await task
    if demo_tasks:
        # A thread das ações do roteiro é um executor próprio, fora do event
        # loop: sem este join, um pg_dump em curso é abandonado no meio.
        from src.services.demo_simulation import shutdown_action_executor

        shutdown_action_executor()
    logger.info("Encerramento concluído.")


# Descrição exibida no topo do /docs (Swagger UI) e /redoc.
# Mantida genérica e reutilizável — sem credenciais, clientes ou dados reais.
API_DESCRIPTION = """
PostgreSQL database management platform — provisioning, monitoring, automation
and data protection (DBA-as-a-Service).

**Pillars:** Monitoring · Backup & Recovery · Automated Maintenance · Proactive Alerting

All domain routes live under `/api/v1/`. `GET /health` stays at the root for
infrastructure probes and load balancers.
Most endpoints require Bearer JWT authentication (`POST /api/v1/auth/login`).
"""

# Ordem e descrição das tags no /docs. O FastAPI renderiza os grupos na ordem
# desta lista — do fluxo de acesso (auth) ao painel administrativo.
openapi_tags = [
    {"name": "Health", "description": "API liveness/readiness and connectivity to the platform database."},
    {"name": "Authentication", "description": "Register, login, refresh and logout. Issues and revokes JWT tokens."},
    {"name": "Users", "description": "Self-service management of the authenticated user's account."},
    {"name": "Companies", "description": "Companies (multi-tenant). Restricted to the platform superuser."},
    {"name": "Instances", "description": "Database instance lifecycle: create, start, stop and delete."},
    {"name": "Monitoring", "description": "Metrics, health, slow queries, locks, indexes and bloat per instance."},
    {"name": "SQL Console", "description": "Read-only SELECT execution and query plans (EXPLAIN) per instance."},
    {"name": "Backups", "description": "Logical (pg_dump) and physical (pg_basebackup) backups, restore and scheduling."},
    {"name": "Maintenance", "description": "VACUUM, ANALYZE, REINDEX, connection management and tuning recommendations."},
    {"name": "Alerts", "description": "Alert rules, automatic evaluation and event history."},
    {"name": "Replication", "description": "Streaming standbys, lag monitoring and promotion (manual failover)."},
    {"name": "Administration", "description": "Consolidated platform view and audit trail."},
    {"name": "Demo", "description": "Scripted usage simulation on the demo fleet (demo mode only)."},
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
    allow_headers=["Authorization", "Content-Type", "X-Company-Id"],
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
    logger.exception(
        "Unhandled exception on %s %s: %s", request.method, request.url.path, exc
    )
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
api_v1.include_router(query.router)
api_v1.include_router(backups.router)
api_v1.include_router(maintenance.router)
api_v1.include_router(alerts.router)
api_v1.include_router(replicas.router)
api_v1.include_router(admin.router)
api_v1.include_router(demo.router)
app.include_router(api_v1)