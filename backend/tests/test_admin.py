"""
Testes do painel de administração (PHASE 8): GET /admin/dashboard e
GET /admin/audit-log.

Estratégia: montar dados direto no banco (instâncias em vários status, eventos
de alerta, backups, tarefas de manutenção) e verificar a agregação retornada
pelo dashboard. Para o audit-log, semear via admin_service.write_audit_log e
exercitar os filtros (action / resource_type / user_id) e a paginação.

Sem Docker: nada aqui toca em containers — só lógica de agregação SQL.
"""
from datetime import datetime, timedelta, timezone

from src.models.alert import AlertEvent, AlertRule, AlertCondition, AlertSeverity
from src.models.backup import Backup, BackupStatus
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.maintenance import MaintenanceTask, TaskStatus, TaskType
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
        # Soft-deleted NÃO deve entrar na contagem.
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
        # 1 alerta aberto + 1 resolvido (só o aberto conta).
        AlertEvent(rule_id=rule.id, instance_id=inst.id, current_value=99, message="open"),
        AlertEvent(
            rule_id=rule.id, instance_id=inst.id, current_value=99,
            message="closed", resolved_at=now,
        ),
        # Backups nas últimas 24h: 1 completed + 1 failed; 1 antigo fora da janela.
        Backup(instance_id=inst.id, status=BackupStatus.COMPLETED, created_at=now),
        Backup(instance_id=inst.id, status=BackupStatus.FAILED, created_at=now),
        Backup(
            instance_id=inst.id, status=BackupStatus.COMPLETED,
            created_at=now - timedelta(hours=48),
        ),
        # Manutenção pendente/rodando conta; concluída não.
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
# Audit log
# --------------------------------------------------------------------------- #


def test_audit_log_requires_auth(client):
    assert client.get(AUDIT).status_code == 401


def test_audit_log_lists_recent_first(client, auth_headers, db):
    headers, _ = auth_headers()
    admin_service.write_audit_log(db, action="login", resource_type="auth")
    admin_service.write_audit_log(db, action="instance_created", resource_type="instance")

    resp = client.get(AUDIT, headers=headers)
    assert resp.status_code == 200
    actions = [e["action"] for e in resp.json()]
    # timestamp desc → o mais recente (instance_created) vem primeiro.
    assert actions[0] == "instance_created"
    assert set(actions) == {"login", "instance_created"}


def test_audit_log_filters_by_action_and_resource_type(client, auth_headers, db):
    headers, _ = auth_headers()
    admin_service.write_audit_log(db, action="login", resource_type="auth")
    admin_service.write_audit_log(db, action="backup_created", resource_type="backup")
    admin_service.write_audit_log(db, action="instance_created", resource_type="instance")

    by_action = client.get(f"{AUDIT}?action=login", headers=headers).json()
    assert [e["action"] for e in by_action] == ["login"]

    by_resource = client.get(f"{AUDIT}?resource_type=backup", headers=headers).json()
    assert [e["resource_type"] for e in by_resource] == ["backup"]


def test_audit_log_pagination(client, auth_headers, db):
    headers, _ = auth_headers()
    for i in range(5):
        admin_service.write_audit_log(db, action=f"act_{i}", resource_type="test")

    page = client.get(f"{AUDIT}?limit=2&offset=0", headers=headers).json()
    assert len(page) == 2

    rest = client.get(f"{AUDIT}?limit=2&offset=4", headers=headers).json()
    assert len(rest) == 1  # 5 registros, offset 4 → sobra 1


def test_audit_log_rejects_invalid_limit(client, auth_headers):
    headers, _ = auth_headers()
    # limit tem ge=1, le=500 — 0 e 999 violam os bounds.
    assert client.get(f"{AUDIT}?limit=0", headers=headers).status_code == 422
    assert client.get(f"{AUDIT}?limit=999", headers=headers).status_code == 422
