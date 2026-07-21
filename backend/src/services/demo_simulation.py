"""
Diretor da simulação de uso da frota de demonstração.

O clone limpo desta plataforma provisiona containers PostgreSQL reais e mais
nada: sem tráfego, sem alertas, sem backups — porque nada disso aconteceu ainda.
Honesto, mas um visitante não consegue ver o produto trabalhando em cinco
minutos de visita.

Este módulo é o "Simular uso": um roteiro em fases que, uma vez iniciado pelo
usuário, faz a plataforma administrar a frota **de verdade** — sobe tráfego OLTP,
dispara um alerta a partir de métrica medida, roda `pg_dump`, roda VACUUM/ANALYZE,
deixa o alerta resolver — e complementa com o backfill histórico daquilo que é
impossível produzir ao vivo (uptime de 30 dias, semanas de backup). Enquanto
qualquer dado semeado existir, a UI mostra o banner de "uso simulado", e
`reset()` devolve a frota ao estado real.

Desenho:
- **Estado no banco** (`DemoSimulation`, linha única): sobrevive a restart, é a
  mesma verdade para todas as abas, e guarda os `restore_points` que o reset usa
  para desfazer o que a simulação alterou nos registros reais.
- **Relógio virtual**: `virtual_now()` acelera o tempo por `speed_factor` (144 →
  24h em 10 min) para a curva diária de tráfego se desenhar na tela. Só o
  tráfego usa esse relógio; tudo o que é persistido usa o tempo real.
- **Diretor**: `simulation_loop` bate a cada 2s, vê se a fase venceu e executa a
  ação da próxima. Uma fase que falha (Docker fora, pg_dump ausente) é
  registrada no log de eventos e o roteiro segue — a demo nunca trava.

Escopo: só instâncias da frota demo (`notes == DEMO_MARKER`). Com
`DEMO_MODE=false` o router não é registrado e este loop não sobe.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.database import SessionLocal
from src.models.alert import AlertEvent, AlertRule
from src.models.audit_log import AuditLog
from src.models.backup import Backup, BackupSchedule, BackupType
from src.models.database_instance import DatabaseInstance, Environment, InstanceStatus
from src.models.demo_simulation import DemoSimulation, SimulationPhase
from src.models.instance_status_history import InstanceStatusHistory
from src.models.maintenance import MaintenanceSchedule, MaintenanceTask, TaskType
from src.models.metric import Metric
from src.models.user import User, UserRole
from src.schemas.maintenance import MaintenanceTaskCreate

logger = logging.getLogger(__name__)

# Intervalo do diretor. Curto porque ele só lê uma linha e, na maioria dos
# ticks, não faz nada — o custo é irrelevante e a transição de fase fica no ponto.
_TICK_SECONDS = 2

# Duração de cada fase do roteiro. STEADY não tem duração: é o fim (o tráfego
# continua até o usuário parar).
PHASE_DURATIONS: dict[SimulationPhase, timedelta] = {
    SimulationPhase.BACKFILL: timedelta(seconds=10),
    SimulationPhase.WARMUP: timedelta(seconds=60),
    SimulationPhase.ALERT: timedelta(seconds=60),
    SimulationPhase.BACKUP: timedelta(seconds=75),
    SimulationPhase.MAINTENANCE: timedelta(seconds=60),
    SimulationPhase.RECOVER: timedelta(seconds=60),
}

# Ordem do roteiro.
PHASE_ORDER: list[SimulationPhase] = [
    SimulationPhase.BACKFILL,
    SimulationPhase.WARMUP,
    SimulationPhase.ALERT,
    SimulationPhase.BACKUP,
    SimulationPhase.MAINTENANCE,
    SimulationPhase.RECOVER,
    SimulationPhase.STEADY,
]

# Intensidade do tráfego por fase (multiplica o alvo de conexões). RECOVER cai
# de propósito: é a queda que faz o avaliador resolver o alerta aberto na fase
# ALERT — a recuperação é observada, não escrita à mão.
_TRAFFIC_INTENSITY: dict[SimulationPhase, float] = {
    SimulationPhase.IDLE: 0.0,
    SimulationPhase.BACKFILL: 0.0,
    SimulationPhase.WARMUP: 1.0,
    SimulationPhase.ALERT: 1.0,
    SimulationPhase.BACKUP: 0.9,
    SimulationPhase.MAINTENANCE: 0.8,
    SimulationPhase.RECOVER: 0.15,
    SimulationPhase.STEADY: 1.0,
}

# Enquanto a simulação roda, métricas e alertas são coletados/avaliados neste
# intervalo, em vez dos 60s normais: com o tempo acelerado, 60s de relógio real
# seriam ~2.5h virtuais e o gráfico viraria uma escada de dois degraus.
ACCELERATED_INTERVAL_SECONDS = 10

# Margem do limiar do alerta: a regra é criada logo ABAIXO do valor medido
# naquele instante, para o evento abrir a partir de dado real no ciclo seguinte.
_ALERT_MARGIN_RATIO = 0.85

_MAX_EVENTS = 40


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Estado
# --------------------------------------------------------------------------- #
def get_state(db: Session) -> DemoSimulation:
    """Lê (ou cria) a linha única de estado."""
    state = db.query(DemoSimulation).first()
    if state is None:
        state = DemoSimulation(phase=SimulationPhase.IDLE)
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def _log_event(state: DemoSimulation, phase: SimulationPhase, message: str) -> None:
    """Acrescenta uma linha ao log do roteiro (mantido curto, é UI)."""
    events = list(state.events or [])
    events.append({
        "at": _now().isoformat(),
        "phase": phase.value,
        "message": message,
    })
    state.events = events[-_MAX_EVENTS:]


def is_running(state: DemoSimulation) -> bool:
    return state.phase != SimulationPhase.IDLE


def _demo_instances(db: Session) -> list[DatabaseInstance]:
    from src.seed.demo import DEMO_MARKER  # lazy: evita import circular

    return (
        db.query(DatabaseInstance)
        .filter(
            DatabaseInstance.notes == DEMO_MARKER,
            DatabaseInstance.deleted_at.is_(None),
        )
        .order_by(DatabaseInstance.name.asc())
        .all()
    )


# --------------------------------------------------------------------------- #
# Relógio virtual e intensidade — lidos pelo workload simulator e pelos pollers
# --------------------------------------------------------------------------- #
def _read_live_state() -> tuple[SimulationPhase, datetime | None, float]:
    """
    Fase/início/velocidade atuais, numa sessão própria e curta.

    Chamado por loops que rodam fora de contexto HTTP e não têm sessão à mão.
    Falha de banco devolve IDLE: sem simulação, ninguém gera carga.
    """
    db = SessionLocal()
    try:
        state = db.query(DemoSimulation).first()
        if state is None:
            return SimulationPhase.IDLE, None, 1.0
        return state.phase, state.started_at, state.speed_factor or 1.0
    except Exception:  # noqa: BLE001 — leitura best-effort de estado de demo
        return SimulationPhase.IDLE, None, 1.0
    finally:
        db.close()


def virtual_now() -> datetime:
    """
    Tempo do ponto de vista do tráfego simulado.

    Sem simulação ativa, é o tempo real. Com simulação, o tempo desde o início
    é multiplicado por `speed_factor` — é o que faz a curva diária de conexões
    se desenhar em minutos em vez de 24 horas.
    """
    phase, started_at, factor = _read_live_state()
    if phase == SimulationPhase.IDLE or started_at is None:
        return _now()
    return started_at + (_now() - started_at) * factor


def traffic_intensity() -> float:
    """Multiplicador de carga da fase atual (0 = simulador dorme)."""
    phase, _, _ = _read_live_state()
    return _TRAFFIC_INTENSITY.get(phase, 0.0)


def tick_interval(default: int) -> int:
    """
    Intervalo que os loops de coleta/avaliação devem usar agora.

    Acelera durante a simulação e volta ao normal quando ela termina — assim os
    gráficos acompanham o tempo virtual sem mudar o comportamento em produção.
    """
    phase, _, _ = _read_live_state()
    if phase == SimulationPhase.IDLE:
        return default
    return min(default, ACCELERATED_INTERVAL_SECONDS)


# --------------------------------------------------------------------------- #
# Ações das fases — todas usam os serviços REAIS da plataforma
# --------------------------------------------------------------------------- #
def _audit(
    db: Session,
    instance: DatabaseInstance,
    action: str,
    resource_type: str,
    resource_id: str,
) -> None:
    """
    Registra a ação no audit log atribuída ao admin da empresa.

    O AuditMiddleware só enxerga requests HTTP; estas ações nascem no diretor,
    então a entrada é escrita aqui — com `simulated: true` nos detalhes, para
    a trilha não mentir sobre a origem.
    """
    admin = (
        db.query(User)
        .filter(User.company_id == instance.company_id, User.role == UserRole.ADMIN)
        .first()
    )
    db.add(AuditLog(
        user_id=admin.id if admin else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details={"instance": instance.name, "simulated": True},
        company_id=instance.company_id,
    ))
    db.commit()


def _phase_backfill(db: Session, state: DemoSimulation) -> None:
    """
    Semeia o histórico que não dá para produzir ao vivo (uptime de 30 dias,
    semanas de backup, frota com idade) e guarda os pontos de restauração.
    """
    from src.seed import history

    instances = _demo_instances(db)
    restore = dict(state.restore_points or {})
    for inst in instances:
        restore.setdefault(str(inst.id), inst.created_at.isoformat())
    state.restore_points = restore
    state.has_simulated_data = True
    db.commit()

    history.enrich_fleet(db)
    _log_event(
        state,
        SimulationPhase.BACKFILL,
        f"Seeded 24h of metrics, uptime and operational history for "
        f"{len(instances)} instances",
    )
    db.commit()


def _phase_warmup(db: Session, state: DemoSimulation) -> None:
    _log_event(
        state,
        SimulationPhase.WARMUP,
        "Traffic ramping up — connection pools follow an accelerated daily curve",
    )
    db.commit()


def _phase_alert(db: Session, state: DemoSimulation) -> None:
    """
    Cria uma regra cujo limiar fica logo abaixo da razão de conexões MEDIDA
    agora, para o avaliador real abrir o evento a partir de dado real.
    """
    from src.models.alert import AlertCondition, AlertSeverity

    target = next(
        (i for i in _demo_instances(db)
         if i.environment == Environment.PRODUCTION and i.status == InstanceStatus.RUNNING),
        None,
    )
    if target is None:
        _log_event(state, SimulationPhase.ALERT, "No running production instance to watch")
        db.commit()
        return

    active = _latest_metric(db, target.id, "connections_active")
    max_conn = _latest_metric(db, target.id, "connections_max") or 100.0
    if active is None:
        _log_event(state, SimulationPhase.ALERT, "No connection metric collected yet — rule skipped")
        db.commit()
        return

    ratio = (active / max_conn) * 100.0
    threshold = round(max(1.0, ratio * _ALERT_MARGIN_RATIO), 1)
    name = "Connection pool under load"
    existing = (
        db.query(AlertRule)
        .filter(AlertRule.instance_id == target.id, AlertRule.name == name)
        .first()
    )
    if existing is None:
        db.add(AlertRule(
            instance_id=target.id,
            name=name,
            metric_type="connections_ratio",
            condition=AlertCondition.GT,
            threshold=threshold,
            severity=AlertSeverity.WARNING,
            is_active=True,
        ))
    else:
        existing.threshold = threshold
        existing.is_active = True
    db.commit()

    _log_event(
        state,
        SimulationPhase.ALERT,
        f"Watching {target.name}: rule connections_ratio > {threshold}% "
        f"(measured {ratio:.1f}%) — the evaluator opens the event on its own",
    )
    db.commit()


def _phase_backup(db: Session, state: DemoSimulation) -> None:
    """pg_dump de verdade na instância de produção de cada empresa."""
    from src.services import backup as backup_service

    done = 0
    for inst in _demo_instances(db):
        if inst.environment != Environment.PRODUCTION or inst.status != InstanceStatus.RUNNING:
            continue
        try:
            record = backup_service.create_logical_backup(
                db, inst, backup_type=BackupType.MANUAL, retention_days=7
            )
            _audit(db, inst, "backup_created", "backup", str(record.id))
            done += 1
        except Exception as exc:  # noqa: BLE001 — uma falha não trava o roteiro
            logger.warning("Simulação: backup de %s falhou: %s", inst.name, exc)
            _log_event(state, SimulationPhase.BACKUP, f"Backup of {inst.name} failed: {exc}")
    _log_event(state, SimulationPhase.BACKUP, f"{done} logical backup(s) written with pg_dump")
    db.commit()


def _phase_maintenance(db: Session, state: DemoSimulation) -> None:
    """VACUUM e ANALYZE de verdade nas instâncias de produção."""
    from src.services import maintenance as maintenance_service

    done = 0
    for inst in _demo_instances(db):
        if inst.environment != Environment.PRODUCTION or inst.status != InstanceStatus.RUNNING:
            continue
        for task_type in (TaskType.VACUUM, TaskType.ANALYZE):
            try:
                task = maintenance_service.run_task(
                    db, inst, MaintenanceTaskCreate(task_type=task_type)
                )
                _audit(db, inst, "maintenance_run", "maintenance", str(task.id))
                done += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Simulação: %s em %s falhou: %s", task_type, inst.name, exc)
    _log_event(state, SimulationPhase.MAINTENANCE, f"{done} maintenance task(s) executed")
    db.commit()


def _phase_recover(db: Session, state: DemoSimulation) -> None:
    _log_event(
        state,
        SimulationPhase.RECOVER,
        "Traffic falling back to baseline — open alerts resolve from real metrics",
    )
    db.commit()


def _phase_steady(db: Session, state: DemoSimulation) -> None:
    _log_event(
        state,
        SimulationPhase.STEADY,
        "Scripted run finished — the fleet keeps serving traffic until you stop it",
    )
    db.commit()


_PHASE_ACTIONS = {
    SimulationPhase.BACKFILL: _phase_backfill,
    SimulationPhase.WARMUP: _phase_warmup,
    SimulationPhase.ALERT: _phase_alert,
    SimulationPhase.BACKUP: _phase_backup,
    SimulationPhase.MAINTENANCE: _phase_maintenance,
    SimulationPhase.RECOVER: _phase_recover,
    SimulationPhase.STEADY: _phase_steady,
}


def _latest_metric(db: Session, instance_id: uuid.UUID, name: str) -> float | None:
    row = (
        db.query(Metric.value)
        .filter(Metric.instance_id == instance_id, Metric.metric_name == name)
        .order_by(Metric.collected_at.desc())
        .first()
    )
    return row[0] if row else None


# --------------------------------------------------------------------------- #
# Controle: start / stop / reset / status
# --------------------------------------------------------------------------- #
def start(db: Session) -> DemoSimulation:
    """
    Inicia o roteiro. Idempotente: se já está rodando, devolve o estado atual
    (dois cliques no botão não reiniciam a demo pela metade).
    """
    state = get_state(db)
    if is_running(state):
        return state

    now = _now()
    state.phase = PHASE_ORDER[0]
    state.started_at = now
    state.phase_started_at = now
    state.stopped_at = None
    state.speed_factor = settings.DEMO_SIMULATION_SPEED_FACTOR
    state.events = []
    _log_event(state, state.phase, "Simulation started")
    db.commit()

    _run_phase_action(db, state)
    return state


def stop(db: Session) -> DemoSimulation:
    """
    Para o tráfego e o roteiro, PRESERVANDO os dados gerados — o visitante pode
    continuar navegando pelo que a simulação produziu. `has_simulated_data`
    segue verdadeiro, então o aviso continua na tela.
    """
    state = get_state(db)
    if is_running(state):
        _log_event(state, state.phase, "Simulation stopped by the user")
    state.phase = SimulationPhase.IDLE
    state.stopped_at = _now()
    state.phase_started_at = None
    db.commit()

    from src.services import workload_simulator

    workload_simulator.shutdown_pools()
    return state


def reset(db: Session) -> DemoSimulation:
    """
    Devolve a frota ao estado real: para tudo e apaga o que a simulação criou —
    métricas, alertas, backups (registros e arquivos), manutenção, histórico de
    status e audit das empresas demo — restaurando o `created_at` original das
    instâncias. Os containers e o dataset semeado ficam de pé: eles são reais.
    """
    from src.services import backup as backup_service

    state = stop(db)
    instances = _demo_instances(db)
    restore = state.restore_points or {}

    for inst in instances:
        db.query(Metric).filter(Metric.instance_id == inst.id).delete(synchronize_session=False)
        db.query(AlertEvent).filter(AlertEvent.instance_id == inst.id).delete(synchronize_session=False)
        db.query(AlertRule).filter(AlertRule.instance_id == inst.id).delete(synchronize_session=False)
        db.query(MaintenanceTask).filter(MaintenanceTask.instance_id == inst.id).delete(synchronize_session=False)
        db.query(MaintenanceSchedule).filter(MaintenanceSchedule.instance_id == inst.id).delete(synchronize_session=False)
        db.query(InstanceStatusHistory).filter(InstanceStatusHistory.instance_id == inst.id).delete(synchronize_session=False)

        # Backups: apagar o arquivo no disco ANTES do registro — é ele que
        # guarda o caminho; sem isso o .dump ficaria órfão em data/backups/.
        # delete_backup_record só marca DELETED (histórico), então o registro
        # em si é removido logo em seguida: aqui o objetivo é não deixar rastro.
        for record in db.query(Backup).filter(Backup.instance_id == inst.id).all():
            try:
                backup_service.delete_backup_record(db, record)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Reset: falha ao remover backup %s: %s", record.id, exc)
        db.query(Backup).filter(Backup.instance_id == inst.id).delete(synchronize_session=False)
        db.query(BackupSchedule).filter(BackupSchedule.instance_id == inst.id).delete(synchronize_session=False)

        original = restore.get(str(inst.id))
        if original:
            inst.created_at = datetime.fromisoformat(original)

    company_ids = {i.company_id for i in instances if i.company_id}
    if company_ids:
        db.query(AuditLog).filter(AuditLog.company_id.in_(company_ids)).delete(
            synchronize_session=False
        )

    state.has_simulated_data = False
    state.restore_points = {}
    state.events = []
    state.started_at = None
    db.commit()
    logger.info("Simulação: frota demo devolvida ao estado real.")
    return state


def status(db: Session) -> dict[str, Any]:
    """Estado para a UI: fase, progresso do roteiro e log de eventos."""
    state = get_state(db)
    running = is_running(state)
    phase_index = PHASE_ORDER.index(state.phase) if running else -1
    duration = PHASE_DURATIONS.get(state.phase)

    phase_progress = 1.0
    if running and duration and state.phase_started_at:
        elapsed = (_now() - state.phase_started_at).total_seconds()
        phase_progress = min(1.0, max(0.0, elapsed / duration.total_seconds()))

    return {
        "enabled": settings.DEMO_MODE,
        "running": running,
        "phase": state.phase.value,
        "phase_index": phase_index,
        "phase_count": len(PHASE_ORDER),
        "phase_progress": round(phase_progress, 3),
        "has_simulated_data": state.has_simulated_data,
        "speed_factor": state.speed_factor,
        "started_at": state.started_at,
        "events": list(state.events or []),
    }


# --------------------------------------------------------------------------- #
# Diretor
# --------------------------------------------------------------------------- #
def _run_phase_action(db: Session, state: DemoSimulation) -> None:
    """Executa a ação da fase atual; falha vira evento no log e o roteiro segue."""
    action = _PHASE_ACTIONS.get(state.phase)
    if action is None:
        return
    try:
        action(db, state)
    except Exception as exc:  # noqa: BLE001 — demo nunca deve travar
        db.rollback()
        logger.exception("Simulação: fase %s falhou: %s", state.phase, exc)
        _log_event(state, state.phase, f"Phase failed: {exc}")
        db.commit()


def advance_once() -> None:
    """
    Um tick do diretor: se a fase atual venceu, entra na próxima e executa a
    ação dela. STEADY e IDLE não vencem nunca.
    """
    db = SessionLocal()
    try:
        state = get_state(db)
        if not is_running(state) or state.phase == SimulationPhase.STEADY:
            return

        duration = PHASE_DURATIONS.get(state.phase)
        if duration is None or state.phase_started_at is None:
            return
        if _now() - state.phase_started_at < duration:
            return

        next_phase = PHASE_ORDER[PHASE_ORDER.index(state.phase) + 1]
        state.phase = next_phase
        state.phase_started_at = _now()
        db.commit()
        _run_phase_action(db, state)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("Erro no tick da simulação: %s", exc)
    finally:
        db.close()


async def simulation_loop(stop_event: asyncio.Event) -> None:
    """Loop do diretor — mesmo padrão dos demais workers do lifespan."""
    logger.info("Demo simulation director iniciado (tick: %ds)", _TICK_SECONDS)
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(advance_once)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Erro no loop da simulação: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_TICK_SECONDS)
        except asyncio.TimeoutError:
            continue
    logger.info("Demo simulation director encerrado.")
