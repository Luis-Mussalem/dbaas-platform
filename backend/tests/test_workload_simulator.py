"""
Tests for the demo fleet's load simulator.

Two independent halves:

1. The curve (`traffic_factor` / `target_connections`) — pure and deterministic,
   testable with no database or Docker. It's the contract shared with the seed's
   historical backfill, so it's where it's worth pinning down the invariants.
2. The cycle (`simulate_once`) — with psycopg replaced by a stub, to
   verify instance selection, pool resizing, and resilience to failures
   without needing real containers.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.core.encryption import encrypt_value
from src.models.database_instance import DatabaseInstance, Environment, InstanceStatus
from src.services import workload_simulator as ws

DEMO_MARKER = "__demo_fleet__"


# --------------------------------------------------------------------------- #
# Traffic curve
# --------------------------------------------------------------------------- #
def _at(hour: int, day: int = 8) -> datetime:
    # 2026-07-08 is a Wednesday (a weekday).
    return datetime(2026, 7, day, hour, 0, tzinfo=timezone.utc)


def test_traffic_factor_stays_in_range_over_a_full_week():
    at = _at(0, day=6)
    for step in range(7 * 24 * 4):  # one week, in 15 min steps
        f = ws.traffic_factor("neptune-payments-prod", at + timedelta(minutes=15 * step))
        assert 0.0 <= f <= 1.0


def test_traffic_factor_is_deterministic():
    moment = _at(15)
    assert ws.traffic_factor("saturn-store-prod", moment) == ws.traffic_factor(
        "saturn-store-prod", moment
    )


def test_daytime_busier_than_night():
    # The per-instance offset is ±2h, so we compare with a generous margin at the extremes.
    for name in ("neptune-payments-prod", "saturn-store-prod", "jupiter-clothing-prod"):
        assert ws.traffic_factor(name, _at(15)) > ws.traffic_factor(name, _at(3))


def test_weekend_is_quieter_than_weekday():
    # 2026-07-11 is a Saturday; same time of day as the weekday 2026-07-08 (Wednesday).
    name = "jupiter-clothing-prod"
    assert ws.traffic_factor(name, _at(15, day=11)) < ws.traffic_factor(name, _at(15))


def test_instances_do_not_peak_in_unison():
    moment = _at(9)
    values = {
        ws.traffic_factor(n, moment)
        for n in ("neptune-payments-prod", "saturn-store-prod", "jupiter-clothing-prod")
    }
    assert len(values) == 3


@pytest.mark.parametrize("hour", range(0, 24, 3))
def test_target_connections_respects_cap_and_floor(hour):
    cap = 14
    prod = ws.target_connections("neptune-payments-prod", Environment.PRODUCTION, _at(hour), cap)
    staging = ws.target_connections("neptune-payments-staging", Environment.STAGING, _at(hour), cap)
    assert 1 <= prod <= cap
    assert 1 <= staging <= max(2, cap // 2)


def test_production_carries_more_load_than_staging_at_peak():
    prod = ws.target_connections("saturn-store-prod", Environment.PRODUCTION, _at(15), 14)
    staging = ws.target_connections("saturn-store-staging", Environment.STAGING, _at(15), 14)
    assert prod > staging


def test_target_queries_per_second_is_alive_and_matches_the_drive_model():
    """
    The modeled rate must be > 0 (otherwise the card shows "0") and match EXACTLY
    what `_drive` produces — that's the contract that makes the pair anchored at boot
    join up with the live measurement without a step.
    """
    prod = ws.target_queries_per_second("saturn-store-prod", Environment.PRODUCTION, _at(15))
    staging = ws.target_queries_per_second("saturn-store-staging", Environment.STAGING, _at(15))
    assert prod > staging > 0

    conns = ws.target_connections(
        "saturn-store-prod", Environment.PRODUCTION, _at(15), intensity=ws.BASELINE_INTENSITY
    )
    expected = (
        ws._ACTIVE_FRACTION
        * conns
        * ws._QUERIES_PER_ACTIVE_CONN
        / ws.settings.DEMO_WORKLOAD_INTERVAL_SECONDS
    )
    assert prod == pytest.approx(expected)


# --------------------------------------------------------------------------- #
# Cycle (simulate_once) with a stub psycopg
# --------------------------------------------------------------------------- #
class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return [self._row] if self._row else []


class _FakeConnection:
    """Fake connection: records the queries and can fail on demand."""

    opened: list["_FakeConnection"] = []

    def __init__(self, fail_on_execute: bool = False):
        self.closed = False
        self.queries: list[str] = []
        self.fail_on_execute = fail_on_execute
        _FakeConnection.opened.append(self)

    def execute(self, query, params=None):
        self.queries.append(str(query))
        if self.fail_on_execute:
            raise RuntimeError("connection dropped")
        # _prepare() asks which is the largest table (the business fact table)...
        if "pg_stat_user_tables" in str(query):
            return _FakeCursor(("payments",))
        # ...and whether it has the amount/created_at columns (the heavy query's contract).
        if "information_schema.columns" in str(query):
            return _FakeCursor((True,))
        return _FakeCursor((1,))

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _clean_pools():
    ws.shutdown_pools()
    _FakeConnection.opened = []
    yield
    ws.shutdown_pools()
    _FakeConnection.opened = []


@pytest.fixture
def fake_connect(monkeypatch):
    monkeypatch.setattr(ws, "_connect", lambda uri: _FakeConnection())
    return _FakeConnection


def _instance(db, name, *, marker=DEMO_MARKER, status=InstanceStatus.RUNNING, uri="postgresql://u:p@127.0.0.1:5433/appdb"):
    inst = DatabaseInstance(
        name=name,
        status=status,
        environment=Environment.PRODUCTION,
        notes=marker,
        connection_uri=encrypt_value(uri) if uri else None,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def test_baseline_traffic_flows_by_default(db, fake_connect):
    # The demo fleet never goes dead: the generator always runs at the baseline load, so
    # it opens connections on its own. That's what keeps the cards alive from boot onward.
    inst = _instance(db, "demo-baseline")
    ws.simulate_once()

    assert len(ws._pools[inst.id].conns) > 0
    assert _FakeConnection.opened


def test_simulate_once_opens_connections_for_demo_instances(db, fake_connect):
    inst = _instance(db, "demo-prod")
    ws.simulate_once()

    assert len(ws._pools[inst.id].conns) > 0
    assert _FakeConnection.opened, "no connection was opened"


def test_simulate_once_ignores_non_demo_and_stopped_instances(db, fake_connect):
    _instance(db, "user-owned", marker="user notes")
    _instance(db, "demo-stopped", status=InstanceStatus.STOPPED)
    _instance(db, "demo-no-uri", uri=None)

    ws.simulate_once()

    assert ws._pools == {}
    assert _FakeConnection.opened == []


def test_pool_ramps_up_gradually_across_cycles(db, fake_connect):
    inst = _instance(db, "demo-ramp")
    sizes = []
    for _ in range(3):
        ws.simulate_once()
        sizes.append(len(ws._pools[inst.id].conns))

    # Grows, but by at most _MAX_POOL_STEP per cycle (a ramp, not a step).
    assert sizes[0] <= ws._MAX_POOL_STEP
    assert sizes == sorted(sizes)
    assert all(b - a <= ws._MAX_POOL_STEP for a, b in zip(sizes, sizes[1:]))


def test_pool_is_released_when_instance_leaves_the_fleet(db, fake_connect):
    inst = _instance(db, "demo-gone")
    ws.simulate_once()
    conns = list(ws._pools[inst.id].conns)
    assert conns

    inst.status = InstanceStatus.STOPPED
    db.commit()
    ws.simulate_once()

    assert inst.id not in ws._pools
    assert all(c.closed for c in conns)


def test_failing_instance_does_not_break_the_cycle(db, monkeypatch):
    broken = _instance(db, "demo-broken")
    healthy = _instance(db, "demo-healthy")

    calls = {"n": 0}

    def _connect_by_order(uri):
        # The cycle's first instance refuses the connection; the next one responds
        # normally — that's what proves a failure doesn't cancel the cycle.
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection refused")
        return _FakeConnection()

    monkeypatch.setattr(ws, "_connect", _connect_by_order)
    ws.simulate_once()  # must not raise

    # At least one of the two instances ended up with a live pool despite the failure.
    assert any(pool.conns for pool in ws._pools.values())
    assert {broken.id, healthy.id} >= set(ws._pools)


def test_shutdown_closes_every_connection(db, fake_connect):
    _instance(db, "demo-shutdown")
    ws.simulate_once()
    conns = [c for pool in ws._pools.values() for c in pool.conns]
    assert conns

    ws.shutdown_pools()

    assert ws._pools == {}
    assert all(c.closed for c in conns)


# --------------------------------------------------------------------------- #
# Query mix — the "heavy query"
# --------------------------------------------------------------------------- #
class _ScriptedRandom:
    """Stub RNG: returns a fixed roll, to pick a branch of the mix."""

    def __init__(self, roll: float):
        self._roll = roll

    def random(self) -> float:
        return self._roll

    def randint(self, a: int, b: int) -> int:
        return a


def _pool(bulk_ready: bool) -> ws._InstancePool:
    pool = ws._InstancePool("demo-prod")
    pool.dataset_table = "payments"
    pool.bulk_ready = bulk_ready
    pool.prepared = True
    return pool


def test_heavy_query_aggregates_a_bounded_slice_of_the_fact_table():
    """
    The heavy query must be EXPENSIVE and BOUNDED: an "hourly revenue" aggregation
    over a slice of the fact table, not the whole table.
    """
    pool = _pool(bulk_ready=True)
    conn = _FakeConnection()

    ws._run_heavy_query(pool, conn, _ScriptedRandom(0.99))

    query = conn.queries[-1]
    assert "payments" in query           # runs over the fact table
    assert "sum(amount)" in query        # it's the business aggregation
    assert "LIMIT" in query.upper()      # and it's bounded


def test_heavy_query_falls_back_when_the_fact_table_is_not_ready():
    """Without a ready fact table (amount/created_at), falls back to a cheap count."""
    pool = _pool(bulk_ready=False)
    conn = _FakeConnection()

    ws._run_heavy_query(pool, conn, _ScriptedRandom(0.99))

    assert "payments" not in conn.queries[-1]
    assert ws.WORKLOAD_TABLE in conn.queries[-1]


def test_drive_bursts_light_queries_on_each_active_connection():
    """
    Each active connection fires a burst of `_QUERIES_PER_ACTIVE_CONN` light queries — it's the
    volume that gives the live queries/s. With roll=0.1: all active (0.1 ≤ _ACTIVE_FRACTION),
    the read branch (0.1 < 0.90), and NO heavy query (0.1 ≥ _HEAVY_QUERY_PROB), so the
    count is exact.
    """
    pool = _pool(bulk_ready=True)
    pool.conns = [_FakeConnection(), _FakeConnection(), _FakeConnection()]

    executed = ws._drive(pool, _ScriptedRandom(0.1))

    assert executed == len(pool.conns) * ws._QUERIES_PER_ACTIVE_CONN
    for conn in pool.conns:
        assert len(conn.queries) == ws._QUERIES_PER_ACTIVE_CONN
