import logging
from typing import Any

import psycopg
import psycopg.rows
from psycopg import sql as psql

# Re-export keeps the name _EXPLAIN_MAX_LEN used by tests/test_explain_guard.py.
from src.core.sql_guard import MAX_QUERY_LEN as _EXPLAIN_MAX_LEN  # noqa: F401
from src.core.sql_guard import assert_read_only_select

logger = logging.getLogger(__name__)


def collect_base_metrics(conn: psycopg.Connection) -> dict[str, float]:
    """
    Collects scalar metrics from the database via pg_stat_database and pg_settings.

    Metrics collected:
    - connections_active: connections currently open on this database
    - connections_max: the server's total limit (max_connections)
    - blks_hit/blks_read: blocks served from cache vs. read from disk
    - db_size_bytes: total database size in bytes
    - tup_inserted/updated/deleted/fetched: volume of DML operations
    - xact_commit/rollback: committed and aborted transactions

    Why raw blks_hit/blks_read, and not the already-computed cache_hit_ratio?
    pg_stat_database's counters are LIFETIME ones and PostgreSQL discards them
    on restart. The ratio over the cumulative total measures "since the server came up",
    so every restart brings the database back to ~0% and the metric takes hours to climb
    back to the real value — the whole time firing a low-cache alert. What derives the
    counters as a ratio over an interval is services.metrics.collect_and_store,
    which has the history to compare against the previous collection.
    """
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute("""
            SELECT
                d.numbackends AS connections_active,
                (
                    SELECT setting::int
                    FROM pg_settings
                    WHERE name = 'max_connections'
                ) AS connections_max,
                d.blks_hit,
                d.blks_read,
                pg_database_size(d.datname) AS db_size_bytes,
                d.tup_inserted,
                d.tup_updated,
                d.tup_deleted,
                d.tup_fetched,
                d.xact_commit,
                d.xact_rollback
            FROM pg_stat_database d
            WHERE d.datname = current_database()
        """)
        row = cur.fetchone()
        if not row:
            return {}

        return {k: float(v) if v is not None else 0.0 for k, v in row.items()}


def collect_latency_percentiles(conn: psycopg.Connection) -> dict[str, float]:
    """
    P50/P95/P99 of mean execution time (ms) across the monitored queries.

    An honest approximation: percentiles over mean_exec_time per query
    *fingerprint* — pg_stat_statements aggregates by normalized query and doesn't keep
    per-execution samples. All three percentiles come from the SAME query
    (percentile_cont accepts an array), so measuring p50 and p99 alongside p95 costs
    no extra trip to the database.

    Requires the extension to be installed; instances without it return {} (same
    graceful degradation as collect_slow_queries), in which case the metrics simply
    aren't persisted that cycle.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT percentile_cont(ARRAY[0.5, 0.95, 0.99]) "
                "WITHIN GROUP (ORDER BY mean_exec_time) "
                "FROM pg_stat_statements"
            )
            row = cur.fetchone()
            if not row or row[0] is None:
                return {}
            p50, p95, p99 = row[0]
            return {
                "p50_query_latency_ms": round(float(p50), 2),
                "p95_query_latency_ms": round(float(p95), 2),
                "p99_query_latency_ms": round(float(p99), 2),
            }
    except Exception as exc:
        logger.warning("Latency percentiles not available on this instance: %s", exc)
        return {}


def collect_slow_queries(
    conn: psycopg.Connection,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Returns the slowest queries via pg_stat_statements.

    Requires the pg_stat_statements extension to be installed on the instance's database.
    On instances without the extension (provisioned before PHASE 4 Step 1),
    returns an empty list with a warning log instead of raising an exception.

    Ordered by total_exec_time DESC — queries with the highest accumulated CPU
    impact are more relevant for optimization than rare, unit-slow queries.
    """
    try:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                psql.SQL("""
                    SELECT
                        query,
                        calls,
                        round(total_exec_time::numeric, 2) AS total_exec_time_ms,
                        round(mean_exec_time::numeric, 2)  AS mean_exec_time_ms,
                        rows,
                        CASE
                            WHEN (shared_blks_hit + shared_blks_read) > 0
                            THEN round(
                                (shared_blks_hit::numeric /
                                 (shared_blks_hit + shared_blks_read)) * 100,
                                2
                            )
                            ELSE 0
                        END AS cache_hit_ratio
                    FROM pg_stat_statements
                    ORDER BY total_exec_time DESC
                    LIMIT {}
                """).format(psql.Literal(limit))
            )
            return cur.fetchall()
    except Exception as exc:
        logger.warning(
            "pg_stat_statements not available on this instance: %s", exc
        )
        return []


