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
    Conexão psycopg com autocommit=True.

    Por que autocommit é obrigatório para manutenção?
    VACUUM, ANALYZE e REINDEX não podem rodar dentro de uma transação
    explícita — o PostgreSQL os rejeita com:
      "VACUUM cannot run inside a transaction block"
    O psycopg 3 abre um BEGIN implícito em toda conexão por padrão.
    autocommit=True desabilita esse BEGIN, permitindo que esses
    comandos executem diretamente como statements avulsos.

    kill_idle e kill_long (pg_terminate_backend) são SELECTs e não
    precisariam de autocommit, mas usam a mesma conexão por consistência.
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
# Executores de tarefa
# ---------------------------------------------------------------------------

def run_vacuum(
    db: Session,
    instance: DatabaseInstance,
    target_table: str | None = None,
) -> MaintenanceTask:
    """
    VACUUM ANALYZE em uma tabela ou no banco inteiro.

    Por que VACUUM ANALYZE (não só VACUUM)?
    VACUUM libera tuplas mortas (MVCC dead rows). ANALYZE atualiza as
    estatísticas do query planner. Rodar ambos juntos é o padrão DBA —
    um banco sem estatísticas recentes gera planos de execução ruins
    mesmo que não haja bloat.

    psql.Identifier() garante quoting correto de nomes de tabela —
    previne SQL injection mesmo que o nome venha de entrada do usuário.
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
    VACUUM FULL em uma única tabela.

    VACUUM FULL reescreve fisicamente a tabela em um novo arquivo —
    recupera espaço em disco real (ao contrário do VACUUM normal, que
    apenas marca o espaço como reutilizável). O custo: lock exclusivo
    na tabela durante toda a operação, bloqueando leitura E escrita.

    Por isso é sempre obrigatório informar target_table — nunca VACUUM
    FULL automático no banco inteiro. Use apenas com janela de manutenção
    definida e quando bloat > ~30%.
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
    ANALYZE atualiza as estatísticas usadas pelo query planner.

    Quando rodar manualmente: após carga batch (INSERT massivo em tabela grande),
    o autovacuum ainda não terá rodado — o planner usaria estatísticas defasadas
    e poderia escolher sequential scan onde deveria usar index scan.
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
    REINDEX recria índices do zero a partir dos dados nas tabelas.

    Quando usar: índices com bloat alto (estimado pela FASE 4 /bloat endpoint)
    ou após corrupção de índice (raro, mas ocorre em crashes sem fsync).

    target_table=None → REINDEX DATABASE (todos os índices, sequencialmente).
    target_table fornecido → REINDEX TABLE (mais rápido, lock por tabela).

    Nota de produção: REINDEX TABLE adquire ShareLock — leitura ok, escrita bloqueada.
    Para bancos em produção com SLA, use REINDEX CONCURRENTLY (não implementado
    aqui por complexidade — requer PostgreSQL 12+ e não pode estar em transação).
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
    Encerrar backends em estado 'idle' há mais de idle_minutes minutos.

    'idle' = conectado mas sem transação ativa. Cada conexão idle consome
    um slot de max_connections e ~5–10 MB de memória shared no PostgreSQL.
    Em aplicações que não fecham conexões corretamente, isso se acumula até
    esgotar max_connections e impedir novas conexões.

    pg_terminate_backend() envia SIGTERM ao processo backend — encerramento
    gracioso. A role precisa de pg_signal_backend (concedido no provisioner).
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
    Encerrar queries ativas há mais de max_minutes minutos.

    Exclui processos autovacuum — eles são gerenciados pelo PostgreSQL e
    podem durar horas legitimamente em tabelas grandes.

    Quando usar: queries travadas (lock wait), full table scans acidentais,
    ou queries de ETL que ultrapassaram o tempo esperado.
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


# Dispatcher: TaskType → função executora (para o scheduler e run_task)
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
    Ponto de entrada do router — despacha para o executor correto.

    VACUUM_FULL é tratado separadamente por exigir target_table obrigatório
    (lock exclusivo — nunca permitir banco inteiro).

    KILL_IDLE e KILL_LONG ignoram target_table — operam sobre conexões,
    não sobre tabelas.
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
    """Avançar next_run_at para o próximo horário no cron, a partir de agora."""
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
    Calcular recomendações de configuração PostgreSQL baseadas nos recursos.

    Não conecta ao banco — computa offline com memory_mb e cpu da instância.
    Funciona mesmo com a instância STOPPED.

    As fórmulas seguem as recomendações do wiki.postgresql.org e do pgTune:
    - shared_buffers:               25% da RAM
    - effective_cache_size:         75% da RAM
    - maintenance_work_mem:         5% da RAM, máximo 2 GB
    - work_mem:                     RAM ÷ (max_connections × 2) — conservador
    - max_parallel_workers:         igual ao número de vCPUs
    - max_parallel_workers_per_gather: metade dos vCPUs
    - wal_buffers:                  16 MB (fixo)
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
        # Conservador: assume 100 conexões, 2 operações sort/hash cada
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
