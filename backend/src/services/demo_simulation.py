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
- **Diretor**: `simulation_loop` bate a cada 2s e, quando a fase vence, avança e
  *despacha* a ação da próxima para uma thread dedicada. Despachar em vez de
  executar é o que mantém o relógio do roteiro previsível: `pg_dump`, `VACUUM` e
  o backfill variam de segundos a mais de um minuto conforme a máquina, e no tick
  eles esticavam a fase pelo próprio tempo de execução. Uma ação que falha
  (Docker fora, pg_dump ausente) vira evento no log e o roteiro segue — a demo
  nunca trava.

Escopo: só instâncias da frota demo (`notes == DEMO_MARKER`). Com
`DEMO_MODE=false` o router não é registrado e este loop não sobe.
"""
import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
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

# Duração de cada fase do roteiro (~1m40 no total). STEADY não tem duração: é o
# fim (o tráfego continua até o usuário parar).
#
# O piso de cada fase não é estético: o alerta precisa abrir a partir de uma
# métrica COLETADA e resolver a partir da queda MEDIDA depois. Com coleta a cada
# ACCELERATED_INTERVAL_SECONDS, estes valores dão 3-4 ciclos por fase — encurtar
# mais faria a fase passar em branco quando um ciclo atrasasse.
PHASE_DURATIONS: dict[SimulationPhase, timedelta] = {
    SimulationPhase.BACKFILL: timedelta(seconds=5),
    SimulationPhase.WARMUP: timedelta(seconds=18),
    SimulationPhase.ALERT: timedelta(seconds=22),
    SimulationPhase.BACKUP: timedelta(seconds=20),
    SimulationPhase.MAINTENANCE: timedelta(seconds=15),
    SimulationPhase.RECOVER: timedelta(seconds=22),
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

# Fases que compõem o roteiro propriamente dito — STEADY fica de fora porque é
# a conclusão, não um passo: a UI conta "etapa X de 6" e desenha o fim à parte.
SCRIPT_PHASES: list[SimulationPhase] = PHASE_ORDER[:-1]

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
# seriam ~2.5h virtuais e o gráfico viraria uma escada de dois degraus. É também
# o que permite fases de ~20s — cada uma ainda vê 3-4 amostras.
ACCELERATED_INTERVAL_SECONDS = 5

# Ciclo do gerador de carga durante a simulação. Precisa ser curto pelo mesmo
# motivo: o pool sobe _MAX_POOL_STEP conexões por ciclo, e a fase WARMUP inteira
# dura 18s.
ACCELERATED_WORKLOAD_INTERVAL_SECONDS = 5

# Margem do limiar do alerta: a regra é criada logo ABAIXO do valor medido
# naquele instante, para o evento abrir a partir de dado real no ciclo seguinte.
_ALERT_MARGIN_RATIO = 0.85

_MAX_EVENTS = 40

# Thread única para as ações das fases: mantém o diretor livre para avançar no
# horário e, ao mesmo tempo, garante que duas ações nunca rodem em paralelo
# (um pg_dump e um VACUUM concorrentes na mesma instância seriam um teste de
# carga, não uma demonstração).
_ACTION_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="demo-sim")


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
    """
    Acrescenta uma linha ao log do roteiro (mantido curto, é UI).

    Não commita: quem chama decide o momento. Para escritas vindas da thread das
    ações — que corre em paralelo ao diretor — use `log_event_atomic`, senão as
    duas transações se sobrescrevem e um evento some.
    """
    events = list(state.events or [])
    events.append({
        "at": _now().isoformat(),
        "phase": phase.value,
        "message": message,
    })
    state.events = events[-_MAX_EVENTS:]


def log_event_atomic(phase: SimulationPhase, message: str) -> None:
    """
    Append seguro sob concorrência: relê a linha com FOR UPDATE, acrescenta e
    commita numa transação curta e própria.

    Necessário porque a JSONB é reescrita inteira a cada append: sem o lock, o
    diretor e a thread de ações partiriam da mesma lista e a última gravação
    apagaria o evento da outra.
    """
    db = SessionLocal()
    try:
        state = db.query(DemoSimulation).with_for_update().first()
        if state is None:
            return
        _log_event(state, phase, message)
        db.commit()
    except Exception as exc:  # noqa: BLE001 — log de demo nunca derruba a fase
        db.rollback()
        logger.warning("Simulação: falha ao registrar evento: %s", exc)
    finally:
        db.close()


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


def _production_instances(db: Session) -> list[DatabaseInstance]:
    """Instâncias demo de produção no ar — o alvo das operações do roteiro."""
    return [
        i for i in _demo_instances(db)
        if i.environment == Environment.PRODUCTION
        and i.status == InstanceStatus.RUNNING
    ]


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


def workload_interval(default: int) -> int:
    """Ciclo do gerador de carga: acelerado durante a simulação, normal fora."""
    phase, _, _ = _read_live_state()
    if phase == SimulationPhase.IDLE:
        return default
    return min(default, ACCELERATED_WORKLOAD_INTERVAL_SECONDS)


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


def _phase_backfill(db: Session) -> None:
    """
    Semeia o histórico que não dá para produzir ao vivo (uptime de 30 dias,
    semanas de backup, frota com idade) e guarda os pontos de restauração.
    """
    from src.seed import history

    instances = _demo_instances(db)
    state = db.query(DemoSimulation).with_for_update().first()
    if state is not None:
        restore = dict(state.restore_points or {})
        for inst in instances:
            restore.setdefault(str(inst.id), inst.created_at.isoformat())
        state.restore_points = restore
        state.has_simulated_data = True
        db.commit()

    history.enrich_fleet(db)
    log_event_atomic(
        SimulationPhase.BACKFILL,
        f"Seeded 24h of metrics, uptime and operational history for "
        f"{len(instances)} instances",
    )


def _phase_warmup(db: Session) -> None:
    log_event_atomic(
        SimulationPhase.WARMUP,
        "Traffic ramping up — connection pools follow an accelerated daily curve",
    )


def _phase_alert(db: Session) -> None:
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
        log_event_atomic(SimulationPhase.ALERT, "No running production instance to watch")
        return

    active = _latest_metric(db, target.id, "connections_active")
    max_conn = _latest_metric(db, target.id, "connections_max") or 100.0
    if active is None:
        log_event_atomic(
            SimulationPhase.ALERT, "No connection metric collected yet — rule skipped"
        )
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

    log_event_atomic(
        SimulationPhase.ALERT,
        f"Watching {target.name}: rule connections_ratio > {threshold}% "
        f"(measured {ratio:.1f}%) — the evaluator opens the event on its own",
    )


def _phase_backup(db: Session) -> None:
    """pg_dump de verdade na instância de produção de cada empresa."""
    from src.services import backup as backup_service

    done = 0
    for inst in _production_instances(db):
        try:
            record = backup_service.create_logical_backup(
                db, inst, backup_type=BackupType.MANUAL, retention_days=7
            )
            _audit(db, inst, "backup_created", "backup", str(record.id))
            done += 1
        except Exception as exc:  # noqa: BLE001 — uma falha não trava o roteiro
            logger.warning("Simulação: backup de %s falhou: %s", inst.name, exc)
            log_event_atomic(
                SimulationPhase.BACKUP, f"Backup of {inst.name} failed: {exc}"
            )
    log_event_atomic(
        SimulationPhase.BACKUP, f"{done} logical backup(s) written with pg_dump"
    )


def _phase_maintenance(db: Session) -> None:
    """
    Manutenção de verdade nas instâncias de produção.

    ANALYZE em todas e VACUUM só na primeira: sob a carga da simulação, um
    VACUUM por instância levava mais tempo que a fase inteira. Uma tarefa de
    cada tipo já mostra o recurso funcionando — que é o ponto da demo.
    """
    from src.services import maintenance as maintenance_service

    done = 0
    for index, inst in enumerate(_production_instances(db)):
        task_types = (TaskType.ANALYZE, TaskType.VACUUM) if index == 0 else (TaskType.ANALYZE,)
        for task_type in task_types:
            try:
                task = maintenance_service.run_task(
                    db, inst, MaintenanceTaskCreate(task_type=task_type)
                )
                _audit(db, inst, "maintenance_run", "maintenance", str(task.id))
                done += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Simulação: %s em %s falhou: %s", task_type, inst.name, exc)
    log_event_atomic(
        SimulationPhase.MAINTENANCE, f"{done} maintenance task(s) executed"
    )


def _phase_recover(db: Session) -> None:
    log_event_atomic(
        SimulationPhase.RECOVER,
        "Traffic falling back to baseline — open alerts resolve from real metrics",
    )


def _phase_steady(db: Session) -> None:
    log_event_atomic(
        SimulationPhase.STEADY,
        "Scripted run finished — the fleet keeps serving traffic until you stop it",
    )


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

    _dispatch_action(state.phase)
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
    # STEADY não é etapa: reporta o índice logo além da última, e a UI usa isso
    # (ou a própria fase) para desenhar a conclusão em vez de mais um passo.
    if not running:
        phase_index = -1
    elif state.phase in SCRIPT_PHASES:
        phase_index = SCRIPT_PHASES.index(state.phase)
    else:
        phase_index = len(SCRIPT_PHASES)
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
        "phase_count": len(SCRIPT_PHASES),
        "phase_progress": round(phase_progress, 3),
        "has_simulated_data": state.has_simulated_data,
        "speed_factor": state.speed_factor,
        "started_at": state.started_at,
        "events": list(state.events or []),
    }


# --------------------------------------------------------------------------- #
# Diretor
# --------------------------------------------------------------------------- #
def _execute_action(phase: SimulationPhase) -> None:
    """
    Roda a ação de uma fase numa sessão própria. Falha vira evento no log e o
    roteiro segue — uma demo nunca deve travar.
    """
    action = _PHASE_ACTIONS.get(phase)
    if action is None:
        return
    db = SessionLocal()
    try:
        action(db)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("Simulação: fase %s falhou: %s", phase, exc)
        log_event_atomic(phase, f"Phase failed: {exc}")
    finally:
        db.close()


def _dispatch_action(phase: SimulationPhase) -> None:
    """
    Dispara a ação FORA do tick do diretor.

    O relógio do roteiro precisa ser previsível: `pg_dump`, `VACUUM` e o backfill
    levam de segundos a mais de um minuto dependendo da máquina, e rodando dentro
    do tick eles esticavam a fase pelo próprio tempo de execução (a barra de
    progresso ficava parada e o roteiro dobrava de duração). Numa thread única
    dedicada, as fases avançam no horário e as ações continuam serializadas
    entre si.
    """
    _ACTION_EXECUTOR.submit(_execute_action, phase)


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
        logger.info(
            "Simulação: %s → %s (%.0fs na fase anterior)",
            state.phase.value,
            next_phase.value,
            (_now() - state.phase_started_at).total_seconds(),
        )
        state.phase = next_phase
        state.phase_started_at = _now()
        db.commit()
        _dispatch_action(next_phase)
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
