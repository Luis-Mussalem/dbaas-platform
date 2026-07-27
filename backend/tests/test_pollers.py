"""
Tests for the background loops (PHASE 3-7): status poller, metrics poller,
backup scheduler, maintenance scheduler, and alert evaluator.

Each loop exposes a SYNCHRONOUS tick function (poll_once / poll_metrics_once /
poll_schedules_once / evaluate_once) that opens its own SessionLocal — in
other words, it runs outside the HTTP context. We test that function directly, with the
external dependencies (Docker, pg_dump, metrics collection) replaced by
stubs. The async versions (…_loop) are exercised through a controlled cycle,
with asyncio.to_thread replaced by an in-loop shim that fires the stop_event.

Important: the tick uses its own SessionLocal(), but points to the SAME test
database as the `db` fixture. After the tick, we use db.expire_all() to re-read the state
committed by the poller's session.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.core.encryption import decrypt_value, encrypt_value
from src.models.backup import BackupSchedule, BackupStrategy
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.instance_status_history import InstanceStatusHistory
from src.models.maintenance import MaintenanceSchedule, TaskType
from src.models.metric import Metric
from src.services import alert_evaluator, backup_scheduler, maintenance_scheduler, metrics_poller
from src.services import instance as instance_service
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
    def __init__(
        self,
        status: ProvisionerStatus,
        port: int | None = None,
        start_port: int | None = None,
        start_error: bool = False,
    ):
        self._status = status
        self._port = port
        self._start_port = start_port
        self._start_error = start_error
        self.started = False

    def get_status(self, instance_id):
        return self._status

    def get_port(self, instance_id):
        return self._port

    def start(self, instance_id):
        self.started = True
        if self._start_error:
            raise RuntimeError("simulated start failure")
        return self._start_port


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
    # The RUNNING→FAILED transition was recorded in the history.
    hist = (
        db.query(InstanceStatusHistory)
        .filter_by(instance_id=running_instance.id)
        .all()
    )
    assert [h.status for h in hist] == [InstanceStatus.FAILED]


def test_poll_once_keeps_running_when_container_running(db, running_instance, monkeypatch):
    monkeypatch.setattr(
        status_poller, "get_provisioner",
        lambda: _FakeProvisioner(ProvisionerStatus.RUNNING),
    )
    status_poller.poll_once()

    db.expire_all()
    refreshed = db.get(DatabaseInstance, running_instance.id)
    assert refreshed.status == InstanceStatus.RUNNING
    # A poll with no status change must NOT write history (avoids flooding it).
    assert (
        db.query(InstanceStatusHistory)
        .filter_by(instance_id=running_instance.id)
        .count()
    ) == 0


def test_poll_once_resyncs_port_when_container_republished(db, running_instance, monkeypatch):
    # Container alive on a new port (Docker restarted it after a host restart) →
    # the poller resyncs the port and connection_uri.
    monkeypatch.setattr(
        status_poller, "get_provisioner",
        lambda: _FakeProvisioner(ProvisionerStatus.RUNNING, port=62000),
    )
    status_poller.poll_once()

    db.expire_all()
    refreshed = db.get(DatabaseInstance, running_instance.id)
    assert refreshed.status == InstanceStatus.RUNNING
    assert refreshed.port == 62000
    assert "62000" in decrypt_value(refreshed.connection_uri)


def test_poll_once_recovers_failed_when_container_restartable(db, monkeypatch):
    # FAILED instance whose stopped container can be restarted → auto-recovery.
    # (This is the case of a Docker restart that took the instances down.)
    inst = DatabaseInstance(
        name="failed-db",
        status=InstanceStatus.FAILED,
        port=5433,
        connection_uri=encrypt_value("postgresql://u:p@127.0.0.1:5433/appdb"),
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)

    fake = _FakeProvisioner(ProvisionerStatus.STOPPED, start_port=63000)
    monkeypatch.setattr(status_poller, "get_provisioner", lambda: fake)
    status_poller.poll_once()

    db.expire_all()
    refreshed = db.get(DatabaseInstance, inst.id)
    assert fake.started is True
    assert refreshed.status == InstanceStatus.RUNNING
    assert refreshed.port == 63000
    assert "63000" in decrypt_value(refreshed.connection_uri)


def test_poll_once_keeps_failed_when_container_gone(db, monkeypatch):
    # FAILED instance with no container (NOT_FOUND) → nothing to recover, stays FAILED.
    inst = DatabaseInstance(
        name="gone-db",
        status=InstanceStatus.FAILED,
        connection_uri=encrypt_value("postgresql://u:p@127.0.0.1:5433/appdb"),
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)

    monkeypatch.setattr(
        status_poller, "get_provisioner",
        lambda: _FakeProvisioner(ProvisionerStatus.NOT_FOUND),
    )
    status_poller.poll_once()

    db.expire_all()
    refreshed = db.get(DatabaseInstance, inst.id)
    assert refreshed.status == InstanceStatus.FAILED


def test_poll_once_marks_failed_when_restart_fails(db, running_instance, monkeypatch):
    # Container stopped but the restart fails → instance marked FAILED.
    fake = _FakeProvisioner(ProvisionerStatus.STOPPED, start_error=True)
    monkeypatch.setattr(status_poller, "get_provisioner", lambda: fake)
    status_poller.poll_once()

    db.expire_all()
    refreshed = db.get(DatabaseInstance, running_instance.id)
    assert fake.started is True
    assert refreshed.status == InstanceStatus.FAILED


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
    # An instance that blows up during collection doesn't take down the cycle (exception swallowed).
    def boom(session, instance):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(metrics_poller, "collect_and_store", boom)
    metrics_poller.poll_metrics_once()  # doesn't raise

    db.expire_all()
    assert db.query(Metric).count() == 0


def test_poll_metrics_once_rolls_back_failed_instance(db, monkeypatch):
    # Regression: a collection that leaves the session dirty and blows up must not
    # contaminate the commit of the cycle's following instances (db.rollback()).
    for name in ("m-db-1", "m-db-2"):
        db.add(
            DatabaseInstance(
                name=name,
                status=InstanceStatus.RUNNING,
                connection_uri=encrypt_value(f"postgresql://u:p@127.0.0.1:5433/{name}"),
            )
        )
    db.commit()

    failed_once = []

    def flaky_collect(session, instance):
        if not failed_once:
            failed_once.append(instance.id)
            # Leaves pending garbage in the session before blowing up — without a rollback,
            # this orphan Metric would be committed together with the next instance.
            session.add(
                Metric(instance_id=instance.id, metric_name="orphan", value=1.0)
            )
            raise RuntimeError("connection refused")
        session.add(
            Metric(instance_id=instance.id, metric_name="cache_hit_ratio", value=99.0)
        )
        session.commit()
        return 1

    monkeypatch.setattr(metrics_poller, "collect_and_store", flaky_collect)
    metrics_poller.poll_metrics_once()

    db.expire_all()
    assert db.query(Metric).filter_by(metric_name="orphan").count() == 0
    assert db.query(Metric).filter_by(metric_name="cache_hit_ratio").count() == 1


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
        next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),  # overdue
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
    assert schedule.last_run_at is not None  # schedule advanced


def test_backup_scheduler_resyncs_port_before_backup(db, running_instance, monkeypatch):
    """
    Docker republishes ports when containers restart. If an overdue backup runs
    before the status_poller's first pass, pg_dump hits a dead port,
    writes FAILED, and the schedule advances — leaving an overdue-backup CRITICAL
    open until the next cron window. That's why it checks the port beforehand.
    """
    stale_port = running_instance.port
    db.add(BackupSchedule(
        instance_id=running_instance.id,
        strategy=BackupStrategy.LOGICAL,
        cron_expression="*/5 * * * *",
        retention_days=7,
        is_active=True,
        next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    ))
    db.commit()

    port_at_backup = {}

    def fake_logical(session, instance, backup_type, retention_days):
        port_at_backup["port"] = instance.port

    monkeypatch.setattr(backup_scheduler, "create_logical_backup", fake_logical)
    monkeypatch.setattr(backup_scheduler, "apply_retention", lambda s, iid: 0)
    monkeypatch.setattr(
        instance_service, "get_provisioner",
        lambda: SimpleNamespace(get_port=lambda iid: 54321),
    )

    backup_scheduler.poll_schedules_once()

    assert stale_port != 54321
    assert port_at_backup["port"] == 54321  # backup used the live port, not the database's


def test_backup_scheduler_runs_when_port_check_fails(db, running_instance, monkeypatch):
    """An unavailable provisioner must not block the backup — it's only best-effort."""
    db.add(BackupSchedule(
        instance_id=running_instance.id,
        strategy=BackupStrategy.LOGICAL,
        cron_expression="*/5 * * * *",
        retention_days=7,
        is_active=True,
        next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    ))
    db.commit()

    called = []
    monkeypatch.setattr(
        backup_scheduler, "create_logical_backup",
        lambda *a, **k: called.append(1),
    )
    monkeypatch.setattr(backup_scheduler, "apply_retention", lambda s, iid: 0)

    def boom():
        raise RuntimeError("docker daemon unreachable")

    monkeypatch.setattr(instance_service, "get_provisioner", boom)

    backup_scheduler.poll_schedules_once()
    assert called == [1]


