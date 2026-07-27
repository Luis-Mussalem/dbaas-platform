import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import urlparse

import psycopg
import psycopg.sql as psql
from sqlalchemy.orm import Session

from src.core.encryption import decrypt_value
from src.models.database_instance import DatabaseInstance
from src.models.maintenance import (
    MaintenanceSchedule,
    MaintenanceTask,
    TaskStatus,
    TaskType,
)
from src.schemas.maintenance import (
    ConfigRecommendation,
    ConfigRecommendationsResponse,
    MaintenanceScheduleCreate,
    MaintenanceTaskCreate,
)


@contextmanager
def _get_conn(instance: DatabaseInstance):
    """
    psycopg connection with autocommit=True.

    Why is autocommit required for maintenance?
    VACUUM, ANALYZE, and REINDEX cannot run inside an explicit
    transaction — PostgreSQL rejects them with:
      "VACUUM cannot run inside a transaction block"
    psycopg 3 opens an implicit BEGIN on every connection by default.
    autocommit=True disables that BEGIN, letting these
    commands execute directly as standalone statements.

    kill_idle and kill_long (pg_terminate_backend) are SELECTs and wouldn't
    need autocommit, but use the same connection for consistency.
    """
    uri = decrypt_value(instance.connection_uri)
    parsed = urlparse(uri)
    conn = psycopg.connect(
        host=parsed.hostname,
        port=parsed.port,
        dbname=parsed.path.lstrip("/"),
        user=parsed.username,
        password=parsed.password or "",
        autocommit=True,
        connect_timeout=10,
    )
    try:
        yield conn
    finally:
        conn.close()


def _make_task(
    db: Session,
    instance_id: uuid.UUID,
    task_type: TaskType,
    target_table: str | None,
) -> MaintenanceTask:
    task = MaintenanceTask(
        instance_id=instance_id,
        task_type=task_type,
        target_table=target_table,
        status=TaskStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _finish_task(
    db: Session,
    task: MaintenanceTask,
    success: bool,
    summary: str,
) -> MaintenanceTask:
    task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
    task.completed_at = datetime.now(timezone.utc)
    task.result_summary = summary
    db.commit()
    db.refresh(task)
    return task


# ---------------------------------------------------------------------------
# Task runners
# ---------------------------------------------------------------------------

def run_vacuum(
    db: Session,
    instance: DatabaseInstance,
    target_table: str | None = None,
) -> MaintenanceTask:
    """
    VACUUM ANALYZE on a table or on the entire database.

    Why VACUUM ANALYZE (not just VACUUM)?
    VACUUM frees dead tuples (MVCC dead rows). ANALYZE updates the
    query planner's statistics. Running both together is the DBA standard —
    a database without recent statistics produces bad execution plans
    even without bloat.

    psql.Identifier() guarantees correct quoting of table names —
    prevents SQL injection even if the name comes from user input.
    """
    task = _make_task(db, instance.id, TaskType.VACUUM, target_table)
    try:
        with _get_conn(instance) as conn:
            with conn.cursor() as cur:
                if target_table:
                    cur.execute(
                        psql.SQL("VACUUM ANALYZE {}").format(
                            psql.Identifier(target_table)
                        )
                    )
                    summary = f"VACUUM ANALYZE completed on table '{target_table}'"
                else:
                    cur.execute(psql.SQL("VACUUM ANALYZE"))
                    summary = "VACUUM ANALYZE completed on entire database"
        return _finish_task(db, task, True, summary)
    except Exception as exc:
        return _finish_task(db, task, False, str(exc))


def run_vacuum_full(
    db: Session,
    instance: DatabaseInstance,
    target_table: str,
) -> MaintenanceTask:
    """
    VACUUM FULL on a single table.

    VACUUM FULL physically rewrites the table into a new file —
    reclaims actual disk space (unlike regular VACUUM, which only
    marks the space as reusable). The cost: an exclusive lock
    on the table for the whole operation, blocking both reads AND writes.

    That's why target_table is always required — never an automatic VACUUM
    FULL on the entire database. Use only with a defined maintenance window
    and when bloat > ~30%.
    """
    task = _make_task(db, instance.id, TaskType.VACUUM_FULL, target_table)
    try:
        with _get_conn(instance) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    psql.SQL("VACUUM FULL {}").format(
                        psql.Identifier(target_table)
                    )
                )
        return _finish_task(
            db, task, True,
            f"VACUUM FULL completed on table '{target_table}'"
        )
    except Exception as exc:
        return _finish_task(db, task, False, str(exc))


