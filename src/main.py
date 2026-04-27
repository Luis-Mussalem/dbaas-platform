import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.core.config import settings
from src.core.rate_limit import limiter
from src.routers import auth, health, instances, users

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

    yield  # Aplicação em execução — processando requests

    # --- SHUTDOWN ---
    logger.info("Encerrando status poller...")
    stop_event.set()
    await poller_task
    logger.info("Encerramento concluído.")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
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
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(instances.router)