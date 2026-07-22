"""
Testes do diretor do "demo ao vivo" (o botão "Ver ao vivo").

O que importa garantir aqui:
- o roteiro avança fase a fase e nunca trava quando uma ação falha;
- não há mais relógio acelerado: virtual_now é sempre o tempo real;
- a frota nunca esvazia — IDLE mantém a carga-base, `stop` volta à base e
  `reset` RESTAURA a base semeada (repopula via enrich_fleet), não o vazio;
- os endpoints exigem autenticação e somem com DEMO_MODE desligado.

As ações de fase que tocam Docker/pg_dump (backup, manutenção) são substituídas
por dublês: o valor testado é a máquina de estados, não o pg_dump — esse já tem
cobertura em test_backup_service.py.
"""
import time
from datetime import timedelta

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
        SimulationPhase.BACKUP,
        SimulationPhase.MAINTENANCE,
    ):
        monkeypatch.setitem(sim._PHASE_ACTIONS, phase, lambda db: None)
    monkeypatch.setattr(sim, "_dispatch_action", sim._execute_action)
    # Estado de processo (marcas monotônicas e cache) não pode vazar entre testes.
    sim._MONOTONIC_REFS.clear()
    sim.invalidate_state_cache()
    yield
    sim._MONOTONIC_REFS.clear()
    sim.invalidate_state_cache()


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
    """
    Faz a fase atual vencer: recua a marca monotônica (o relógio que o diretor
    de fato consulta) e o timestamp persistido, que é o fallback.
    """
    state = sim.get_state(db)
    state.phase_started_at = sim._now() - timedelta(seconds=seconds_ago)
    db.commit()
    sim._MONOTONIC_REFS[sim._PHASE_KEY] = time.monotonic() - seconds_ago
    sim.invalidate_state_cache()
    return state


# --------------------------------------------------------------------------- #
# Máquina de estados
# --------------------------------------------------------------------------- #
def test_start_enters_the_first_phase(db, demo_instance):
    state = sim.start(db)
    assert state.phase == sim.PHASE_ORDER[0]
    assert state.started_at is not None


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

    # ALERT (2ª fase) falha: o diretor tem de entrar nela mesmo assim e logar.
    monkeypatch.setitem(sim._PHASE_ACTIONS, SimulationPhase.ALERT, _boom)
    sim.start(db)  # → WARMUP (ação real, só loga)
    _expire_phase(db)
    sim.advance_once()  # WARMUP → ALERT, despacha _boom
    db.expire_all()

    state = sim.get_state(db)
    assert state.phase == SimulationPhase.ALERT  # entrou na fase apesar do erro
    assert any("Phase failed" in e["message"] for e in state.events)


# --------------------------------------------------------------------------- #
# Tempo real (sem aceleração) e intensidade
# --------------------------------------------------------------------------- #
def test_virtual_clock_is_real_time_while_idle(db):
    sim.get_state(db)
    assert abs((sim.virtual_now() - sim._now()).total_seconds()) < 2


def test_virtual_clock_stays_real_time_during_a_run(db, demo_instance):
    # A aceleração 144× foi removida (fazia o gráfico "subir estranho"): mesmo
    # com o reel rodando há um bom tempo, virtual_now segue o relógio real.
    sim.start(db)
    sim._MONOTONIC_REFS[sim._RUN_KEY] = time.monotonic() - 600  # 10 min de execução
    assert abs((sim.virtual_now() - sim._now()).total_seconds()) < 2


def test_traffic_intensity_is_baseline_until_started(db, demo_instance):
    # IDLE não é 0: a frota demo mantém uma carga-base contínua para nunca
    # parecer morta.
    sim.get_state(db)
    assert sim.traffic_intensity() == sim.BASELINE_INTENSITY
    assert sim.BASELINE_INTENSITY > 0

    sim.start(db)
    _expire_phase(db)
    sim.advance_once()  # → WARMUP
    assert sim.traffic_intensity() == 1.0


