import asyncio
import logging

from src.core.database import SessionLocal
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.services.metrics import collect_and_store

logger = logging.getLogger(__name__)

# Intervalo entre ciclos de coleta de métricas
_POLL_INTERVAL_SECONDS = 60


def poll_metrics_once() -> None:
    """
    Coletar e persistir métricas de todas as instâncias RUNNING.

    Padrão idêntico ao poll_once() do status_poller:
    - SessionLocal() direto (task de background — fora de contexto HTTP)
    - Filtro connection_uri IS NOT NULL: garantia defensiva de que o
      provisionamento foi concluído antes de tentar conectar
    - Exceção por instância: uma instância problemática não cancela as demais
    - finally: db.close() sempre executa
    """
    db = SessionLocal()
    try:
        instances = (
            db.query(DatabaseInstance)
            .filter(
                DatabaseInstance.status == InstanceStatus.RUNNING,
                DatabaseInstance.deleted_at.is_(None),
                DatabaseInstance.connection_uri.isnot(None),
            )
            .all()
        )

        for instance in instances:
            try:
                count = collect_and_store(db, instance)
                logger.debug(
                    "Instância %s: %d métricas coletadas e persistidas",
                    instance.id,
                    count,
                )
            except Exception as exc:
                logger.exception(
                    "Erro ao coletar métricas da instância %s: %s",
                    instance.id,
                    exc,
                )

    finally:
        db.close()


async def metrics_polling_loop(stop_event: asyncio.Event) -> None:
    """
    Loop async que executa poll_metrics_once() a cada _POLL_INTERVAL_SECONDS.

    Padrão idêntico ao status_polling_loop — shutdown limpo via stop_event:
    asyncio.wait_for(stop_event.wait()) retorna imediatamente quando
    stop_event.set() é chamado no lifespan do FastAPI, garantindo que
    a task termina antes do processo encerrar.

    asyncio.to_thread(): poll_metrics_once() faz I/O bloqueante (SQL no banco
    da plataforma + psycopg nos bancos das instâncias). Thread pool mantém
    o event loop livre para processar requests HTTP durante a coleta.
    """
    logger.info(
        "Metrics poller iniciado (intervalo: %ds)", _POLL_INTERVAL_SECONDS
    )

    while not stop_event.is_set():
        try:
            await asyncio.to_thread(poll_metrics_once)
        except Exception as exc:
            logger.exception("Erro no ciclo de coleta de métricas: %s", exc)

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=_POLL_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            pass  # Normal — intervalo expirou, próximo ciclo

    logger.info("Metrics poller encerrado")
