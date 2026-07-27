import logging
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Generator

import psycopg
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.collectors.pg_stats import (
    collect_active_connections,
    collect_base_metrics,
    collect_bloat,
    collect_explain,
    collect_index_stats,
    collect_locks,
    collect_latency_percentiles,
    collect_schema,
    collect_slow_queries,
)
from src.core.encryption import decrypt_value
from src.models.database_instance import DatabaseInstance
from src.models.metric import Metric

logger = logging.getLogger(__name__)


@contextmanager
def get_connection(
    instance: DatabaseInstance,
) -> Generator[psycopg.Connection, None, None]:
    """
    Context manager that decrypts the connection URI and opens a psycopg
    connection to the managed instance's database.

    The decrypted URI exists only inside this 'with' block. Upon leaving the
    context manager — whether by success or exception — the 'uri' variable is
    collected by the GC. It is never logged, never sent to the platform's
    database, never shows up in stack traces.
    """
    uri = decrypt_value(instance.connection_uri)
    # statement_timeout caps any query on this connection (30s). Covers the
    # monitoring reads — especially EXPLAIN ANALYZE, which actually executes the
    # query: without the cap, a `SELECT pg_sleep(...)` would hold the thread pool
    # worker indefinitely. The maintenance connection (VACUUM/REINDEX) does
    # NOT use this helper on purpose — those operations can be long-running.
    with psycopg.connect(
        uri,
        connect_timeout=5,
        options="-c statement_timeout=30000",
    ) as conn:
        yield conn


def _latest_values(
    db: Session,
    instance_id: uuid.UUID,
    names: tuple[str, ...],
) -> dict[str, float]:
    """Latest value of each metric in `names` (missing ones are left out)."""
    subq = (
        db.query(
            Metric.metric_name,
            func.max(Metric.collected_at).label("max_collected_at"),
        )
        .filter(Metric.instance_id == instance_id, Metric.metric_name.in_(names))
        .group_by(Metric.metric_name)
        .subquery()
    )
    rows = (
        db.query(Metric.metric_name, Metric.value)
        .join(
            subq,
            (Metric.metric_name == subq.c.metric_name)
            & (Metric.collected_at == subq.c.max_collected_at),
        )
        .filter(Metric.instance_id == instance_id)
        .all()
    )
    return {name: value for name, value in rows}


def _interval_cache_hit_ratio(
    db: Session,
    instance_id: uuid.UUID,
    blks_hit: float,
    blks_read: float,
) -> float | None:
    """
    Cache hit ratio for the INTERVAL between this collection and the previous one, in %.

    pg_stat_database only exposes cumulative counters; the ratio over them measures the
    server's entire lifetime, not the present. A database that spent the day at 99%
    would keep reporting ~99% during a whole hour of disk reads —
    and, worse, a restart zeroes the counters and the ratio collapses toward 0%
    even though the database is healthy. Deriving from the delta answers the question
    the alert actually asks: "right now, is it reading from cache?".

    Returns None when the interval doesn't allow an honest answer:
    - no previous collection (the instance's first) → there's no delta;
    - the counter went backwards → the server restarted and reset the statistics;
    - no blocks read in the interval → the database is idle, the ratio is undefined.

    In the last two cases it returns the previous value, if any: a repeated
    data point is better than a false "0%" that would open an alert on its own.
    """
    prev = _latest_values(db, instance_id, ("blks_hit", "blks_read", "cache_hit_ratio"))
    prev_hit = prev.get("blks_hit")
    prev_read = prev.get("blks_read")
    carry = prev.get("cache_hit_ratio")

    if prev_hit is None or prev_read is None:
        return None

    if blks_hit < prev_hit or blks_read < prev_read:
        return carry

    delta_total = (blks_hit - prev_hit) + (blks_read - prev_read)
    if delta_total <= 0:
        return carry

    return round((blks_hit - prev_hit) / delta_total * 100.0, 2)


