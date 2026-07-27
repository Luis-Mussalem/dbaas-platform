"""
Synthetic load generator for the demo fleet.

A clean clone brings up real PostgreSQL containers, but nobody uses them: the poller
measures 1 connection, 0 transactions/s, and pg_stat_statements stays empty. The product
works, it just looks turned off — flat sparklines, zeroed KPIs, no slow
query to investigate.

This background loop gives these instances "life": it keeps a pool of open
connections whose size follows a daily curve (peak in the afternoon, trough in the
early hours, weaker on weekends) and fires off a mix of queries per cycle.
Everything the rest of the platform measures gets a real signal — connections,
transactions/s, cache hit, p95 latency, slow queries, disk growth.

In demo mode it runs all the time at a light **baseline load**
(`BASELINE_INTENSITY`), so the fleet never looks dead from the first login onward.
Outside demo mode the loops don't even start (main.py), so instances created by the
user never receive load.

Scope and safety:
- Only touches instances of the demo fleet (`notes == DEMO_MARKER`), RUNNING and with a
  connection_uri. Instances created by the user never receive load.
- Only runs with `DEMO_MODE=true` and the simulation active; the connection cap per
  instance is configurable (`DEMO_WORKLOAD_MAX_CONNECTIONS`).
- Connections use application_name='dbaas-demo-workload', so they show up
  identified on the active-connections screen — none of this disguises itself as
  user traffic.
- Writes are confined to the `workload_events` table, created by this module.
  The seeded business schema (catalog + fact table payments/sales) is only read.

The SAME curve (`target_connections`) feeds the seed's historical backfill,
so the 24h chart joins up seamlessly at the point where the synthetic history
ends and the live load begins.
"""
import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from math import cos, pi

import psycopg
from psycopg import sql as psql

from src.core.config import settings
from src.core.database import SessionLocal
from src.core.encryption import decrypt_value
from src.models.database_instance import DatabaseInstance, Environment, InstanceStatus

logger = logging.getLogger(__name__)

# Name the simulator's connections identify themselves with in pg_stat_activity.
APPLICATION_NAME = "dbaas-demo-workload"

# Table the simulator writes to (created on the first pass through an instance).
WORKLOAD_TABLE = "workload_events"

# Rows kept in the write table: continuous inserting would make the database grow
# without bound, and the size chart would turn into an infinite ramp.
_WORKLOAD_TABLE_MAX_ROWS = 2_000

# Hour (UTC) of peak traffic. The fleet is global (us/eu/sa), so a single
# curve with a per-instance offset is more honest than faking a timezone per region.
_PEAK_HOUR_UTC = 15.0

# Floor of the curve: even in the early hours a real app keeps idle connections.
_TROUGH_FACTOR = 0.18

# Weekends move less.
_WEEKEND_FACTOR = 0.55

# Max pool-size change per cycle — a smooth ramp instead of a step. With the
# simulation's sped-up cycle (5s), 4 connections per step gets the pool to
# target within the WARMUP phase's 18s without turning into an instant jump.
_MAX_POOL_STEP = 4

# Rows scanned by the mix's heavy query: an "hourly revenue" aggregation over a
# LIMITED slice of the business fact table (payments/sales). ~20k rows
# scanned + aggregated cost tens of ms against ~2 ms for a point read: enough of a
# tail to show up in p95 and pg_stat_statements, while still well below
# statement_timeout. Fires roughly once every 10s per instance (5% of the mix) — a
# pricey business query, not a load test.
_HEAVY_QUERY_ROWS = 20_000

# Fraction of the connection target the demo fleet keeps at rest — the continuous
# baseline load that keeps the dashboard alive from the first login onward (connections, queries/s,
# latency, and disk growth always with a real, measured signal). The seed's 24h
# backfill uses the SAME fraction (see seed/history), so the history joins up with the
# live measurement without a step. Tunable: raising it makes the fleet at rest more
# active, at the cost of more open connections per instance.
BASELINE_INTENSITY = 0.3