def test_recover_phase_falls_back_to_baseline(db, demo_instance):
    # RECOVER volta à base (não a zero): é a queda do pico à base que faz o
    # avaliador resolver o alerta aberto.
    state = sim.get_state(db)
    state.phase = SimulationPhase.RECOVER
    state.started_at = sim._now()
    db.commit()
    sim.invalidate_state_cache()
    assert sim.traffic_intensity() == sim.BASELINE_INTENSITY


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
def test_stop_returns_to_baseline_without_emptying(db, demo_instance):
    # Stop não fecha pools nem apaga nada: a frota volta à carga-base, cheia. O
    # modelo antigo media a frota ociosa aqui e o dashboard parecia morto.
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
    assert db.query(Metric).count() == 1  # nada foi apagado
    # Em IDLE a intensidade é a base (> 0): o gerador não fecha os pools.
    assert sim.traffic_intensity() == sim.BASELINE_INTENSITY


def test_reset_wipes_reel_artifacts_and_repopulates_the_baseline(db, demo_instance, monkeypatch):
    # O reset já NÃO devolve a frota ao vazio: apaga o resíduo do reel e RESTAURA
    # a base semeada chamando enrich_fleet. Aqui enrich é um dublê — a garantia é
    # "limpou e repopulou (chamou enrich)"; o conteúdo de enrich tem cobertura em
    # test_seed_history.py.
    enrich_calls: list[bool] = []
    monkeypatch.setattr(
        "src.seed.history.enrich_fleet", lambda _db: enrich_calls.append(True)
    )

    sim.start(db)
    state = sim.get_state(db)
    state.has_simulated_data = True
    db.commit()

    # Resíduo típico de um reel: métrica, regra de alerta e backup.
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
    db.commit()

    sim.reset(db)
    db.expire_all()

    # Resíduo apagado (enrich é dublê, então nada foi re-semeado no seu lugar).
    assert db.query(Metric).count() == 0
    assert db.query(AlertRule).count() == 0
    assert db.query(Backup).count() == 0
    # Mas a base FOI restaurada: enrich_fleet foi chamado, e o estado segue
    # marcando dado de demonstração — nunca "frota vazia".
    assert enrich_calls == [True]

    state = sim.get_state(db)
    assert state.has_simulated_data is True
    assert state.phase == SimulationPhase.IDLE


