"""
Testes do serviço de métricas (PHASE 4) sem um Postgres-alvo vivo.

- get_latest_metrics: lógica pura de SQL sobre a tabela metrics (último valor
  por metric_name) — testada com linhas reais inseridas no banco de teste.
- collect_and_store: get_connection e collect_base_metrics são substituídos por
  dublês; validamos persistência e o caso "sem dados → 0 métricas".
- check_health: psycopg.connect é substituído para simular banco saudável
  (SELECT 1 ok) e indisponível (exceção → 'unhealthy', sem propagar 5xx).
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
               collected_at=base + timedelta(minutes=1)),  # mais recente
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
        yield object()  # conexão nunca é usada de verdade

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
