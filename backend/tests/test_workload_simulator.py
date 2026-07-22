"""
Testes do simulador de carga da frota demo.

Duas metades independentes:

1. A curva (`traffic_factor` / `target_connections`) — pura e determinística,
   testável sem banco nem Docker. É o contrato compartilhado com o backfill
   histórico do seed, então é onde vale cravar as invariantes.
2. O ciclo (`simulate_once`) — com psycopg substituído por um dublê, para
   verificar seleção de instâncias, resize do pool e resiliência a falhas
   sem precisar de containers de verdade.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.core.encryption import encrypt_value
from src.models.database_instance import DatabaseInstance, Environment, InstanceStatus
from src.models.demo_simulation import SimulationPhase
from src.services import demo_simulation as sim
from src.services import workload_simulator as ws

DEMO_MARKER = "__demo_fleet__"


# --------------------------------------------------------------------------- #
# Curva de tráfego
# --------------------------------------------------------------------------- #
def _at(hour: int, day: int = 8) -> datetime:
    # 2026-07-08 é uma quarta-feira (dia útil).
    return datetime(2026, 7, day, hour, 0, tzinfo=timezone.utc)


def test_traffic_factor_stays_in_range_over_a_full_week():
    at = _at(0, day=6)
    for step in range(7 * 24 * 4):  # uma semana, de 15 em 15 min
        f = ws.traffic_factor("neptune-payments-prod", at + timedelta(minutes=15 * step))
        assert 0.0 <= f <= 1.0


def test_traffic_factor_is_deterministic():
    moment = _at(15)
    assert ws.traffic_factor("saturn-store-prod", moment) == ws.traffic_factor(
        "saturn-store-prod", moment
    )


def test_daytime_busier_than_night():
    # A defasagem por instância é de ±2h, então comparamos extremos folgados.
    for name in ("neptune-payments-prod", "saturn-store-prod", "jupiter-clothing-prod"):
        assert ws.traffic_factor(name, _at(15)) > ws.traffic_factor(name, _at(3))


def test_weekend_is_quieter_than_weekday():
    # 2026-07-11 é sábado; mesma hora do dia útil de 2026-07-08 (quarta).
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


# --------------------------------------------------------------------------- #
# Ciclo (simulate_once) com psycopg dublê
# --------------------------------------------------------------------------- #
class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return [self._row] if self._row else []


class _FakeConnection:
    """Conexão de mentira: registra as queries e pode falhar sob demanda."""

    opened: list["_FakeConnection"] = []

    def __init__(self, fail_on_execute: bool = False):
        self.closed = False
        self.queries: list[str] = []
        self.fail_on_execute = fail_on_execute
        _FakeConnection.opened.append(self)

    def execute(self, query, params=None):
        self.queries.append(str(query))
        if self.fail_on_execute:
            raise RuntimeError("conexão caiu")
        # _prepare() pergunta qual é a tabela do dataset.
        if "pg_stat_user_tables" in str(query):
            return _FakeCursor(("transactions",))
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
def simulation_running(db):
    """
    Em modo demo o gerador roda sempre (carga-base), mas estes testes fixam a
    fase STEADY para um estado explícito e estável — o roteiro em si tem testes
    próprios. A intensidade de STEADY é a base (> 0), então o motor trabalha.
    """
    state = sim.get_state(db)
    state.phase = SimulationPhase.STEADY
    state.started_at = sim._now()
    db.commit()
    # O estado é lido através de um cache de 1s pelos loops — sem invalidar,
    # o gerador de carga ainda enxergaria a simulação parada.
    sim.invalidate_state_cache()
    yield state
    sim.invalidate_state_cache()


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


def test_baseline_traffic_flows_without_a_reel(db, fake_connect):
    # A frota demo nunca fica morta: mesmo sem reel rodando (IDLE), há a
    # carga-base, então o gerador abre conexões. É o que mantém os cards vivos
    # desde o boot, sem ninguém clicar em nada.
    sim.invalidate_state_cache()
    inst = _instance(db, "demo-baseline")
    ws.simulate_once()

    assert len(ws._pools[inst.id].conns) > 0
    assert _FakeConnection.opened


def test_simulate_once_opens_connections_for_demo_instances(db, fake_connect, simulation_running):
    inst = _instance(db, "demo-prod")
    ws.simulate_once()

    assert len(ws._pools[inst.id].conns) > 0
    assert _FakeConnection.opened, "nenhuma conexão aberta"


def test_simulate_once_ignores_non_demo_and_stopped_instances(db, fake_connect, simulation_running):
    _instance(db, "user-owned", marker="notas do usuário")
    _instance(db, "demo-stopped", status=InstanceStatus.STOPPED)
    _instance(db, "demo-no-uri", uri=None)

    ws.simulate_once()

    assert ws._pools == {}
    assert _FakeConnection.opened == []


def test_pool_ramps_up_gradually_across_cycles(db, fake_connect, simulation_running):
    inst = _instance(db, "demo-ramp")
    sizes = []
    for _ in range(3):
        ws.simulate_once()
        sizes.append(len(ws._pools[inst.id].conns))

    # Cresce, mas no máximo _MAX_POOL_STEP por ciclo (rampa, não degrau).
    assert sizes[0] <= ws._MAX_POOL_STEP
    assert sizes == sorted(sizes)
    assert all(b - a <= ws._MAX_POOL_STEP for a, b in zip(sizes, sizes[1:]))


def test_pool_is_released_when_instance_leaves_the_fleet(db, fake_connect, simulation_running):
    inst = _instance(db, "demo-gone")
    ws.simulate_once()
    conns = list(ws._pools[inst.id].conns)
    assert conns

    inst.status = InstanceStatus.STOPPED
    db.commit()
    ws.simulate_once()

    assert inst.id not in ws._pools
    assert all(c.closed for c in conns)


def test_failing_instance_does_not_break_the_cycle(db, monkeypatch, simulation_running):
    broken = _instance(db, "demo-broken")
    healthy = _instance(db, "demo-healthy")

    calls = {"n": 0}

    def _connect_by_order(uri):
        # A primeira instância do ciclo recusa conexão; a seguinte responde
        # normalmente — é isso que prova que uma falha não cancela o ciclo.
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection refused")
        return _FakeConnection()

    monkeypatch.setattr(ws, "_connect", _connect_by_order)
    ws.simulate_once()  # não deve levantar

    # Ao menos uma das duas instâncias ficou com pool vivo apesar da falha.
    assert any(pool.conns for pool in ws._pools.values())
    assert {broken.id, healthy.id} >= set(ws._pools)


def test_shutdown_closes_every_connection(db, fake_connect, simulation_running):
    _instance(db, "demo-shutdown")
    ws.simulate_once()
    conns = [c for pool in ws._pools.values() for c in pool.conns]
    assert conns

    ws.shutdown_pools()

    assert ws._pools == {}
    assert all(c.closed for c in conns)


# --------------------------------------------------------------------------- #
# Mix de queries — a "query pesada"
# --------------------------------------------------------------------------- #
class _ScriptedRandom:
    """RNG dublê: devolve um roll fixo, para escolher um ramo do mix."""

    def __init__(self, roll: float):
        self._roll = roll

    def random(self) -> float:
        return self._roll

    def randint(self, a: int, b: int) -> int:
        return a


def _pool_with_ballast(has_ballast: bool) -> ws._InstancePool:
    pool = ws._InstancePool("demo-prod")
    pool.dataset_table = "transactions"
    pool.has_ballast = has_ballast
    pool.prepared = True
    return pool


def test_heavy_query_scans_the_ballast_table_with_a_bounded_slice():
    """
    A query pesada tem que ser CARA e LIMITADA.

    Antes ela era um self-join sobre o dataset de ~100 linhas: terminava em
    microssegundos e a tela de queries lentas não tinha o que investigar.
    """
    pool = _pool_with_ballast(True)
    conn = _FakeConnection()

    ws._run_query(pool, conn, _ScriptedRandom(0.99))

    query = conn.queries[-1]
    assert ws.BALLAST_TABLE in query
    assert "LIMIT" in query.upper()


def test_heavy_query_falls_back_to_the_dataset_without_ballast():
    """Instância sem lastro (criada pelo usuário) continua com o self-join."""
    pool = _pool_with_ballast(False)
    conn = _FakeConnection()

    ws._run_query(pool, conn, _ScriptedRandom(0.99))

    assert ws.BALLAST_TABLE not in conn.queries[-1]
    assert "transactions" in conn.queries[-1]