def run_analyze(
    db: Session,
    instance: DatabaseInstance,
    target_table: str | None = None,
) -> MaintenanceTask:
    """
    ANALYZE updates the statistics used by the query planner.

    When to run it manually: after a batch load (massive INSERT into a large table),
    autovacuum won't have run yet — the planner would use stale statistics
    and might pick a sequential scan where it should use an index scan.
    """
    task = _make_task(db, instance.id, TaskType.ANALYZE, target_table)
    try:
        with _get_conn(instance) as conn:
            with conn.cursor() as cur:
                if target_table:
                    cur.execute(
                        psql.SQL("ANALYZE {}").format(
                            psql.Identifier(target_table)
                        )
                    )
                    summary = f"ANALYZE completed on table '{target_table}'"
                else:
                    cur.execute(psql.SQL("ANALYZE"))
                    summary = "ANALYZE completed on entire database"
        return _finish_task(db, task, True, summary)
    except Exception as exc:
        return _finish_task(db, task, False, str(exc))


def run_reindex(
    db: Session,
    instance: DatabaseInstance,
    target_table: str | None = None,
) -> MaintenanceTask:
    """
    REINDEX rebuilds indexes from scratch based on the data in the tables.

    When to use: indexes with high bloat (estimated by the PHASE 4 /bloat endpoint)
    or after index corruption (rare, but happens in crashes without fsync).

    target_table=None → REINDEX DATABASE (all indexes, sequentially).
    target_table given → REINDEX TABLE (faster, per-table lock).

    Production note: REINDEX TABLE acquires a ShareLock — reads ok, writes blocked.
    For production databases with an SLA, use REINDEX CONCURRENTLY (not implemented
    here due to complexity — requires PostgreSQL 12+ and cannot be inside a transaction).
    """
    task = _make_task(db, instance.id, TaskType.REINDEX, target_table)
    try:
        with _get_conn(instance) as conn:
            with conn.cursor() as cur:
                if target_table:
                    cur.execute(
                        psql.SQL("REINDEX TABLE {}").format(
                            psql.Identifier(target_table)
                        )
                    )
                    summary = f"REINDEX TABLE completed on '{target_table}'"
                else:
                    cur.execute(psql.SQL("SELECT current_database()"))
                    row = cur.fetchone()
                    dbname = row[0] if row else "unknown"
                    cur.execute(
                        psql.SQL("REINDEX DATABASE {}").format(
                            psql.Identifier(dbname)
                        )
                    )
                    summary = f"REINDEX DATABASE completed on '{dbname}'"
        return _finish_task(db, task, True, summary)
    except Exception as exc:
        return _finish_task(db, task, False, str(exc))


