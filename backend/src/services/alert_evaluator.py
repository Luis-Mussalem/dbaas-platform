import asyncio
import logging

from src.core.database import SessionLocal

logger = logging.getLogger(__name__)

_EVALUATOR_INTERVAL_SECONDS = 60


def evaluate_once() -> None:
    """
    Runs one full alert evaluation cycle.

    Synchronous function called via asyncio.to_thread so it doesn't block the event loop.
    Opens and closes the database session explicitly in the finally — ensures the
    connection returns to the pool even if an exception occurs inside evaluate_all_rules.
    """
    from src.services.alert import evaluate_all_rules

    db = SessionLocal()
    try:
        evaluate_all_rules(db)
    except Exception as exc:
        logger.error("Error in alert evaluation cycle: %s", exc)
    finally:
        db.close()


async def alert_evaluation_loop(stop_event: asyncio.Event) -> None:
    """
    Async loop for the alert evaluator.

    Follows the same pattern as the project's other pollers (metrics_poller,
    backup_scheduler, maintenance_scheduler):
    - asyncio.to_thread for blocking operations (SQL + psycopg)
    - asyncio.wait_for with a safety timeout so it never hangs indefinitely
    - stop_event for graceful shutdown (comes from FastAPI's lifespan)
    - 60s interval aligned with metrics_poller — alerts evaluate the same
      data collected in the previous metrics cycle

    120s timeout: the cycle includes live connections to instances (long_query_seconds).
    120s gives enough margin for a 3s connect_timeout per instance on slow networks,
    without a stuck cycle blocking all subsequent ones indefinitely.
    """
    logger.info("Alert evaluation loop started")
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(
                asyncio.to_thread(evaluate_once),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Alert evaluation cycle exceeded the 120s timeout"
            )
        except Exception as exc:
            logger.error("Unexpected exception in alert evaluation loop: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_EVALUATOR_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            continue

    logger.info("Alert evaluation loop stopped")
