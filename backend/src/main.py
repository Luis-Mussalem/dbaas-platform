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
from src.routers import admin, alerts, auth, backups, companies, health, instances, maintenance, metrics, query, replicas, users
from src.services.alert_evaluator import alert_evaluation_loop
from src.services.backup_scheduler import backup_scheduling_loop
from src.services.maintenance_scheduler import maintenance_scheduling_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the application's lifecycle (startup and shutdown).

    Why replace @app.on_event?
    The @app.on_event("startup/shutdown") decorator was deprecated in FastAPI 0.93+.
    The current pattern is a single async context manager that uses 'yield' to
    separate the startup code (before the yield) from the shutdown code (after).
    This guarantees shutdown always runs, even if there's an error at startup.

    What happens at startup:
    1. get_provisioner() — opens a connection to the Docker daemon via a Unix socket.
       If Docker isn't running, the application fails immediately with a
       clear message (fail fast), instead of failing silently on the first
       provisioning request.
    2. status_polling_loop — starts the background task that monitors containers.

    What happens at shutdown:
    1. stop_event.set() — signals the poller to exit its loop gracefully.
    2. await poller_task — waits for the task to finish before shutting down.
       This guarantees no database commit is left half-done when closing.
    """
    # --- STARTUP ---
    from src.services.provisioning import get_provisioner
    from src.services.provisioning.status_poller import status_polling_loop
    from src.services.metrics_poller import metrics_polling_loop
    from src.services.replication_poller import replication_polling_loop

    logger.info("Connecting to the Docker daemon...")
    try:
        get_provisioner()  # Initializes via lru_cache — fails fast if Docker is unavailable
        logger.info("Docker available. Provisioner ready.")
    except Exception as exc:
        raise RuntimeError(
            f"Could not connect to Docker. "
            f"Make sure the Docker Engine is running. Error: {exc}"
        ) from exc

    stop_event = asyncio.Event()
    poller_task = asyncio.create_task(status_polling_loop(stop_event))
    logger.info("Status poller started.")

    metrics_stop_event = asyncio.Event()
    metrics_poller_task = asyncio.create_task(
        metrics_polling_loop(metrics_stop_event)
    )
    logger.info("Metrics poller started.")

    backup_stop_event = asyncio.Event()
    backup_scheduler_task = asyncio.create_task(
        backup_scheduling_loop(backup_stop_event)
    )
    logger.info("Backup scheduler started.")

    maintenance_stop_event = asyncio.Event()
    maintenance_scheduler_task = asyncio.create_task(
        maintenance_scheduling_loop(maintenance_stop_event)
    )
    logger.info("Maintenance scheduler started.")

    alert_stop_event = asyncio.Event()
    alert_evaluator_task = asyncio.create_task(
        alert_evaluation_loop(alert_stop_event)
    )
    logger.info("Alert evaluator started.")

    replication_stop_event = asyncio.Event()
    replication_poller_task = asyncio.create_task(
        replication_polling_loop(replication_stop_event)
    )
    logger.info("Replication poller started.")

    # Demo mode: the baseline-load generator, which keeps the demo fleet alive
    # (light, continuous traffic) so the dashboard doesn't look dead on boot.
    demo_stop_event = asyncio.Event()
    demo_tasks: list[asyncio.Task] = []
    if settings.DEMO_MODE:
        from src.services.workload_simulator import workload_loop

        demo_tasks = [asyncio.create_task(workload_loop(demo_stop_event))]
        logger.info("Demo mode active: baseline-load generator ready.")

    yield  # Application running — processing requests

    # --- SHUTDOWN ---
    logger.info("Stopping pollers...")
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
    logger.info("Shutdown complete.")


# Description shown at the top of /docs (Swagger UI) and /redoc.
# Kept generic and reusable — no credentials, clients, or real data.
API_DESCRIPTION = """
PostgreSQL database management platform — provisioning, monitoring, automation
and data protection (DBA-as-a-Service).

**Pillars:** Monitoring · Backup & Recovery · Automated Maintenance · Proactive Alerting

All domain routes live under `/api/v1/`. `GET /health` stays at the root for
infrastructure probes and load balancers.
Most endpoints require Bearer JWT authentication (`POST /api/v1/auth/login`).
"""

# Order and description of the tags in /docs. FastAPI renders the groups in the
# order of this list — from the access flow (auth) to the admin panel.
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

# AuditMiddleware added last = innermost in the chain.
# Runs after the handler has already processed the request and the response is ready.
# This way, it only records actions the handler confirmed as successful (2xx).
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

# All domain routes live under /api/v1/.
# health.router stays at the root — load balancers and infra probes
# do GET /health directly, without knowing the API version.
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
app.include_router(api_v1)