def kill_idle_connections(
    db: Session,
    instance: DatabaseInstance,
    idle_minutes: int = 30,
) -> MaintenanceTask:
    """
    Terminates backends in 'idle' state for more than idle_minutes minutes.

    'idle' = connected but with no active transaction. Each idle connection consumes
    a max_connections slot and ~5-10 MB of shared memory in PostgreSQL.
    In applications that don't close connections properly, this accumulates until
    max_connections is exhausted and new connections are blocked.

    pg_terminate_backend() sends SIGTERM to the backend process — a graceful
    shutdown. The role needs pg_signal_backend (granted by the provisioner).
    """
    task = _make_task(db, instance.id, TaskType.KILL_IDLE, None)
    try:
        with _get_conn(instance) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND state = 'idle'
                      AND state_change < NOW() - (%(minutes)s || ' minutes')::interval
                      AND pid <> pg_backend_pid()
                    """,
                    {"minutes": idle_minutes},
                )
                rows = cur.fetchall()
                killed = sum(1 for r in rows if r[0])
        return _finish_task(
            db, task, True,
            f"Terminated {killed} idle connection(s) idle for >{idle_minutes} min",
        )
    except Exception as exc:
        return _finish_task(db, task, False, str(exc))


def kill_long_queries(
    db: Session,
    instance: DatabaseInstance,
    max_minutes: int = 60,
) -> MaintenanceTask:
    """
    Terminates queries active for more than max_minutes minutes.

    Excludes autovacuum processes — they are managed by PostgreSQL and
    can legitimately run for hours on large tables.

    When to use: stuck queries (lock wait), accidental full table scans,
    or ETL queries that exceeded their expected time.
    """
    task = _make_task(db, instance.id, TaskType.KILL_LONG, None)
    try:
        with _get_conn(instance) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND state = 'active'
                      AND query_start < NOW() - (%(minutes)s || ' minutes')::interval
                      AND pid <> pg_backend_pid()
                      AND query NOT ILIKE 'autovacuum%%'
                    """,
                    {"minutes": max_minutes},
                )
                rows = cur.fetchall()
                killed = sum(1 for r in rows if r[0])
        return _finish_task(
            db, task, True,
            f"Terminated {killed} long-running query(ies) running for >{max_minutes} min",
        )
    except Exception as exc:
        return _finish_task(db, task, False, str(exc))


# Dispatcher: TaskType → runner function (for the scheduler and run_task)
_TASK_RUNNERS = {
    TaskType.VACUUM:    run_vacuum,
    TaskType.ANALYZE:   run_analyze,
    TaskType.REINDEX:   run_reindex,
    TaskType.KILL_IDLE: kill_idle_connections,
    TaskType.KILL_LONG: kill_long_queries,
}


def run_task(
    db: Session,
    instance: DatabaseInstance,
    data: MaintenanceTaskCreate,
) -> MaintenanceTask:
    """
    Router entry point — dispatches to the correct runner.

    VACUUM_FULL is handled separately because it requires a mandatory target_table
    (exclusive lock — never allow the whole database).

    KILL_IDLE and KILL_LONG ignore target_table — they operate on connections,
    not on tables.
    """
    if data.task_type == TaskType.VACUUM_FULL:
        if not data.target_table:
            raise ValueError(
                "VACUUM_FULL requires target_table — "
                "running VACUUM FULL on the entire database would lock all tables simultaneously."
            )
        return run_vacuum_full(db, instance, data.target_table)

    runner = _TASK_RUNNERS[data.task_type]

    if data.task_type in (TaskType.KILL_IDLE, TaskType.KILL_LONG):
        return runner(db, instance)

    return runner(db, instance, data.target_table)


def get_task_history(
    db: Session,
    instance_id: uuid.UUID,
    limit: int = 50,
) -> list[MaintenanceTask]:
    return (
        db.query(MaintenanceTask)
        .filter(MaintenanceTask.instance_id == instance_id)
        .order_by(MaintenanceTask.scheduled_at.desc())
        .limit(limit)
        .all()
    )


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