def test_status_reports_progress_and_phase_position(db, demo_instance):
    payload = sim.status(db)
    assert payload["running"] is False
    assert payload["phase"] == "idle"

    sim.start(db)
    payload = sim.status(db)
    assert payload["running"] is True
    assert payload["phase_index"] == 0
    # STEADY não conta como etapa — a UI numera "X de 5".
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

    # ALERT e RECOVER são as únicas fases cuja duração é uma RESTRIÇÃO, não uma
    # escolha: o alerta só abre (e só resolve) depois que o poller coletou e o
    # avaliador rodou. Menos de 3 ciclos e a fase passa em branco.
    for phase in (SimulationPhase.ALERT, SimulationPhase.RECOVER):
        assert (
            sim.PHASE_DURATIONS[phase].total_seconds()
            >= 3 * sim.ACCELERATED_INTERVAL_SECONDS
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


# --------------------------------------------------------------------------- #
# Cronômetro imune a saltos do relógio
# --------------------------------------------------------------------------- #
def test_schedule_ignores_a_wall_clock_jump_backwards(db, demo_instance):
    """
    Este ambiente (WSL2) volta o relógio de parede dezenas de segundos. Quando o
    roteiro dependia dele, TODAS as fases seguintes atrasavam pelo mesmo tanto —
    um roteiro de 1m40 virava 2m30. O cronômetro é monotônico justamente por isso.
    """
    sim.start(db)
    # A fase já venceu no relógio monotônico...
    sim._MONOTONIC_REFS[sim._PHASE_KEY] = time.monotonic() - 3600
    # ...mas o relógio de parede diz que ela começou no futuro (salto para trás).
    state = sim.get_state(db)
    state.phase_started_at = sim._now() + timedelta(seconds=90)
    db.commit()
    sim.invalidate_state_cache()

    sim.advance_once()
    db.expire_all()
    assert sim.get_state(db).phase != sim.PHASE_ORDER[0], "a fase tinha de ter avançado"


def test_overall_progress_never_goes_backwards_between_phases(db, demo_instance):
    sim.start(db)
    seen = [sim.status(db)["progress"]]

    for _ in range(len(sim.SCRIPT_PHASES) - 1):
        _expire_phase(db)
        sim.advance_once()
        db.expire_all()
        seen.append(sim.status(db)["progress"])

    assert seen == sorted(seen), f"progresso andou para trás: {seen}"
    assert seen[-1] <= 1.0


def test_progress_is_full_in_steady_and_zero_while_idle(db, demo_instance):
    assert sim.status(db)["progress"] == 0.0

    state = sim.get_state(db)
    state.phase = SimulationPhase.STEADY
    state.started_at = sim._now()
    db.commit()
    sim.invalidate_state_cache()
    assert sim.status(db)["progress"] == 1.0


# --------------------------------------------------------------------------- #
# Variedade do alerta, geração da execução e escopo do reset
# --------------------------------------------------------------------------- #
def _prod_instance(db, name: str) -> DatabaseInstance:
    inst = DatabaseInstance(
        name=name,
        status=InstanceStatus.RUNNING,
        environment=Environment.PRODUCTION,
        notes=DEMO_MARKER,
        storage_gb=1,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    # A fase ALERT precisa de uma leitura de conexões para calcular o limiar.
    db.add_all([
        Metric(instance_id=inst.id, metric_name="connections_active", value=40.0),
        Metric(instance_id=inst.id, metric_name="connections_max", value=100.0),
    ])
    db.commit()
    return inst


def test_alert_phase_does_not_always_pick_the_same_instance(db):
    """
    A demo contava sempre a mesma história no mesmo card, porque a fase pegava
    a primeira instância de produção em ordem alfabética.
    """
    for name in ("demo-a-prod", "demo-b-prod", "demo-c-prod"):
        _prod_instance(db, name)

    watched = set()
    for _ in range(25):
        sim._phase_alert(db)
        watched |= {
            r.instance_id for r in db.query(AlertRule)
            .filter(AlertRule.name == "Connection pool under load").all()
        }
        db.query(AlertRule).delete(synchronize_session=False)
        db.commit()

    assert len(watched) > 1, "a fase ALERT continua determinística"


def test_action_from_a_stopped_run_is_discarded(db, demo_instance, monkeypatch):
    """
    Uma ação lenta despachada antes do stop não pode gravar depois dele — nem,
    pior, no meio da execução seguinte.
    """
    executed: list[str] = []
    monkeypatch.setitem(
        sim._PHASE_ACTIONS, SimulationPhase.WARMUP, lambda _db: executed.append("ran")
    )

    generation = sim._current_generation()
    sim._next_generation()  # simula um stop/start entre o despacho e a execução

    sim._execute_action(SimulationPhase.WARMUP, generation)

    assert executed == []


def test_action_from_the_current_run_still_executes(db, demo_instance, monkeypatch):
    executed: list[str] = []
    monkeypatch.setitem(
        sim._PHASE_ACTIONS, SimulationPhase.WARMUP, lambda _db: executed.append("ran")
    )

    sim._execute_action(SimulationPhase.WARMUP, sim._current_generation())

    assert executed == ["ran"]


def test_reset_keeps_audit_the_visitor_generated(db, demo_instance, make_company, monkeypatch):
    """
    O reset apaga o que a SIMULAÇÃO escreveu, não tudo da empresa: os logins e
    ações do próprio visitante são reais e continuam na trilha.
    """
    from src.models.audit_log import AuditLog

    # enrich_fleet como dublê: o foco aqui é o ESCOPO do reset (só o audit
    # simulado sai), não a repopulação.
    monkeypatch.setattr("src.seed.history.enrich_fleet", lambda _db: None)

    company = make_company("Demo Co")
    demo_instance.company_id = company.id
    db.add(demo_instance)
    db.add_all([
        AuditLog(company_id=company.id, action="login", resource_type="auth",
                 details={"method": "POST", "path": "/api/v1/auth/login"}),
        AuditLog(company_id=company.id, action="backup_created", resource_type="backup",
                 details={"instance": demo_instance.name, "simulated": True}),
    ])
    db.commit()

    sim.reset(db)

    remaining = [a.action for a in db.query(AuditLog).all()]
    assert remaining == ["login"]
