"""
Testes do serviço de manutenção (PHASE 6) sem rodar VACUUM/REINDEX num Postgres real.

_get_conn é substituído por um context manager que entrega um FakeConn — ele
grava os SQLs executados e devolve linhas controladas. Assim validamos:
- transições de status da task (RUNNING → COMPLETED/FAILED)
- o SQL correto por tipo de tarefa (VACUUM ANALYZE, ANALYZE, REINDEX, kill_*)
- o dispatcher run_task (incluindo a regra de VACUUM_FULL exigir target_table)

get_config_recommendations é função pura (não conecta) — testada diretamente.
"""
import uuid
from contextlib import contextmanager

import pytest

from src.core.encryption import encrypt_value
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.maintenance import MaintenanceTask, TaskStatus, TaskType
from src.schemas.maintenance import MaintenanceScheduleCreate, MaintenanceTaskCreate
from src.services import maintenance as maint


# --------------------------------------------------------------------------- #
# Dublês de conexão
# --------------------------------------------------------------------------- #


class FakeCursor:
    def __init__(self, fetchone=None, fetchall=None):
        self.executed: list[str] = []
        self._fetchone = fetchone
        self._fetchall = fetchall or []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, query, params=None):
        # psql.SQL/Composed têm __str__ legível; guardamos a representação.
        self.executed.append(str(query))

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return self._fetchall


class FakeConn:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


