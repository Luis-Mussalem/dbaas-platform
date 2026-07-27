"""
Tests for the admin panel (PHASE 8): GET /admin/dashboard and
GET /admin/audit-log.

Strategy: set up data directly in the database (instances in various statuses, alert
events, backups, maintenance tasks) and verify the aggregation returned
by the dashboard. For the audit log, seed via admin_service.write_audit_log and
exercise the filters (action / resource_type / user_id) and pagination.

No Docker: nothing here touches containers — just SQL aggregation logic.
"""
from datetime import datetime, timedelta, timezone

from src.models.alert import AlertEvent, AlertRule, AlertCondition, AlertSeverity
from src.models.audit_log import AuditLog
from src.models.backup import Backup, BackupStatus
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.instance_status_history import InstanceStatusHistory
from src.models.maintenance import MaintenanceTask, TaskStatus, TaskType
from src.models.metric import Metric
from src.services import admin as admin_service

DASHBOARD = "/api/v1/admin/dashboard"
AUDIT = "/api/v1/admin/audit-log"


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #


def test_dashboard_requires_auth(client):
    assert client.get(DASHBOARD).status_code == 401


def test_dashboard_empty_platform(client, auth_headers):
    headers, _ = auth_headers()
    resp = client.get(DASHBOARD, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_instances"] == 0
    assert body["instances_by_status"] == {}
    assert body["active_alerts"] == 0
    assert body["backups_last_24h"] == 0
    assert body["failed_backups_last_24h"] == 0
    assert body["pending_maintenance_tasks"] == 0


def test_dashboard_aggregates_instances_by_status(client, auth_headers, db):
    headers, _ = auth_headers()
    db.add_all([
        DatabaseInstance(name="r1", status=InstanceStatus.RUNNING),
        DatabaseInstance(name="r2", status=InstanceStatus.RUNNING),
        DatabaseInstance(name="s1", status=InstanceStatus.STOPPED),
        # Soft-deleted must NOT be counted.
        DatabaseInstance(
            name="gone",
            status=InstanceStatus.DELETED,
            deleted_at=datetime.now(timezone.utc),
        ),
    ])
    db.commit()

    body = client.get(DASHBOARD, headers=headers).json()
    assert body["total_instances"] == 3
    assert body["instances_by_status"] == {"running": 2, "stopped": 1}


def test_dashboard_counts_alerts_backups_and_maintenance(client, auth_headers, db):
    headers, _ = auth_headers()
    inst = DatabaseInstance(name="db", status=InstanceStatus.RUNNING)
    db.add(inst)
    db.commit()
    db.refresh(inst)

    rule = AlertRule(
        instance_id=inst.id,
        name="r",
        metric_type="backup_age_hours",
        condition=AlertCondition.GT,
        threshold=24.0,
        severity=AlertSeverity.CRITICAL,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    now = datetime.now(timezone.utc)
    db.add_all([
        # 1 open alert + 1 resolved (only the open one counts).
        AlertEvent(rule_id=rule.id, instance_id=inst.id, current_value=99, message="open"),
        AlertEvent(
            rule_id=rule.id, instance_id=inst.id, current_value=99,
            message="closed", resolved_at=now,
        ),
        # Backups in the last 24h: 1 completed + 1 failed; 1 old one outside the window.
        Backup(instance_id=inst.id, status=BackupStatus.COMPLETED, created_at=now),
        Backup(instance_id=inst.id, status=BackupStatus.FAILED, created_at=now),
        Backup(
            instance_id=inst.id, status=BackupStatus.COMPLETED,
            created_at=now - timedelta(hours=48),
        ),
        # Pending/running maintenance counts; completed doesn't.
        MaintenanceTask(instance_id=inst.id, task_type=TaskType.VACUUM, status=TaskStatus.PENDING),
        MaintenanceTask(instance_id=inst.id, task_type=TaskType.REINDEX, status=TaskStatus.RUNNING),
        MaintenanceTask(instance_id=inst.id, task_type=TaskType.ANALYZE, status=TaskStatus.COMPLETED),
    ])
    db.commit()

    body = client.get(DASHBOARD, headers=headers).json()
    assert body["active_alerts"] == 1
    assert body["backups_last_24h"] == 2
    assert body["failed_backups_last_24h"] == 1
    assert body["pending_maintenance_tasks"] == 2


# --------------------------------------------------------------------------- #
# Dashboard — performance KPIs (queries/s, p95, uptime)
# --------------------------------------------------------------------------- #


def test_dashboard_performance_kpis_empty_when_no_data(client, auth_headers):
    headers, _ = auth_headers()
    body = client.get(DASHBOARD, headers=headers).json()
    # No samples: throughput 0, latency/uptime "—" (None), never a false zero.
    assert body["queries_per_second"] == 0.0
    assert body["p95_latency_ms"] is None
    assert body["fleet_uptime_pct"] is None


def test_dashboard_queries_per_second_from_commit_rate(client, auth_headers, db):
    headers, _ = auth_headers()
    inst = DatabaseInstance(name="qps", status=InstanceStatus.RUNNING)
    db.add(inst)
    db.commit()
    db.refresh(inst)

    # Two 15s buckets 30s apart → the derived series has one point.
    t0 = datetime.now(timezone.utc) - timedelta(seconds=30)
    db.add_all([
        Metric(instance_id=inst.id, metric_name="xact_commit", value=1000.0, collected_at=t0),
        Metric(
            instance_id=inst.id, metric_name="xact_commit", value=1060.0,
            collected_at=t0 + timedelta(seconds=30),
        ),
    ])
    db.commit()

    body = client.get(DASHBOARD, headers=headers).json()
    # 60 commits in 30s → 2.0/s.
    assert body["queries_per_second"] == 2.0


def test_dashboard_queries_per_second_ignores_counter_reset(client, auth_headers, db):
    headers, _ = auth_headers()
    inst = DatabaseInstance(name="reset", status=InstanceStatus.RUNNING)
    db.add(inst)
    db.commit()
    db.refresh(inst)

    t0 = datetime.now(timezone.utc) - timedelta(seconds=60)
    # The counter dropped (Postgres restart): a negative delta is discarded, it doesn't turn
    # into a negative rate.
    db.add_all([
        Metric(instance_id=inst.id, metric_name="xact_commit", value=5000.0, collected_at=t0),
        Metric(
            instance_id=inst.id, metric_name="xact_commit", value=12.0,
            collected_at=t0 + timedelta(seconds=60),
        ),
    ])
    db.commit()

    body = client.get(DASHBOARD, headers=headers).json()
    assert body["queries_per_second"] == 0.0


def test_dashboard_p95_latency_uses_latest_per_instance(client, auth_headers, db):
    headers, _ = auth_headers()
    inst = DatabaseInstance(name="p95", status=InstanceStatus.RUNNING)
    db.add(inst)
    db.commit()
    db.refresh(inst)

    base = datetime.now(timezone.utc)
    db.add_all([
        Metric(
            instance_id=inst.id, metric_name="p95_query_latency_ms", value=10.0,
            collected_at=base - timedelta(minutes=1),
        ),
        Metric(
            instance_id=inst.id, metric_name="p95_query_latency_ms", value=42.0,
            collected_at=base,  # most recent
        ),
    ])
    db.commit()

    body = client.get(DASHBOARD, headers=headers).json()
    assert body["p95_latency_ms"] == 42.0


def test_dashboard_fleet_uptime_from_history(client, auth_headers, db):
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    inst = DatabaseInstance(
        name="up",
        status=InstanceStatus.STOPPED,
        created_at=now - timedelta(days=10),
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)

    db.add_all([
        InstanceStatusHistory(
            instance_id=inst.id, status=InstanceStatus.RUNNING,
            changed_at=now - timedelta(days=10),
        ),
        InstanceStatusHistory(
            instance_id=inst.id, status=InstanceStatus.STOPPED,
            changed_at=now - timedelta(days=5),
        ),
    ])
    db.commit()

    body = client.get(DASHBOARD, headers=headers).json()
    # RUNNING for 5 of 10 days → ~50%.
    assert abs(body["fleet_uptime_pct"] - 50.0) < 0.5


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #


def test_audit_log_requires_auth(client):
    assert client.get(AUDIT).status_code == 401


def test_audit_log_lists_recent_first(client, auth_headers, db):
    # Superuser with no header sees all entries (incl. NULL-company).
    headers, _ = auth_headers(is_superuser=True)
    # EXPLICIT, distinct timestamps: writing the two entries in sequence
    # left the order at the mercy of the database clock's resolution, and the test would fail
    # every so often. What's being verified is the ordering — not the tie-break.
    now = datetime.now(timezone.utc)
    db.add_all([
        AuditLog(action="login", resource_type="auth",
                 timestamp=now - timedelta(minutes=5)),
        AuditLog(action="instance_created", resource_type="instance",
                 timestamp=now),
    ])
    db.commit()

    resp = client.get(AUDIT, headers=headers)
    assert resp.status_code == 200
    actions = [e["action"] for e in resp.json()]
    # timestamp desc → the most recent one (instance_created) comes first.
    assert actions[0] == "instance_created"
    assert set(actions) == {"login", "instance_created"}


def test_audit_log_filters_by_action_and_resource_type(client, auth_headers, db):
    headers, _ = auth_headers(is_superuser=True)
    admin_service.write_audit_log(db, action="login", resource_type="auth")
    admin_service.write_audit_log(db, action="backup_created", resource_type="backup")
    admin_service.write_audit_log(db, action="instance_created", resource_type="instance")

    by_action = client.get(f"{AUDIT}?action=login", headers=headers).json()
    assert [e["action"] for e in by_action] == ["login"]

    by_resource = client.get(f"{AUDIT}?resource_type=backup", headers=headers).json()
    assert [e["resource_type"] for e in by_resource] == ["backup"]


def test_audit_log_pagination(client, auth_headers, db):
    headers, _ = auth_headers(is_superuser=True)
    for i in range(5):
        admin_service.write_audit_log(db, action=f"act_{i}", resource_type="test")

    page = client.get(f"{AUDIT}?limit=2&offset=0", headers=headers).json()
    assert len(page) == 2

    rest = client.get(f"{AUDIT}?limit=2&offset=4", headers=headers).json()
    assert len(rest) == 1  # 5 records, offset 4 → 1 left over


def test_audit_log_rejects_invalid_limit(client, auth_headers):
    headers, _ = auth_headers(is_superuser=True)
    # limit has ge=1, le=500 — 0 and 999 violate the bounds.
    assert client.get(f"{AUDIT}?limit=0", headers=headers).status_code == 422
    assert client.get(f"{AUDIT}?limit=999", headers=headers).status_code == 422
