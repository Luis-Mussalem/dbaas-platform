"""
Tests for the metrics service (PHASE 4) without a live target Postgres.

- get_latest_metrics: pure SQL logic over the metrics table (latest value
  per metric_name) — tested with real rows inserted into the test database.
- collect_and_store: get_connection and collect_base_metrics are replaced by
  stubs; we validate persistence and the "no data → 0 metrics" case.
- check_health: psycopg.connect is replaced to simulate a healthy database
  (SELECT 1 ok) and an unavailable one (exception → 'unhealthy', without propagating a 5xx).
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from src.core.encryption import encrypt_value
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.metric import Metric
from src.services import metrics as metrics_service


@pytest.fixture
def instance(db):
    inst = DatabaseInstance(
        name="metrics-db",
        status=InstanceStatus.RUNNING,
        connection_uri=encrypt_value("postgresql://u:p@127.0.0.1:5433/appdb"),
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


# --------------------------------------------------------------------------- #
# get_latest_metrics
# --------------------------------------------------------------------------- #


def test_get_latest_metrics_returns_most_recent_per_name(db, instance):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.add_all([
        Metric(instance_id=instance.id, metric_name="cache_hit_ratio", value=90.0, collected_at=base),
        Metric(instance_id=instance.id, metric_name="cache_hit_ratio", value=98.5,
               collected_at=base + timedelta(minutes=1)),  # more recent
        Metric(instance_id=instance.id, metric_name="db_size_bytes", value=1234.0, collected_at=base),
    ])
    db.commit()

    latest = metrics_service.get_latest_metrics(db, instance.id)
    assert latest == {"cache_hit_ratio": 98.5, "db_size_bytes": 1234.0}


def test_get_latest_metrics_empty(db, instance):
    assert metrics_service.get_latest_metrics(db, instance.id) == {}


# --------------------------------------------------------------------------- #
# collect_and_store
# --------------------------------------------------------------------------- #


def test_collect_and_store_persists_metrics(db, instance, monkeypatch):
    @contextmanager
    def fake_conn(inst):
        yield object()  # connection is never actually used

    monkeypatch.setattr(metrics_service, "get_connection", fake_conn)
    monkeypatch.setattr(
        metrics_service, "collect_base_metrics",
        lambda conn: {"connections_active": 3.0, "cache_hit_ratio": 99.0},
    )

    count = metrics_service.collect_and_store(db, instance)
    assert count == 2
    stored = {m.metric_name: m.value for m in db.query(Metric).all()}
    assert stored == {"connections_active": 3.0, "cache_hit_ratio": 99.0}


def test_collect_and_store_no_data_returns_zero(db, instance, monkeypatch):
    @contextmanager
    def fake_conn(inst):
        yield object()

    monkeypatch.setattr(metrics_service, "get_connection", fake_conn)
    monkeypatch.setattr(metrics_service, "collect_base_metrics", lambda conn: {})

    assert metrics_service.collect_and_store(db, instance) == 0
    assert db.query(Metric).count() == 0


def test_collect_and_store_persists_latency_percentiles(db, instance, monkeypatch):
    @contextmanager
    def fake_conn(inst):
        yield object()

    monkeypatch.setattr(metrics_service, "get_connection", fake_conn)
    monkeypatch.setattr(
        metrics_service, "collect_base_metrics",
        lambda conn: {"connections_active": 1.0},
    )
    # Instance with pg_stat_statements → the three percentiles become extra metrics.
    monkeypatch.setattr(
        metrics_service, "collect_latency_percentiles",
        lambda conn: {
            "p50_query_latency_ms": 4.0,
            "p95_query_latency_ms": 12.5,
            "p99_query_latency_ms": 31.0,
        },
    )

    count = metrics_service.collect_and_store(db, instance)
    assert count == 4
    stored = {m.metric_name: m.value for m in db.query(Metric).all()}
    assert stored == {
        "connections_active": 1.0,
        "p50_query_latency_ms": 4.0,
        "p95_query_latency_ms": 12.5,
        "p99_query_latency_ms": 31.0,
    }


def test_collect_and_store_without_pg_stat_statements(db, instance, monkeypatch):
    """Without the extension, the percentiles disappear — the base metrics remain."""
    @contextmanager
    def fake_conn(inst):
        yield object()

    monkeypatch.setattr(metrics_service, "get_connection", fake_conn)
    monkeypatch.setattr(
        metrics_service, "collect_base_metrics",
        lambda conn: {"connections_active": 1.0},
    )
    monkeypatch.setattr(metrics_service, "collect_latency_percentiles", lambda conn: {})

    assert metrics_service.collect_and_store(db, instance) == 1


# --------------------------------------------------------------------------- #
# cache_hit_ratio derived from the interval
# --------------------------------------------------------------------------- #


def _collect_with_counters(monkeypatch, db, instance, blks_hit, blks_read):
    """Runs a collection cycle with the given cache counters."""
    @contextmanager
    def fake_conn(inst):
        yield object()

    monkeypatch.setattr(metrics_service, "get_connection", fake_conn)
    monkeypatch.setattr(metrics_service, "collect_latency_percentiles", lambda conn: {})
    monkeypatch.setattr(
        metrics_service, "collect_base_metrics",
        lambda conn: {"blks_hit": blks_hit, "blks_read": blks_read},
    )
    metrics_service.collect_and_store(db, instance)
    return metrics_service.get_latest_metrics(db, instance.id).get("cache_hit_ratio")


def test_cache_hit_ratio_omitted_on_first_collection(db, instance, monkeypatch):
    """With no previous collection there's no interval — better to not report than to guess."""
    assert _collect_with_counters(monkeypatch, db, instance, 100.0, 900.0) is None


