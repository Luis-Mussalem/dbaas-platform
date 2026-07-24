"""
Enriquecimento histórico da frota de demonstração.

O seed base (demo.py) cria empresas, usuários e instâncias — mas as telas de
Alertas, Backups, Manutenção e o KPI de uptime nascem vazias num clone limpo,
porque essas tabelas só se populam com o tempo (pollers/schedulers) ou com ação
manual. Este módulo preenche esse histórico de uma vez, de forma idempotente,
para o recrutador ver um produto "com quilometragem":

- **Métricas** — 24h de série sintética (a janela máxima dos gráficos é 24h),
  em TODAS as instâncias demo (containers reais inclusos: o poller ao vivo
  continua adicionando pontos por cima).
- **Uptime** — retroage `created_at` ~45 dias e semeia `instance_status_history`
  (RUNNING desde a criação, com um blip curto numa instância) para o KPI de
  30 dias exibir ~99.9% em vez de "—".
- **Alertas** — regras por instância + uma timeline de eventos resolvidos e
  poucos eventos abertos (para o dashboard mostrar alertas ativos reais).
- **Backups** — um schedule diário por prod + ~2 semanas de backups COMPLETED
  (tamanho crescente), 1 FAILED e 1 nas últimas 24h.
- **Manutenção** — um schedule semanal por prod + histórico de VACUUM/ANALYZE.
- **Audit log** — um fluxo de ações atribuídas aos usuários demo, para a
  atividade recente ter profundidade e o ator real (email@empresa) aparecer.

Tudo é dado mock plausível (nada sensível). Idempotente: cada instância é pulada
se já tiver regras de alerta, então religar o stack não duplica nada.
`clear()` no demo.py remove os recursos sem FK-cascade (backups, schedules e
audit logs demo).
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

# Quanto tempo a frota "existe": retroagimos created_at para além da janela de
# 30 dias do uptime, para o KPI cobrir os 30 dias inteiros.
_FLEET_AGE_DAYS = 45

# Instâncias (por nome) que ficam com 1 alerta ABERTO — o resto só tem histórico
# resolvido. Mantém o contador de "alertas ativos" pequeno e crível.
_OPEN_ALERT_INSTANCES = {"neptune-payments-prod", "saturn-store-staging"}

# Idade máxima do último backup antes de _refresh_backup_anchor reaproximá-lo.
# Folga sob as 24h da regra `backup_age_hours`: a frota nunca sobe já vencida,
# e o alerta continua livre para disparar se um backup real falhar.
_BACKUP_ANCHOR_MAX_AGE = timedelta(hours=20)

# Janela e resolução da série sintética. 24h é o maior intervalo que os
# gráficos oferecem; 5 min é a cadência que o poller usaria em repouso.
_BACKFILL_WINDOW = timedelta(hours=24)
_BACKFILL_STEP = timedelta(minutes=5)

# Idade a partir da qual consideramos a janela "já coberta" e não semeamos de
# novo. Um pouco menor que a janela, para o poller ao vivo (que grava a cada
# minuto) não passar por histórico — só passa quando a frota realmente
# acumulou quase 24h de medição, e aí o sintético é desnecessário mesmo.
_BACKFILL_COVERED_AFTER = _BACKFILL_WINDOW - timedelta(hours=1)

# Quanto o banco "cresceu" ao longo da janela, em fração do tamanho medido.
# Modesto de propósito: é o que o card mostra como crescimento em 24h.
_BACKFILL_GROWTH_RATIO = 0.02

# Distância entre os dois pontos do par de xact_commit ancorado no boot. Igual à
# cadência do poller, para o par parecer duas coletas normais e CABER na janela
# móvel do queries/s (que é relativa ao poll, ver fleet_summary). Definida em
# tempo de execução para acompanhar METRICS_POLL_INTERVAL_SECONDS.
def _xact_anchor_gap_seconds() -> int:
    from src.core.config import settings

    return settings.METRICS_POLL_INTERVAL_SECONDS

# Latência base quando a instância nunca reportou percentis (dados-apenas, sem
# pg_stat_statements) e quanto ela sobe do vale ao pico de carga.
_P95_FALLBACK_MS = 3.2
_P95_LOAD_SPREAD = 1.6

# Razão p50/p95 e p99/p95 usada para derivar os outros dois percentis quando a
# instância só reportou um deles. Valores típicos de uma carga OLTP: a mediana
# fica bem abaixo do p95 e o p99 estica a cauda.
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
    """Já existe algum registro deste tipo para a instância? (guarda de idempotência)"""
    return (
        db.query(model).filter(model.instance_id == instance.id).first() is not None
    )


def _rng(instance: DatabaseInstance) -> random.Random:
    """RNG determinístico por instância — variedade estável entre reboots."""
    return random.Random(f"demo-history::{instance.name}")


def _alert_message(rule: AlertRule, current_value: float) -> str:
    """Mesmo formato que services.alert._build_message grava nos eventos reais."""
    unit = _UNIT_BY_METRIC.get(rule.metric_type, "")
    return (
        f"[{rule.severity.value.upper()}] {rule.name}: "
        f"current={current_value:.2f}{unit}, "
        f"threshold={rule.condition.value} {rule.threshold}{unit}"
    )


# --------------------------------------------------------------------------- #
# Métricas (24h @ 5min) — a janela máxima dos gráficos é 24h
# --------------------------------------------------------------------------- #
def _earliest_measured(
    db: Session, instance: DatabaseInstance, metric_name: str
) -> float | None:
    """Valor da amostra REAL mais antiga de uma métrica — a âncora da emenda."""
    row = (
        db.query(Metric.value)
        .filter(Metric.instance_id == instance.id, Metric.metric_name == metric_name)
        .order_by(Metric.collected_at.asc())
        .first()
    )
    return row[0] if row else None


def _backfill_metrics(db: Session, instance: DatabaseInstance, idx: int) -> None:
    """
    Série sintética de 24h (um ponto a cada 5 min) para sparklines e gráficos.

    As conexões vêm da MESMA curva que o simulador de carga usa ao vivo
    (`workload_simulator.target_connections`), e na MESMA intensidade da
    carga-base (`workload_simulator.BASELINE_INTENSITY`). É isso que faz o histórico
    emendar com o presente: sem a curva a série mostraria um degrau; sem a
    intensidade-base, o histórico desenharia a curva CHEIA (~14 conexões) e a
    medição ao vivo em repouso (~5) cairia num degrau no ponto "agora". Semeia os
    percentis de latência (grandezas instantâneas, moduladas pela mesma curva)
    mas NÃO xact_commit: aquele é um contador cumulativo, e uma série sintética de
    24h produziria uma taxa falsa de queries/s exatamente na emenda com a medição
    real. O queries/s do card não fica em branco por isso: `_seed_xact_commit_anchor`
    semeia um par recente ANCORADO no contador real do container, o que dá a taxa
    de imediato sem inventar a série inteira.

    Guarda: pula só quando JÁ EXISTE medição cobrindo a janela. A guarda antiga
    ("existe qualquer métrica?") tornava o backfill inócuo na prática — o poller
    ao vivo grava uma linha por minuto, então bastava um intervalo de 60s entre
    o reset e o clique em "Simular uso" para a série de 24h nunca ser semeada e
    os gráficos ficarem com poucos minutos de dados.

    A série termina onde a medição real começa (não por cima dela) e é ANCORADA
    no valor medido nessa emenda: tamanho e cache hit partem do que a instância
    de fato reporta, em vez de uma fração arbitrária da capacidade — que, com o
    plano de 1 GB, desenhava um degrau e uma barra de storage acima de 100%.
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
        return  # a janela já tem histórico (semeado antes ou medido de verdade)

    # Onde a medição real começa: o sintético para aí, para não haver dois
    # pontos concorrentes no mesmo instante.
    oldest_live = (
        db.query(Metric.collected_at)
        .filter(Metric.instance_id == instance.id)
        .order_by(Metric.collected_at.asc())
        .first()
    )
    end = oldest_live[0] if oldest_live else now
    start = now - _BACKFILL_WINDOW

    # Âncoras: o valor medido na emenda. Sem medição (instância dados-apenas,
    # que nunca conecta), cai para números plausíveis do porte da instância.
    capacity = (instance.storage_gb or 20) * 1024 ** 3
    size_anchor = _earliest_measured(db, instance, "db_size_bytes") or capacity * 0.25
    cache_anchor = _earliest_measured(db, instance, "cache_hit_ratio") or (96 + idx * 0.7)
    max_conn = _earliest_measured(db, instance, "connections_max") or 100.0
    p95_anchor = _earliest_measured(db, instance, "p95_query_latency_ms") or _P95_FALLBACK_MS
    # p50 e p99 usam a própria medição quando existe; senão derivam do p95, para
    # os três percentis se moverem juntos em vez de virarem linhas independentes.
    p50_anchor = (
        _earliest_measured(db, instance, "p50_query_latency_ms")
        or p95_anchor * _P50_OF_P95
    )
    p99_anchor = (
        _earliest_measured(db, instance, "p99_query_latency_ms")
        or p95_anchor * _P99_OF_P95
    )

    # Faixa de conexões da instância — usada para converter a curva de tráfego em
    # um fator de carga em [0, 1], que é o que modula a latência.
    peak_conns = max(
        1,
        target_connections(
            instance.name, instance.environment, now.replace(hour=15, minute=0)
        ),
    )

    # Intensidade da carga-base: o histórico tem de bater com o que o gerador de
    # carga mede em repouso.
    from src.services.workload_simulator import BASELINE_INTENSITY

    rows: list[Metric] = []
    steps = int((end - start).total_seconds() // (_BACKFILL_STEP.total_seconds())) + 1
    if steps <= 1:
        return
    for k in range(steps):
        ts = start + _BACKFILL_STEP * k
        # progress ∈ [0, 1]: 0 no começo da janela, 1 na emenda com o real.
        progress = k / (steps - 1)
        conns = target_connections(
            instance.name, instance.environment, ts, intensity=BASELINE_INTENSITY
        )
        # O banco cresceu _BACKFILL_GROWTH_RATIO ao longo do dia até o valor medido.
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
        # Os percentis acompanham a carga: mais conexões concorrentes, fila
        # maior, cauda mais alta. Sem estas séries o gráfico de latência da tela
        # de detalhe nascia vazio, mesmo com o card já mostrando o p95 do
        # instante. O p99 abre mais que o p50 sob carga — é o que caracteriza
        # uma cauda, e o que uma linha só não mostraria.
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
    Semeia um par recente de `xact_commit` ancorado no contador REAL do container,
    para o queries/s do card aparecer já no primeiro render.

    Sem isto, o queries/s (Δcommits ÷ Δsegundos sobre os dois samples mais recentes)
    fica em "—" por até dois ciclos do poller (60s cada) num boot recém-aberto,
    porque o seed não semeia a série de xact_commit (ver `_backfill_metrics`). Numa
    demo clonada do GitHub, esse é o único número que nasce vazio — uma primeira
    impressão ruim para o recrutador que abre o projeto.

    Roda em TODO boot (como `_refresh_backup_anchor`, sem guarda de idempotência):
    o contador é cumulativo e o Postgres o zera ao reiniciar, então samples de um
    boot anterior ficariam MAIORES que o atual e o Δ derivaria negativo (descartado
    → "—"). Por isso apaga o histórico de xact_commit e regrava um par fresco — o
    contador não é plotado em nenhum gráfico (só alimenta o queries/s dos dois
    pontos mais recentes), então apagá-lo não perde nada visível.

    O par é datado com FOLGA no passado (`now-2*GAP`, `now-GAP`), nunca em `now`.
    O seed roda concorrente com o poller ao vivo (que grava xact_commit perto de
    `now`): se o par mais novo fosse em `now`, ele empataria/cruzaria com a coleta
    do poller e a série ficaria não-monotônica — um sample do poller com timestamp
    ligeiramente anterior mas valor maior derivaria Δ negativo. Datando no passado,
    TODA coleta viva é mais nova por timestamp e o par é só a ponte até ela chegar.

    Os dois pontos representam o contador COMO ELE ESTAVA no passado — recuados da
    taxa-base modelada (`target_queries_per_second`): `newer = current - taxa*GAP`,
    `older = current - taxa*2*GAP`. Não gravamos o valor atual: a primeira coleta
    do poller lê ~`current` no mesmo instante do boot, e se o par mais novo já fosse
    `current` o Δ contra ela sairia ~0 (queries/s "0"). Recuando o par, a leitura
    real (≥ current, mais nova) dá Δ ≈ taxa*GAP → a taxa-base viva. O par sozinho
    (antes da 1ª coleta) já rende a mesma taxa. Só instâncias com container.
    """
    if not instance.connection_uri:
        return

    # Import tardio: o seed é carregado no startup, antes de tudo estar de pé.
    from src.collectors.pg_stats import collect_base_metrics
    from src.services.metrics import get_connection

    try:
        with get_connection(instance) as conn:
            current = collect_base_metrics(conn).get("xact_commit")
    except Exception as exc:  # noqa: BLE001 — o boot não pode falhar por isto
        db.rollback()
        logger.warning("Seed demo: leitura de xact_commit em %s falhou: %s", instance.name, exc)
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
# Uptime — created_at retroagido + histórico de status
# --------------------------------------------------------------------------- #
def _backdate_status(db: Session, instance: DatabaseInstance, blip: bool) -> None:
    """
    Retroage created_at ~45 dias e grava o histórico de status para o uptime.

    RUNNING desde a criação. Se `blip`, insere um par STOPPED→RUNNING de ~25 min
    ~9 dias atrás — assim o uptime fica ~99.9x% (crível) em vez de 100% redondo.
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
# Alertas — regras + timeline de eventos
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

    # Timeline de eventos RESOLVIDOS (o problema veio e passou). Alguns por
    # instância, espalhados nas últimas semanas — dão histórico à página.
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

    # Evento ABERTO (resolved_at=NULL) só nas instâncias escolhidas — mantém o
    # contador de alertas ativos pequeno e realista.
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
# Backups — schedule + histórico
# --------------------------------------------------------------------------- #
def _seed_backup_schedule(
    db: Session, instance: DatabaseInstance, is_prod: bool
) -> None:
    """
    Agendamento diário de backup — em TODA instância, prod e staging.

    Staging também precisa do seu: a regra `backup_age_hours > 24` é semeada na
    frota inteira, então uma instância sem agendamento nunca ganha um backup
    novo e acumula um CRITICAL permanente assim que o marco semeado passa das
    24h. Difere de produção no horário (04:00, fora da janela de prod) e na
    retenção (3 dias em vez de 7), que é como uma frota real trata staging.
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
    # ~14 dias de backups diários agendados, COMPLETED, tamanho crescendo devagar.
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

    # Um FAILED no meio do caminho, para o histórico não parecer "bom demais".
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

    # Um backup manual FÍSICO recente (variedade de strategy/type na UI).
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

    # Garante ≥1 backup nas últimas 24h (para o KPI "backups nas últimas 24h").
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
    Reaproximar o backup COMPLETED mais recente de "agora", se envelheceu demais.

    Diferente do resto do seed, isto roda em TODO boot. O histórico de backup é
    semeado uma única vez, com o marco mais novo a 2–9h atrás; a frota demo,
    porém, passa a maior parte do tempo desligada e esse marco envelhece em tempo
    de parede. Ao subir depois de um dia parada, toda instância cruza o
    `backup_age_hours > 24` e o painel abre com CRITICAL em série — que fala do
    computador ter ficado desligado, não da plataforma.

    Mesma licença que já tomamos ao retroagir `created_at` e o histórico de
    status para dar 45 dias de idade à frota: a demo é declaradamente sintética
    (banner + página /demo). Backups REAIS — os que o scheduler acabou de rodar —
    já entram recentes e a guarda de idade os deixa em paz.
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
# Manutenção — schedule + histórico
# --------------------------------------------------------------------------- #
def _seed_maintenance(
    db: Session, instance: DatabaseInstance, is_prod: bool, table: str | None
) -> None:
    rng = _rng(instance)
    now = _now()

    if is_prod:
        # Domingo 03:00 → próxima ocorrência.
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
# Audit log — fluxo de ações dos usuários demo
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
            # `simulated: true` rotula honestamente esta entrada como dado de
            # demonstração semeado (não uma ação real de usuário).
            details={"method": method, "path": path, "status": 200, "simulated": True},
            ip_address="203.0.113.%d" % (7 + (hash(user.email) % 40) if user else 1),
            timestamp=ts,
        ))

    # Criação da frota (admin), no começo da vida da empresa.
    for inst in instances:
        add(admin, "instance_created", "instance", inst.id,
            "/api/v1/instances", "POST", days_ago=_FLEET_AGE_DAYS - 1)
        add(admin, "schedule_created", "backup_schedule", inst.id,
            f"/api/v1/instances/{inst.id}/schedules", "POST", days_ago=_FLEET_AGE_DAYS - 1)

    # Fluxo recente e crível: logins, backups manuais, manutenção, um restore.
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
# Orquestração
# --------------------------------------------------------------------------- #
def enrich_fleet(db: Session) -> None:
    """
    Semeia histórico (métricas, uptime, alertas, backups, manutenção, audit) para
    a frota demo. Idempotente: instância com regras de alerta já existentes é
    pulada; audit por empresa só é semeado se a empresa ainda não tem logs.
    """
    from src.seed.demo import COMPANIES, DEMO_MARKER  # lazy: evita import circular

    instances = (
        db.query(DatabaseInstance)
        .filter(DatabaseInstance.notes == DEMO_MARKER,
                DatabaseInstance.deleted_at.is_(None))
        .order_by(DatabaseInstance.name.asc())
        .all()
    )
    if not instances:
        return

    # Tabela alvo (para ANALYZE/REINDEX) por empresa, via config do demo: a
    # tabela-fato de negócio, que é a grande e a que faz sentido manutenir.
    table_by_company: dict[uuid.UUID, str] = {}
    for company_name, cfg in COMPANIES.items():
        comp = db.query(Company).filter(Company.name == company_name).first()
        if comp is not None:
            table_by_company[comp.id] = cfg["fact"]["name"]

    for idx, inst in enumerate(instances):
        is_prod = inst.environment == Environment.PRODUCTION
        blip = inst.name in _OPEN_ALERT_INSTANCES  # reaproveita: quem tem alerta aberto teve um blip
        logger.info("Seed demo: enriquecendo histórico de %s ...", inst.name)
        # Uma guarda POR RECURSO, não uma só para a instância inteira. Com a
        # guarda única ("tem regra de alerta?"), a fase ALERT da simulação —
        # que cria uma regra — passava a marcar a instância como enriquecida:
        # numa segunda execução nada mais era semeado, nem as métricas.
        _backfill_metrics(db, inst, idx)
        # Sem guarda: o contador zera a cada restart do Postgres, então o par é
        # regravado ancorado no valor atual em todo boot.
        _seed_xact_commit_anchor(db, inst)
        if not _has(db, InstanceStatusHistory, inst):
            _backdate_status(db, inst, blip=blip)
        if not _has(db, AlertRule, inst):
            _seed_alerts(db, inst, is_prod)
        if not _has(db, BackupSchedule, inst):
            _seed_backup_schedule(db, inst, is_prod)
        if not _has(db, Backup, inst):
            _seed_backups(db, inst, is_prod)
        # Sem guarda: o marco de backup envelhece em tempo de parede entre boots.
        _refresh_backup_anchor(db, inst)
        if not _has(db, MaintenanceTask, inst):
            _seed_maintenance(db, inst, is_prod, table_by_company.get(inst.company_id))

    # Audit por empresa (uma vez, se ainda vazia).
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

    logger.info("Seed demo: histórico da frota concluído.")


def reseed_metrics(db: Session) -> int:
    """
    Apaga e regenera as 24h de métricas sintéticas da frota demo.

    Existe para consertar um histórico gerado por uma versão anterior da curva
    (o caso concreto: séries semeadas na casa das dezenas de conexões contra
    uma frota ociosa medindo 1, o que desenhava um degrau no sparkline).
    Diferente de `enrich_fleet`, não é idempotente por definição — sempre
    substitui. Só mexe em métricas; alertas, backups e audit ficam intactos.

        python -m src.seed.history --reseed-metrics
    """
    from src.seed.demo import DEMO_MARKER  # lazy: evita import circular

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
        logger.info("Seed demo: métricas de %s regeneradas.", inst.name)
    return len(instances)


if __name__ == "__main__":
    import sys

    from src.core.database import SessionLocal

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if "--reseed-metrics" not in sys.argv:
        print("uso: python -m src.seed.history --reseed-metrics")
        raise SystemExit(2)
    session = SessionLocal()
    try:
        n = reseed_metrics(session)
        print(f"Métricas regeneradas para {n} instância(s) demo.")
    finally:
        session.close()
