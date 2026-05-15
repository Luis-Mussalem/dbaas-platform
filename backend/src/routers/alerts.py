import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.dependencies import get_current_user, get_instance_or_404
from src.models.alert import AlertEvent, AlertRule
from src.models.user import User
from src.schemas.alert import AlertEventRead, AlertRuleCreate, AlertRuleRead, AlertRuleUpdate
from src.services import alert as alert_service

router = APIRouter(tags=["alerts"])


def _get_rule_or_404(rule_id: uuid.UUID, db: Session) -> AlertRule:
    rule = alert_service.get_rule(db, rule_id)
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alert rule not found"
        )
    return rule


def _get_event_or_404(event_id: uuid.UUID, db: Session) -> AlertEvent:
    event = alert_service.get_event(db, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alert event not found"
        )
    return event


# ──────────────────────────────────────────────────────────────────────────────
# Regras de alerta
# ──────────────────────────────────────────────────────────────────────────────

@router.post(
    "/instances/{instance_id}/alerts/rules",
    response_model=AlertRuleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_alert_rule(
    instance_id: uuid.UUID,
    data: AlertRuleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    get_instance_or_404(instance_id, db)
    return alert_service.create_rule(db, instance_id, data)


@router.get(
    "/instances/{instance_id}/alerts/rules",
    response_model=list[AlertRuleRead],
)
def list_alert_rules(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    get_instance_or_404(instance_id, db)
    return alert_service.list_rules(db, instance_id)


@router.get(
    "/alerts/rules/{rule_id}",
    response_model=AlertRuleRead,
)
def get_alert_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return _get_rule_or_404(rule_id, db)


@router.patch(
    "/alerts/rules/{rule_id}",
    response_model=AlertRuleRead,
)
def update_alert_rule(
    rule_id: uuid.UUID,
    data: AlertRuleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rule = _get_rule_or_404(rule_id, db)
    return alert_service.update_rule(db, rule, data)


@router.delete(
    "/alerts/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_alert_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rule = _get_rule_or_404(rule_id, db)
    alert_service.delete_rule(db, rule)


# ──────────────────────────────────────────────────────────────────────────────
# Seed de regras padrão
# ──────────────────────────────────────────────────────────────────────────────

@router.post(
    "/instances/{instance_id}/alerts/seed-defaults",
    response_model=list[AlertRuleRead],
    status_code=status.HTTP_201_CREATED,
)
def seed_default_alert_rules(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Cria as 5 regras padrão para a instância.

    Idempotente: regras já existentes do mesmo metric_type são puladas.
    Use após provisionar uma nova instância para ativar o monitoramento
    automático com os thresholds recomendados.
    """
    get_instance_or_404(instance_id, db)
    return alert_service.seed_default_rules(db, instance_id)


# ──────────────────────────────────────────────────────────────────────────────
# Eventos de alerta
# ──────────────────────────────────────────────────────────────────────────────

@router.get(
    "/instances/{instance_id}/alerts/events",
    response_model=list[AlertEventRead],
)
def list_instance_alert_events(
    instance_id: uuid.UUID,
    only_open: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Lista eventos de alerta de uma instância específica.

    ?only_open=true retorna apenas eventos ainda não resolvidos.
    """
    get_instance_or_404(instance_id, db)
    return alert_service.list_events(db, instance_id, only_open=only_open)


@router.get(
    "/alerts/events",
    response_model=list[AlertEventRead],
)
def list_all_alert_events(
    only_open: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Lista todos os eventos da plataforma. ?only_open=true filtra abertos."""
    return alert_service.list_events(db, only_open=only_open)


@router.post(
    "/alerts/events/{event_id}/resolve",
    response_model=AlertEventRead,
)
def resolve_alert_event(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Resolve manualmente um evento de alerta aberto.

    O avaliador automático resolve eventos quando a condição deixa de ser
    satisfeita. Este endpoint permite resolução manual quando o operador
    sabe que o problema foi tratado antes do próximo ciclo de 60s.

    Retorna 409 se o evento já foi resolvido.
    """
    event = _get_event_or_404(event_id, db)
    if event.resolved_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event is already resolved",
        )
    return alert_service.resolve_event(db, event)