def test_backup_scheduler_skips_when_no_due(db, monkeypatch):
    # No overdue schedule → early return, nothing is called.
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

    # run_task is imported inside the function → patch on the origin module.
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
    # With no active rules, the cycle just opens/closes the session without error.
    alert_evaluator.evaluate_once()


def test_evaluate_once_swallows_errors(monkeypatch):
    monkeypatch.setattr(
        "src.services.alert.evaluate_all_rules",
        lambda session: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    # Exception is caught and logged — evaluate_once doesn't propagate it.
    alert_evaluator.evaluate_once()


# --------------------------------------------------------------------------- #
# Async loops: a controlled cycle via a to_thread shim
# --------------------------------------------------------------------------- #


def _run_one_loop_cycle(module, loop_coro_name, tick_name):
    """
    Runs exactly one cycle of an async …_loop.

    Replaces asyncio.to_thread with a shim that runs the tick on the same event
    loop (no thread, avoiding thread-safety issues with asyncio.Event) and
    sets the stop_event right after — so the while loop ends after one iteration.
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


def test_metrics_cleanup_is_time_based_not_cycle_based(db, monkeypatch):
    """
    Retention cleanup runs once per WALL-CLOCK day.

    Counting cycles, the periodicity would depend on the collection interval: during
    a usage simulation it drops to 5s and cleanup would end up scanning the table
    every ~2h, with nothing to delete.
    """
    from src.services import metrics_poller

    monkeypatch.setattr(metrics_poller, "_last_metrics_cleanup", None)

    metrics_poller.poll_metrics_once()
    first = metrics_poller._last_metrics_cleanup
    assert first is not None, "the first pass should clean up"

    for _ in range(5):
        metrics_poller.poll_metrics_once()
    assert metrics_poller._last_metrics_cleanup == first

    # After a day passes, cleans up again.
    monkeypatch.setattr(
        metrics_poller,
        "_last_metrics_cleanup",
        first - metrics_poller._METRICS_CLEANUP_INTERVAL,
    )
    metrics_poller.poll_metrics_once()
    assert metrics_poller._last_metrics_cleanup > first
