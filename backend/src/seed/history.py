"""
Historical enrichment of the demo fleet.

The base seed (demo.py) creates companies, users, and instances — but the
Alerts, Backups, Maintenance screens and the uptime KPI are born empty on a clean
clone, because those tables only get populated over time (pollers/schedulers) or by
manual action. This module fills in that history all at once, idempotently,
so the recruiter sees a product "with mileage on it":

- **Metrics** — 24h of synthetic series (the charts' maximum window is 24h),
  on ALL demo instances (real containers included: the live poller
  keeps adding points on top).
- **Uptime** — backdates `created_at` ~45 days and seeds `instance_status_history`
  (RUNNING since creation, with a short blip on one instance) so the
  30-day KPI shows ~99.9% instead of "—".
- **Alerts** — rules per instance + a timeline of resolved events and
  a few open events (so the dashboard shows real active alerts).
- **Backups** — a daily schedule per prod + ~2 weeks of COMPLETED backups
  (growing size), 1 FAILED, and 1 in the last 24h.
- **Maintenance** — a weekly schedule per prod + a history of VACUUM/ANALYZE.
- **Audit log** — a stream of actions attributed to the demo users, so recent
  activity has depth and the real actor (email@company) shows up.

Everything is plausible mock data (nothing sensitive). Idempotent: each instance is
skipped if it already has alert rules, so restarting the stack doesn't duplicate anything.
`clear()` in demo.py removes the resources with no FK-cascade (backups, schedules, and
demo audit logs).
"""
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from math import sin

from sqlalchemy.orm import Session

from src.models.alert import (
    AlertCondition,
    AlertEvent,
    AlertRule,
    AlertSeverity,
)
from src.models.audit_log import AuditLog
from src.models.backup import (
    Backup,
    BackupSchedule,
    BackupStatus,
    BackupStrategy,
    BackupType,
)
from src.models.company import Company
from src.models.database_instance import DatabaseInstance, Environment, InstanceStatus
from src.models.instance_status_history import InstanceStatusHistory
from src.models.maintenance import (
    MaintenanceSchedule,
    MaintenanceTask,
    TaskStatus,
    TaskType,
)
from src.models.metric import Metric
from src.models.user import User, UserRole
from src.services.workload_simulator import (
    target_connections,
    target_queries_per_second,
)

logger = logging.getLogger(__name__)

# How long the fleet "has existed": we backdate created_at beyond the uptime's
# 30-day window, so the KPI covers the entire 30 days.
_FLEET_AGE_DAYS = 45

# Instances (by name) left with 1 OPEN alert — the rest only have resolved
# history. Keeps the "active alerts" count small and believable.
_OPEN_ALERT_INSTANCES = {"neptune-payments-prod", "saturn-store-staging"}

# Max age of the last backup before _refresh_backup_anchor brings it closer to now.
# Slack under the 24h of the `backup_age_hours` rule: the fleet never boots already
# overdue, and the alert stays free to fire if a real backup fails.
_BACKUP_ANCHOR_MAX_AGE = timedelta(hours=20)

# Window and resolution of the synthetic series. 24h is the largest interval the
# charts offer; 5 min is the cadence the poller would use at rest.
_BACKFILL_WINDOW = timedelta(hours=24)
_BACKFILL_STEP = timedelta(minutes=5)

# Age beyond which we consider the window "already covered" and don't seed
# again. Slightly smaller than the window, so the live poller (which writes every
# minute) doesn't run through history — it only kicks in once the fleet has
# genuinely accumulated close to 24h of measurement, at which point the synthetic data
# is unnecessary anyway.
_BACKFILL_COVERED_AFTER = _BACKFILL_WINDOW - timedelta(hours=1)

# How much the database "grew" over the window, as a fraction of the measured size.
# Modest on purpose: it's what the card shows as 24h growth.
_BACKFILL_GROWTH_RATIO = 0.02

# Distance between the two points of the xact_commit pair anchored at boot. Equal to
# the poller's cadence, so the pair looks like two normal collections and FITS within the
# queries/s moving window (which is relative to the poll, see fleet_summary). Defined at
# runtime to follow METRICS_POLL_INTERVAL_SECONDS.
def _xact_anchor_gap_seconds() -> int:
    from src.core.config import settings

    return settings.METRICS_POLL_INTERVAL_SECONDS

