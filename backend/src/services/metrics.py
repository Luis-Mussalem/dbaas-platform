import logging
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Generator

import psycopg
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.collectors.pg_stats import (
    collect_active_connections,
    collect_base_metrics,
    collect_bloat,
    collect_explain,
    collect_index_stats,
    collect_locks,
    collect_latency_percentiles,
    collect_schema,
    collect_slow_queries,
)
from src.core.encryption import decrypt_value
from src.models.database_instance import DatabaseInstance
from src.models.metric import Metric

logger = logging.getLogger(__name__)


@contextmanager
def get_connection(
    instance: DatabaseInstance,
) -> Generator[psycopg.Connection, None, None]:
    """
    Context manager que decripta a URI de conexão e abre uma conexão psycopg
    com o banco da instância gerenciada.

    A URI decriptada existe apenas dentro deste bloco 'with'. Ao sair do
    context manager — por sucesso ou exceção — a variável 'uri' é coletada
    pelo GC. Ela nunca é logada, nunca vai para o banco da plataforma,
    nunca aparece em stack traces.
    """
    uri = decrypt_value(instance.connection_uri)
    # statement_timeout limita qualquer query nesta conexão (30s). Cobre as
    # leituras de monitoramento — em especial EXPLAIN ANALYZE, que executa a
    # query de verdade: sem o cap, um `SELECT pg_sleep(...)` seguraria o worker
    # do thread pool indefinidamente. A conexão de manutenção (VACUUM/REINDEX)
    # NÃO usa este helper de propósito — essas operações podem ser longas.
    with psycopg.connect(
        uri,
        connect_timeout=5,
        options="-c statement_timeout=30000",
    ) as conn:
        yield conn


def _latest_values(
    db: Session,
    instance_id: uuid.UUID,
    names: tuple[str, ...],
) -> dict[str, float]:
    """Último valor de cada métrica em `names` (as ausentes ficam de fora)."""
    subq = (
        db.query(
            Metric.metric_name,
            func.max(Metric.collected_at).label("max_collected_at"),
        )
        .filter(Metric.instance_id == instance_id, Metric.metric_name.in_(names))
        .group_by(Metric.metric_name)
        .subquery()
    )
    rows = (
        db.query(Metric.metric_name, Metric.value)
        .join(
            subq,
            (Metric.metric_name == subq.c.metric_name)
            & (Metric.collected_at == subq.c.max_collected_at),
        )
        .filter(Metric.instance_id == instance_id)
        .all()
    )
    return {name: value for name, value in rows}


def _interval_cache_hit_ratio(
    db: Session,
    instance_id: uuid.UUID,
    blks_hit: float,
    blks_read: float,
) -> float | None:
    """
    Cache hit ratio do INTERVALO entre esta coleta e a anterior, em %.

    O pg_stat_database só expõe contadores acumulados; a razão sobre eles mede a
    vida inteira do servidor e não o presente. Um banco que passou o dia a 99%
    continuaria reportando ~99% durante uma hora inteira de leituras em disco —
    e, pior, um restart zera os contadores e a razão desaba para perto de 0%
    ainda que o banco esteja saudável. Derivar do delta responde à pergunta que
    o alerta faz de fato: "e agora, está lendo do cache?".

    Retorna None quando o intervalo não permite uma resposta honesta:
    - sem coleta anterior (primeira da instância) → não há delta;
    - contador andou para trás → servidor reiniciou e zerou as estatísticas;
    - nenhum bloco lido no intervalo → banco ocioso, razão indefinida.

    Nos dois últimos casos devolve o valor anterior, se houver: um ciclo de
    dado repetido é melhor que um falso "0%" que abriria alerta sozinho.
    """
    prev = _latest_values(db, instance_id, ("blks_hit", "blks_read", "cache_hit_ratio"))
    prev_hit = prev.get("blks_hit")
    prev_read = prev.get("blks_read")
    carry = prev.get("cache_hit_ratio")

    if prev_hit is None or prev_read is None:
        return None

    if blks_hit < prev_hit or blks_read < prev_read:
        return carry

    delta_total = (blks_hit - prev_hit) + (blks_read - prev_read)
    if delta_total <= 0:
        return carry

    return round((blks_hit - prev_hit) / delta_total * 100.0, 2)


