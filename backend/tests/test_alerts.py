"""
Testes de alertas (PHASE 7): CRUD de regras via router, seed idempotente de
regras padrão, ciclo de vida de eventos e o motor de avaliação.

Duas camadas exercitadas:
- Router (/api/v1/instances/{id}/alerts/...) — autenticação, 404, validação.
- Service alert_service — funções puras (_evaluate_condition, _build_message) e
  o evaluate_all_rules ponta-a-ponta usando a métrica backup_age_hours, que NÃO
  depende de conexão viva ao Postgres da instância (999h quando não há backup).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.models.alert import (
    AlertCondition,
    AlertEvent,
    AlertRule,
    AlertSeverity,
)
from src.models.backup import Backup, BackupStatus
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.services import alert as alert_service


@pytest.fixture
def instance(db):
    """Instância RUNNING — pré-requisito para regras e avaliação."""
    inst = DatabaseInstance(
        name="alert-db", status=InstanceStatus.RUNNING, storage_gb=1
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _rules_url(instance_id) -> str:
    return f"/api/v1/instances/{instance_id}/alerts/rules"


# --------------------------------------------------------------------------- #
# CRUD de regras (router)
# --------------------------------------------------------------------------- #


def test_create_rule_requires_auth(client, instance):
    resp = client.post(_rules_url(instance.id), json={})
    assert resp.status_code == 401


def test_create_rule_unknown_instance_404(client, auth_headers):
    headers, _ = auth_headers()
    resp = client.post(
        _rules_url(uuid.uuid4()),
        headers=headers,
        json={
            "name": "x",
            "metric_type": "cache_hit_ratio",
            "condition": "lt",
            "threshold": 95,
        },
    )
    assert resp.status_code == 404


def test_create_and_list_rule(client, auth_headers, instance):
    headers, _ = auth_headers()
    resp = client.post(
        _rules_url(instance.id),
        headers=headers,
        json={
            "name": "Low Cache",
            "metric_type": "cache_hit_ratio",
            "condition": "lt",
            "threshold": 95.0,
            "severity": "warning",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Low Cache"
    assert body["metric_type"] == "cache_hit_ratio"

    listed = client.get(_rules_url(instance.id), headers=headers).json()
    assert [r["id"] for r in listed] == [body["id"]]


def test_create_rule_rejects_unknown_metric_type(client, auth_headers, instance):
    headers, _ = auth_headers()
    resp = client.post(
        _rules_url(instance.id),
        headers=headers,
        json={"name": "x", "metric_type": "bogus", "condition": "lt", "threshold": 1},
    )
    assert resp.status_code == 422  # AlertMetricType enum rejeita valor inválido


def test_update_and_delete_rule(client, auth_headers, instance):
    headers, _ = auth_headers()
    created = client.post(
        _rules_url(instance.id),
        headers=headers,
        json={
            "name": "tmp",
            "metric_type": "db_usage_percent",
            "condition": "gte",
            "threshold": 80,
        },
    ).json()
    rule_id = created["id"]

    patched = client.patch(
        f"/api/v1/alerts/rules/{rule_id}",
        headers=headers,
        json={"threshold": 90, "is_active": False},
    )
    assert patched.status_code == 200
    assert patched.json()["threshold"] == 90.0
    assert patched.json()["is_active"] is False

    assert client.delete(f"/api/v1/alerts/rules/{rule_id}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/alerts/rules/{rule_id}", headers=headers).status_code == 404


# --------------------------------------------------------------------------- #
# Seed de regras padrão (idempotência)
# --------------------------------------------------------------------------- #


def test_seed_defaults_is_idempotent(client, auth_headers, instance):
    headers, _ = auth_headers()
    url = f"/api/v1/instances/{instance.id}/alerts/seed-defaults"

    first = client.post(url, headers=headers)
    assert first.status_code == 201
    assert len(first.json()) == 5  # as 5 regras padrão

    # Segunda chamada não duplica: todos os metric_types já existem.
    second = client.post(url, headers=headers)
    assert second.status_code == 201
    assert second.json() == []

    all_rules = client.get(_rules_url(instance.id), headers=headers).json()
    assert len(all_rules) == 5


# --------------------------------------------------------------------------- #
# Eventos (resolução manual)
# --------------------------------------------------------------------------- #


def test_resolve_event_then_conflict(client, auth_headers, instance, db):
    headers, _ = auth_headers()
    rule = AlertRule(
        instance_id=instance.id,
        name="r",
        metric_type="backup_age_hours",
        condition=AlertCondition.GT,
        threshold=24.0,
        severity=AlertSeverity.CRITICAL,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    event = AlertEvent(
        rule_id=rule.id, instance_id=instance.id, current_value=999.0, message="m"
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    resolved = client.post(f"/api/v1/alerts/events/{event.id}/resolve", headers=headers)
    assert resolved.status_code == 200
    assert resolved.json()["resolved_at"] is not None

    # Resolver de novo → 409.
    again = client.post(f"/api/v1/alerts/events/{event.id}/resolve", headers=headers)
    assert again.status_code == 409


def test_list_only_open_events(client, auth_headers, instance, db):
    headers, _ = auth_headers()
    rule = AlertRule(
        instance_id=instance.id,
        name="r",
        metric_type="backup_age_hours",
        condition=AlertCondition.GT,
        threshold=24.0,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    db.add_all([
        AlertEvent(rule_id=rule.id, instance_id=instance.id, current_value=1, message="open"),
        AlertEvent(
            rule_id=rule.id, instance_id=instance.id, current_value=1,
            message="closed", resolved_at=datetime.now(timezone.utc),
        ),
    ])
    db.commit()

    url = f"/api/v1/instances/{instance.id}/alerts/events?only_open=true"
    msgs = [e["message"] for e in client.get(url, headers=headers).json()]
    assert msgs == ["open"]


# --------------------------------------------------------------------------- #
# Funções puras de avaliação
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "current,cond,threshold,expected",
    [
        (90.0, AlertCondition.GT, 80.0, True),
        (80.0, AlertCondition.GT, 80.0, False),
        (80.0, AlertCondition.GTE, 80.0, True),
        (70.0, AlertCondition.LT, 95.0, True),
        (95.0, AlertCondition.LTE, 95.0, True),
        (5.0, AlertCondition.EQ, 5.0, True),
        (5.0, AlertCondition.EQ, 6.0, False),
    ],
)
def test_evaluate_condition(current, cond, threshold, expected):
    assert alert_service._evaluate_condition(current, cond, threshold) is expected


def test_build_message_includes_unit_and_severity(db):
    rule = AlertRule(
        instance_id=uuid.uuid4(),
        name="Backup Overdue",
        metric_type="backup_age_hours",
        condition=AlertCondition.GT,
        threshold=24.0,
        severity=AlertSeverity.CRITICAL,
    )
    msg = alert_service._build_message(rule, 999.0)
    assert "[CRITICAL]" in msg
    assert "Backup Overdue" in msg
    assert "999.00h" in msg


# --------------------------------------------------------------------------- #
# Avaliador ponta-a-ponta (fire + auto-resolve via backup_age_hours)
# --------------------------------------------------------------------------- #


def test_evaluate_all_rules_fires_and_resolves(db, instance):
    """
    backup_age_hours não exige conexão viva: sem backup COMPLETED retorna 999h,
    o que dispara a regra "> 24". Depois de inserir um backup recente, o valor
    cai e o avaliador resolve o evento automaticamente.
    """
    rule = AlertRule(
        instance_id=instance.id,
        name="Backup Overdue",
        metric_type="backup_age_hours",
        condition=AlertCondition.GT,
        threshold=24.0,
        severity=AlertSeverity.CRITICAL,
        is_active=True,
    )
    db.add(rule)
    db.commit()

    # 1º ciclo: nenhum backup → 999h > 24 → dispara um evento aberto.
    alert_service.evaluate_all_rules(db)
    open_events = (
        db.query(AlertEvent)
        .filter(AlertEvent.instance_id == instance.id, AlertEvent.resolved_at.is_(None))
        .all()
    )
    assert len(open_events) == 1

    # 2º ciclo sem mudança: não duplica (já há evento aberto).
    alert_service.evaluate_all_rules(db)
    still_open = (
        db.query(AlertEvent)
        .filter(AlertEvent.instance_id == instance.id, AlertEvent.resolved_at.is_(None))
        .count()
    )
    assert still_open == 1

    # Backup recente COMPLETED → idade << 24h → condição deixa de valer → resolve.
    db.add(Backup(
        instance_id=instance.id,
        status=BackupStatus.COMPLETED,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=1),
    ))
    db.commit()

    alert_service.evaluate_all_rules(db)
    remaining_open = (
        db.query(AlertEvent)
        .filter(AlertEvent.instance_id == instance.id, AlertEvent.resolved_at.is_(None))
        .count()
    )
    assert remaining_open == 0


def test_evaluate_skips_non_running_instances(db):
    """Regras de instâncias STOPPED não são avaliadas (nenhum evento criado)."""
    inst = DatabaseInstance(name="stopped", status=InstanceStatus.STOPPED, storage_gb=1)
    db.add(inst)
    db.commit()
    db.refresh(inst)
    db.add(AlertRule(
        instance_id=inst.id,
        name="r",
        metric_type="backup_age_hours",
        condition=AlertCondition.GT,
        threshold=24.0,
    ))
    db.commit()

    alert_service.evaluate_all_rules(db)
    assert db.query(AlertEvent).filter(AlertEvent.instance_id == inst.id).count() == 0