def collect_and_store(db: Session, instance: DatabaseInstance) -> int:
    """
    Collects base metrics for the instance and persists them into the metrics table.

    Called by the metrics_poller every 60s for RUNNING instances.
    The 'collected_at' timestamp is generated in Python to guarantee that
    all records from the same cycle have exactly the same value,
    making it easy to query "metrics collected together in the last cycle".

    Returns the number of metrics persisted.
    """
    # A single connection collects both the base metrics AND the latency percentiles
    # (avoids opening two connections per cycle). The percentiles come from
    # pg_stat_statements and degrade to {} on instances without the extension.
    with get_connection(instance) as conn:
        raw = collect_base_metrics(conn)
        percentiles = collect_latency_percentiles(conn)

    if not raw:
        return 0

    # Must run BEFORE the insert: the ratio comes from the delta against the previous
    # collection, which would stop being "the previous one" as soon as these rows go in.
    if "blks_hit" in raw and "blks_read" in raw:
        ratio = _interval_cache_hit_ratio(
            db, instance.id, raw["blks_hit"], raw["blks_read"]
        )
        if ratio is None:
            raw.pop("cache_hit_ratio", None)
        else:
            raw["cache_hit_ratio"] = ratio

    now = datetime.now(timezone.utc)
    metrics = [
        Metric(
            instance_id=instance.id,
            metric_name=name,
            value=value,
            collected_at=now,
        )
        for name, value in raw.items()
    ]
    metrics.extend(
        Metric(
            instance_id=instance.id,
            metric_name=name,
            value=value,
            collected_at=now,
        )
        for name, value in percentiles.items()
    )

    db.add_all(metrics)
    db.commit()
    return len(metrics)


def get_latest_metrics(
    db: Session,
    instance_id: uuid.UUID,
) -> dict[str, float]:
    """
    Returns the most recent value of each metric for the instance.

    A subquery finds MAX(collected_at) per metric_name, then a join
    fetches the corresponding values. The composite index
    (instance_id, metric_name, collected_at) guarantees an index scan.

    Returns {} if no metric has been collected yet.
    """
    subq = (
        db.query(
            Metric.metric_name,
            func.max(Metric.collected_at).label("max_collected_at"),
        )
        .filter(Metric.instance_id == instance_id)
        .group_by(Metric.metric_name)
        .subquery()
    )

    rows = (
        db.query(Metric.metric_name, Metric.value)
        .join(
            subq,
            (Metric.metric_name == subq.c.metric_name)
            & (Metric.collected_at == subq.c.max_collected_at),
        )
        .filter(Metric.instance_id == instance_id)
        .all()
    )

    return {name: value for name, value in rows}


# Points returned by get_metric_history. The series is resampled down to this
# ceiling: a ~500px sparkline can't show more than that, and the chart would be
# hostage to the collection cadence — which varies (60s normal, 5s during the usage
# simulation). With a fixed bucket, the SAME window always draws the same shape.
_HISTORY_MAX_POINTS = 120


# "Virtual" metrics that aren't stored raw: they're derived from a cumulative
# counter already collected. queries_per_second comes from the derivative of xact_commit —
# the same counter that feeds the card's number (services.fleet_summary), now
# exposed as a series for the chart.
_DERIVED_RATE_SOURCE = {"queries_per_second": "xact_commit"}


def _bucketed_avg(
    db: Session,
    instance_id: uuid.UUID,
    metric_name: str,
    since: datetime,
    bucket_seconds: int,
) -> list[tuple[datetime, float]]:
    """Series of ONE metric, resampled into buckets of `bucket_seconds` (average per bucket)."""
    # floor(epoch / bucket) * bucket → start of the bucket; average within it.
    bucket_start = func.to_timestamp(
        func.floor(func.extract("epoch", Metric.collected_at) / bucket_seconds)
        * bucket_seconds
    ).label("bucket_start")

    rows = (
        db.query(bucket_start, func.avg(Metric.value).label("value"))
        .filter(
            Metric.instance_id == instance_id,
            Metric.metric_name == metric_name,
            Metric.collected_at >= since,
        )
        .group_by(bucket_start)
        .order_by(bucket_start.asc())
        .all()
    )
    return [(row.bucket_start, float(row.value)) for row in rows]


