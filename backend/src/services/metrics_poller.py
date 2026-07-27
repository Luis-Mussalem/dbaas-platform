import asyncio
import logging
from datetime import datetime, timedelta, timezone

from src.core.config import settings
from src.core.database import SessionLocal
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.metric import Metric
from src.services.metrics import collect_and_store

logger = logging.getLogger(__name__)

# Retention: delete metrics older than N days (default: 30 days)
METRICS_RETENTION_DAYS = 30

# Old-metrics cleanup: once a day, measured in TIME rather than in cycle
# count. Counting cycles, the periodicity would depend on the collection interval —
# in the demo it drops to 15s and cleanup would end up running every ~6h of wall clock,
# spending a DELETE that scans the table with nothing to delete.
_METRICS_CLEANUP_INTERVAL = timedelta(hours=24)
_last_metrics_cleanup: datetime | None = None


def poll_metrics_once() -> None:
    """
    Collects and persists metrics for all RUNNING instances.

    Identical pattern to status_poller's poll_once():
    - Direct SessionLocal() (background task — outside HTTP context)
    - connection_uri IS NOT NULL filter: defensive guarantee that
      provisioning completed before attempting to connect
    - Exception per instance: a problematic instance doesn't cancel the rest
    - finally: db.close() always runs

    Metrics retention:
    - Once every _METRICS_CLEANUP_INTERVAL, deletes metrics older than
      METRICS_RETENTION_DAYS days. Without retention, the metrics table would grow
      ~864,000 rows/day with 10 RUNNING instances.
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
                    "Instance %s: %d metrics collected and persisted",
                    instance.id,
                    count,
                )
            except Exception as exc:
                # Without a rollback, a failed commit leaves the shared session in
                # PendingRollbackError and takes down the remaining instances in the cycle.
                db.rollback()
                logger.exception(
                    "Error collecting metrics for instance %s: %s",
                    instance.id,
                    exc,
                )

        # Periodic cleanup of old metrics
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
    Async loop that runs poll_metrics_once() every
    settings.METRICS_POLL_INTERVAL_SECONDS.

    Identical pattern to status_polling_loop — clean shutdown via stop_event:
    asyncio.wait_for(stop_event.wait()) returns immediately when
    stop_event.set() is called in FastAPI's lifespan, ensuring
    the task finishes before the process exits.

    asyncio.to_thread(): poll_metrics_once() does blocking I/O (SQL on the
    platform database + psycopg on the instances' databases). The thread pool keeps
    the event loop free to process HTTP requests during collection.
    """
    interval = settings.METRICS_POLL_INTERVAL_SECONDS
    logger.info("Metrics poller started (interval: %ds)", interval)

    while not stop_event.is_set():
        try:
            await asyncio.to_thread(poll_metrics_once)
        except Exception as exc:
            logger.exception("Error in metrics collection cycle: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue

    logger.info("Metrics poller stopped")
