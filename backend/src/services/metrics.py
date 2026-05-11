import logging
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

import psycopg
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.collectors.pg_stats import (
    collect_base_metrics,
    collect_bloat,
    collect_explain,
    collect_index_stats,
    collect_locks,
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
    with psycopg.connect(uri, connect_timeout=5) as conn:
        yield conn


def collect_and_store(db: Session, instance: DatabaseInstance) -> int:
    """
    Coletar métricas base da instância e persistir na tabela metrics.

    Chamado pelo metrics_poller a cada 60s para instâncias RUNNING.
    O timestamp 'collected_at' é gerado em Python para garantir que
    todos os registros de um mesmo ciclo tenham exatamente o mesmo valor,
    facilitando a query "métricas coletadas juntas no último ciclo".

    Retorna o número de métricas persistidas.
    """
    with get_connection(instance) as conn:
        raw = collect_base_metrics(conn)

    if not raw:
        return 0

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