# Fraction of the pool's connections that fires a query on each _drive cycle. Each
# query runs in autocommit (= 1 transaction = 1 xact_commit), so this fraction is what
# converts "open connections" into "commits per cycle" — the basis of queries/s.
# Named because `target_queries_per_second` needs the SAME value that _drive uses
# to model the rate the poller will measure.
_ACTIVE_FRACTION = 0.45

# How many LIGHT queries each active connection fires per cycle. This is what gives a
# live queries/s (~6-12/s in prod, ~3-6/s in staging) instead of ~0.1/s, which the card
# used to round down to "0". These are point, indexed reads (microseconds), so the
# volume is cheap — the HEAVY query is kept out of the burst (_HEAVY_QUERY_PROB), so
# traffic doesn't turn into a load test.
#
# Sized TOGETHER with DEMO_WORKLOAD_INTERVAL_SECONDS (5s): the baseline rate is
# `_ACTIVE_FRACTION × conns × this / interval`, so smaller, more frequent
# bursts (5s) give the SAME queries/s as 100/15s, but spread out — each
# 15s collection window covers ~3 bursts, which removes the aliasing from the
# queries/s chart (before, poll and burst shared the same 15s period and beat against each other).
_QUERIES_PER_ACTIVE_CONN = 33

# Probability that an active connection fires ONE heavy query in the cycle — the tail
# that populates the slow-queries screen. Rare on purpose (outside the light burst): it's
# the same sparse cadence as before, now independent of the read volume.
_HEAVY_QUERY_PROB = 0.05


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Traffic curve (shared with the seed's historical backfill)
# --------------------------------------------------------------------------- #
def _instance_phase_hours(name: str) -> float:
    """Stable peak offset (±2h) per instance — avoids the fleet moving in unison."""
    return random.Random(f"workload-phase::{name}").uniform(-2.0, 2.0)


def _jitter(name: str, at: datetime) -> float:
    """Deterministic noise per instance and 5-min bucket, in [-1, 1]."""
    bucket = int(at.timestamp()) // 300
    return random.Random(f"workload-jitter::{name}::{bucket}").uniform(-1.0, 1.0)


def traffic_factor(name: str, at: datetime) -> float:
    """
    Traffic intensity in [0, 1] for an instance at a given instant.

    A 24h-period cosine (1.0 at the peak, floor at _TROUGH_FACTOR), offset per
    instance, dampened on weekends. Deterministic: the same (name, at)
    always returns the same value, which makes the curve testable and makes the
    seeded history match up with the live load.
    """
    hour = at.hour + at.minute / 60.0 + _instance_phase_hours(name)
    daily = 0.5 + 0.5 * cos(2 * pi * (hour - _PEAK_HOUR_UTC) / 24.0)
    factor = _TROUGH_FACTOR + (1.0 - _TROUGH_FACTOR) * daily
    if at.weekday() >= 5:
        factor *= _WEEKEND_FACTOR
    return min(1.0, max(0.0, factor))


def target_connections(
    name: str,
    environment: Environment | None,
    at: datetime,
    cap: int | None = None,
    intensity: float = 1.0,
) -> int:
    """
    How many connections this instance should keep open at `at`.

    Production uses the whole range up to the cap; staging stays at ~half of it —
    the size difference between environments is what makes the fleet look real
    on the dashboard, not just each card in isolation.

    `intensity` is the load multiplier (`BASELINE_INTENSITY` live; 1.0 at the
    curve's peak, used by the backfill to size the latency).
    """
    cap = cap or settings.DEMO_WORKLOAD_MAX_CONNECTIONS
    if environment == Environment.PRODUCTION:
        low, high = max(1, cap // 5), cap
    else:
        low, high = 1, max(2, cap // 2)
    value = low + (high - low) * traffic_factor(name, at) + _jitter(name, at)
    return int(max(1, min(high, round(value * intensity))))


def target_queries_per_second(
    name: str,
    environment: Environment | None,
    at: datetime,
    intensity: float = BASELINE_INTENSITY,
) -> float:
    """
    Commits/s the baseline load produces on this instance at `at`.

    Models what `_drive` actually does: ~`_ACTIVE_FRACTION` of the open connections
    fire a query — each in autocommit, hence one transaction and one
    `xact_commit` — on every `DEMO_WORKLOAD_INTERVAL_SECONDS` cycle. It's derived from the
    SAME `target_connections` as the live load, so the modeled rate matches what
    the poller measures. This is what the seed uses to anchor the `xact_commit` pair at
    boot (see `seed/history._seed_xact_commit_anchor`), so the card shows queries/s
    right on the first render instead of "—" for two poller cycles.
    """
    conns = target_connections(name, environment, at, intensity=intensity)
    return (
        _ACTIVE_FRACTION
        * conns
        * _QUERIES_PER_ACTIVE_CONN
        / settings.DEMO_WORKLOAD_INTERVAL_SECONDS
    )


# --------------------------------------------------------------------------- #
# Per-instance connection pool
# --------------------------------------------------------------------------- #
class _InstancePool:
    """An instance's live connections + the state that survives between cycles."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.conns: list[psycopg.Connection] = []
        # Largest business table (the fact table: payments/sales), discovered on
        # the first connection. It's the target of the light reads and the heavy query.
        self.dataset_table: str | None = None
        # Does the fact table have `amount` + `created_at`? Only then does the heavy query run
        # the "hourly revenue" aggregation; otherwise it falls back to a cheap count.
        self.bulk_ready = False
        self.prepared = False

    def close_all(self) -> None:
        for conn in self.conns:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 — shutting down, the reason doesn't matter
                pass
        self.conns = []


# Live pools, per instance. Module-level state (like the metrics_poller's cycle
# counter): the loop is a singleton per process.
_pools: dict[uuid.UUID, _InstancePool] = {}


def _connect(uri: str) -> psycopg.Connection:
    """
    Simulator connection: autocommit (each query = one transaction, feeding
    xact_commit, which is the basis of the queries/s KPI) and a short statement_timeout
    so no synthetic query holds a backend hostage.
    """
    return psycopg.connect(
        uri,
        connect_timeout=5,
        autocommit=True,
        application_name=APPLICATION_NAME,
        options="-c statement_timeout=10000",
    )


def _prepare(pool: _InstancePool, conn: psycopg.Connection) -> None:
    """Creates the write table and discovers the fact table (on a fresh connection)."""
    conn.execute(
        psql.SQL(
            "CREATE TABLE IF NOT EXISTS {} ("
            "  id         BIGSERIAL PRIMARY KEY,"
            "  kind       TEXT NOT NULL,"
            "  payload    TEXT NOT NULL,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        ).format(psql.Identifier(WORKLOAD_TABLE))
    )
    _discover(pool, conn)


def _discover(pool: _InstancePool, conn: psycopg.Connection) -> None:
    """
    (Re)discovers the largest business table (payments/sales) and whether it serves the heavy
    query. Cheap — runs again every cycle WHILE the fact table hasn't been found yet, and
    after an error (e.g.: the seed migrated the schema out from under the pool, dropping the old one).
    `prepared` only becomes True when there is a fact table, so a boot where the load ramps up before
    the seed finishes keeps trying until the table exists.
    """
    # The largest table (excluding the write table) is the business fact table (payments/sales):
    # it's where the point read looks and where the heavy query aggregates a slice.
    row = conn.execute(
        "SELECT relname FROM pg_stat_user_tables "
        "WHERE relname <> %s ORDER BY n_live_tup DESC LIMIT 1",
        (WORKLOAD_TABLE,),
    ).fetchone()
    pool.dataset_table = row[0] if row else None
    # The heavy query aggregates by `amount`/`created_at`; only run it if the table has them
    # (every seeded fact table does — but an instance mid-seeding might not).
    pool.bulk_ready = bool(
        pool.dataset_table
        and conn.execute(
            "SELECT count(*) = 2 FROM information_schema.columns "
            "WHERE table_name = %s AND column_name IN ('amount', 'created_at')",
            (pool.dataset_table,),
        ).fetchone()[0]
    )
    pool.prepared = pool.dataset_table is not None


def _resize(pool: _InstancePool, uri: str, target: int) -> None:
    """Moves the pool toward the target, at most _MAX_POOL_STEP connections per cycle."""
    current = len(pool.conns)
    if current < target:
        for _ in range(min(_MAX_POOL_STEP, target - current)):
            conn = _connect(uri)
            if not pool.prepared:
                _prepare(pool, conn)
            pool.conns.append(conn)
    elif current > target:
        for _ in range(min(_MAX_POOL_STEP, current - target)):
            conn = pool.conns.pop()
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def _run_light_query(pool: _InstancePool, conn: psycopg.Connection, rng: random.Random) -> None:
    """
    One LIGHT query from the OLTP mix: a point read (dominant), an occasional write, or an
    aggregation. Each call is one transaction in autocommit (= 1 xact_commit) — it's the
    VOLUME of these, fired in a burst by `_drive`, that gives the card its live queries/s.
    Reads dominate on purpose: they're microseconds and don't bloat the table,
    so the high volume is cheap. The HEAVY query is kept out of here
    (`_run_heavy_query`), so the burst doesn't turn into a load test.
    """
    table = pool.dataset_table
    roll = rng.random()

    if roll < 0.90:  # point read (dominates the mix)
        if table:
            conn.execute(
                psql.SQL("SELECT * FROM {} ORDER BY id LIMIT 20 OFFSET %s").format(
                    psql.Identifier(table)
                ),
                (rng.randint(0, 80),),
            ).fetchall()
        else:  # no fact table yet: reads the workload table itself
            conn.execute(
                psql.SQL("SELECT count(*), max(created_at) FROM {}").format(
                    psql.Identifier(WORKLOAD_TABLE)
                )
            ).fetchone()
    elif roll < 0.97:  # occasional write
        conn.execute(
            psql.SQL("INSERT INTO {} (kind, payload) VALUES (%s, %s)").format(
                psql.Identifier(WORKLOAD_TABLE)
            ),
            ("page_view", f"session-{rng.randint(1000, 9999)}"),
        )
        if rng.random() < 0.1:  # pruning: keeps the table at a stable size
            conn.execute(
                psql.SQL(
                    "DELETE FROM {t} WHERE id < "
                    "(SELECT max(id) - %s FROM {t})"
                ).format(t=psql.Identifier(WORKLOAD_TABLE)),
                (_WORKLOAD_TABLE_MAX_ROWS,),
            )
    else:  # LIGHT aggregation: a count over a recent tail, not the whole table
        # (count(*) on a fact table with millions of rows would be an expensive seq scan mid-
        # burst; here the slice is bounded by the PK and comes back in microseconds).
        target = table or WORKLOAD_TABLE
        conn.execute(
            psql.SQL(
                "SELECT count(*) FROM (SELECT id FROM {} ORDER BY id DESC LIMIT 200) s"
            ).format(psql.Identifier(target))
        ).fetchone()


def _run_heavy_query(pool: _InstancePool, conn: psycopg.Connection, rng: random.Random) -> None:
    """
    The expensive query that populates the slow-queries screen. Called rarely by
    `_drive` (`_HEAVY_QUERY_PROB`), outside the light burst.
    """
    table = pool.dataset_table
    if pool.bulk_ready and table:
        # "Hourly revenue" report over a LIMITED slice of the fact table:
        # scans ~_HEAVY_QUERY_ROWS rows and aggregates by hour — tens of ms, a
        # real p95 tail, and a query that makes business sense on the
        # slow-queries screen. The slice is LIMITED on purpose: expensive, not dangerous.
        conn.execute(
            psql.SQL(
                "SELECT date_trunc('hour', created_at) AS bucket, count(*), "
                "round(sum(amount), 2) FROM ("
                "  SELECT amount, created_at FROM {} ORDER BY id OFFSET %s LIMIT %s"
                ") s GROUP BY bucket ORDER BY bucket DESC"
            ).format(psql.Identifier(table)),
            (rng.randint(0, 20_000), _HEAVY_QUERY_ROWS),
        ).fetchall()
    else:  # fact table not ready yet: cheap count on the write buffer
        conn.execute(
            psql.SQL("SELECT count(*), max(created_at) FROM {}").format(
                psql.Identifier(WORKLOAD_TABLE)
            )
        ).fetchone()


def _drive(pool: _InstancePool, rng: random.Random) -> int:
    """Fires the mix on part of the pool. A connection that fails is discarded."""
    executed = 0
    for conn in list(pool.conns):
        # Not every connection of an app is executing something at every instant —
        # the idle ones count toward numbackends and keep the connections curve up.
        if rng.random() > _ACTIVE_FRACTION:
            continue
        try:
            # Burst of light queries: the volume that gives the card its live queries/s.
            for _ in range(_QUERIES_PER_ACTIVE_CONN):
                _run_light_query(pool, conn, rng)
                executed += 1
            # A heavy one every once in a while, to give the slow-queries screen some substance.
            if rng.random() < _HEAVY_QUERY_PROB:
                _run_heavy_query(pool, conn, rng)
                executed += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("Workload: connection discarded on %s: %s", pool.name, exc)
            # The schema may have changed under the pool (the seed migrated the fact table):
            # forces rediscovery on the next cycle, against the current schema.
            pool.prepared = False
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            if conn in pool.conns:
                pool.conns.remove(conn)
    return executed


# --------------------------------------------------------------------------- #
# Cycle and loop
# --------------------------------------------------------------------------- #
def _demo_instances(db) -> list[DatabaseInstance]:
    from src.seed.demo import DEMO_MARKER  # lazy: avoids a circular import

    return (
        db.query(DatabaseInstance)
        .filter(
            DatabaseInstance.notes == DEMO_MARKER,
            DatabaseInstance.status == InstanceStatus.RUNNING,
            DatabaseInstance.deleted_at.is_(None),
            DatabaseInstance.connection_uri.isnot(None),
        )
        .all()
    )


def simulate_once() -> None:
    """
    One cycle: adjusts each demo instance's pool to the baseline load target and runs the
    query mix. An error on one instance (stopped container, network) doesn't cancel the
    others — its pool is closed and restarts on the next cycle.

    Always runs at the baseline load's intensity: the loop only starts in demo mode (main.py),
    so the pools stay continuously open as long as there are demo instances, and
    the fleet never looks dead.
    """
    db = SessionLocal()
    try:
        instances = _demo_instances(db)
        alive = {inst.id for inst in instances}

        # An instance that left the fleet (stopped, removed): return its connections.
        for instance_id in list(_pools):
            if instance_id not in alive:
                _pools.pop(instance_id).close_all()

        # Real time-of-day: the curve positions the connection target by the clock.
        now = _now()
        for inst in instances:
            pool = _pools.setdefault(inst.id, _InstancePool(inst.name))
            try:
                # The decrypted URI lives only within this cycle — never stored
                # in the pool (same discipline as metrics.get_connection).
                uri = decrypt_value(inst.connection_uri)
                _resize(
                    pool,
                    uri,
                    target_connections(
                        inst.name, inst.environment, now, intensity=BASELINE_INTENSITY
                    ),
                )
                # The fact table can appear AFTER the pool is already at target (the seed still
                # seeding at boot): until we find it, rediscover every cycle
                # on an existing connection, without waiting for the pool to grow.
                if not pool.prepared and pool.conns:
                    _discover(pool, pool.conns[0])
                executed = _drive(pool, random.Random())
                logger.debug(
                    "Workload %s: %d connections, %d queries",
                    inst.name,
                    len(pool.conns),
                    executed,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Workload: cycle failed on %s: %s", inst.name, exc)
                pool.close_all()
    finally:
        db.close()


def shutdown_pools() -> None:
    """Closes all connections — called on app shutdown."""
    for pool in _pools.values():
        pool.close_all()
    _pools.clear()


async def workload_loop(stop_event: asyncio.Event) -> None:
    """
    Async loop of the simulator (same pattern as metrics_polling_loop).

    The interval is much shorter than the metrics poller's: the curve needs to
    move between two collections, otherwise the connections chart turns into a staircase.
    """
    interval = settings.DEMO_WORKLOAD_INTERVAL_SECONDS
    logger.info("Demo workload generator started (interval: %ds)", interval)

    while not stop_event.is_set():
        try:
            await asyncio.to_thread(simulate_once)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error in workload generator cycle: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue

    await asyncio.to_thread(shutdown_pools)
    logger.info("Demo workload generator stopped.")