def collect_index_stats(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """
    Returns index usage statistics via pg_stat_user_indexes.

    unused=True (idx_scan == 0) indicates an index that's never been used — a candidate for DROP.
    Unnecessary indexes increase write time and consume disk space.
    """
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute("""
            SELECT
                s.schemaname                   AS schema_name,
                s.relname                      AS "table",
                s.indexrelname                 AS "index",
                s.idx_scan                     AS scans,
                s.idx_tup_read                 AS tup_read,
                s.idx_tup_fetch                AS tup_fetch,
                pg_relation_size(s.indexrelid) AS size_bytes,
                (s.idx_scan = 0)               AS unused
            FROM pg_stat_user_indexes s
            ORDER BY s.idx_scan ASC, size_bytes DESC
        """)
        return cur.fetchall()


def collect_locks(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """
    Returns active locks on relations (tables) via pg_locks.

    granted=False indicates a query blocked waiting for a lock to be released.
    Multiple False entries can indicate an imminent deadlock.
    The locktype='relation' filter shows only contention on tables (relevant
    to the operator), excluding PostgreSQL's internal locks (page, tuple, etc.).
    """
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute("""
            SELECT
                l.pid,
                c.relname AS "table",
                l.mode,
                l.granted,
                l.locktype
            FROM pg_locks l
            LEFT JOIN pg_class c ON c.oid = l.relation
            WHERE l.locktype = 'relation'
            ORDER BY l.granted, l.pid
        """)
        return cur.fetchall()


def collect_bloat(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """
    Estimates table bloat via pg_stat_user_tables.

    dead_ratio > 20% indicates VACUUM is running behind or disabled.
    PHASE 6 (Automated Maintenance) will use this data to trigger
    VACUUM automatically when dead_ratio exceeds the threshold.

    Uses cumulative counters (lightweight, no lock) — sufficient for detecting
    trends without impacting the monitored database's performance.
    """
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute("""
            SELECT
                schemaname AS schema_name,
                relname    AS "table",
                n_live_tup AS live_rows,
                n_dead_tup AS dead_rows,
                CASE
                    WHEN (n_live_tup + n_dead_tup) > 0
                    THEN round(
                        100.0 * n_dead_tup / (n_live_tup + n_dead_tup),
                        2
                    )
                    ELSE 0
                END AS dead_ratio,
                pg_total_relation_size(schemaname || '.' || relname) AS total_bytes
            FROM pg_stat_user_tables
            ORDER BY n_dead_tup DESC
        """)
        return cur.fetchall()


def collect_active_connections(
    conn: psycopg.Connection,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Returns the active connections (backends) on the database via pg_stat_activity.

    Excludes the monitoring backend itself (pg_backend_pid) and stateless
    internal backends (state IS NULL). wait_event combines type:event for
    direct reading ("Lock:transactionid"). duration_seconds is the time since the
    start of the current query — None for idle connections (query_start is null).
    """
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT
                pid,
                usename AS "user",
                state,
                NULLIF(
                    concat_ws(':', wait_event_type, wait_event), ''
                ) AS wait_event,
                EXTRACT(EPOCH FROM (now() - query_start))::float AS duration_seconds,
                query
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
              AND state IS NOT NULL
            ORDER BY query_start ASC NULLS LAST
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def collect_schema(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """
    Returns user tables with an estimated row count via pg_class.

    Uses c.reltuples (an estimate maintained by ANALYZE) instead of COUNT(*) —
    cheap and without scanning the tables. Excludes PostgreSQL's internal schemas.
    Returns flat rows (schema_name, table, estimated_rows); grouping
    by schema is done in the layer above.
    """
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT
                n.nspname                      AS schema_name,
                c.relname                      AS "table",
                GREATEST(c.reltuples, 0)::bigint AS estimated_rows
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r'
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND n.nspname NOT LIKE 'pg_%%'
            ORDER BY n.nspname, c.relname
            """
        )
        return cur.fetchall()


def collect_explain(conn: psycopg.Connection, query: str) -> list:
    """
    Runs EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) for a SELECT query.

    Restricted to SELECTs: EXPLAIN ANALYZE actually executes the query.
    A DELETE with EXPLAIN ANALYZE would cause real modification of the data — that's why
    the SELECT-only validation (defense in depth) runs beforehand via sql_guard.

    FORMAT JSON returns the plan as a navigable structure.
    BUFFERS exposes cache hits/misses per node — essential for identifying
    which parts of the query force disk I/O.
    """
    assert_read_only_select(query)

    with conn.cursor() as cur:
        cur.execute(
            psql.SQL("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {}").format(
                psql.SQL(query)
            )
        )
        result = cur.fetchone()
        return result[0] if result else []
