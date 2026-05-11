import asyncio
import logging

from src.core.database import SessionLocal

logger = logging.getLogger(__name__)

_EVALUATOR_INTERVAL_SECONDS = 60


def evaluate_once() -> None:
    """
    Executa um ciclo completo de avaliação de alertas.

    Função síncrona chamada via asyncio.to_thread para não bloquear o event loop.
    Abre e fecha a sessão de banco explicitamente no finally — garante que a
    conexão retorne ao pool mesmo em caso de exceção dentro de evaluate_all_rules.
    """
    from src.services.alert import evaluate_all_rules

    db = SessionLocal()
    try:
        evaluate_all_rules(db)
    except Exception as exc:
        logger.error("Erro no ciclo de avaliação de alertas: %s", exc)
    finally:
        db.close()


async def alert_evaluation_loop(stop_event: asyncio.Event) -> None:
    """
    Loop assíncrono do avaliador de alertas.

    Segue o padrão dos outros pollers do projeto (metrics_poller, backup_scheduler,
    maintenance_scheduler):
    - asyncio.to_thread para operações bloqueantes (SQL + psycopg)
    - asyncio.wait_for com timeout de segurança para não travar indefinidamente
    - stop_event para shutdown gracioso (vem do lifespan do FastAPI)
    - intervalo de 60s alinhado ao metrics_poller — alertas avaliam os mesmos
      dados coletados no ciclo anterior de métricas

    Timeout de 120s: o ciclo inclui conexões ao vivo a instâncias (long_query_seconds).
    120s dá margem para connect_timeout=3s por instância em redes lentas, sem
    que um ciclo travado bloqueie todos os subsequentes indefinidamente.
    """
    logger.info("Alert evaluation loop iniciado")
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(
                asyncio.to_thread(evaluate_once),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Ciclo de avaliação de alertas excedeu 120s de timeout"
            )
        except Exception as exc:
            logger.error("Exceção inesperada no alert evaluation loop: %s", exc)

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=_EVALUATOR_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            pass

    logger.info("Alert evaluation loop encerrado")
