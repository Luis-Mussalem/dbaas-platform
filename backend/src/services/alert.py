import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import psycopg
import psycopg.rows
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.encryption import decrypt_value
from src.models.alert import AlertCondition, AlertEvent, AlertRule, AlertSeverity
from src.models.backup import Backup, BackupStatus
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.metric import Metric
from src.schemas.alert import AlertMetricType, AlertRuleCreate, AlertRuleUpdate

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# CRUD de regras
# ──────────────────────────────────────────────────────────────────────────────

def create_rule(
    db: Session, instance_id: uuid.UUID, data: AlertRuleCreate
) -> AlertRule:
    rule = AlertRule(
        instance_id=instance_id,
        name=data.name,
        metric_type=data.metric_type.value,
        condition=AlertCondition(data.condition.value),
        threshold=data.threshold,
        severity=AlertSeverity(data.severity.value),
        is_active=data.is_active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def list_rules(
    db: Session, instance_id: Optional[uuid.UUID] = None
) -> list[AlertRule]:
    q = db.query(AlertRule)
    if instance_id:
        q = q.filter(AlertRule.instance_id == instance_id)
    return q.order_by(AlertRule.created_at.desc()).all()


def get_rule(db: Session, rule_id: uuid.UUID) -> Optional[AlertRule]:
    return db.query(AlertRule).filter(AlertRule.id == rule_id).first()


def update_rule(db: Session, rule: AlertRule, data: AlertRuleUpdate) -> AlertRule:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


def delete_rule(db: Session, rule: AlertRule) -> None:
    db.delete(rule)
    db.commit()


# ──────────────────────────────────────────────────────────────────────────────
# CRUD de eventos
# ──────────────────────────────────────────────────────────────────────────────

def list_events(
    db: Session,
    instance_id: Optional[uuid.UUID] = None,
    only_open: bool = False,
) -> list[AlertEvent]:
    q = db.query(AlertEvent)
    if instance_id:
        q = q.filter(AlertEvent.instance_id == instance_id)
    if only_open:
        q = q.filter(AlertEvent.resolved_at.is_(None))
    return q.order_by(AlertEvent.triggered_at.desc()).all()


def get_event(db: Session, event_id: uuid.UUID) -> Optional[AlertEvent]:
    return db.query(AlertEvent).filter(AlertEvent.id == event_id).first()


def resolve_event(db: Session, event: AlertEvent) -> AlertEvent:
    event.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(event)
    return event


# ──────────────────────────────────────────────────────────────────────────────
# Regras padrão
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT_RULES: list[dict] = [
    {
        "name": "High Connection Usage",
        "metric_type": AlertMetricType.CONNECTIONS_RATIO.value,
        "condition": AlertCondition.GTE,
        "threshold": 90.0,
        "severity": AlertSeverity.WARNING,
    },
    {
        "name": "Low Cache Hit Ratio",
        "metric_type": AlertMetricType.CACHE_HIT_RATIO.value,
        "condition": AlertCondition.LT,
        "threshold": 95.0,
        "severity": AlertSeverity.WARNING,
    },
    {
        "name": "High Disk Usage",
        "metric_type": AlertMetricType.DB_USAGE_PERCENT.value,
        "condition": AlertCondition.GTE,
        "threshold": 80.0,
        "severity": AlertSeverity.WARNING,
    },
    {
        "name": "Long Running Query",
        "metric_type": AlertMetricType.LONG_QUERY_SECONDS.value,
        "condition": AlertCondition.GT,
        "threshold": 60.0,
        "severity": AlertSeverity.WARNING,
    },
    {
        "name": "Backup Overdue",
        "metric_type": AlertMetricType.BACKUP_AGE_HOURS.value,
        "condition": AlertCondition.GT,
        "threshold": 24.0,
        "severity": AlertSeverity.CRITICAL,
    },
]


def seed_default_rules(db: Session, instance_id: uuid.UUID) -> list[AlertRule]:
    """
    Cria as 5 regras padrão para a instância, pulando tipos já existentes.

    Idempotente: chamar duas vezes não duplica regras.
    """
    existing_types = {
        row[0]
        for row in db.query(AlertRule.metric_type)
        .filter(AlertRule.instance_id == instance_id)
        .all()
    }

    rules: list[AlertRule] = []
    for rule_data in _DEFAULT_RULES:
        if rule_data["metric_type"] in existing_types:
            continue
        rule = AlertRule(instance_id=instance_id, **rule_data)
        db.add(rule)
        rules.append(rule)

    if rules:
        db.commit()
        for r in rules:
            db.refresh(r)

    return rules


# ──────────────────────────────────────────────────────────────────────────────
# Helpers de avaliação
# ──────────────────────────────────────────────────────────────────────────────

def _get_latest_metric(
    db: Session, instance_id: uuid.UUID, metric_name: str
) -> Optional[float]:
    """Retorna o valor mais recente de uma métrica armazenada."""
    row = (
        db.query(Metric.value)
        .filter(Metric.instance_id == instance_id, Metric.metric_name == metric_name)
        .order_by(Metric.collected_at.desc())
        .first()
    )
    return row[0] if row else None


def _get_long_query_seconds(instance: DatabaseInstance) -> Optional[float]:
    """
    Consulta pg_stat_activity ao vivo na instância para encontrar a query mais longa.

    Por que ao vivo e não da tabela metrics?
    Queries longas podem surgir e desaparecer entre ciclos de 60s. Usar o valor
    armazenado seria uma foto antiga — o avaliador perderia eventos de curta duração.
    Ao conectar diretamente, capturamos o estado real no momento da avaliação.

    Filtra a própria query de monitoramento (ILIKE '%pg_stat_activity%') para
    não criar um falso-positivo de "long query" na query do avaliador.

    Retorna 0.0 se não há queries ativas (sem alertar desnecessariamente).
    """
    try:
        uri = decrypt_value(instance.connection_uri)
        with psycopg.connect(uri, connect_timeout=3) as conn:
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                cur.execute("""
                    SELECT EXTRACT(EPOCH FROM (now() - query_start))::float
                           AS duration_seconds
                    FROM pg_stat_activity
                    WHERE state = 'active'
                      AND query NOT ILIKE '%pg_stat_activity%'
                    ORDER BY query_start ASC
                    LIMIT 1
                """)
                row = cur.fetchone()
                return row["duration_seconds"] if row else 0.0
    except Exception as exc:
        logger.warning(
            "Falha ao consultar long queries na instância %s: %s", instance.id, exc
        )
        return None


def _get_backup_age_hours(db: Session, instance_id: uuid.UUID) -> float:
    """
    Retorna horas desde o último backup COMPLETED.

    999.0 quando nunca houve backup bem-sucedido — valor propositalmente alto
    para garantir que uma regra "backup_age_hours > 24" dispare imediatamente.
    """
    row = (
        db.query(Backup.completed_at)
        .filter(
            Backup.instance_id == instance_id,
            Backup.status == BackupStatus.COMPLETED,
        )
        .order_by(Backup.completed_at.desc())
        .first()
    )
    if not row or not row[0]:
        return 999.0
    delta = datetime.now(timezone.utc) - row[0]
    return delta.total_seconds() / 3600.0


def _compute_current_value(
    db: Session,
    rule: AlertRule,
    instance: DatabaseInstance,
) -> Optional[float]:
    """
    Calcula o valor atual da métrica monitorada pela regra.

    Retorna None quando os dados necessários não estão disponíveis —
    o avaliador pula a regra neste ciclo em vez de disparar falso-positivo.
    """
    mt = rule.metric_type

    if mt == AlertMetricType.CONNECTIONS_RATIO.value:
        active = _get_latest_metric(db, instance.id, "connections_active")
        max_conn = _get_latest_metric(db, instance.id, "connections_max")
        if active is None or not max_conn:
            return None
        return (active / max_conn) * 100.0

    if mt == AlertMetricType.CACHE_HIT_RATIO.value:
        return _get_latest_metric(db, instance.id, "cache_hit_ratio")

    if mt == AlertMetricType.DB_USAGE_PERCENT.value:
        size_bytes = _get_latest_metric(db, instance.id, "db_size_bytes")
        if size_bytes is None or not instance.storage_gb:
            return None
        capacity_bytes = instance.storage_gb * (1024 ** 3)
        return (size_bytes / capacity_bytes) * 100.0

    if mt == AlertMetricType.LONG_QUERY_SECONDS.value:
        return _get_long_query_seconds(instance)

    if mt == AlertMetricType.BACKUP_AGE_HOURS.value:
        return _get_backup_age_hours(db, instance.id)

    logger.warning("metric_type desconhecido na regra %s: '%s'", rule.id, mt)
    return None


def _evaluate_condition(
    current: float, condition: AlertCondition, threshold: float
) -> bool:
    return {
        AlertCondition.GT:  current >  threshold,
        AlertCondition.GTE: current >= threshold,
        AlertCondition.LT:  current <  threshold,
        AlertCondition.LTE: current <= threshold,
        AlertCondition.EQ:  current == threshold,
    }[condition]


def _get_open_event(
    db: Session, rule_id: uuid.UUID, instance_id: uuid.UUID
) -> Optional[AlertEvent]:
    return (
        db.query(AlertEvent)
        .filter(
            AlertEvent.rule_id == rule_id,
            AlertEvent.instance_id == instance_id,
            AlertEvent.resolved_at.is_(None),
        )
        .first()
    )


def _build_message(rule: AlertRule, current_value: float) -> str:
    unit_map = {
        AlertMetricType.CONNECTIONS_RATIO.value:  "%",
        AlertMetricType.CACHE_HIT_RATIO.value:    "%",
        AlertMetricType.DB_USAGE_PERCENT.value:   "%",
        AlertMetricType.LONG_QUERY_SECONDS.value: "s",
        AlertMetricType.BACKUP_AGE_HOURS.value:   "h",
    }
    unit = unit_map.get(rule.metric_type, "")
    return (
        f"[{rule.severity.value.upper()}] {rule.name}: "
        f"current={current_value:.2f}{unit}, "
        f"threshold={rule.condition.value} {rule.threshold}{unit}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Notificação
# ──────────────────────────────────────────────────────────────────────────────

def _notify(rule: AlertRule, event: AlertEvent, *, fired: bool) -> None:
    """
    Emite log e, se ALERT_WEBHOOK_URL estiver configurado, envia webhook HTTP POST.

    Usa httpx síncrono porque esta função é chamada dentro de asyncio.to_thread —
    o contexto é uma thread comum sem event loop ativo. Tentar usar httpx.AsyncClient
    aqui exigiria criar um novo event loop manualmente, o que é frágil.

    Webhook é fire-and-forget: falhas são logadas mas não propagadas para não
    interromper o ciclo de avaliação dos alertas restantes.
    """
    if not settings.ALERT_WEBHOOK_URL:
        return

    import httpx

    payload = {
        "event": "alert_fired" if fired else "alert_resolved",
        "severity": rule.severity.value,
        "metric_type": rule.metric_type,
        "rule_name": rule.name,
        "instance_id": str(event.instance_id),
        "current_value": event.current_value,
        "threshold": rule.threshold,
        "condition": rule.condition.value,
        "message": event.message,
        "triggered_at": event.triggered_at.isoformat(),
        "resolved_at": event.resolved_at.isoformat() if event.resolved_at else None,
    }
    try:
        httpx.post(settings.ALERT_WEBHOOK_URL, json=payload, timeout=10.0)
    except Exception as exc:
        logger.warning("Falha na entrega do webhook de alerta: %s", exc)


# ──────────────────────────────────────────────────────────────────────────────
# Disparo e resolução
# ──────────────────────────────────────────────────────────────────────────────

def _fire_event(
    db: Session, rule: AlertRule, instance: DatabaseInstance, current_value: float
) -> AlertEvent:
    message = _build_message(rule, current_value)
    event = AlertEvent(
        rule_id=rule.id,
        instance_id=instance.id,
        current_value=current_value,
        message=message,
        triggered_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    logger.warning("ALERT FIRED: %s | instance=%s", message, instance.id)
    _notify(rule, event, fired=True)
    return event


def _auto_resolve_event(
    db: Session, event: AlertEvent, rule: AlertRule
) -> None:
    event.resolved_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(
        "ALERT RESOLVED: rule=%s instance=%s metric=%s",
        rule.id,
        event.instance_id,
        rule.metric_type,
    )
    _notify(rule, event, fired=False)


# ──────────────────────────────────────────────────────────────────────────────
# Ponto de entrada do evaluator
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_all_rules(db: Session) -> None:
    """
    Avalia todas as regras ativas de todas as instâncias RUNNING.

    Chamado pelo alert_evaluator a cada 60 segundos.

    Fluxo por regra:
    1. Calcula o valor atual da métrica.
    2. Se None (dados indisponíveis) → pula sem disparar falso-positivo.
    3. Avalia a condição (current_value <op> threshold).
    4. Se disparou e não há evento aberto → cria AlertEvent.
    5. Se não disparou e há evento aberto → resolve automaticamente.

    Por que buscar instâncias via JOIN na query de regras?
    Evita N+1: uma única query traz as regras já filtradas por instâncias RUNNING,
    em vez de buscar todas as regras e depois filtrar a instância em Python.
    """
    active_rules = (
        db.query(AlertRule)
        .join(DatabaseInstance, AlertRule.instance_id == DatabaseInstance.id)
        .filter(
            AlertRule.is_active.is_(True),
            DatabaseInstance.status == InstanceStatus.RUNNING,
            DatabaseInstance.deleted_at.is_(None),
        )
        .all()
    )

    for rule in active_rules:
        instance = (
            db.query(DatabaseInstance)
            .filter(DatabaseInstance.id == rule.instance_id)
            .first()
        )
        if not instance:
            continue

        try:
            current_value = _compute_current_value(db, rule, instance)
        except Exception as exc:
            logger.warning(
                "Erro ao computar valor para regra %s (metric=%s): %s",
                rule.id,
                rule.metric_type,
                exc,
            )
            continue

        if current_value is None:
            continue

        triggered = _evaluate_condition(current_value, rule.condition, rule.threshold)
        open_event = _get_open_event(db, rule.id, instance.id)

        if triggered and not open_event:
            _fire_event(db, rule, instance, current_value)
        elif not triggered and open_event:
            _auto_resolve_event(db, open_event, rule)
