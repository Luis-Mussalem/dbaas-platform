"""
Agregado por instância para os cards da frota.

Os cards mostravam só o que o poller guarda como último valor bruto (conexões,
cache hit, tamanho). Numa frota pequena o cache hit é sempre ~100% e a barra de
storage sempre 0%, então três gauges ficavam constantes e o card não dizia nada
sobre o estado da instância.

Este módulo devolve, numa única resposta, o que já existe espalhado por
alerts/backups/metrics/status_history: throughput, latência, crescimento de
disco, alertas abertos, último backup e uptime. É um agregado de LEITURA — o
custo de N+1 requests (um card = 5 endpoints × 6 cards) é o que ele evita.

Os helpers por instância (`queries_per_second_by_instance`,
`latest_metric_by_instance`) também alimentam os KPIs de frota em
`services/admin.py`, que antes tinham a mesma janela SQL duplicada.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.alert import AlertEvent, AlertRule, AlertSeverity
from src.models.backup import Backup, BackupStatus
from src.models.database_instance import DatabaseInstance
from src.models.metric import Metric
from src.schemas.instance import InstanceSummary
from src.services import metrics as metrics_service
from src.services import status_history

# O NÚMERO de queries/s do card é a MÉDIA da mesma série que o sparkline desenha —
# não um cálculo à parte. O card pede get_metric_history("queries_per_second",
# "15m", 60 baldes) (InstanceCard.tsx); derivamos a MESMA série aqui e tiramos a
# média dos pontos. Assim o número é, por construção, a média da linha: ela oscila
# em torno dele e gráfico e número contam uma história só. A robustez a leituras
# stale e a resets do contador vive no _counter_rate (services.metrics), que os
# dois caminhos compartilham. Estes dois valores TÊM de casar com os do card.
_QPS_SERIES_MINUTES = 15
_QPS_SERIES_POINTS = 60

# Ordem de gravidade, para o card destacar o pior alerta aberto.
_SEVERITY_RANK = {
    AlertSeverity.INFO: 0,
    AlertSeverity.WARNING: 1,
    AlertSeverity.CRITICAL: 2,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Métricas (janela sobre a tabela metrics)
# --------------------------------------------------------------------------- #
def _latest_samples(
    db: Session,
    instance_ids: list[uuid.UUID],
    metric_name: str,
    limit: int,
) -> dict[uuid.UUID, list[tuple[float, datetime]]]:
    """
    Os `limit` pontos mais recentes de uma métrica, por instância (mais novo
    primeiro). Uma window function em vez de N queries: a frota inteira sai
    numa ida ao banco.
    """
    if not instance_ids:
        return {}

    rn = func.row_number().over(
        partition_by=Metric.instance_id,
        order_by=Metric.collected_at.desc(),
    ).label("rn")
    subq = (
        db.query(Metric.instance_id, Metric.value, Metric.collected_at, rn)
        .filter(
            Metric.instance_id.in_(instance_ids),
            Metric.metric_name == metric_name,
        )
        .subquery()
    )
    rows = (
        db.query(subq.c.instance_id, subq.c.value, subq.c.collected_at)
        .filter(subq.c.rn <= limit)
        .order_by(subq.c.instance_id, subq.c.rn)
        .all()
    )

    by_instance: dict[uuid.UUID, list[tuple[float, datetime]]] = {}
    for instance_id, value, collected_at in rows:
        by_instance.setdefault(instance_id, []).append((value, collected_at))
    return by_instance


def latest_metric_by_instance(
    db: Session, instance_ids: list[uuid.UUID], metric_name: str
) -> dict[uuid.UUID, float]:
    """Último valor de uma métrica por instância (ausente = sem coleta ainda)."""
    return {
        instance_id: samples[0][0]
        for instance_id, samples in _latest_samples(db, instance_ids, metric_name, 1).items()
    }


def queries_per_second_by_instance(
    db: Session, instance_ids: list[uuid.UUID]
) -> dict[uuid.UUID, float]:
    """
    Taxa de commits por instância = MÉDIA da série de queries/s que o card desenha
    no sparkline. Deriva a MESMA série que o gráfico (get_metric_history sobre o
    contador xact_commit, mesma janela e baldes) e devolve a média dos pontos.

    Por que a média da série, e não um cálculo próprio: o número e o gráfico têm
    de bater. Enquanto o número saía de uma janela/derivação diferente (era a média
    das últimas ~5 amostras cruas), ele nunca coincidia com a linha ao lado. Sendo
    a média EXATA da série desenhada, a linha oscila em torno do número e os dois
    contam uma história só.

    Ausente (série vazia) quando não há dado para uma taxa — o card mostra "—" em
    vez de um zero inventado. A robustez a leituras stale e a resets do contador
    está no _counter_rate (services.metrics), que produz a série.
    """
    result: dict[uuid.UUID, float] = {}
    for instance_id in instance_ids:
        series = metrics_service.get_metric_history(
            db,
            instance_id,
            "queries_per_second",
            _QPS_SERIES_MINUTES,
            max_points=_QPS_SERIES_POINTS,
        )
        if not series:
            continue
        result[instance_id] = round(sum(value for _, value in series) / len(series), 2)
    return result


def _size_delta_24h(
    db: Session, instance_ids: list[uuid.UUID], latest_size: dict[uuid.UUID, float]
) -> dict[uuid.UUID, float]:
    """
    Crescimento do banco nas últimas 24h: tamanho atual menos o mais antigo
    dentro da janela. É o número que mostra que a carga simulada escreve de
    verdade — a barra de storage sozinha mal se move em 24h.
    """
    if not instance_ids:
        return {}

    since = _now() - timedelta(hours=24)
    rn = func.row_number().over(
        partition_by=Metric.instance_id,
        order_by=Metric.collected_at.asc(),
    ).label("rn")
    subq = (
        db.query(Metric.instance_id, Metric.value, rn)
        .filter(
            Metric.instance_id.in_(instance_ids),
            Metric.metric_name == "db_size_bytes",
            Metric.collected_at >= since,
        )
        .subquery()
    )
    oldest = {
        instance_id: value
        for instance_id, value in db.query(subq.c.instance_id, subq.c.value)
        .filter(subq.c.rn == 1)
        .all()
    }
    return {
        instance_id: current - oldest[instance_id]
        for instance_id, current in latest_size.items()
        if instance_id in oldest
    }


# --------------------------------------------------------------------------- #
# Alertas, backups e uptime
# --------------------------------------------------------------------------- #
def _open_alerts(
    db: Session, instance_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, AlertSeverity]]:
    """
    Alertas abertos (resolved_at NULL) por instância: quantidade e pior severidade.

    A severidade é atributo da REGRA, não do evento — daí o join.
    """
    if not instance_ids:
        return {}

    rows = (
        db.query(AlertRule.severity, AlertEvent.instance_id, func.count(AlertEvent.id))
        .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
        .filter(
            AlertEvent.instance_id.in_(instance_ids),
            AlertEvent.resolved_at.is_(None),
        )
        .group_by(AlertEvent.instance_id, AlertRule.severity)
        .all()
    )

    result: dict[uuid.UUID, tuple[int, AlertSeverity]] = {}
    for severity, instance_id, count in rows:
        total, worst = result.get(instance_id, (0, AlertSeverity.INFO))
        if _SEVERITY_RANK[severity] > _SEVERITY_RANK[worst]:
            worst = severity
        result[instance_id] = (total + count, worst)
    return result


def _last_backup(
    db: Session, instance_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[datetime, BackupStatus]]:
    """
    Último backup não-deletado por instância (data + status). Inclui os que
    falharam de propósito: um card que esconde a falha é pior que nenhum card.
    """
    if not instance_ids:
        return {}

    rn = func.row_number().over(
        partition_by=Backup.instance_id,
        order_by=Backup.created_at.desc(),
    ).label("rn")
    subq = (
        db.query(Backup.instance_id, Backup.created_at, Backup.status, rn)
        .filter(
            Backup.instance_id.in_(instance_ids),
            Backup.status != BackupStatus.DELETED,
        )
        .subquery()
    )
    return {
        instance_id: (created_at, status)
        for instance_id, created_at, status in db.query(
            subq.c.instance_id, subq.c.created_at, subq.c.status
        )
        .filter(subq.c.rn == 1)
        .all()
    }


# --------------------------------------------------------------------------- #
# Agregado
# --------------------------------------------------------------------------- #
def get_fleet_summary(
    db: Session, instances: list[DatabaseInstance]
) -> list[InstanceSummary]:
    """Um resumo por instância recebida (já filtrada por escopo pelo router)."""
    instance_ids = [inst.id for inst in instances]

    qps = queries_per_second_by_instance(db, instance_ids)
    p95 = latest_metric_by_instance(db, instance_ids, "p95_query_latency_ms")
    conns = latest_metric_by_instance(db, instance_ids, "connections_active")
    conns_max = latest_metric_by_instance(db, instance_ids, "connections_max")
    size = latest_metric_by_instance(db, instance_ids, "db_size_bytes")
    growth = _size_delta_24h(db, instance_ids, size)
    alerts = _open_alerts(db, instance_ids)
    backups = _last_backup(db, instance_ids)
    uptime = status_history.get_uptime_pct_by_instance(db, instances)

    summaries = []
    for inst in instances:
        open_count, worst = alerts.get(inst.id, (0, None))
        last_backup = backups.get(inst.id)
        summaries.append(
            InstanceSummary(
                instance_id=inst.id,
                connections_active=conns.get(inst.id),
                connections_max=conns_max.get(inst.id),
                queries_per_second=qps.get(inst.id),
                p95_latency_ms=p95.get(inst.id),
                db_size_bytes=size.get(inst.id),
                size_delta_24h_bytes=growth.get(inst.id),
                open_alerts=open_count,
                max_alert_severity=worst,
                last_backup_at=last_backup[0] if last_backup else None,
                last_backup_status=last_backup[1] if last_backup else None,
                uptime_30d_pct=uptime.get(inst.id),
            )
        )
    return summaries