# Below this fraction of the "clean" value, a drop in the counter is a real RESET
# (Postgres restart), not a stale reading from pg_stat_database. Same rule as
# fleet_summary, so the chart and the number treat the same data the same way.
_RATE_RESET_FRACTION = 0.5


def _counter_rate(buckets: list[tuple[datetime, float]]) -> list[tuple[datetime, float]]:
    """
    Derives a rate (per second) from an already-bucketed cumulative counter:
    Δcounter / Δseconds between consecutive buckets, dated at the newest bucket.

    The counter is NON-DECREASING, but pg_stat_database sometimes returns a
    STALE reading (an old snapshot) that makes a bucket "dip" slightly. That
    point is SKIPPED (it emits neither 0 nor a spike): we keep the last clean value and the
    next real bucket measures growth over the larger interval — the line
    interpolates over the gap and stays smooth, without the sawtooth the card used to show. A
    LARGE drop (< _RATE_RESET_FRACTION) is a genuine reset: re-anchor and continue.
    """
    series: list[tuple[datetime, float]] = []
    if not buckets:
        return series
    prev_t, clean = buckets[0]
    for t_cur, v_cur in buckets[1:]:
        if v_cur >= clean:  # real growth
            dt = (t_cur - prev_t).total_seconds()
            if dt > 0:
                series.append((t_cur, round((v_cur - clean) / dt, 2)))
            prev_t, clean = t_cur, v_cur
        elif v_cur < clean * _RATE_RESET_FRACTION:  # counter reset: re-anchor
            prev_t, clean = t_cur, v_cur
        # otherwise: stale reading (small dip) → skip the point, keep clean/prev_t
    return series


# A rate derived from a counter is inherently noisy over short buckets: a
# bursty load measured every 15s jumps a lot from one bucket to the next (one bucket
# catches the burst, its neighbor catches the lull). We always present the trailing
# average of the last ~1 min, so each point is the average of the buckets covering 60s. The line
# still advances on every bucket (stays responsive, without turning into 1 point/min) but
# without the jaggedness. In windows where the bucket is already ≥ 60s this becomes a
# no-op (a 1-point window). Applies to both the CHART and the NUMBER (services.fleet_summary
# averages THIS series), so both keep telling the same story.
_RATE_SMOOTHING_SECONDS = 60


def _trailing_mean(
    series: list[tuple[datetime, float]], window: int
) -> list[tuple[datetime, float]]:
    """
    Trailing moving average of `window` points, dated at the newest point of each
    window. The window shrinks at the start of the series (the 1st point is itself), so
    no point is dropped — the sparkline keeps the same point count.
    """
    if window <= 1 or len(series) < 2:
        return series
    values = [value for _, value in series]
    smoothed: list[tuple[datetime, float]] = []
    for i, (t_cur, _) in enumerate(series):
        chunk = values[max(0, i - window + 1) : i + 1]
        smoothed.append((t_cur, round(sum(chunk) / len(chunk), 2)))
    return smoothed


