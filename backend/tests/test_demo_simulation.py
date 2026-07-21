"""
Testes do diretor da simulação de uso (o botão "Simular uso").

O que importa garantir aqui:
- o roteiro avança fase a fase e nunca trava quando uma ação falha;
- o relógio virtual acelera só enquanto a simulação roda;
- `stop` preserva os dados e `reset` devolve a frota ao estado real,
  inclusive o `created_at` que o backfill retroagiu;
- os endpoints exigem autenticação e somem com DEMO_MODE desligado.

As ações de fase que tocam Docker/pg_dump (backup, manutenção, backfill) são
substituídas por dublês: o valor testado é a máquina de estados, não o pg_dump —
esse já tem cobertura em test_backup_service.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.core.config import settings
from src.models.alert import AlertRule
from src.models.backup import Backup, BackupStrategy, BackupStatus
from src.models.database_instance import DatabaseInstance, Environment, InstanceStatus
from src.models.demo_simulation import DemoSimulation, SimulationPhase
from src.models.metric import Metric
from src.services import demo_simulation as sim

DEMO_MARKER = "__demo_fleet__"


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    """
    Neutraliza as fases que dependem de Docker, pg_dump e psycopg, e torna o
    despacho SÍNCRONO: em produção as ações rodam numa thread própria (para o
    relógio do roteiro não depender da duração de um pg_dump), o que aqui só
    tornaria as asserções uma corrida.
    """
    for phase in (
        SimulationPhase.BACKFILL,
        SimulationPhase.BACKUP,
        SimulationPhase.MAINTENANCE,
    ):
        monkeypatch.setitem(sim._PHASE_ACTIONS, phase, lambda db: None)
    monkeypatch.setattr(sim, "_dispatch_action", sim._execute_action)


@pytest.fixture
def demo_instance(db):
    inst = DatabaseInstance(
        name="demo-prod",
        status=InstanceStatus.RUNNING,
        environment=Environment.PRODUCTION,
        notes=DEMO_MARKER,
        storage_gb=20,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _expire_phase(db, seconds_ago: int = 3600):
    state = sim.get_state(db)
    state.phase_started_at = sim._now() - timedelta(seconds=seconds_ago)
    db.commit()
    return state


# --------------------------------------------------------------------------- #
# Máquina de estados
# --------------------------------------------------------------------------- #
def test_start_enters_the_first_phase(db, demo_instance):
    state = sim.start(db)
    assert state.phase == sim.PHASE_ORDER[0]
    assert state.started_at is not None
    assert state.speed_factor == settings.DEMO_SIMULATION_SPEED_FACTOR


def test_start_is_idempotent(db, demo_instance):
    first = sim.start(db)
    started_at = first.started_at
    _expire_phase(db)
    sim.advance_once()
    db.expire_all()

    again = sim.start(db)
    assert again.started_at == started_at, "segundo clique não pode reiniciar o roteiro"
    assert again.phase != sim.PHASE_ORDER[0]


def test_script_advances_through_every_phase(db, demo_instance):
    sim.start(db)
    seen = [sim.get_state(db).phase]

    for _ in range(len(sim.PHASE_ORDER)):
        _expire_phase(db)
        sim.advance_once()
        db.expire_all()
        seen.append(sim.get_state(db).phase)

    assert seen[: len(sim.PHASE_ORDER)] == sim.PHASE_ORDER
    # STEADY é terminal: mais ticks não mudam nada.
    assert seen[-1] == SimulationPhase.STEADY


def test_phase_does_not_advance_before_its_duration(db, demo_instance):
    sim.start(db)
    sim.advance_once()
    db.expire_all()
    assert sim.get_state(db).phase == sim.PHASE_ORDER[0]


def test_failing_phase_is_logged_and_the_script_continues(db, demo_instance, monkeypatch):
    def _boom(db_):
        raise RuntimeError("pg_dump não encontrado")

    monkeypatch.setitem(sim._PHASE_ACTIONS, SimulationPhase.WARMUP, _boom)
    sim.start(db)
    _expire_phase(db)
    sim.advance_once()
    db.expire_all()

    state = sim.get_state(db)
    assert state.phase == SimulationPhase.WARMUP  # avançou apesar do erro
    assert any("Phase failed" in e["message"] for e in state.events)


# --------------------------------------------------------------------------- #
# Relógio virtual e intensidade
# --------------------------------------------------------------------------- #
def test_virtual_clock_is_real_time_while_idle(db):
    sim.get_state(db)
    assert abs((sim.virtual_now() - sim._now()).total_seconds()) < 2


def test_virtual_clock_accelerates_during_the_simulation(db, demo_instance):
    sim.start(db)
    state = sim.get_state(db)
    state.started_at = sim._now() - timedelta(seconds=60)
    state.speed_factor = 144.0
    db.commit()

    # 60s reais × 144 ≈ 2.4h virtuais à frente do início.
    ahead = (sim.virtual_now() - state.started_at).total_seconds()
    assert 8000 < ahead < 9000


def test_traffic_intensity_is_zero_until_started(db, demo_instance):
    sim.get_state(db)
    assert sim.traffic_intensity() == 0.0

    sim.start(db)
    _expire_phase(db)
    sim.advance_once()  # → WARMUP
    assert sim.traffic_intensity() == 1.0


def test_recover_phase_drops_the_load(db, demo_instance):
    state = sim.get_state(db)
    state.phase = SimulationPhase.RECOVER
    state.started_at = sim._now()
    db.commit()
    assert 0 < sim.traffic_intensity() < 0.5


def test_tick_interval_accelerates_only_during_the_simulation(db, demo_instance):
    sim.get_state(db)
    assert sim.tick_interval(60) == 60

    sim.start(db)
    assert sim.tick_interval(60) == sim.ACCELERATED_INTERVAL_SECONDS
    # Nunca desacelera um loop que já é mais rápido que o intervalo acelerado.
    assert sim.tick_interval(5) == 5


# --------------------------------------------------------------------------- #
# Alerta a partir de métrica REAL
# --------------------------------------------------------------------------- #
def test_alert_phase_uses_the_measured_value_as_threshold(db, demo_instance):
    db.add_all([
        Metric(instance_id=demo_instance.id, metric_name="connections_active", value=20.0),
        Metric(instance_id=demo_instance.id, metric_name="connections_max", value=100.0),
    ])
    db.commit()

    sim._phase_alert(db)

    rule = db.query(AlertRule).filter(AlertRule.instance_id == demo_instance.id).one()
    assert rule.metric_type == "connections_ratio"
    # Medido 20% → limiar logo abaixo, para o avaliador abrir o evento sozinho.
    assert 0 < rule.threshold < 20.0


def test_alert_phase_skips_when_no_metric_was_collected(db, demo_instance):
    sim.get_state(db)  # a linha de estado é onde o log da fase é escrito
    sim._phase_alert(db)

    assert db.query(AlertRule).count() == 0
    assert any("skipped" in e["message"] for e in sim.get_state(db).events)


# --------------------------------------------------------------------------- #
# stop / reset
# --------------------------------------------------------------------------- #
def test_stop_keeps_the_data_and_the_warning(db, demo_instance):
    sim.start(db)
    state = sim.get_state(db)
    state.has_simulated_data = True
    db.commit()
    db.add(Metric(instance_id=demo_instance.id, metric_name="connections_active", value=7.0))
    db.commit()

    sim.stop(db)
    db.expire_all()

    state = sim.get_state(db)
    assert state.phase == SimulationPhase.IDLE
    assert state.has_simulated_data is True
    assert db.query(Metric).count() == 1


def test_reset_restores_the_real_fleet(db, demo_instance):
    original_created_at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    demo_instance.created_at = original_created_at
    db.commit()

    sim.start(db)
    state = sim.get_state(db)
    state.has_simulated_data = True
    state.restore_points = {str(demo_instance.id): original_created_at.isoformat()}
    db.commit()

    # Resíduo típico de uma simulação: métrica, regra de alerta, backup e o
    # created_at retroagido pelo backfill.
    db.add_all([
        Metric(instance_id=demo_instance.id, metric_name="connections_active", value=9.0),
        AlertRule(
            instance_id=demo_instance.id,
            name="Connection pool under load",
            metric_type="connections_ratio",
            condition="gt",
            threshold=10.0,
            severity="warning",
        ),
        Backup(
            instance_id=demo_instance.id,
            strategy=BackupStrategy.LOGICAL,
            status=BackupStatus.COMPLETED,
        ),
    ])
    demo_instance.created_at = original_created_at - timedelta(days=45)
    db.commit()

    sim.reset(db)
    db.expire_all()

    assert db.query(Metric).count() == 0
    assert db.query(AlertRule).count() == 0
    assert db.query(Backup).count() == 0
    refreshed = db.get(DatabaseInstance, demo_instance.id)
    assert refreshed.created_at == original_created_at

    state = sim.get_state(db)
    assert state.has_simulated_data is False
    assert state.phase == SimulationPhase.IDLE


def test_status_reports_progress_and_phase_position(db, demo_instance):
    payload = sim.status(db)
    assert payload["running"] is False
    assert payload["phase"] == "idle"

    sim.start(db)
    payload = sim.status(db)
    assert payload["running"] is True
    assert payload["phase_index"] == 0
    # STEADY não conta como etapa — a UI numera "X de 6".
    assert payload["phase_count"] == len(sim.SCRIPT_PHASES) == len(sim.PHASE_ORDER) - 1
    assert 0.0 <= payload["phase_progress"] <= 1.0


def test_steady_reports_itself_as_finished_not_as_a_step(db, demo_instance):
    # Em regime a timeline tem de aparecer inteira concluída (índice além da
    # última etapa) — foi o que evitou o "parece que ainda está carregando".
    state = sim.get_state(db)
    state.phase = SimulationPhase.STEADY
    state.started_at = sim._now()
    db.commit()

    payload = sim.status(db)
    assert payload["running"] is True
    assert payload["phase"] == "steady"
    assert payload["phase_index"] == payload["phase_count"]


def test_the_whole_script_fits_in_two_minutes(db):
    # O roteiro existe para ser assistido inteiro por quem está de passagem.
    total = sum(d.total_seconds() for d in sim.PHASE_DURATIONS.values())
    assert total <= 120
    # ...mas cada fase precisa de pelo menos 3 ciclos de coleta, senão o alerta
    # pode não abrir a partir de um valor medido.
    timed = {p: d for p, d in sim.PHASE_DURATIONS.items() if p != SimulationPhase.BACKFILL}
    assert all(
        d.total_seconds() >= 3 * sim.ACCELERATED_INTERVAL_SECONDS for d in timed.values()
    )


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
def test_endpoints_require_authentication(client):
    assert client.get("/api/v1/demo/simulation").status_code == 401
    assert client.post("/api/v1/demo/simulation/start").status_code == 401


def test_start_and_stop_through_the_api(client, auth_headers, demo_instance):
    headers, _ = auth_headers()

    started = client.post("/api/v1/demo/simulation/start", headers=headers)
    assert started.status_code == 200
    assert started.json()["running"] is True

    stopped = client.post("/api/v1/demo/simulation/stop", headers=headers)
    assert stopped.status_code == 200
    assert stopped.json()["running"] is False


def test_endpoints_are_hidden_when_demo_mode_is_off(client, auth_headers, monkeypatch):
    headers, _ = auth_headers()
    monkeypatch.setattr(settings, "DEMO_MODE", False)

    assert client.post("/api/v1/demo/simulation/start", headers=headers).status_code == 404
    # O GET continua respondendo, com enabled=false, para a UI só esconder o botão.
    payload = client.get("/api/v1/demo/simulation", headers=headers).json()
    assert payload["enabled"] is False


def test_state_row_is_a_singleton(db):
    sim.get_state(db)
    sim.get_state(db)
    assert db.query(DemoSimulation).count() == 1