def create_schedule(
    db: Session,
    instance_id: uuid.UUID,
    data: MaintenanceScheduleCreate,
) -> MaintenanceSchedule:
    from croniter import croniter

    next_run = croniter(data.cron_expression).get_next(datetime)
    next_run = next_run.replace(tzinfo=timezone.utc)

    schedule = MaintenanceSchedule(
        instance_id=instance_id,
        task_type=data.task_type,
        cron_expression=data.cron_expression,
        next_run_at=next_run,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


def list_schedules(
    db: Session,
    instance_id: uuid.UUID,
) -> list[MaintenanceSchedule]:
    return (
        db.query(MaintenanceSchedule)
        .filter(MaintenanceSchedule.instance_id == instance_id)
        .order_by(MaintenanceSchedule.created_at.desc())
        .all()
    )


def delete_schedule(db: Session, schedule: MaintenanceSchedule) -> None:
    db.delete(schedule)
    db.commit()


def advance_schedule(
    db: Session,
    schedule: MaintenanceSchedule,
) -> MaintenanceSchedule:
    """Advances next_run_at to the next cron time, starting from now."""
    from croniter import croniter

    now = datetime.now(timezone.utc)
    next_run = croniter(schedule.cron_expression, now).get_next(datetime)
    schedule.next_run_at = next_run.replace(tzinfo=timezone.utc)
    db.commit()
    db.refresh(schedule)
    return schedule


# ---------------------------------------------------------------------------
# Config recommendations
# ---------------------------------------------------------------------------

def get_config_recommendations(
    instance: DatabaseInstance,
) -> ConfigRecommendationsResponse:
    """
    Computes PostgreSQL configuration recommendations based on the resources.

    Doesn't connect to the database — computes offline using the instance's memory_mb and cpu.
    Works even with the instance STOPPED.

    The formulas follow the recommendations from wiki.postgresql.org and from pgTune:
    - shared_buffers:               25% of RAM
    - effective_cache_size:         75% of RAM
    - maintenance_work_mem:         5% of RAM, capped at 2 GB
    - work_mem:                     RAM ÷ (max_connections × 2) — conservative
    - max_parallel_workers:         equal to the number of vCPUs
    - max_parallel_workers_per_gather: half of the vCPUs
    - wal_buffers:                  16 MB (fixed)
    - checkpoint_completion_target: 0.9
    """
    recommendations: list[ConfigRecommendation] = []

    if instance.memory_mb:
        mem = instance.memory_mb

        recommendations.append(ConfigRecommendation(
            parameter="shared_buffers",
            current_value=None,
            recommended_value=f"{mem // 4}MB",
            reason=f"25% of {mem}MB RAM — primary PostgreSQL buffer cache",
        ))
        recommendations.append(ConfigRecommendation(
            parameter="effective_cache_size",
            current_value=None,
            recommended_value=f"{mem * 3 // 4}MB",
            reason=(
                f"75% of {mem}MB RAM — planner estimate of total cache "
                "(OS page cache + shared_buffers); does not allocate memory"
            ),
        ))
        maintenance_mem = min(mem // 20, 2048)
        recommendations.append(ConfigRecommendation(
            parameter="maintenance_work_mem",
            current_value=None,
            recommended_value=f"{maintenance_mem}MB",
            reason=(
                f"5% of {mem}MB RAM, capped at 2GB — "
                "used per VACUUM, REINDEX, CREATE INDEX, ALTER TABLE operation"
            ),
        ))
        # Conservative: assumes 100 connections, 2 sort/hash operations each
        work_mem = max(4, mem // 200)
        recommendations.append(ConfigRecommendation(
            parameter="work_mem",
            current_value=None,
            recommended_value=f"{work_mem}MB",
            reason=(
                f"{mem}MB ÷ 200 (100 connections × 2 operations) = {work_mem}MB — "
                "per sort/hash node per query; too high causes OOM under concurrent load"
            ),
        ))

    if instance.cpu:
        recommendations.append(ConfigRecommendation(
            parameter="max_parallel_workers",
            current_value=None,
            recommended_value=str(instance.cpu),
            reason=f"Match vCPU count ({instance.cpu}) — total background parallel workers",
        ))
        recommendations.append(ConfigRecommendation(
            parameter="max_parallel_workers_per_gather",
            current_value=None,
            recommended_value=str(max(1, instance.cpu // 2)),
            reason=f"Half of vCPUs ({instance.cpu // 2}) — parallel workers per query node",
        ))

    recommendations.append(ConfigRecommendation(
        parameter="wal_buffers",
        current_value=None,
        recommended_value="16MB",
        reason=(
            "Default (-1 = 1/32 of shared_buffers) is often too low; "
            "16MB fits most OLTP workloads and reduces WAL write latency"
        ),
    ))
    recommendations.append(ConfigRecommendation(
        parameter="checkpoint_completion_target",
        current_value=None,
        recommended_value="0.9",
        reason=(
            "Spread checkpoint I/O over 90% of the checkpoint_timeout interval "
            "to avoid write spikes at checkpoint boundaries"
        ),
    ))

    return ConfigRecommendationsResponse(
        instance_id=instance.id,
        memory_mb=instance.memory_mb,
        cpu=instance.cpu,
        recommendations=recommendations,
    )