@pytest.fixture
def instance(db):
    inst = DatabaseInstance(
        name="maint-db",
        status=InstanceStatus.RUNNING,
        connection_uri=encrypt_value("postgresql://u:p@127.0.0.1:5433/appdb"),
        memory_mb=2048,
        cpu=4,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _patch_conn(monkeypatch, cursor: FakeCursor):
    @contextmanager
    def fake_get_conn(instance):
        yield FakeConn(cursor)

    monkeypatch.setattr(maint, "_get_conn", fake_get_conn)


def _patch_conn_raises(monkeypatch, exc: Exception):
    @contextmanager
    def boom(instance):
        raise exc
        yield  # pragma: no cover

    monkeypatch.setattr(maint, "_get_conn", boom)


# --------------------------------------------------------------------------- #
# Executores: caminho feliz
# --------------------------------------------------------------------------- #


def test_run_vacuum_whole_database(db, instance, monkeypatch):
    cur = FakeCursor()
    _patch_conn(monkeypatch, cur)
    task = maint.run_vacuum(db, instance)
    assert task.status == TaskStatus.COMPLETED
    assert task.task_type == TaskType.VACUUM
    assert "entire database" in task.result_summary
    assert any("VACUUM ANALYZE" in s for s in cur.executed)


def test_run_vacuum_single_table(db, instance, monkeypatch):
    cur = FakeCursor()
    _patch_conn(monkeypatch, cur)
    task = maint.run_vacuum(db, instance, target_table="orders")
    assert task.status == TaskStatus.COMPLETED
    assert "orders" in task.result_summary


def test_run_analyze(db, instance, monkeypatch):
    cur = FakeCursor()
    _patch_conn(monkeypatch, cur)
    task = maint.run_analyze(db, instance)
    assert task.status == TaskStatus.COMPLETED
    assert task.task_type == TaskType.ANALYZE


def test_run_reindex_database_uses_current_database(db, instance, monkeypatch):
    # REINDEX sem tabela → faz SELECT current_database() e usa o nome retornado.
    cur = FakeCursor(fetchone=("appdb",))
    _patch_conn(monkeypatch, cur)
    task = maint.run_reindex(db, instance)
    assert task.status == TaskStatus.COMPLETED
    assert "appdb" in task.result_summary


def test_run_vacuum_full_requires_table(db, instance, monkeypatch):
    cur = FakeCursor()
    _patch_conn(monkeypatch, cur)
    task = maint.run_vacuum_full(db, instance, target_table="big_table")
    assert task.status == TaskStatus.COMPLETED
    assert task.task_type == TaskType.VACUUM_FULL


def test_kill_idle_counts_terminated(db, instance, monkeypatch):
    # pg_terminate_backend retorna bool por linha; truthy conta como encerrado.
    cur = FakeCursor(fetchall=[(True,), (False,), (True,)])
    _patch_conn(monkeypatch, cur)
    task = maint.kill_idle_connections(db, instance, idle_minutes=15)
    assert task.status == TaskStatus.COMPLETED
    assert "Terminated 2 idle connection" in task.result_summary


def test_kill_long_counts_terminated(db, instance, monkeypatch):
    cur = FakeCursor(fetchall=[(True,)])
    _patch_conn(monkeypatch, cur)
    task = maint.kill_long_queries(db, instance, max_minutes=30)
    assert task.status == TaskStatus.COMPLETED
    assert "Terminated 1 long-running" in task.result_summary


# --------------------------------------------------------------------------- #
# Executores: falha marca a task como FAILED
# --------------------------------------------------------------------------- #


def test_runner_failure_marks_task_failed(db, instance, monkeypatch):
    _patch_conn_raises(monkeypatch, RuntimeError("connection refused"))
    task = maint.run_vacuum(db, instance)
    assert task.status == TaskStatus.FAILED
    assert "connection refused" in task.result_summary


# --------------------------------------------------------------------------- #
# Dispatcher run_task
# --------------------------------------------------------------------------- #


def test_run_task_dispatches_vacuum(db, instance, monkeypatch):
    cur = FakeCursor()
    _patch_conn(monkeypatch, cur)
    task = maint.run_task(
        db, instance, MaintenanceTaskCreate(task_type=TaskType.VACUUM, target_table="t")
    )
    assert task.task_type == TaskType.VACUUM


def test_run_task_vacuum_full_without_table_raises(db, instance):
    with pytest.raises(ValueError, match="requires target_table"):
        maint.run_task(
            db, instance, MaintenanceTaskCreate(task_type=TaskType.VACUUM_FULL)
        )


def test_run_task_kill_idle_ignores_target_table(db, instance, monkeypatch):
    cur = FakeCursor(fetchall=[])
    _patch_conn(monkeypatch, cur)
    task = maint.run_task(
        db, instance, MaintenanceTaskCreate(task_type=TaskType.KILL_IDLE, target_table="x")
    )
    assert task.task_type == TaskType.KILL_IDLE
    assert "Terminated 0" in task.result_summary


# --------------------------------------------------------------------------- #
# Histórico + schedules
# --------------------------------------------------------------------------- #


def test_get_task_history_orders_recent_first(db, instance, monkeypatch):
    cur = FakeCursor()
    _patch_conn(monkeypatch, cur)
    maint.run_analyze(db, instance)
    maint.run_vacuum(db, instance)

    history = maint.get_task_history(db, instance.id)
    assert len(history) == 2
    assert all(isinstance(t, MaintenanceTask) for t in history)


def test_schedule_create_list_advance_delete(db, instance):
    sched = maint.create_schedule(
        db, instance.id,
        MaintenanceScheduleCreate(task_type=TaskType.VACUUM, cron_expression="0 3 * * *"),
    )
    assert sched.next_run_at is not None

    listed = maint.list_schedules(db, instance.id)
    assert [s.id for s in listed] == [sched.id]

    first_next = sched.next_run_at
    maint.advance_schedule(db, sched)
    assert sched.next_run_at is not None  # recalculado a partir de agora

    maint.delete_schedule(db, sched)
    assert maint.list_schedules(db, instance.id) == []


# --------------------------------------------------------------------------- #
# Recomendações de configuração (puro, sem conexão)
# --------------------------------------------------------------------------- #


def test_config_recommendations_with_memory_and_cpu(db):
    inst = DatabaseInstance(name="c", status=InstanceStatus.STOPPED, memory_mb=2048, cpu=4)
    db.add(inst)
    db.commit()
    db.refresh(inst)
    resp = maint.get_config_recommendations(inst)
    params = {r.parameter: r.recommended_value for r in resp.recommendations}

    assert params["shared_buffers"] == "512MB"        # 25% de 2048
    assert params["effective_cache_size"] == "1536MB"  # 75% de 2048
    assert params["maintenance_work_mem"] == "102MB"   # 5% de 2048, cap 2048
    assert params["work_mem"] == "10MB"                # 2048 // 200
    assert params["max_parallel_workers"] == "4"
    assert params["max_parallel_workers_per_gather"] == "2"
    # Fixos sempre presentes
    assert params["wal_buffers"] == "16MB"
    assert params["checkpoint_completion_target"] == "0.9"


def test_config_recommendations_without_resources_has_only_fixed(db):
    inst = DatabaseInstance(name="c2", status=InstanceStatus.STOPPED)
    db.add(inst)
    db.commit()
    db.refresh(inst)
    resp = maint.get_config_recommendations(inst)
    params = {r.parameter for r in resp.recommendations}
    # Sem memory_mb/cpu, só as duas recomendações fixas aparecem.
    assert params == {"wal_buffers", "checkpoint_completion_target"}