def collect_and_store(db: Session, instance: DatabaseInstance) -> int:
    """
    Coletar métricas base da instância e persistir na tabela metrics.

    Chamado pelo metrics_poller a cada 60s para instâncias RUNNING.
    O timestamp 'collected_at' é gerado em Python para garantir que
    todos os registros de um mesmo ciclo tenham exatamente o mesmo valor,
    facilitando a query "métricas coletadas juntas no último ciclo".

    Retorna o número de métricas persistidas.
    """
    # Uma única conexão coleta as métricas base E os percentis de latência
    # (evita abrir duas conexões por ciclo). Os percentis vêm do
    # pg_stat_statements e degradam para {} em instâncias sem a extensão.
    with get_connection(instance) as conn:
        raw = collect_base_metrics(conn)
        percentiles = collect_latency_percentiles(conn)

    if not raw:
        return 0

    # Precisa rodar ANTES do insert: a razão sai do delta contra a coleta anterior,
    # que deixaria de ser "a anterior" assim que estas linhas entrassem.
    if "blks_hit" in raw and "blks_read" in raw:
        ratio = _interval_cache_hit_ratio(
            db, instance.id, raw["blks_hit"], raw["blks_read"]
        )
        if ratio is None:
            raw.pop("cache_hit_ratio", None)
        else:
            raw["cache_hit_ratio"] = ratio

    now = datetime.now(timezone.utc)
    metrics = [
        Metric(
            instance_id=instance.id,
            metric_name=name,
            value=value,
            collected_at=now,
        )
        for name, value in raw.items()
    ]
    metrics.extend(
        Metric(
            instance_id=instance.id,
            metric_name=name,
            value=value,
            collected_at=now,
        )
        for name, value in percentiles.items()
    )

    db.add_all(metrics)
    db.commit()
    return len(metrics)


def get_latest_metrics(
    db: Session,
    instance_id: uuid.UUID,
) -> dict[str, float]:
    """
    Retornar o valor mais recente de cada métrica para a instância.

    Subquery encontra MAX(collected_at) por metric_name, depois join
    busca os values correspondentes. O índice composto
    (instance_id, metric_name, collected_at) garante index scan.

    Retorna {} se nenhuma métrica foi coletada ainda.
    """
    subq = (
        db.query(
            Metric.metric_name,
            func.max(Metric.collected_at).label("max_collected_at"),
        )
        .filter(Metric.instance_id == instance_id)
        .group_by(Metric.metric_name)
        .subquery()
    )

    rows = (
        db.query(Metric.metric_name, Metric.value)
        .join(
            subq,
            (Metric.metric_name == subq.c.metric_name)
            & (Metric.collected_at == subq.c.max_collected_at),
        )
        .filter(Metric.instance_id == instance_id)
        .all()
    )

    return {name: value for name, value in rows}


# Pontos devolvidos por get_metric_history. A série é reamostrada para este
# teto: um sparkline de ~500px não representa mais que isso, e o gráfico fica
# refém da cadência de coleta — que varia (60s normal, 5s durante a simulação
# de uso). Com bucket fixo, a MESMA janela desenha a mesma forma sempre.
_HISTORY_MAX_POINTS = 120


# Métricas "virtuais" que não são armazenadas cruas: são derivadas de um contador
# cumulativo já coletado. queries_per_second vem da derivada de xact_commit — o
# mesmo contador que alimenta o número do card (services.fleet_summary), agora
# exposto como série para o gráfico.
_DERIVED_RATE_SOURCE = {"queries_per_second": "xact_commit"}


def _bucketed_avg(
    db: Session,
    instance_id: uuid.UUID,
    metric_name: str,
    since: datetime,
    bucket_seconds: int,
) -> list[tuple[datetime, float]]:
    """Série de UMA métrica, reamostrada em baldes de `bucket_seconds` (média por balde)."""
    # floor(epoch / bucket) * bucket → início do balde; média dentro dele.
    bucket_start = func.to_timestamp(
        func.floor(func.extract("epoch", Metric.collected_at) / bucket_seconds)
        * bucket_seconds
    ).label("bucket_start")

    rows = (
        db.query(bucket_start, func.avg(Metric.value).label("value"))
        .filter(
            Metric.instance_id == instance_id,
            Metric.metric_name == metric_name,
            Metric.collected_at >= since,
        )
        .group_by(bucket_start)
        .order_by(bucket_start.asc())
        .all()
    )
    return [(row.bucket_start, float(row.value)) for row in rows]


