import asyncio
import logging
from datetime import datetime, timedelta, timezone

from src.core.config import settings
from src.core.database import SessionLocal
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.metric import Metric
from src.services.metrics import collect_and_store

logger = logging.getLogger(__name__)

# Retenção: apagar métricas com mais de N dias (padrão: 30 dias)
METRICS_RETENTION_DAYS = 30

# Limpeza de métricas antigas: uma vez por dia, medida em TEMPO e não em número
# de ciclos. Contando ciclos, a periodicidade dependia do intervalo de coleta —
# na demo ele cai para 15s e a limpeza passaria a rodar a cada ~6h de relógio,
# gastando um DELETE varrendo a tabela sem nada a apagar.
_METRICS_CLEANUP_INTERVAL = timedelta(hours=24)
_last_metrics_cleanup: datetime | None = None


def poll_metrics_once() -> None:
    """
    Coletar e persistir métricas de todas as instâncias RUNNING.

    Padrão idêntico ao poll_once() do status_poller:
    - SessionLocal() direto (task de background — fora de contexto HTTP)
    - Filtro connection_uri IS NOT NULL: garantia defensiva de que o
      provisionamento foi concluído antes de tentar conectar
    - Exceção por instância: uma instância problemática não cancela as demais
    - finally: db.close() sempre executa

    Retenção de métricas:
    - Uma vez a cada _METRICS_CLEANUP_INTERVAL, apaga métricas com mais de
      METRICS_RETENTION_DAYS dias. Sem retenção, a tabela metrics cresceria
      ~864.000 linhas/dia com 10 instâncias RUNNING.
    """
    global _last_metrics_cleanup

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
                # Sem rollback, um commit falho deixa a sessão compartilhada em
                # PendingRollbackError e derruba as instâncias seguintes do ciclo.
                db.rollback()
                logger.exception(
                    "Erro ao coletar métricas da instância %s: %s",
                    instance.id,
                    exc,
                )

        # Limpeza periódica de métricas antigas
        now = datetime.now(timezone.utc)
        if (
            _last_metrics_cleanup is None
            or now - _last_metrics_cleanup >= _METRICS_CLEANUP_INTERVAL
        ):
            _last_metrics_cleanup = now
            try:
                cutoff = now - timedelta(days=METRICS_RETENTION_DAYS)
                deleted = (
                    db.query(Metric)
                    .filter(Metric.collected_at < cutoff)
                    .delete(synchronize_session=False)
                )
                db.commit()
                if deleted:
                    logger.info(
                        "Metrics retention: %d records older than %d days removed",
                        deleted,
                        METRICS_RETENTION_DAYS,
                    )
            except Exception as exc:
                logger.warning("Metrics retention cleanup failed: %s", exc)

    finally:
        db.close()


async def metrics_polling_loop(stop_event: asyncio.Event) -> None:
    """
    Loop async que executa poll_metrics_once() a cada
    settings.METRICS_POLL_INTERVAL_SECONDS.

    Padrão idêntico ao status_polling_loop — shutdown limpo via stop_event:
    asyncio.wait_for(stop_event.wait()) retorna imediatamente quando
    stop_event.set() é chamado no lifespan do FastAPI, garantindo que
    a task termina antes do processo encerrar.

    asyncio.to_thread(): poll_metrics_once() faz I/O bloqueante (SQL no banco
    da plataforma + psycopg nos bancos das instâncias). Thread pool mantém
    o event loop livre para processar requests HTTP durante a coleta.
    """
    interval = settings.METRICS_POLL_INTERVAL_SECONDS
    logger.info("Metrics poller iniciado (intervalo: %ds)", interval)

    while not stop_event.is_set():
        try:
            await asyncio.to_thread(poll_metrics_once)
        except Exception as exc:
            logger.exception("Erro no ciclo de coleta de métricas: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue

    logger.info("Metrics poller encerrado")
