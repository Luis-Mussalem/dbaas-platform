import asyncio
import logging
from collections import defaultdict

from src.core.database import SessionLocal
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.replica import Replica, ReplicationState
from src.services.metrics import get_connection

logger = logging.getLogger(__name__)

# Interval between lag measurement cycles
_POLL_INTERVAL_SECONDS = 30

# Above this delay (1 WAL segment = 16 MiB) the replica is considered in CATCHUP,
# not stable STREAMING — it signals it's still catching up to the primary.
_CATCHUP_THRESHOLD_BYTES = 16 * 1024 * 1024

# pg_stat_replication lives on the PRIMARY and lists each connected standby. We measure the
# replay delay in bytes (how far behind the standby is from the current WAL) and in
# seconds (replay_lag). Ordered by the worst delay first.
_LAG_QUERY = """
    SELECT
        pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)::bigint AS lag_bytes,
        EXTRACT(EPOCH FROM replay_lag)::float AS lag_seconds
    FROM pg_stat_replication
    ORDER BY replay_lag DESC NULLS LAST
"""


def poll_replication_once() -> None:
    """
    Updates the state and lag of each active replica by querying the primary.

    Same pattern as the other pollers: its own SessionLocal(), try/rollback per
    group (a problematic replica doesn't take down the others), finally: close.

    Assumed simplification: a primary usually has one standby. When there's more than
    one replica on the same primary, we apply the worst observed lag to all of them — without
    trying to match row↔replica by application_name (out of scope for this project).
    """
    db = SessionLocal()
    try:
        active = (
            db.query(Replica)
            .filter(
                Replica.replication_state.notin_(
                    [ReplicationState.PROMOTED, ReplicationState.FAILED]
                )
            )
            .all()
        )

        by_primary: dict = defaultdict(list)
        for replica in active:
            by_primary[replica.primary_instance_id].append(replica)

        for primary_id, group in by_primary.items():
            try:
                primary = (
                    db.query(DatabaseInstance)
                    .filter(
                        DatabaseInstance.id == primary_id,
                        DatabaseInstance.deleted_at.is_(None),
                        DatabaseInstance.connection_uri.isnot(None),
                    )
                    .first()
                )
                # Primary unavailable → no way to measure; marks disconnected.
                if not primary or primary.status != InstanceStatus.RUNNING:
                    for replica in group:
                        replica.replication_state = ReplicationState.DISCONNECTED
                    db.commit()
                    continue

                with get_connection(primary) as conn:
                    with conn.cursor() as cur:
                        cur.execute(_LAG_QUERY)
                        rows = cur.fetchall()

                if rows:
                    lag_bytes, lag_seconds = rows[0]
                    lag_bytes = int(lag_bytes) if lag_bytes is not None else None
                    lag_seconds = float(lag_seconds) if lag_seconds is not None else None
                    state = (
                        ReplicationState.CATCHUP
                        if (lag_bytes or 0) > _CATCHUP_THRESHOLD_BYTES
                        else ReplicationState.STREAMING
                    )
                    for replica in group:
                        replica.lag_bytes = lag_bytes
                        replica.lag_seconds = lag_seconds
                        replica.replication_state = state
                else:
                    # No rows on the primary → no standby is streaming.
                    for replica in group:
                        replica.replication_state = ReplicationState.DISCONNECTED
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.exception(
                    "Error measuring replication for primary %s: %s", primary_id, exc
                )
    finally:
        db.close()


async def replication_polling_loop(stop_event: asyncio.Event) -> None:
    """
    Async loop that runs poll_replication_once() every _POLL_INTERVAL_SECONDS.

    Same clean shutdown as the other pollers (asyncio.wait_for on the stop_event);
    the blocking work (SQL on the platform + psycopg on the primary) goes to the
    thread pool via asyncio.to_thread so it doesn't block the event loop.
    """
    logger.info(
        "Replication poller started (interval: %ds)", _POLL_INTERVAL_SECONDS
    )

    while not stop_event.is_set():
        try:
            await asyncio.to_thread(poll_replication_once)
        except Exception as exc:
            logger.exception("Error in replication measurement cycle: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass

    logger.info("Replication poller stopped")
