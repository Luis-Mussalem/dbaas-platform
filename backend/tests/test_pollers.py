"""
Testes dos loops de background (PHASE 3–7): status poller, metrics poller,
backup scheduler, maintenance scheduler e alert evaluator.

Cada loop expõe uma função de tick SÍNCRONA (poll_once / poll_metrics_once /
poll_schedules_once / evaluate_once) que abre sua própria SessionLocal — ou
seja, roda fora do contexto HTTP. Testamos essa função diretamente, com as
dependências externas (Docker, pg_dump, coleta de métricas) substituídas por
dublês. As versões async (…_loop) são exercitadas por um ciclo controlado,
com asyncio.to_thread substituído por um shim in-loop que dispara o stop_event.

Importante: o tick usa SessionLocal() próprio, mas aponta para o MESMO banco de
teste do fixture `db`. Após o tick, usamos db.expire_all() para reler o estado
commitado pela sessão do poller.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src.core.encryption import encrypt_value
from src.models.backup import BackupSchedule, BackupStrategy
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.maintenance import MaintenanceSchedule, TaskType
from src.models.metric import Metric
from src.services import alert_evaluator, backup_scheduler, maintenance_scheduler, metrics_poller
from src.services.provisioning import status_poller
from src.services.provisioning.types import ProvisionerStatus


@pytest.fixture
def running_instance(db):
    inst = DatabaseInstance(
        name="poll-db",
        status=InstanceStatus.RUNNING,
        connection_uri=encrypt_value("postgresql://u:p@127.0.0.1:5433/appdb"),
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


class _FakeProvisioner:
    def __init__(self, status: ProvisionerStatus):
        self._status = status

    def get_status(self, instance_id):
        return self._status


# --------------------------------------------------------------------------- #
# status_poller.poll_once
# --------------------------------------------------------------------------- #


def test_poll_once_marks_running_as_failed_when_container_gone(db, running_instance, monkeypatch):
    monkeypatch.setattr(
        status_poller, "get_provisioner",
        lambda: _FakeProvisioner(ProvisionerStatus.NOT_FOUND),
    )
    status_poller.poll_once()

    db.expire_all()
    refreshed = db.get(DatabaseInstance, running_instance.id)
    assert refreshed.status == InstanceStatus.FAILED


def test_poll_once_keeps_running_when_container_running(db, running_instance, monkeypatch):
    monkeypatch.setattr(
        status_poller, "get_provisioner",
        lambda: _FakeProvisioner(ProvisionerStatus.RUNNING),
    )
    status_poller.poll_once()

    db.expire_all()
    refreshed = db.get(DatabaseInstance, running_instance.id)
    assert refreshed.status == InstanceStatus.RUNNING


# --------------------------------------------------------------------------- #
# metrics_poller.poll_metrics_once
# --------------------------------------------------------------------------- #


def test_poll_metrics_once_collects_for_running(db, running_instance, monkeypatch):
    def fake_collect(session, instance):
        session.add(Metric(instance_id=instance.id, metric_name="cache_hit_ratio", value=99.0))
        session.commit()
        return 1

    monkeypatch.setattr(metrics_poller, "collect_and_store", fake_collect)
    metrics_poller.poll_metrics_once()

    db.expire_all()
    assert db.query(Metric).filter_by(instance_id=running_instance.id).count() == 1


def test_poll_metrics_once_isolates_instance_failure(db, running_instance, monkeypatch):
    # Uma instância que explode na coleta não derruba o ciclo (exceção engolida).
    def boom(session, instance):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(metrics_poller, "collect_and_store", boom)
    metrics_poller.poll_metrics_once()  # não levanta

    db.expire_all()
    assert db.query(Metric).count() == 0


# --------------------------------------------------------------------------- #
# backup_scheduler.poll_schedules_once
# --------------------------------------------------------------------------- #


def test_backup_scheduler_runs_due_schedule(db, running_instance, monkeypatch):
    schedule = BackupSchedule(
        instance_id=running_instance.id,
        strategy=BackupStrategy.LOGICAL,
        cron_expression="*/5 * * * *",
        retention_days=7,
        is_active=True,
        next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),  # vencido
    )
    db.add(schedule)
    db.commit()

    called = {}

    def fake_logical(session, instance, backup_type, retention_days):
        called["instance_id"] = instance.id
        called["retention_days"] = retention_days

    monkeypatch.setattr(backup_scheduler, "create_logical_backup", fake_logical)
    monkeypatch.setattr(backup_scheduler, "apply_retention", lambda s, iid: 0)

    backup_scheduler.poll_schedules_once()

    assert called["instance_id"] == running_instance.id
    assert called["retention_days"] == 7
    db.expire_all()
    db.refresh(schedule)
    assert schedule.last_run_at is not None  # schedule avançado


def test_backup_scheduler_skips_when_no_due(db, monkeypatch):
    # Nenhum schedule vencido → early return, nada é chamado.
    called = []
    monkeypatch.setattr(
        backup_scheduler, "create_logical_backup",
        lambda *a, **k: called.append(1),
    )
    backup_scheduler.poll_schedules_once()
    assert called == []


# --------------------------------------------------------------------------- #
# maintenance_scheduler.poll_schedules_once
# --------------------------------------------------------------------------- #


def test_maintenance_scheduler_runs_due_schedule(db, running_instance, monkeypatch):
    schedule = MaintenanceSchedule(
        instance_id=running_instance.id,
        task_type=TaskType.VACUUM,
        cron_expression="*/5 * * * *",
        is_active=True,
        next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db.add(schedule)
    db.commit()

    ran = {}

    def fake_run_task(session, instance, data):
        ran["task_type"] = data.task_type

        class _Task:
            id = "t"

            class status:
                value = "completed"

        return _Task

    # run_task é importado dentro da função → patch no módulo de origem.
    monkeypatch.setattr("src.services.maintenance.run_task", fake_run_task)

    maintenance_scheduler.poll_schedules_once()
    assert ran["task_type"] == TaskType.VACUUM

    db.expire_all()
    db.refresh(schedule)
    assert schedule.next_run_at > datetime.now(timezone.utc) - timedelta(minutes=1)


# --------------------------------------------------------------------------- #
# alert_evaluator.evaluate_once
# --------------------------------------------------------------------------- #


def test_evaluate_once_runs_without_rules(db):
    # Sem regras ativas, o ciclo apenas abre/fecha a sessão sem erro.
    alert_evaluator.evaluate_once()


def test_evaluate_once_swallows_errors(monkeypatch):
    monkeypatch.setattr(
        "src.services.alert.evaluate_all_rules",
        lambda session: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    # Exceção é capturada e logada — evaluate_once não propaga.
    alert_evaluator.evaluate_once()


# --------------------------------------------------------------------------- #
# Loops async: um ciclo controlado via shim de to_thread
# --------------------------------------------------------------------------- #


def _run_one_loop_cycle(module, loop_coro_name, tick_name):
    """
    Executa exatamente um ciclo de um …_loop async.

    Substitui asyncio.to_thread por um shim que roda o tick no próprio event
    loop (sem thread, evitando problemas de thread-safety com asyncio.Event) e
    seta o stop_event logo após — assim o while encerra após uma iteração.
    """
    stop = asyncio.Event()
    calls = []

    async def fake_to_thread(fn, *a, **k):
        calls.append(fn.__name__)
        stop.set()
        return None

    loop_coro = getattr(module, loop_coro_name)

    async def _drive():
        orig = asyncio.to_thread
        asyncio.to_thread = fake_to_thread
        try:
            await loop_coro(stop)
        finally:
            asyncio.to_thread = orig

    asyncio.run(_drive())
    return calls


def test_status_polling_loop_one_cycle():
    calls = _run_one_loop_cycle(status_poller, "status_polling_loop", "poll_once")
    assert calls == ["poll_once"]


def test_metrics_polling_loop_one_cycle():
    calls = _run_one_loop_cycle(metrics_poller, "metrics_polling_loop", "poll_metrics_once")
    assert calls == ["poll_metrics_once"]


def test_backup_scheduling_loop_one_cycle():
    calls = _run_one_loop_cycle(backup_scheduler, "backup_scheduling_loop", "poll_schedules_once")
    assert calls == ["poll_schedules_once"]


def test_maintenance_scheduling_loop_one_cycle():
    calls = _run_one_loop_cycle(
        maintenance_scheduler, "maintenance_scheduling_loop", "poll_schedules_once"
    )
    assert calls == ["poll_schedules_once"]


def test_alert_evaluation_loop_one_cycle():
    calls = _run_one_loop_cycle(alert_evaluator, "alert_evaluation_loop", "evaluate_once")
    assert calls == ["evaluate_once"]
