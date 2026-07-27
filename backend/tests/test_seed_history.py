"""
Tests for the demo fleet's historical backfill (`src/seed/history.py`).

The focus is the idempotency guard, which is where things actually broke: the
previous version skipped the backfill if ANY metric existed, and since the
live poller writes one row per minute, a mere gap between the reset and
clicking "Simulate usage" was enough for the 24h charts to never get seeded.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.models.alert import AlertRule
from src.models.backup import (
    Backup,
    BackupSchedule,
    BackupStatus,
    BackupStrategy,
    BackupType,
)
from src.models.database_instance import DatabaseInstance, Environment, InstanceStatus
from src.models.metric import Metric
from src.seed import history

DEMO_MARKER = "__demo_fleet__"


@pytest.fixture
def demo_instance(db):
    inst = DatabaseInstance(
        name="demo-prod",
        status=InstanceStatus.RUNNING,
        environment=Environment.PRODUCTION,
        notes=DEMO_MARKER,
        storage_gb=1,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _series(db, instance, metric_name="connections_active") -> list[Metric]:
    return (
        db.query(Metric)
        .filter(Metric.instance_id == instance.id, Metric.metric_name == metric_name)
        .order_by(Metric.collected_at.asc())
        .all()
    )


def _add_live_sample(db, instance, name, value, minutes_ago=0):
    db.add(Metric(
        instance_id=instance.id,
        metric_name=name,
        value=value,
        collected_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    ))
    db.commit()


def test_backfill_seeds_the_window(db, demo_instance):
    history._backfill_metrics(db, demo_instance, idx=0)

    points = _series(db, demo_instance)
    span = points[-1].collected_at - points[0].collected_at
    assert len(points) > 200
    assert span > timedelta(hours=23)


def test_backfill_runs_even_when_the_live_poller_already_wrote(db, demo_instance):
    """
    REGRESSION: a few minutes of live collection must not suppress the backfill —
    that was exactly what left the charts with only a few minutes of data
    after stopping and simulating again.
    """
    for minutes in (4, 3, 2, 1, 0):
        _add_live_sample(db, demo_instance, "connections_active", 7.0, minutes)

    history._backfill_metrics(db, demo_instance, idx=0)

    points = _series(db, demo_instance)
    assert points[0].collected_at < datetime.now(timezone.utc) - timedelta(hours=23)


def test_backfill_skips_when_the_window_is_already_covered(db, demo_instance):
    """With 24h of real measurement, the synthetic data is unnecessary — and must not be added."""
    _add_live_sample(db, demo_instance, "connections_active", 7.0, minutes_ago=60 * 24)
    before = len(_series(db, demo_instance))

    history._backfill_metrics(db, demo_instance, idx=0)

    assert len(_series(db, demo_instance)) == before


def test_seeded_series_stops_where_the_measured_one_starts(db, demo_instance):
    """No overlap: two competing points at the same instant become noise."""
    _add_live_sample(db, demo_instance, "connections_active", 7.0, minutes_ago=10)

    history._backfill_metrics(db, demo_instance, idx=0)

    seeded = [p for p in _series(db, demo_instance) if p.value != 7.0]
    junction = datetime.now(timezone.utc) - timedelta(minutes=10)
    assert max(p.collected_at for p in seeded) <= junction


def test_size_series_is_anchored_to_the_measured_size(db, demo_instance):
    """
    The seeded size converges to what the instance ACTUALLY reports.

    It used to be an arbitrary fraction of the contracted capacity: with the
    1 GB plan that drew a step at the join and a storage bar above 100%.
    """
    measured = 264.0 * 1024 ** 2
    _add_live_sample(db, demo_instance, "db_size_bytes", measured, minutes_ago=10)

    history._backfill_metrics(db, demo_instance, idx=0)

    seeded = [p.value for p in _series(db, demo_instance, "db_size_bytes")
              if p.value != measured]
    # Ends just below the measured value (the database grew over the day) and never
    # exceeds the plan's capacity.
    assert 0.95 * measured < max(seeded) <= measured
    assert max(seeded) < demo_instance.storage_gb * 1024 ** 3


def test_enrich_fleet_still_seeds_backups_when_only_a_rule_exists(db, demo_instance):
    """
    REGRESSION: the simulation's ALERT phase creates a rule. With the single guard
    ("has a rule?"), the instance would be considered already enriched and
    no other history would be seeded on a second run.
    """
    db.add(AlertRule(
        instance_id=demo_instance.id,
        name="Connection pool under load",
        metric_type="connections_ratio",
        condition="gt",
        threshold=40.0,
    ))
    db.commit()

    history.enrich_fleet(db)

    assert db.query(Backup).filter(Backup.instance_id == demo_instance.id).first()
    assert _series(db, demo_instance)


def test_staging_also_gets_a_backup_schedule(db):
    """
    REGRESSION: only production used to get a schedule, but the `backup_age_hours`
    rule is seeded across the whole fleet. Without a schedule, staging never produced
    a new backup and accumulated a permanent CRITICAL 24h after the first boot.
    """
    staging = DatabaseInstance(
        name="demo-staging",
        status=InstanceStatus.RUNNING,
        environment=Environment.STAGING,
        notes=DEMO_MARKER,
        storage_gb=1,
    )
    db.add(staging)
    db.commit()

    history.enrich_fleet(db)

    schedule = (
        db.query(BackupSchedule)
        .filter(BackupSchedule.instance_id == staging.id)
        .one()
    )
    assert schedule.is_active
    assert schedule.next_run_at > datetime.now(timezone.utc)


def test_backup_anchor_is_refreshed_when_the_fleet_boots_stale(db, demo_instance):
    """
    The demo fleet spends most of its time turned off and the backup marker
    ages in wall-clock time. Coming up after a day of being stopped, every
    instance would cross `backup_age_hours > 24` and the panel would open in CRITICAL.
    """
    stale = datetime.now(timezone.utc) - timedelta(hours=31)
    db.add(Backup(
        instance_id=demo_instance.id,
        backup_type=BackupType.SCHEDULED,
        strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.COMPLETED,
        created_at=stale,
        started_at=stale,
        completed_at=stale,
    ))
    db.commit()

    history._refresh_backup_anchor(db, demo_instance)

    newest = (
        db.query(Backup)
        .filter(Backup.instance_id == demo_instance.id)
        .order_by(Backup.completed_at.desc())
        .first()
    )
    age = datetime.now(timezone.utc) - newest.completed_at
    assert age < timedelta(hours=24)  # doesn't boot already overdue


def test_backup_anchor_leaves_recent_backups_alone(db, demo_instance):
    """A real, recent backup must not be rewritten by the seed."""
    recent = datetime.now(timezone.utc) - timedelta(hours=3)
    db.add(Backup(
        instance_id=demo_instance.id,
        backup_type=BackupType.SCHEDULED,
        strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.COMPLETED,
        created_at=recent,
        started_at=recent,
        completed_at=recent,
    ))
    db.commit()

    history._refresh_backup_anchor(db, demo_instance)

    newest = db.query(Backup).filter(Backup.instance_id == demo_instance.id).one()
    assert newest.completed_at == recent


def test_backfill_seeds_p95_but_never_the_cumulative_counter(db, demo_instance):
    """
    p95 is an instantaneous quantity and can be seeded; xact_commit is a cumulative
    COUNTER — a synthetic series of it would produce a false queries/s rate
    exactly at the join with the real measurement.
    """
    history._backfill_metrics(db, demo_instance, idx=0)

    assert _series(db, demo_instance, "p95_query_latency_ms")
    assert not _series(db, demo_instance, "xact_commit")


def test_seeded_p95_follows_the_traffic_curve(db, demo_instance):
    """Higher latency under load: a straight line wouldn't teach anything."""
    history._backfill_metrics(db, demo_instance, idx=0)

    values = [p.value for p in _series(db, demo_instance, "p95_query_latency_ms")]
    assert min(values) < max(values)


