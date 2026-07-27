"""
Per-instance aggregate for the fleet cards.

The cards used to show only what the poller keeps as the last raw value (connections,
cache hit, size). In a small fleet, cache hit is always ~100% and the storage bar
is always 0%, so three gauges stayed constant and the card said nothing
about the instance's actual state.

This module returns, in a single response, what's already scattered across
alerts/backups/metrics/status_history: throughput, latency, disk growth,
open alerts, last backup, and uptime. It's a READ aggregate — the
cost of N+1 requests (one card = 5 endpoints × 6 cards) is what it avoids.

The per-instance helpers (`queries_per_second_by_instance`,
`latest_metric_by_instance`) also feed the fleet KPIs in
`services/admin.py`, which used to have the same SQL window duplicated.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.alert import AlertEvent, AlertRule, AlertSeverity
from src.models.backup import Backup, BackupStatus
from src.models.database_instance import DatabaseInstance
from src.models.metric import Metric
from src.schemas.instance import InstanceSummary
from src.services import metrics as metrics_service
from src.services import status_history

# The card's queries/s NUMBER is the AVERAGE of the same series the sparkline draws —
# not a separate calculation. The card requests get_metric_history("queries_per_second",
# "15m", 60 buckets) (InstanceCard.tsx); we derive the SAME series here and take the
# average of the points. This way the number is, by construction, the average of the line: it oscillates
# around it and the chart and the number tell a single story. Robustness against stale
# readings and counter resets lives in _counter_rate (services.metrics), which the
# two paths share. These two values MUST match the card's.
_QPS_SERIES_MINUTES = 15
_QPS_SERIES_POINTS = 60

# Severity order, so the card can highlight the worst open alert.
_SEVERITY_RANK = {
    AlertSeverity.INFO: 0,
    AlertSeverity.WARNING: 1,
    AlertSeverity.CRITICAL: 2,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Metrics (window over the metrics table)
# --------------------------------------------------------------------------- #
def _latest_samples(
    db: Session,
    instance_ids: list[uuid.UUID],
    metric_name: str,
    limit: int,
) -> dict[uuid.UUID, list[tuple[float, datetime]]]:
    """
    The `limit` most recent points of a metric, per instance (newest
    first). A window function instead of N queries: the whole fleet comes back
    in a single trip to the database.
    """
    if not instance_ids:
        return {}

    rn = func.row_number().over(
        partition_by=Metric.instance_id,
        order_by=Metric.collected_at.desc(),
    ).label("rn")
    subq = (
        db.query(Metric.instance_id, Metric.value, Metric.collected_at, rn)
        .filter(
            Metric.instance_id.in_(instance_ids),
            Metric.metric_name == metric_name,
        )
        .subquery()
    )
    rows = (
        db.query(subq.c.instance_id, subq.c.value, subq.c.collected_at)
        .filter(subq.c.rn <= limit)
        .order_by(subq.c.instance_id, subq.c.rn)
        .all()
    )

    by_instance: dict[uuid.UUID, list[tuple[float, datetime]]] = {}
    for instance_id, value, collected_at in rows:
        by_instance.setdefault(instance_id, []).append((value, collected_at))
    return by_instance


def latest_metric_by_instance(
    db: Session, instance_ids: list[uuid.UUID], metric_name: str
) -> dict[uuid.UUID, float]:
    """Latest value of a metric per instance (missing = no collection yet)."""
    return {
        instance_id: samples[0][0]
        for instance_id, samples in _latest_samples(db, instance_ids, metric_name, 1).items()
    }


def queries_per_second_by_instance(
    db: Session, instance_ids: list[uuid.UUID]
) -> dict[uuid.UUID, float]:
    """
    Commit rate per instance = AVERAGE of the queries/s series the card draws
    in its sparkline. Derives the SAME series as the chart (get_metric_history over the
    xact_commit counter, same window and buckets) and returns the average of the points.

    Why the average of the series, rather than a separate calculation: the number and the chart have
    to match. While the number came from a different window/derivation (it was the average
    of the last ~5 raw samples), it never lined up with the line next to it. Being
    the EXACT average of the drawn series, the line oscillates around the number and the two
    tell a single story.

    Missing (empty series) when there's no data for a rate — the card shows "—" instead
    of a made-up zero. Robustness against stale readings and counter resets
    is in _counter_rate (services.metrics), which produces the series.
    """
    result: dict[uuid.UUID, float] = {}
    for instance_id in instance_ids:
        series = metrics_service.get_metric_history(
            db,
            instance_id,
            "queries_per_second",
            _QPS_SERIES_MINUTES,
            max_points=_QPS_SERIES_POINTS,
        )
        if not series:
            continue
        result[instance_id] = round(sum(value for _, value in series) / len(series), 2)
    return result


def _size_delta_24h(
    db: Session, instance_ids: list[uuid.UUID], latest_size: dict[uuid.UUID, float]
) -> dict[uuid.UUID, float]:
    """
    Database growth over the last 24h: current size minus the oldest one
    within the window. It's the number that shows the simulated load actually
    writes — the storage bar alone barely moves in 24h.
    """
    if not instance_ids:
        return {}

    since = _now() - timedelta(hours=24)
    rn = func.row_number().over(
        partition_by=Metric.instance_id,
        order_by=Metric.collected_at.asc(),
    ).label("rn")
    subq = (
        db.query(Metric.instance_id, Metric.value, rn)
        .filter(
            Metric.instance_id.in_(instance_ids),
            Metric.metric_name == "db_size_bytes",
            Metric.collected_at >= since,
        )
        .subquery()
    )
    oldest = {
        instance_id: value
        for instance_id, value in db.query(subq.c.instance_id, subq.c.value)
        .filter(subq.c.rn == 1)
        .all()
    }
    return {
        instance_id: current - oldest[instance_id]
        for instance_id, current in latest_size.items()
        if instance_id in oldest
    }


# --------------------------------------------------------------------------- #
# Alerts, backups, and uptime
# --------------------------------------------------------------------------- #
def _open_alerts(
    db: Session, instance_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, AlertSeverity]]:
    """
    Open alerts (resolved_at NULL) per instance: count and worst severity.

    Severity is an attribute of the RULE, not of the event — hence the join.
    """
    if not instance_ids:
        return {}

    rows = (
        db.query(AlertRule.severity, AlertEvent.instance_id, func.count(AlertEvent.id))
        .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
        .filter(
            AlertEvent.instance_id.in_(instance_ids),
            AlertEvent.resolved_at.is_(None),
        )
        .group_by(AlertEvent.instance_id, AlertRule.severity)
        .all()
    )

    result: dict[uuid.UUID, tuple[int, AlertSeverity]] = {}
    for severity, instance_id, count in rows:
        total, worst = result.get(instance_id, (0, AlertSeverity.INFO))
        if _SEVERITY_RANK[severity] > _SEVERITY_RANK[worst]:
            worst = severity
        result[instance_id] = (total + count, worst)
    return result


def _last_backup(
    db: Session, instance_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[datetime, BackupStatus]]:
    """
    Last non-deleted backup per instance (date + status). Includes ones that
    failed on purpose: a card that hides the failure is worse than no card.
    """
    if not instance_ids:
        return {}

    rn = func.row_number().over(
        partition_by=Backup.instance_id,
        order_by=Backup.created_at.desc(),
    ).label("rn")
    subq = (
        db.query(Backup.instance_id, Backup.created_at, Backup.status, rn)
        .filter(
            Backup.instance_id.in_(instance_ids),
            Backup.status != BackupStatus.DELETED,
        )
        .subquery()
    )
    return {
        instance_id: (created_at, status)
        for instance_id, created_at, status in db.query(
            subq.c.instance_id, subq.c.created_at, subq.c.status
        )
        .filter(subq.c.rn == 1)
        .all()
    }


# --------------------------------------------------------------------------- #
# Aggregate
# --------------------------------------------------------------------------- #
def get_fleet_summary(
    db: Session, instances: list[DatabaseInstance]
) -> list[InstanceSummary]:
    """A summary per instance received (already filtered by scope by the router)."""
    instance_ids = [inst.id for inst in instances]

    qps = queries_per_second_by_instance(db, instance_ids)
    p95 = latest_metric_by_instance(db, instance_ids, "p95_query_latency_ms")
    conns = latest_metric_by_instance(db, instance_ids, "connections_active")
    conns_max = latest_metric_by_instance(db, instance_ids, "connections_max")
    size = latest_metric_by_instance(db, instance_ids, "db_size_bytes")
    growth = _size_delta_24h(db, instance_ids, size)
    alerts = _open_alerts(db, instance_ids)
    backups = _last_backup(db, instance_ids)
    uptime = status_history.get_uptime_pct_by_instance(db, instances)

    summaries = []
    for inst in instances:
        open_count, worst = alerts.get(inst.id, (0, None))
        last_backup = backups.get(inst.id)
        summaries.append(
            InstanceSummary(
                instance_id=inst.id,
                connections_active=conns.get(inst.id),
                connections_max=conns_max.get(inst.id),
                queries_per_second=qps.get(inst.id),
                p95_latency_ms=p95.get(inst.id),
                db_size_bytes=size.get(inst.id),
                size_delta_24h_bytes=growth.get(inst.id),
                open_alerts=open_count,
                max_alert_severity=worst,
                last_backup_at=last_backup[0] if last_backup else None,
                last_backup_status=last_backup[1] if last_backup else None,
                uptime_30d_pct=uptime.get(inst.id),
            )
        )
    return summaries