def test_cache_hit_ratio_uses_interval_not_lifetime(db, instance, monkeypatch):
    """
    Bad cumulative total, good interval: the metric has to follow the interval.

    Lifetime = 100/(100+900) = 10%. Within the interval, 900 hits and 100 reads
    come in, i.e. 90% — that's the number that answers "is it reading from cache right now?".
    """
    _collect_with_counters(monkeypatch, db, instance, 100.0, 900.0)
    ratio = _collect_with_counters(monkeypatch, db, instance, 1000.0, 1000.0)
    assert ratio == 90.0


def test_cache_hit_ratio_carries_forward_on_counter_reset(db, instance, monkeypatch):
    """
    A server restart resets pg_stat_database — the delta would come out negative.

    Without this, every restart would drop the metric to near 0% and open a
    low-cache alert on a healthy fleet.
    """
    _collect_with_counters(monkeypatch, db, instance, 100.0, 900.0)
    assert _collect_with_counters(monkeypatch, db, instance, 1000.0, 1000.0) == 90.0
    # Counters go backwards: keeps the last known value.
    assert _collect_with_counters(monkeypatch, db, instance, 5.0, 40.0) == 90.0


def test_cache_hit_ratio_carries_forward_when_idle(db, instance, monkeypatch):
    """Idle database: no block read in the interval, undefined ratio."""
    _collect_with_counters(monkeypatch, db, instance, 100.0, 900.0)
    assert _collect_with_counters(monkeypatch, db, instance, 1000.0, 1000.0) == 90.0
    assert _collect_with_counters(monkeypatch, db, instance, 1000.0, 1000.0) == 90.0


# --------------------------------------------------------------------------- #
# check_health
# --------------------------------------------------------------------------- #


class _FakeHealthyConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self

    def execute(self, sql):
        return None


def test_check_health_healthy(instance, monkeypatch):
    monkeypatch.setattr(
        metrics_service.psycopg, "connect", lambda *a, **k: _FakeHealthyConn()
    )
    result = metrics_service.check_health(instance)
    assert result["status"] == "healthy"
    assert result["response_time_ms"] >= 0
    assert "checked_at" in result


def test_check_health_unhealthy_on_connection_error(instance, monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(metrics_service.psycopg, "connect", boom)
    result = metrics_service.check_health(instance)
    assert result["status"] == "unhealthy"
    assert "checked_at" in result
