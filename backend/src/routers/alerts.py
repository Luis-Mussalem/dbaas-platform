import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.dependencies import (
    get_current_company_admin,
    get_current_user,
    get_instance_or_404,
)
from src.core.scoping import company_scope
from src.models.alert import AlertEvent, AlertRule
from src.models.user import User
from src.schemas.alert import AlertEventRead, AlertRuleCreate, AlertRuleRead, AlertRuleUpdate
from src.services import alert as alert_service

router = APIRouter(tags=["Alerts"])


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
# Alert rules
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
    current_user: User = Depends(get_current_company_admin),
):
    get_instance_or_404(instance_id, db, current_user)
    return alert_service.create_rule(db, instance_id, data)


@router.get(
    "/instances/{instance_id}/alerts/rules",
    response_model=list[AlertRuleRead],
)
def list_alert_rules(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    get_instance_or_404(instance_id, db, current_user)
    return alert_service.list_rules(db, instance_id)


@router.get(
    "/alerts/rules/{rule_id}",
    response_model=AlertRuleRead,
)
def get_alert_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = _get_rule_or_404(rule_id, db)
    # Scoping: the instance owning the rule must be visible to the user.
    get_instance_or_404(rule.instance_id, db, current_user)
    return rule


@router.patch(
    "/alerts/rules/{rule_id}",
    response_model=AlertRuleRead,
)
def update_alert_rule(
    rule_id: uuid.UUID,
    data: AlertRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_company_admin),
):
    rule = _get_rule_or_404(rule_id, db)
    get_instance_or_404(rule.instance_id, db, current_user)
    return alert_service.update_rule(db, rule, data)


@router.delete(
    "/alerts/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_alert_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_company_admin),
):
    rule = _get_rule_or_404(rule_id, db)
    get_instance_or_404(rule.instance_id, db, current_user)
    alert_service.delete_rule(db, rule)


# ──────────────────────────────────────────────────────────────────────────────
# Default rule seeding
# ──────────────────────────────────────────────────────────────────────────────

@router.post(
    "/instances/{instance_id}/alerts/seed-defaults",
    response_model=list[AlertRuleRead],
    status_code=status.HTTP_201_CREATED,
)
def seed_default_alert_rules(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_company_admin),
):
    """
    Creates the 5 default rules for the instance.

    Idempotent: rules that already exist for the same metric_type are skipped.
    Use after provisioning a new instance to enable automatic
    monitoring with the recommended thresholds.
    """
    get_instance_or_404(instance_id, db, current_user)
    return alert_service.seed_default_rules(db, instance_id)


# ──────────────────────────────────────────────────────────────────────────────
# Alert events
# ──────────────────────────────────────────────────────────────────────────────

@router.get(
    "/instances/{instance_id}/alerts/events",
    response_model=list[AlertEventRead],
)
def list_instance_alert_events(
    instance_id: uuid.UUID,
    only_open: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lists alert events for a specific instance.

    ?only_open=true returns only events that are not yet resolved.
    """
    get_instance_or_404(instance_id, db, current_user)
    return alert_service.list_events(db, instance_id, only_open=only_open)


@router.get(
    "/alerts/events",
    response_model=list[AlertEventRead],
)
def list_all_alert_events(
    only_open: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lists the platform's events visible to the user. ?only_open=true filters to open ones.

    Scoped by company: a regular user only sees events from their own company's
    instances; a superuser with no workspace selected sees all of them.
    """
    return alert_service.list_events(
        db, only_open=only_open, scope=company_scope(current_user)
    )


@router.post(
    "/alerts/events/{event_id}/resolve",
    response_model=AlertEventRead,
)
def resolve_alert_event(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_company_admin),
):
    """
    Manually resolves an open alert event.

    The automatic evaluator resolves events when the condition is no longer
    met. This endpoint allows manual resolution when the operator
    knows the problem was handled before the next 60s cycle.

    Returns 409 if the event is already resolved.
    """
    event = _get_event_or_404(event_id, db)
    # Scoping: the instance owning the event must be visible to the user.
    get_instance_or_404(event.instance_id, db, current_user)
    if event.resolved_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event is already resolved",
        )
    return alert_service.resolve_event(db, event)
