"""
Tests for the metrics history endpoint (time series for sparklines).

GET /api/v1/instances/{id}/metrics/history?metric=&window= reads from the metrics
table on the platform database — it doesn't connect to the monitored database. We cover: window
filtering, ascending order, nonexistent metric (empty list), nonexistent
instance (404), and invalid window (422).
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.core.encryption import encrypt_value
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.metric import Metric


@pytest.fixture
def instance(db):
    inst = DatabaseInstance(
        name="hist-db",
        status=InstanceStatus.RUNNING,
        connection_uri=encrypt_value("postgresql://u:p@127.0.0.1:5433/appdb"),
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _url(instance_id) -> str:
    return f"/api/v1/instances/{instance_id}/metrics/history"


def test_history_requires_auth(client, instance):
    assert client.get(f"{_url(instance.id)}?metric=cache_hit_ratio").status_code == 401


def test_history_returns_points_in_window_ordered(client, auth_headers, instance, db):
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    db.add_all([
        # Outside the 15m window (must not appear).
        Metric(instance_id=instance.id, metric_name="cache_hit_ratio", value=80.0,
               collected_at=now - timedelta(minutes=30)),
        # Within the window (must appear, in ascending order).
        Metric(instance_id=instance.id, metric_name="cache_hit_ratio", value=95.0,
               collected_at=now - timedelta(minutes=10)),
        Metric(instance_id=instance.id, metric_name="cache_hit_ratio", value=98.0,
               collected_at=now - timedelta(minutes=2)),
        # Another metric must not leak into the result.
        Metric(instance_id=instance.id, metric_name="connections_active", value=5.0,
               collected_at=now - timedelta(minutes=1)),
    ])
    db.commit()

    resp = client.get(f"{_url(instance.id)}?metric=cache_hit_ratio&window=15m", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["metric_name"] == "cache_hit_ratio"
    assert body["window"] == "15m"
    values = [p["value"] for p in body["points"]]
    assert values == [95.0, 98.0]  # filtered by window and ordered by time


def test_history_wider_window_includes_more(client, auth_headers, instance, db):
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    db.add_all([
        Metric(instance_id=instance.id, metric_name="cache_hit_ratio", value=80.0,
               collected_at=now - timedelta(minutes=30)),
        Metric(instance_id=instance.id, metric_name="cache_hit_ratio", value=95.0,
               collected_at=now - timedelta(minutes=10)),
    ])
    db.commit()

    resp = client.get(f"{_url(instance.id)}?metric=cache_hit_ratio&window=1h", headers=headers)
    assert [p["value"] for p in resp.json()["points"]] == [80.0, 95.0]


def test_history_unknown_metric_returns_empty(client, auth_headers, instance):
    headers, _ = auth_headers()
    resp = client.get(f"{_url(instance.id)}?metric=does_not_exist", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["points"] == []


def test_history_unknown_instance_404(client, auth_headers):
    import uuid
    headers, _ = auth_headers()
    resp = client.get(f"{_url(uuid.uuid4())}?metric=cache_hit_ratio", headers=headers)
    assert resp.status_code == 404


def test_history_invalid_window_422(client, auth_headers, instance):
    headers, _ = auth_headers()
    resp = client.get(f"{_url(instance.id)}?metric=cache_hit_ratio&window=99y", headers=headers)
    assert resp.status_code == 422


def test_history_is_downsampled_to_a_stable_number_of_points(client, auth_headers, instance, db):
    """
    A 24h window with collection every 5s (what the usage simulation does) brings
    tens of thousands of samples. The endpoint resamples into buckets so the
    sparkline always has the same resolution — and doesn't turn into a sawtooth.
    """
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    db.add_all([
        Metric(
            instance_id=instance.id,
            metric_name="connections_active",
            value=float(10 + (i % 2)),  # alternates 10/11: the noise to be smoothed
            collected_at=now - timedelta(seconds=5 * i),
        )
        for i in range(2000)  # ~2.7h of collection at 5s
    ])
    db.commit()

    points = client.get(
        f"{_url(instance.id)}?metric=connections_active&window=24h", headers=headers
    ).json()["points"]

    assert 0 < len(points) <= 120, f"expected a resampled series, got {len(points)}"
    # The average within the bucket sits between the extremes — the curve loses the
    # jaggedness, not the scale.
    assert all(10.0 <= p["value"] <= 11.0 for p in points)
    # Chronological order preserved.
    assert [p["collected_at"] for p in points] == sorted(p["collected_at"] for p in points)


def test_queries_per_second_is_derived_from_the_xact_commit_counter(
    client, auth_headers, instance, db
):
    """queries/s isn't stored: the series comes from the derivative of the xact_commit counter."""
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    # Cumulative counter growing +600 every 60s → 10 commits/s.
    db.add_all([
        Metric(instance_id=instance.id, metric_name="xact_commit", value=v,
               collected_at=now - timedelta(seconds=s))
        for v, s in [(1000, 180), (1600, 120), (2200, 60), (2800, 0)]
    ])
    db.commit()

    resp = client.get(
        f"{_url(instance.id)}?metric=queries_per_second&window=1h&points=60", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["metric_name"] == "queries_per_second"
    values = [p["value"] for p in body["points"]]
    assert values, "derived series came back empty"
    assert all(v == 10.0 for v in values)


def test_queries_per_second_series_skips_a_counter_reset(
    client, auth_headers, instance, db
):
    """A Postgres reset re-anchors and does NOT emit a point — never a spike or a false 0."""
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    db.add_all([
        Metric(instance_id=instance.id, metric_name="xact_commit", value=v,
               collected_at=now - timedelta(seconds=s))
        for v, s in [(9000, 120), (50, 60), (650, 0)]  # reset between -120s and -60s
    ])
    db.commit()

    resp = client.get(
        f"{_url(instance.id)}?metric=queries_per_second&window=1h&points=60", headers=headers
    )
    values = [p["value"] for p in resp.json()["points"]]
    assert values == [10.0]  # reset skipped; only the post-reset pair (50→650)/60s = 10


def test_queries_per_second_series_skips_a_stale_low_read(
    client, auth_headers, instance, db
):
    """
    A stale reading (a small, transient dip) is SKIPPED instead of turning into 0 and
    then a spike: the line interpolates over the gap and the real growth reappears in the
    next bucket, measured over the larger interval.
    """
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    # +600/60s of real growth; the -60s bucket is STALE (2180 < 2200 from before).
    db.add_all([
        Metric(instance_id=instance.id, metric_name="xact_commit", value=v,
               collected_at=now - timedelta(seconds=s))
        for v, s in [(1600, 180), (2200, 120), (2180, 60), (2800, 0)]
    ])
    db.commit()

    resp = client.get(
        f"{_url(instance.id)}?metric=queries_per_second&window=1h&points=60", headers=headers
    )
    values = [p["value"] for p in resp.json()["points"]]
    # 1600→2200 = +600/60 = 10; the stale 2180 is skipped; 2200→2800 = +600/120 = 5.
    # (window=1h/60 → 60s buckets: the 1 min moving average is a no-op here.)
    assert values == [10.0, 5.0]


def test_queries_per_second_series_is_smoothed_to_one_minute(
    client, auth_headers, instance, db
):
    """
    In short buckets (15s), the rate of a bursty load is very jagged. The series
    goes through a ~1 min moving average: a 0/20 sawtooth becomes a stable
    line at ~10 (the real average rate), keeping one point per bucket.
    """
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    # One sample per 15s bucket; the counter grows +300 on every OTHER bucket —
    # raw rates alternating between 0 and 20 q/s.
    db.add_all([
        Metric(instance_id=instance.id, metric_name="xact_commit", value=v,
               collected_at=now - timedelta(seconds=s))
        for v, s in [(1900, 0), (1600, 15), (1600, 30), (1300, 45),
                     (1300, 60), (1000, 75), (1000, 90)]
    ])
    db.commit()

    # window=15m/60 → 15s buckets → 4-point (1 min) moving average.
    resp = client.get(
        f"{_url(instance.id)}?metric=queries_per_second&window=15m&points=60", headers=headers
    )
    values = [p["value"] for p in resp.json()["points"]]
    # The raw sawtooth would be [0, 20, 0, 20, 0, 20]; smoothed, the tail settles at 10 q/s.
    assert values[-3:] == [10.0, 10.0, 10.0]
    # And no smoothed point reaches the raw peak of 20 (the jaggedness is gone).
    assert max(values) < 20.0