def get_metric_history(
    db: Session,
    instance_id: uuid.UUID,
    metric_name: str,
    minutes: int,
    max_points: int = _HISTORY_MAX_POINTS,
) -> list[tuple[datetime, float]]:
    """
    Returns the time series of ONE metric in the window [now - minutes, now],
    resampled into up to _HISTORY_MAX_POINTS buckets with the AVERAGE of each.

    Reads from the metrics table (platform database) — does not connect to the monitored database.
    The per-bucket average is what gives the smooth curve: without it, a 24h window with
    5s collection would bring back ~17 thousand points and the sparkline would turn into a
    sawtooth (that's exactly what happened when the simulation sped up the poller). Aggregating in
    the database also avoids transferring thousands of points to draw 500 pixels.

    The bucket is derived from the window (24h ÷ 120 = 12 min), so the resolution is
    stable regardless of how many samples exist within it.

    `queries_per_second` is a DERIVED metric: it isn't stored raw, so its
    series comes from the derivative of the `xact_commit` counter (see _DERIVED_RATE_SOURCE) and
    goes through a ~1 min moving average (see _trailing_mean) — the rate of a bursty
    load is too noisy in 15s buckets.
    """
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    bucket_seconds = max(1, (minutes * 60) // max(1, max_points))

    source = _DERIVED_RATE_SOURCE.get(metric_name)
    if source is not None:
        rate = _counter_rate(_bucketed_avg(db, instance_id, source, since, bucket_seconds))
        smoothing = max(1, round(_RATE_SMOOTHING_SECONDS / bucket_seconds))
        return _trailing_mean(rate, smoothing)

    return _bucketed_avg(db, instance_id, metric_name, since, bucket_seconds)


def check_health(instance: DatabaseInstance) -> dict:
    """
    Checks the database's connectivity and responsiveness with a timed SELECT 1.

    response_time_ms includes: TCP handshake, PostgreSQL authentication,
    executing SELECT 1, and the return trip — real end-to-end latency.
    Returns 'unhealthy' on any exception, without raising a 5xx.
    """
    uri = decrypt_value(instance.connection_uri)
    start = time.monotonic()
    try:
        with psycopg.connect(uri, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        response_time_ms = (time.monotonic() - start) * 1000
        return {
            "status": "healthy",
            "response_time_ms": round(response_time_ms, 2),
            "checked_at": datetime.now(timezone.utc),
        }
    except Exception as exc:
        response_time_ms = (time.monotonic() - start) * 1000
        logger.warning(
            "Health check failed for instance %s: %s", instance.id, exc
        )
        return {
            "status": "unhealthy",
            "response_time_ms": round(response_time_ms, 2),
            "checked_at": datetime.now(timezone.utc),
        }


def get_slow_queries(
    instance: DatabaseInstance,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Returns slow queries via pg_stat_statements."""
    with get_connection(instance) as conn:
        return collect_slow_queries(conn, limit=limit)


def get_index_stats(instance: DatabaseInstance) -> list[dict[str, Any]]:
    """Returns index statistics via pg_stat_user_indexes."""
    with get_connection(instance) as conn:
        return collect_index_stats(conn)


def get_locks(instance: DatabaseInstance) -> list[dict[str, Any]]:
    """Returns active locks on tables via pg_locks."""
    with get_connection(instance) as conn:
        return collect_locks(conn)


def get_bloat(instance: DatabaseInstance) -> list[dict[str, Any]]:
    """Returns an estimate of bloat per table via pg_stat_user_tables."""
    with get_connection(instance) as conn:
        return collect_bloat(conn)


def get_explain(instance: DatabaseInstance, query: str) -> list:
    """Runs EXPLAIN ANALYZE for a SELECT query."""
    with get_connection(instance) as conn:
        return collect_explain(conn, query)


def get_active_connections(
    instance: DatabaseInstance,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Lists active connections via pg_stat_activity."""
    with get_connection(instance) as conn:
        return collect_active_connections(conn, limit=limit)


def get_schema(instance: DatabaseInstance) -> list[dict[str, Any]]:
    """
    Returns tables grouped by schema (with an estimated row count).

    Groups the collector's flat rows into [{name, tables:[{table, estimated_rows}]}],
    preserving the (schema, table) order already guaranteed by the query.
    """
    with get_connection(instance) as conn:
        rows = collect_schema(conn)

    groups: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row["schema_name"]
        group = by_name.get(name)
        if group is None:
            group = {"name": name, "tables": []}
            by_name[name] = group
            groups.append(group)
        group["tables"].append(
            {"table": row["table"], "estimated_rows": row["estimated_rows"]}
        )
    return groups