def test_xact_commit_anchor_dates_the_pair_safely_in_the_past(db, monkeypatch):
    """
    The anchored pair is born in the PAST (never at `now`) and monotonic, so it doesn't cross
    with the live poller's near-simultaneous collections — which would derive a negative Δ
    and bring queries/s back to "—". A future live collection keeps the Δ positive.
    """
    import contextlib

    from src.core.encryption import encrypt_value
    from src.services.fleet_summary import queries_per_second_by_instance

    inst = DatabaseInstance(
        name="demo-anchor-prod",
        status=InstanceStatus.RUNNING,
        environment=Environment.PRODUCTION,
        notes=DEMO_MARKER,
        storage_gb=1,
        connection_uri=encrypt_value("postgresql://u:p@127.0.0.1:5433/appdb"),
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)

    # Stale sample from a "previous boot" (a larger counter): must be erased,
    # otherwise the Δ against the fresh pair would come out negative.
    _add_live_sample(db, inst, "xact_commit", 99999.0, minutes_ago=30)

    current = 1000.0
    monkeypatch.setattr(
        "src.services.metrics.get_connection",
        lambda instance: contextlib.nullcontext(object()),
    )
    monkeypatch.setattr(
        "src.collectors.pg_stats.collect_base_metrics",
        lambda conn: {"xact_commit": current},
    )

    now = datetime.now(timezone.utc)
    history._seed_xact_commit_anchor(db, inst)

    pair = _series(db, inst, "xact_commit")
    assert len(pair) == 2  # stale sample erased, fresh pair in its place
    older, newer = pair
    # Dated in the past (never at `now`), so it doesn't cross with the live collection.
    assert newer.collected_at <= now - timedelta(seconds=5)
    assert older.collected_at < newer.collected_at
    # Stepped back from the real counter (we don't write `current`), and monotonic.
    assert older.value < newer.value < current
    # The pair alone — before any live collection — already yields a positive rate.
    assert queries_per_second_by_instance(db, [inst.id])[inst.id] > 0

    # And the next live collection (newer, reads ~the current counter) keeps Δ positive.
    _add_live_sample(db, inst, "xact_commit", current, minutes_ago=0)
    assert queries_per_second_by_instance(db, [inst.id])[inst.id] > 0