# Abaixo desta fração do valor "limpo", uma queda do contador é um RESET real
# (restart do Postgres), não uma leitura stale do pg_stat_database. Mesma regra do
# fleet_summary, para o gráfico e o número tratarem os mesmos dados igual.
_RATE_RESET_FRACTION = 0.5


def _counter_rate(buckets: list[tuple[datetime, float]]) -> list[tuple[datetime, float]]:
    """
    Deriva uma taxa (por segundo) de um contador cumulativo já bucketizado:
    Δcontador / Δsegundos entre baldes consecutivos, datado no balde mais novo.

    O contador é NÃO-DECRESCENTE, mas o pg_stat_database às vezes devolve uma
    leitura STALE (snapshot antigo) que faz um balde "mergulhar" de leve. Esse
    ponto é PULADO (não emite 0 nem pico): mantemos o último valor limpo e o
    próximo balde real mede o crescimento sobre o intervalo maior — a linha
    interpola o buraco e fica suave, sem o dente-de-serra que o card mostrava. Uma
    queda GRANDE (< _RATE_RESET_FRACTION) é um reset de verdade: reancora e segue.
    """
    series: list[tuple[datetime, float]] = []
    if not buckets:
        return series
    prev_t, clean = buckets[0]
    for t_cur, v_cur in buckets[1:]:
        if v_cur >= clean:  # crescimento real
            dt = (t_cur - prev_t).total_seconds()
            if dt > 0:
                series.append((t_cur, round((v_cur - clean) / dt, 2)))
            prev_t, clean = t_cur, v_cur
        elif v_cur < clean * _RATE_RESET_FRACTION:  # reset do contador: reancora
            prev_t, clean = t_cur, v_cur
        # senão: leitura stale (mergulho pequeno) → pula o ponto, mantém clean/prev_t
    return series


# Uma taxa derivada de contador é intrinsecamente ruidosa em baldes curtos: uma
# carga em rajadas medida em 15s salta muito de um balde para o outro (um balde
# pega a rajada, o vizinho pega o vale). Apresentamos SEMPRE a média corrida da
# última ~1 min, então cada ponto é a média dos baldes que cobrem 60s. A linha
# ainda avança a cada balde (segue responsiva, sem virar 1 ponto/min) mas sem o
# serrilhado. Em janelas onde o balde já é ≥ 60s isto vira no-op (janela de 1
# ponto). Vale para o GRÁFICO e para o NÚMERO (services.fleet_summary tira a média
# DESTA série), então os dois seguem contando a mesma história.
_RATE_SMOOTHING_SECONDS = 60


def _trailing_mean(
    series: list[tuple[datetime, float]], window: int
) -> list[tuple[datetime, float]]:
    """
    Média móvel corrida de `window` pontos, datada no ponto mais novo de cada
    janela. A janela encolhe no começo da série (o 1º ponto é ele mesmo), então
    nenhum ponto é descartado — o sparkline mantém a mesma contagem de pontos.
    """
    if window <= 1 or len(series) < 2:
        return series
    values = [value for _, value in series]
    smoothed: list[tuple[datetime, float]] = []
    for i, (t_cur, _) in enumerate(series):
        chunk = values[max(0, i - window + 1) : i + 1]
        smoothed.append((t_cur, round(sum(chunk) / len(chunk), 2)))
    return smoothed


