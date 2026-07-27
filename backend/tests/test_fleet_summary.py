"""
Tests for the per-instance aggregate behind the fleet cards.

GET /api/v1/instances/fleet-summary only reads from the platform database (metrics,
alert_events, backups, instance_status_history) — it doesn't connect to the monitored
database. We cover: throughput calculation from the cumulative counter,
24h disk growth, open alerts with the worst severity, last
backup, absence of data (null fields), and multi-tenant scope.
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
    """Instance with no collection: null fields and zero alerts — never invented zeros."""
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
    # Two 15s buckets 30s apart: the derived series has one point, the rate
    # of that bucket; the number is the average of that series (= the single point).
    db.add_all([
        Metric(instance_id=instance.id, metric_name="xact_commit", value=1_000.0,
               collected_at=now - timedelta(seconds=30)),
        Metric(instance_id=instance.id, metric_name="xact_commit", value=4_000.0,
               collected_at=now),
    ])
    db.commit()

    body = _summary_of(client.get(URL, headers=headers).json(), instance)
    assert body["queries_per_second"] == 100.0  # 3000 commits / 30s


def test_queries_per_second_averages_over_the_window_not_adjacent_points(
    client, auth_headers, instance, db
):
    """
    The demo load commits in bursts: two adjacent points can fall between
    bursts (Δ=0) even with a live fleet. The number is the average of the whole series, not
    the rate of the last pair — so it returns a stable, non-zero value.
    """
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    # +180 bursts every 30s; the most recent pair (now, -15s) has Δ=0.
    db.add_all([
        Metric(instance_id=instance.id, metric_name="xact_commit", value=v,
               collected_at=now - timedelta(seconds=s))
        for v, s in [(1360, 0), (1360, 15), (1180, 30), (1180, 45), (1000, 60)]
    ])
    db.commit()

    body = _summary_of(client.get(URL, headers=headers).json(), instance)
    # 15s buckets → raw rates [12, 0, 12, 0]; the 1 min moving average smooths them
    # to [12, 6, 8, 6] and the number is the average of that line (8 q/s) — the point is
    # it's not the "0" of the last pair, but a stable value that reflects the window.
    assert body["queries_per_second"] == 8.0


def test_queries_per_second_ignores_a_stale_low_read(client, auth_headers, instance, db):
    """
    pg_stat_database sometimes returns a stale reading (an old snapshot): the
    counter "dips" slightly for one sample. If that sample becomes the most
    recent, the derivation must not zero out/nullify the card — the dip is ignored and the
    rate comes from the real growth.
    """
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    # Real growth of +180 over 15s; the most recent sample is STALE (2100 < 2180
    # from 15s before) — a ~4% dip, not a reset.
    db.add_all([
        Metric(instance_id=instance.id, metric_name="xact_commit", value=v,
               collected_at=now - timedelta(seconds=s))
        for v, s in [(2000, 30), (2180, 15), (2100, 0)]
    ])
    db.commit()

    body = _summary_of(client.get(URL, headers=headers).json(), instance)
    # A single real bucket: (2180-2000)/15 = 12 q/s. The stale 2100 reading is
    # ignored (emits no point), so it neither zeroes out nor nullifies the card.
    assert body["queries_per_second"] == 12.0


def test_counter_reset_is_discarded(client, auth_headers, instance, db):
    """Negative delta = Postgres restarted; better to not report than to report a spike."""
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
        # Outside the window: cannot become the basis of the calculation.
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
        # Resolved: doesn't count.
        AlertEvent(rule_id=warning.id, instance_id=instance.id,
                   current_value=1, message="closed",
                   resolved_at=datetime.now(timezone.utc)),
    ])
    db.commit()

    body = _summary_of(client.get(URL, headers=headers).json(), instance)
    assert body["open_alerts"] == 2
    assert body["max_alert_severity"] == "critical"


def test_last_backup_reports_failure(client, auth_headers, instance, db):
    """The most recent backup is what counts — even when it failed."""
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
    """A company's member doesn't see the aggregate of another company's instances."""
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
