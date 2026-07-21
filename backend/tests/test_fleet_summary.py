"""
Testes do agregado por instância dos cards da frota.

GET /api/v1/instances/fleet-summary lê só do banco da plataforma (metrics,
alert_events, backups, instance_status_history) — não conecta ao banco
monitorado. Cobrimos: cálculo de throughput a partir do contador cumulativo,
crescimento de disco em 24h, alertas abertos com a pior severidade, último
backup, ausência de dados (campos null) e escopo multi-tenant.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.core.encryption import encrypt_value
from src.models.alert import AlertCondition, AlertEvent, AlertRule, AlertSeverity
from src.models.backup import Backup, BackupStatus, BackupStrategy
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.instance_status_history import InstanceStatusHistory
from src.models.metric import Metric

URL = "/api/v1/instances/fleet-summary"


@pytest.fixture
def instance(db):
    inst = DatabaseInstance(
        name="fleet-db",
        status=InstanceStatus.RUNNING,
        storage_gb=1,
        connection_uri=encrypt_value("postgresql://u:p@127.0.0.1:5433/appdb"),
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _rule(db, instance, severity=AlertSeverity.WARNING) -> AlertRule:
    rule = AlertRule(
        instance_id=instance.id,
        name=f"r-{severity.value}",
        metric_type="cache_hit_ratio",
        condition=AlertCondition.LT,
        threshold=95.0,
        severity=severity,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def _summary_of(payload, instance) -> dict:
    return next(s for s in payload["instances"] if s["instance_id"] == str(instance.id))


def test_fleet_summary_requires_auth(client, instance):
    assert client.get(URL).status_code == 401


def test_empty_instance_has_all_metrics_null(client, auth_headers, instance):
    """Instância sem coleta: campos null e zero alertas — nunca zeros inventados."""
    headers, _ = auth_headers()
    body = _summary_of(client.get(URL, headers=headers).json(), instance)

    assert body["queries_per_second"] is None
    assert body["p95_latency_ms"] is None
    assert body["db_size_bytes"] is None
    assert body["size_delta_24h_bytes"] is None
    assert body["last_backup_at"] is None
    assert body["open_alerts"] == 0
    assert body["max_alert_severity"] is None


def test_queries_per_second_from_cumulative_counter(client, auth_headers, instance, db):
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    db.add_all([
        Metric(instance_id=instance.id, metric_name="xact_commit", value=1_000.0,
               collected_at=now - timedelta(seconds=60)),
        Metric(instance_id=instance.id, metric_name="xact_commit", value=4_000.0,
               collected_at=now),
    ])
    db.commit()

    body = _summary_of(client.get(URL, headers=headers).json(), instance)
    assert body["queries_per_second"] == 50.0  # 3000 commits / 60s


def test_counter_reset_is_discarded(client, auth_headers, instance, db):
    """Delta negativo = Postgres reiniciou; melhor não reportar que reportar um pico."""
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    db.add_all([
        Metric(instance_id=instance.id, metric_name="xact_commit", value=9_000.0,
               collected_at=now - timedelta(seconds=60)),
        Metric(instance_id=instance.id, metric_name="xact_commit", value=10.0,
               collected_at=now),
    ])
    db.commit()

    body = _summary_of(client.get(URL, headers=headers).json(), instance)
    assert body["queries_per_second"] is None


def test_size_delta_ignores_samples_older_than_24h(client, auth_headers, instance, db):
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    db.add_all([
        # Fora da janela: não pode virar a base do cálculo.
        Metric(instance_id=instance.id, metric_name="db_size_bytes", value=100.0,
               collected_at=now - timedelta(hours=30)),
        Metric(instance_id=instance.id, metric_name="db_size_bytes", value=1_000.0,
               collected_at=now - timedelta(hours=20)),
        Metric(instance_id=instance.id, metric_name="db_size_bytes", value=1_500.0,
               collected_at=now),
    ])
    db.commit()

    body = _summary_of(client.get(URL, headers=headers).json(), instance)
    assert body["db_size_bytes"] == 1_500.0
    assert body["size_delta_24h_bytes"] == 500.0


def test_open_alerts_counted_with_worst_severity(client, auth_headers, instance, db):
    headers, _ = auth_headers()
    warning, critical = _rule(db, instance), _rule(db, instance, AlertSeverity.CRITICAL)
    db.add_all([
        AlertEvent(rule_id=warning.id, instance_id=instance.id,
                   current_value=1, message="open-warning"),
        AlertEvent(rule_id=critical.id, instance_id=instance.id,
                   current_value=1, message="open-critical"),
        # Resolvido: não conta.
        AlertEvent(rule_id=warning.id, instance_id=instance.id,
                   current_value=1, message="closed",
                   resolved_at=datetime.now(timezone.utc)),
    ])
    db.commit()

    body = _summary_of(client.get(URL, headers=headers).json(), instance)
    assert body["open_alerts"] == 2
    assert body["max_alert_severity"] == "critical"


def test_last_backup_reports_failure(client, auth_headers, instance, db):
    """O backup mais recente é o que vale — inclusive quando falhou."""
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    db.add_all([
        Backup(instance_id=instance.id, strategy=BackupStrategy.LOGICAL,
               status=BackupStatus.COMPLETED, created_at=now - timedelta(hours=6)),
        Backup(instance_id=instance.id, strategy=BackupStrategy.LOGICAL,
               status=BackupStatus.FAILED, created_at=now - timedelta(minutes=5)),
    ])
    db.commit()

    body = _summary_of(client.get(URL, headers=headers).json(), instance)
    assert body["last_backup_status"] == "failed"


def test_deleted_backup_is_not_the_last_one(client, auth_headers, instance, db):
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    db.add_all([
        Backup(instance_id=instance.id, strategy=BackupStrategy.LOGICAL,
               status=BackupStatus.COMPLETED, created_at=now - timedelta(hours=6)),
        Backup(instance_id=instance.id, strategy=BackupStrategy.LOGICAL,
               status=BackupStatus.DELETED, created_at=now),
    ])
    db.commit()

    body = _summary_of(client.get(URL, headers=headers).json(), instance)
    assert body["last_backup_status"] == "completed"


def test_uptime_comes_from_status_history(client, auth_headers, instance, db):
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    db.add(InstanceStatusHistory(
        instance_id=instance.id, status=InstanceStatus.RUNNING,
        changed_at=now - timedelta(days=10),
    ))
    db.commit()

    body = _summary_of(client.get(URL, headers=headers).json(), instance)
    assert body["uptime_30d_pct"] == 100.0


def test_summary_is_scoped_to_the_users_company(
    client, auth_headers, make_company, db
):
    """Membro de empresa não vê o agregado das instâncias de outra."""
    mine, theirs = make_company("Mine"), make_company("Theirs")
    db.add_all([
        DatabaseInstance(name="mine-db", status=InstanceStatus.RUNNING, company_id=mine.id),
        DatabaseInstance(name="theirs-db", status=InstanceStatus.RUNNING, company_id=theirs.id),
    ])
    db.commit()

    headers, _ = auth_headers(email="member@mine.com", company_id=mine.id)
    payload = client.get(URL, headers=headers).json()

    instance_ids = {s["instance_id"] for s in payload["instances"]}
    mine_id = str(db.query(DatabaseInstance).filter_by(name="mine-db").one().id)
    theirs_id = str(db.query(DatabaseInstance).filter_by(name="theirs-db").one().id)
    assert mine_id in instance_ids
    assert theirs_id not in instance_ids