def get_metric_history(
    db: Session,
    instance_id: uuid.UUID,
    metric_name: str,
    minutes: int,
    max_points: int = _HISTORY_MAX_POINTS,
) -> list[tuple[datetime, float]]:
    """
    Retorna a série temporal de UMA métrica na janela [agora - minutes, agora],
    reamostrada em até _HISTORY_MAX_POINTS baldes com a MÉDIA de cada um.

    Lê da tabela metrics (banco da plataforma) — não conecta ao banco monitorado.
    A média por balde é o que dá a curva suave: sem ela, uma janela de 24h com
    coleta de 5s traria ~17 mil pontos e o sparkline viraria uma serra (foi
    exatamente o que aconteceu quando a simulação acelerou o poller). Agregar no
    banco também evita trafegar milhares de pontos para desenhar 500 pixels.

    O balde é derivado da janela (24h ÷ 120 = 12 min), então a resolução é
    estável independentemente de quantas amostras existirem dentro dele.

    `queries_per_second` é uma métrica DERIVADA: não é armazenada crua, então a
    série sai da derivada do contador `xact_commit` (ver _DERIVED_RATE_SOURCE) e
    passa por uma média móvel de ~1 min (ver _trailing_mean) — a taxa de uma carga
    em rajadas é ruidosa demais em baldes de 15s.
    """
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    bucket_seconds = max(1, (minutes * 60) // max(1, max_points))

    source = _DERIVED_RATE_SOURCE.get(metric_name)
    if source is not None:
        rate = _counter_rate(_bucketed_avg(db, instance_id, source, since, bucket_seconds))
        smoothing = max(1, round(_RATE_SMOOTHING_SECONDS / bucket_seconds))
        return _trailing_mean(rate, smoothing)

    return _bucketed_avg(db, instance_id, metric_name, since, bucket_seconds)


def check_health(instance: DatabaseInstance) -> dict:
    """
    Verificar conectividade e responsividade do banco com SELECT 1 cronometrado.

    response_time_ms inclui: TCP handshake, autenticação PostgreSQL,
    execução do SELECT 1 e retorno — latência end-to-end real.
    Retorna 'unhealthy' em qualquer exceção, sem levantar 5xx.
    """
    uri = decrypt_value(instance.connection_uri)
    start = time.monotonic()
    try:
        with psycopg.connect(uri, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        response_time_ms = (time.monotonic() - start) * 1000
        return {
            "status": "healthy",
            "response_time_ms": round(response_time_ms, 2),
            "checked_at": datetime.now(timezone.utc),
        }
    except Exception as exc:
        response_time_ms = (time.monotonic() - start) * 1000
        logger.warning(
            "Health check falhou para instância %s: %s", instance.id, exc
        )
        return {
            "status": "unhealthy",
            "response_time_ms": round(response_time_ms, 2),
            "checked_at": datetime.now(timezone.utc),
        }


def get_slow_queries(
    instance: DatabaseInstance,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Retornar queries lentas via pg_stat_statements."""
    with get_connection(instance) as conn:
        return collect_slow_queries(conn, limit=limit)


def get_index_stats(instance: DatabaseInstance) -> list[dict[str, Any]]:
    """Retornar estatísticas de índices via pg_stat_user_indexes."""
    with get_connection(instance) as conn:
        return collect_index_stats(conn)


def get_locks(instance: DatabaseInstance) -> list[dict[str, Any]]:
    """Retornar locks ativos em tabelas via pg_locks."""
    with get_connection(instance) as conn:
        return collect_locks(conn)


def get_bloat(instance: DatabaseInstance) -> list[dict[str, Any]]:
    """Retornar estimativa de bloat por tabela via pg_stat_user_tables."""
    with get_connection(instance) as conn:
        return collect_bloat(conn)


def get_explain(instance: DatabaseInstance, query: str) -> list:
    """Executar EXPLAIN ANALYZE para uma query SELECT."""
    with get_connection(instance) as conn:
        return collect_explain(conn, query)


def get_active_connections(
    instance: DatabaseInstance,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Listar conexões ativas via pg_stat_activity."""
    with get_connection(instance) as conn:
        return collect_active_connections(conn, limit=limit)


def get_schema(instance: DatabaseInstance) -> list[dict[str, Any]]:
    """
    Retornar as tabelas agrupadas por schema (com estimativa de linhas).

    Agrupa as linhas planas do coletor em [{name, tables:[{table, estimated_rows}]}],
    preservando a ordem (schema, tabela) já garantida pela query.
    """
    with get_connection(instance) as conn:
        rows = collect_schema(conn)

    groups: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row["schema_name"]
        group = by_name.get(name)
        if group is None:
            group = {"name": name, "tables": []}
            by_name[name] = group
            groups.append(group)
        group["tables"].append(
            {"table": row["table"], "estimated_rows": row["estimated_rows"]}
        )
    return groups