# Baseline latency when the instance has never reported percentiles (data-only, no
# pg_stat_statements) and how much it rises from the trough to the load peak.
_P95_FALLBACK_MS = 3.2
_P95_LOAD_SPREAD = 1.6

# p50/p95 and p99/p95 ratio used to derive the other two percentiles when the
# instance only reported one of them. Typical values for an OLTP load: the median
# sits well below the p95 and the p99 stretches the tail.
_P50_OF_P95 = 0.35
_P99_OF_P95 = 1.9

_UNIT_BY_METRIC = {
    "connections_ratio": "%",
    "cache_hit_ratio": "%",
    "db_usage_percent": "%",
    "backup_age_hours": "h",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _has(db: Session, model, instance: DatabaseInstance) -> bool:
    """Does a record of this type already exist for the instance? (idempotency guard)"""
    return (
        db.query(model).filter(model.instance_id == instance.id).first() is not None
    )


def _rng(instance: DatabaseInstance) -> random.Random:
    """Deterministic RNG per instance — stable variety across reboots."""
    return random.Random(f"demo-history::{instance.name}")


def _alert_message(rule: AlertRule, current_value: float) -> str:
    """Same format that services.alert._build_message writes into real events."""
    unit = _UNIT_BY_METRIC.get(rule.metric_type, "")
    return (
        f"[{rule.severity.value.upper()}] {rule.name}: "
        f"current={current_value:.2f}{unit}, "
        f"threshold={rule.condition.value} {rule.threshold}{unit}"
    )


# --------------------------------------------------------------------------- #
# Metrics (24h @ 5min) — the charts' maximum window is 24h
# --------------------------------------------------------------------------- #
def _earliest_measured(
    db: Session, instance: DatabaseInstance, metric_name: str
) -> float | None:
    """Value of the oldest REAL sample of a metric — the anchor for the join."""
    row = (
        db.query(Metric.value)
        .filter(Metric.instance_id == instance.id, Metric.metric_name == metric_name)
        .order_by(Metric.collected_at.asc())
        .first()
    )
    return row[0] if row else None


def _backfill_metrics(db: Session, instance: DatabaseInstance, idx: int) -> None:
    """
    24h synthetic series (one point every 5 min) for sparklines and charts.

    Connections come from the SAME curve the load simulator uses live
    (`workload_simulator.target_connections`), at the SAME intensity as the
    baseline load (`workload_simulator.BASELINE_INTENSITY`). That's what makes the history
    join up with the present: without the curve the series would show a step; without
    the baseline intensity, the history would draw the FULL curve (~14 connections) and the
    live measurement at rest (~5) would fall in a step at the "now" point. Seeds the
    latency percentiles (instantaneous quantities, modulated by the same curve)
    but NOT xact_commit: that one is a cumulative counter, and a synthetic 24h
    series would produce a fake queries/s rate right at the join with the
    real measurement. The card's queries/s isn't left blank because of this: `_seed_xact_commit_anchor`
    seeds a recent pair ANCHORED on the container's real counter, which gives the rate
    right away without inventing the whole series.

    Guard: skips only when measurement ALREADY EXISTS covering the window. The old guard
    ("does any metric exist?") made the backfill effectively useless in practice — the
    live poller writes one row per minute, so a mere 60s gap between
    the reset and clicking "Simulate usage" was enough for the 24h series to never be seeded and
    the charts to end up with only a few minutes of data.

    The series ends where the real measurement begins (not on top of it) and is ANCHORED
    on the value measured at that join: size and cache hit start from what the instance
    actually reports, instead of an arbitrary fraction of the capacity — which, with the
    1 GB plan, used to draw a step and a storage bar above 100%.
    """
    now = _now()
    if (
        db.query(Metric)
        .filter(
            Metric.instance_id == instance.id,
            Metric.collected_at < now - _BACKFILL_COVERED_AFTER,
        )
        .first()
    ):
        return  # the window already has history (seeded before or genuinely measured)

    # Where the real measurement begins: the synthetic data stops there, so there
    # aren't two competing points at the same instant.
    oldest_live = (
        db.query(Metric.collected_at)
        .filter(Metric.instance_id == instance.id)
        .order_by(Metric.collected_at.asc())
        .first()
    )
    end = oldest_live[0] if oldest_live else now
    start = now - _BACKFILL_WINDOW

    # Anchors: the value measured at the join. With no measurement (a data-only
    # instance, which never connects), falls back to plausible numbers for the instance's size.
    capacity = (instance.storage_gb or 20) * 1024 ** 3
    size_anchor = _earliest_measured(db, instance, "db_size_bytes") or capacity * 0.25
    cache_anchor = _earliest_measured(db, instance, "cache_hit_ratio") or (96 + idx * 0.7)
    max_conn = _earliest_measured(db, instance, "connections_max") or 100.0
    p95_anchor = _earliest_measured(db, instance, "p95_query_latency_ms") or _P95_FALLBACK_MS
    # p50 and p99 use their own measurement when it exists; otherwise derive from p95, so
    # the three percentiles move together instead of turning into independent lines.
    p50_anchor = (
        _earliest_measured(db, instance, "p50_query_latency_ms")
        or p95_anchor * _P50_OF_P95
    )
    p99_anchor = (
        _earliest_measured(db, instance, "p99_query_latency_ms")
        or p95_anchor * _P99_OF_P95
    )

    # The instance's connection range — used to convert the traffic curve into
    # a load factor in [0, 1], which is what modulates the latency.
    peak_conns = max(
        1,
        target_connections(
            instance.name, instance.environment, now.replace(hour=15, minute=0)
        ),
    )

    # Baseline load intensity: the history has to match what the load generator
    # measures at rest.
    from src.services.workload_simulator import BASELINE_INTENSITY

    rows: list[Metric] = []
    steps = int((end - start).total_seconds() // (_BACKFILL_STEP.total_seconds())) + 1
    if steps <= 1:
        return
    for k in range(steps):
        ts = start + _BACKFILL_STEP * k
        # progress ∈ [0, 1]: 0 at the start of the window, 1 at the join with reality.
        progress = k / (steps - 1)
        conns = target_connections(
            instance.name, instance.environment, ts, intensity=BASELINE_INTENSITY
        )
        # The database grew _BACKFILL_GROWTH_RATIO over the day, up to the measured value.
        size = size_anchor * (1 - _BACKFILL_GROWTH_RATIO * (1 - progress))
        cache = min(99.99, max(90.0, cache_anchor - 0.6 + 0.5 * sin(k / 22.0) + 0.25 * sin(k / 9.0)))
        rows.append(Metric(instance_id=instance.id, metric_name="connections_active",
                           value=float(round(conns)), collected_at=ts))
        rows.append(Metric(instance_id=instance.id, metric_name="cache_hit_ratio",
                           value=round(cache, 2), collected_at=ts))
        rows.append(Metric(instance_id=instance.id, metric_name="db_size_bytes",
                           value=float(int(size)), collected_at=ts))
        rows.append(Metric(instance_id=instance.id, metric_name="connections_max",
                           value=float(max_conn), collected_at=ts))
        # The percentiles follow the load: more concurrent connections, a bigger
        # queue, a higher tail. Without these series the latency chart on the detail
        # screen was born empty, even with the card already showing the current
        # p95. The p99 spreads out more than the p50 under load — that's what
        # characterizes a tail, and what a single line wouldn't show.
        load = min(1.0, conns / peak_conns)
        for metric_name, anchor, spread in (
            ("p50_query_latency_ms", p50_anchor, _P95_LOAD_SPREAD * 0.5),
            ("p95_query_latency_ms", p95_anchor, _P95_LOAD_SPREAD),
            ("p99_query_latency_ms", p99_anchor, _P95_LOAD_SPREAD * 1.4),
        ):
            rows.append(Metric(
                instance_id=instance.id,
                metric_name=metric_name,
                value=round(anchor * (1 + spread * load), 2),
                collected_at=ts,
            ))
    db.add_all(rows)
    db.commit()


def _seed_xact_commit_anchor(db: Session, instance: DatabaseInstance) -> None:
    """
    Seeds a recent `xact_commit` pair anchored on the container's REAL counter,
    so the card's queries/s shows up right on the first render.

    Without this, queries/s (Δcommits ÷ Δseconds over the two most recent samples)
    stays at "—" for up to two poller cycles (60s each) on a freshly opened boot,
    because the seed doesn't seed the xact_commit series (see `_backfill_metrics`). In a
    demo cloned from GitHub, that's the only number born empty — a bad first
    impression for the recruiter opening the project.

    Runs on EVERY boot (like `_refresh_backup_anchor`, with no idempotency guard):
    the counter is cumulative and Postgres resets it on restart, so samples from a
    previous boot would end up LARGER than the current one and the Δ would come out negative (discarded
    → "—"). That's why it deletes the xact_commit history and writes a fresh pair — the
    counter isn't plotted on any chart (it only feeds the queries/s of the two
    most recent points), so deleting it loses nothing visible.

    The pair is dated with SLACK in the past (`now-2*GAP`, `now-GAP`), never at `now`.
    The seed runs concurrently with the live poller (which writes xact_commit near
    `now`): if the newer point of the pair were at `now`, it would tie/cross with the poller's
    collection and the series would become non-monotonic — a poller sample with a
    slightly earlier timestamp but a larger value would derive a negative Δ. By dating it in the past,
    EVERY live collection is newer by timestamp and the pair is just the bridge until it arrives.

    The two points represent the counter AS IT WAS in the past — stepped back from the
    modeled baseline rate (`target_queries_per_second`): `newer = current - rate*GAP`,
    `older = current - rate*2*GAP`. We don't write the current value: the poller's first
    collection reads ~`current` at the same instant as boot, and if the pair's newer point were already
    `current` the Δ against it would come out ~0 (queries/s "0"). By stepping the pair back, the
    real reading (≥ current, newer) gives Δ ≈ rate*GAP → the live baseline rate. The pair alone
    (before the 1st collection) already yields the same rate. Only for instances with a container.
    """
    if not instance.connection_uri:
        return

    # Late import: the seed is loaded at startup, before everything is up.
    from src.collectors.pg_stats import collect_base_metrics
    from src.services.metrics import get_connection

    try:
        with get_connection(instance) as conn:
            current = collect_base_metrics(conn).get("xact_commit")
    except Exception as exc:  # noqa: BLE001 — boot must not fail because of this
        db.rollback()
        logger.warning("Demo seed: reading xact_commit on %s failed: %s", instance.name, exc)
        return
    if current is None:
        return

    now = _now()
    gap = _xact_anchor_gap_seconds()
    rate = target_queries_per_second(instance.name, instance.environment, now)
    newer = max(0.0, current - rate * gap)
    older = max(0.0, current - rate * 2 * gap)

    db.query(Metric).filter(
        Metric.instance_id == instance.id,
        Metric.metric_name == "xact_commit",
    ).delete(synchronize_session=False)
    db.add_all([
        Metric(instance_id=instance.id, metric_name="xact_commit",
               value=round(older, 2),
               collected_at=now - timedelta(seconds=2 * gap)),
        Metric(instance_id=instance.id, metric_name="xact_commit",
               value=round(newer, 2),
               collected_at=now - timedelta(seconds=gap)),
    ])
    db.commit()


# --------------------------------------------------------------------------- #
# Uptime — backdated created_at + status history
# --------------------------------------------------------------------------- #
def _backdate_status(db: Session, instance: DatabaseInstance, blip: bool) -> None:
    """
    Backdates created_at ~45 days and writes the status history for uptime.

    RUNNING since creation. If `blip`, inserts a ~25 min STOPPED→RUNNING pair
    ~9 days ago — that way uptime comes out to ~99.9x% (believable) instead of a round 100%.
    """
    now = _now()
    created = now - timedelta(days=_FLEET_AGE_DAYS)
    instance.created_at = created
    db.add(instance)

    rows = [InstanceStatusHistory(
        instance_id=instance.id, status=InstanceStatus.RUNNING, changed_at=created,
    )]
    if blip:
        down = now - timedelta(days=9, minutes=13)
        up = down + timedelta(minutes=25)
        rows.append(InstanceStatusHistory(
            instance_id=instance.id, status=InstanceStatus.STOPPED, changed_at=down))
        rows.append(InstanceStatusHistory(
            instance_id=instance.id, status=InstanceStatus.RUNNING, changed_at=up))
    db.add_all(rows)
    db.commit()


# --------------------------------------------------------------------------- #
# Alerts — rules + event timeline
# --------------------------------------------------------------------------- #
def _seed_alerts(db: Session, instance: DatabaseInstance, is_prod: bool) -> None:
    rng = _rng(instance)
    now = _now()

    specs = [
        ("Cache hit ratio below target", "cache_hit_ratio", AlertCondition.LT, 95.0,
         AlertSeverity.WARNING),
        ("Connection pool saturation", "connections_ratio", AlertCondition.GT, 80.0,
         AlertSeverity.WARNING),
        ("Backup overdue", "backup_age_hours", AlertCondition.GT, 24.0,
         AlertSeverity.CRITICAL),
    ]
    if is_prod:
        specs.append(("Disk usage high", "db_usage_percent", AlertCondition.GT, 85.0,
                      AlertSeverity.WARNING))

    rules: dict[str, AlertRule] = {}
    for name, metric_type, cond, threshold, severity in specs:
        rule = AlertRule(
            instance_id=instance.id,
            name=name,
            metric_type=metric_type,
            condition=cond,
            threshold=threshold,
            severity=severity,
            is_active=True,
            created_at=now - timedelta(days=_FLEET_AGE_DAYS - 1),
        )
        db.add(rule)
        rules[metric_type] = rule
    db.commit()

    # Timeline of RESOLVED events (the problem came and went). A few per
    # instance, spread across the last few weeks — give the page some history.
    events: list[AlertEvent] = []
    n_resolved = rng.randint(2, 4)
    for _ in range(n_resolved):
        rule = rules[rng.choice(["cache_hit_ratio", "connections_ratio"])]
        days_ago = rng.uniform(1.5, 25.0)
        triggered = now - timedelta(days=days_ago)
        resolved = triggered + timedelta(minutes=rng.randint(6, 90))
        current = (rule.threshold - rng.uniform(0.5, 3.0)
                   if rule.condition == AlertCondition.LT
                   else rule.threshold + rng.uniform(2.0, 15.0))
        events.append(AlertEvent(
            rule_id=rule.id, instance_id=instance.id,
            triggered_at=triggered, resolved_at=resolved,
            current_value=round(current, 2), message=_alert_message(rule, current),
        ))

    # OPEN event (resolved_at=NULL) only on the chosen instances — keeps the
    # active-alerts count small and realistic.
    if instance.name in _OPEN_ALERT_INSTANCES:
        rule = rules["connections_ratio"] if is_prod else rules["cache_hit_ratio"]
        current = (rule.threshold + 9.4 if rule.condition == AlertCondition.GT
                   else rule.threshold - 1.8)
        events.append(AlertEvent(
            rule_id=rule.id, instance_id=instance.id,
            triggered_at=now - timedelta(minutes=rng.randint(12, 140)),
            resolved_at=None,
            current_value=round(current, 2), message=_alert_message(rule, current),
        ))

    db.add_all(events)
    db.commit()


# --------------------------------------------------------------------------- #
# Backups — schedule + history
# --------------------------------------------------------------------------- #
def _seed_backup_schedule(
    db: Session, instance: DatabaseInstance, is_prod: bool
) -> None:
    """
    Daily backup schedule — on EVERY instance, prod and staging.

    Staging needs its own too: the `backup_age_hours > 24` rule is seeded across
    the entire fleet, so an instance with no schedule never gets a new
    backup and accumulates a permanent CRITICAL as soon as the seeded marker passes the
    24h mark. Differs from production in the time of day (04:00, outside prod's
    window) and retention (3 days instead of 7), which is how a real fleet treats staging.
    """
    now = _now()
    hour = 2 if is_prod else 4
    run_at = now.replace(hour=hour, minute=0, second=0, microsecond=0)

    db.add(BackupSchedule(
        instance_id=instance.id,
        strategy=BackupStrategy.LOGICAL,
        cron_expression=f"0 {hour} * * *",
        retention_days=7 if is_prod else 3,
        is_active=True,
        created_at=now - timedelta(days=_FLEET_AGE_DAYS - 1),
        last_run_at=run_at if run_at <= now else run_at - timedelta(days=1),
        next_run_at=run_at + timedelta(days=1),
    ))
    db.commit()


def _seed_backups(db: Session, instance: DatabaseInstance, is_prod: bool) -> None:
    rng = _rng(instance)
    now = _now()
    two_am = now.replace(hour=2, minute=0, second=0, microsecond=0)

    backups: list[Backup] = []
    # ~14 days of scheduled daily backups, COMPLETED, size growing slowly.
    base_size = (55 + rng.randint(0, 40)) * 1024 ** 2  # ~55–95 MB
    for d in range(14, 0, -1):
        started = two_am - timedelta(days=d)
        if started > now:
            continue
        duration = rng.randint(40, 210)
        size = int(base_size * (1 + (14 - d) * 0.015) + rng.randint(-2, 2) * 1024 ** 2)
        backups.append(Backup(
            instance_id=instance.id,
            backup_type=BackupType.SCHEDULED,
            strategy=BackupStrategy.LOGICAL,
            status=BackupStatus.COMPLETED,
            file_path=f"/var/lib/dbaas/backups/{instance.id}/{started:%Y%m%dT%H%M%S}.dump",
            size_bytes=size,
            created_at=started,
            started_at=started,
            completed_at=started + timedelta(seconds=duration),
            expires_at=started + timedelta(days=7),
        ))

    # One FAILED along the way, so the history doesn't look "too good".
    failed_at = two_am - timedelta(days=6)
    backups.append(Backup(
        instance_id=instance.id,
        backup_type=BackupType.SCHEDULED,
        strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.FAILED,
        created_at=failed_at,
        started_at=failed_at,
        completed_at=failed_at + timedelta(seconds=8),
        error_message="pg_dump: connection to server failed: timeout expired",
    ))

    # A recent manual PHYSICAL backup (strategy/type variety in the UI).
    if is_prod:
        man_at = now - timedelta(hours=rng.randint(30, 50))
        backups.append(Backup(
            instance_id=instance.id,
            backup_type=BackupType.MANUAL,
            strategy=BackupStrategy.PHYSICAL,
            status=BackupStatus.COMPLETED,
            file_path=f"/var/lib/dbaas/backups/{instance.id}/basebackup-{man_at:%Y%m%d}",
            size_bytes=int(base_size * 2.4),
            created_at=man_at,
            started_at=man_at,
            completed_at=man_at + timedelta(minutes=4),
            expires_at=man_at + timedelta(days=30),
        ))

    # Guarantees ≥1 backup in the last 24h (for the "backups in the last 24h" KPI).
    recent_at = now - timedelta(hours=rng.randint(2, 9))
    backups.append(Backup(
        instance_id=instance.id,
        backup_type=BackupType.SCHEDULED,
        strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.COMPLETED,
        file_path=f"/var/lib/dbaas/backups/{instance.id}/{recent_at:%Y%m%dT%H%M%S}.dump",
        size_bytes=int(base_size * 1.22),
        created_at=recent_at,
        started_at=recent_at,
        completed_at=recent_at + timedelta(seconds=rng.randint(40, 180)),
        expires_at=recent_at + timedelta(days=7),
    ))

    db.add_all(backups)
    db.commit()


def _refresh_backup_anchor(db: Session, instance: DatabaseInstance) -> None:
    """
    Brings the most recent COMPLETED backup back closer to "now", if it's aged too much.

    Unlike the rest of the seed, this runs on EVERY boot. The backup history is
    seeded once, with the newest marker 2-9h in the past; the demo fleet,
    however, spends most of its time turned off and that marker ages in wall-clock
    time. Coming up after a day of being stopped, every instance would cross the
    `backup_age_hours > 24` threshold and the panel would open with a row of CRITICALs — which
    speaks to the computer having been off, not to the platform.

    Same license we already took backdating `created_at` and the status history
    to give the fleet 45 days of age: the demo is openly synthetic
    (banner + /demo page). REAL backups — the ones the scheduler just ran —
    already come in recent and the age guard leaves them alone.
    """
    now = _now()
    newest = (
        db.query(Backup)
        .filter(Backup.instance_id == instance.id,
                Backup.status == BackupStatus.COMPLETED,
                Backup.completed_at.isnot(None))
        .order_by(Backup.completed_at.desc())
        .first()
    )
    if newest is None or now - newest.completed_at <= _BACKUP_ANCHOR_MAX_AGE:
        return

    rng = _rng(instance)
    started = now - timedelta(hours=rng.uniform(2.0, 9.0))
    newest.created_at = started
    newest.started_at = started
    newest.completed_at = started + timedelta(seconds=rng.randint(40, 180))
    newest.expires_at = started + timedelta(days=7)
    db.add(newest)
    db.commit()


# --------------------------------------------------------------------------- #
# Maintenance — schedule + history
# --------------------------------------------------------------------------- #
def _seed_maintenance(
    db: Session, instance: DatabaseInstance, is_prod: bool, table: str | None
) -> None:
    rng = _rng(instance)
    now = _now()

    if is_prod:
        # Sunday 03:00 → next occurrence.
        days_to_sunday = (6 - now.weekday()) % 7 or 7
        next_run = (now + timedelta(days=days_to_sunday)).replace(
            hour=3, minute=0, second=0, microsecond=0)
        db.add(MaintenanceSchedule(
            instance_id=instance.id,
            task_type=TaskType.VACUUM,
            cron_expression="0 3 * * 0",
            is_active=True,
            created_at=now - timedelta(days=_FLEET_AGE_DAYS - 1),
            next_run_at=next_run,
        ))

    tasks: list[MaintenanceTask] = []
    plan = [
        (TaskType.VACUUM, None, "VACUUM completed: {n} tables processed, {mb} MB reclaimed"),
        (TaskType.ANALYZE, table, "ANALYZE completed on {tbl}: planner statistics refreshed"),
        (TaskType.REINDEX, table, "REINDEX completed: {n} indexes rebuilt"),
        (TaskType.VACUUM, None, "VACUUM completed: {n} tables processed, {mb} MB reclaimed"),
    ]
    for i, (task_type, target, tmpl) in enumerate(plan):
        scheduled = now - timedelta(days=rng.uniform(2.0, 21.0), hours=rng.randint(0, 12))
        started = scheduled + timedelta(seconds=rng.randint(1, 30))
        summary = tmpl.format(
            n=rng.randint(3, 18), mb=round(rng.uniform(0.4, 12.0), 1), tbl=target or "public")
        tasks.append(MaintenanceTask(
            instance_id=instance.id,
            task_type=task_type,
            status=TaskStatus.COMPLETED,
            target_table=target,
            scheduled_at=scheduled,
            started_at=started,
            completed_at=started + timedelta(seconds=rng.randint(2, 240)),
            result_summary=summary,
        ))
    db.add_all(tasks)
    db.commit()


# --------------------------------------------------------------------------- #
# Audit log — stream of demo users' actions
# --------------------------------------------------------------------------- #
def _seed_audit(
    db: Session,
    company: Company,
    admin: User,
    members: list[User],
    instances: list[DatabaseInstance],
) -> None:
    now = _now()
    entries: list[AuditLog] = []

    def add(user, action, resource_type, resource_id, path, method, days_ago, hours=0):
        ts = now - timedelta(days=days_ago, hours=hours)
        entries.append(AuditLog(
            user_id=user.id if user else None,
            company_id=company.id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            # `simulated: true` honestly labels this entry as seeded demo
            # data (not a real user action).
            details={"method": method, "path": path, "status": 200, "simulated": True},
            ip_address="203.0.113.%d" % (7 + (hash(user.email) % 40) if user else 1),
            timestamp=ts,
        ))

    # Fleet creation (admin), at the start of the company's life.
    for inst in instances:
        add(admin, "instance_created", "instance", inst.id,
            "/api/v1/instances", "POST", days_ago=_FLEET_AGE_DAYS - 1)
        add(admin, "schedule_created", "backup_schedule", inst.id,
            f"/api/v1/instances/{inst.id}/schedules", "POST", days_ago=_FLEET_AGE_DAYS - 1)

    # Recent, believable activity: logins, manual backups, maintenance, a restore.
    pool = [admin, *members]
    for d in range(12, 0, -1):
        user = pool[d % len(pool)]
        add(user, "login", "auth", None, "/api/v1/auth/login", "POST",
            days_ago=d, hours=(d * 2) % 12)
    if instances:
        prod = instances[0]
        add(members[0], "backup_created", "backup", prod.id,
            f"/api/v1/instances/{prod.id}/backups", "POST", days_ago=2, hours=6)
        add(admin, "maintenance_run", "maintenance", prod.id,
            f"/api/v1/instances/{prod.id}/maintenance/run", "POST", days_ago=1, hours=3)
        add(members[1 % len(members)], "restore_initiated", "backup", prod.id,
            f"/api/v1/backups/{prod.id}/restore", "POST", days_ago=4, hours=1)
        add(admin, "instance_status_changed", "instance", prod.id,
            f"/api/v1/instances/{prod.id}/status", "PATCH", days_ago=9)

    db.add_all(entries)
    db.commit()


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def enrich_fleet(db: Session) -> None:
    """
    Seeds history (metrics, uptime, alerts, backups, maintenance, audit) for
    the demo fleet. Idempotent: an instance that already has alert rules is
    skipped; per-company audit is only seeded if the company doesn't already have logs.
    """
    from src.seed.demo import COMPANIES, DEMO_MARKER  # lazy: avoids a circular import

    instances = (
        db.query(DatabaseInstance)
        .filter(DatabaseInstance.notes == DEMO_MARKER,
                DatabaseInstance.deleted_at.is_(None))
        .order_by(DatabaseInstance.name.asc())
        .all()
    )
    if not instances:
        return

    # Target table (for ANALYZE/REINDEX) per company, via the demo config: the
    # business fact table, which is the large one and the one that makes sense to maintain.
    table_by_company: dict[uuid.UUID, str] = {}
    for company_name, cfg in COMPANIES.items():
        comp = db.query(Company).filter(Company.name == company_name).first()
        if comp is not None:
            table_by_company[comp.id] = cfg["fact"]["name"]

    for idx, inst in enumerate(instances):
        is_prod = inst.environment == Environment.PRODUCTION
        blip = inst.name in _OPEN_ALERT_INSTANCES  # reused: whoever has an open alert had a blip
        logger.info("Demo seed: enriching history for %s ...", inst.name)
        # One guard PER RESOURCE, not a single one for the whole instance. With the
        # single guard ("does it have an alert rule?"), the simulation's ALERT
        # phase — which creates a rule — used to mark the instance as enriched:
        # on a second run nothing else got seeded, not even the metrics.
        _backfill_metrics(db, inst, idx)
        # No guard: the counter resets on every Postgres restart, so the pair is
        # rewritten anchored on the current value on every boot.
        _seed_xact_commit_anchor(db, inst)
        if not _has(db, InstanceStatusHistory, inst):
            _backdate_status(db, inst, blip=blip)
        if not _has(db, AlertRule, inst):
            _seed_alerts(db, inst, is_prod)
        if not _has(db, BackupSchedule, inst):
            _seed_backup_schedule(db, inst, is_prod)
        if not _has(db, Backup, inst):
            _seed_backups(db, inst, is_prod)
        # No guard: the backup marker ages in wall-clock time between boots.
        _refresh_backup_anchor(db, inst)
        if not _has(db, MaintenanceTask, inst):
            _seed_maintenance(db, inst, is_prod, table_by_company.get(inst.company_id))

    # Per-company audit (once, if still empty).
    by_company: dict[uuid.UUID, list[DatabaseInstance]] = {}
    for inst in instances:
        if inst.company_id is not None:
            by_company.setdefault(inst.company_id, []).append(inst)
    for company_id, insts in by_company.items():
        if db.query(AuditLog).filter(AuditLog.company_id == company_id).first():
            continue
        company = db.query(Company).filter(Company.id == company_id).first()
        if company is None:
            continue
        users = (
            db.query(User)
            .filter(User.company_id == company_id)
            .order_by(User.email.asc())
            .all()
        )
        admin = next((u for u in users if u.role == UserRole.ADMIN), None)
        members = [u for u in users if u.role == UserRole.MEMBER]
        if admin and members:
            _seed_audit(db, company, admin, members, sorted(insts, key=lambda i: i.name))

    logger.info("Demo seed: fleet history complete.")


def reseed_metrics(db: Session) -> int:
    """
    Deletes and regenerates the demo fleet's 24h of synthetic metrics.

    Exists to fix history generated by an earlier version of the curve
    (the concrete case: series seeded in the tens-of-connections range against
    an idle fleet measuring 1, which drew a step in the sparkline).
    Unlike `enrich_fleet`, it's not idempotent by design — it always
    replaces. Only touches metrics; alerts, backups, and audit stay intact.

        python -m src.seed.history --reseed-metrics
    """
    from src.seed.demo import DEMO_MARKER  # lazy: avoids a circular import

    instances = (
        db.query(DatabaseInstance)
        .filter(DatabaseInstance.notes == DEMO_MARKER,
                DatabaseInstance.deleted_at.is_(None))
        .order_by(DatabaseInstance.name.asc())
        .all()
    )
    for idx, inst in enumerate(instances):
        db.query(Metric).filter(Metric.instance_id == inst.id).delete(
            synchronize_session=False
        )
        db.commit()
        _backfill_metrics(db, inst, idx)
        logger.info("Demo seed: metrics for %s regenerated.", inst.name)
    return len(instances)


if __name__ == "__main__":
    import sys

    from src.core.database import SessionLocal

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if "--reseed-metrics" not in sys.argv:
        print("usage: python -m src.seed.history --reseed-metrics")
        raise SystemExit(2)
    session = SessionLocal()
    try:
        n = reseed_metrics(session)
        print(f"Metrics regenerated for {n} demo instance(s).")
    finally:
        session.close()
