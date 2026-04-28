import logging
from typing import Any

import psycopg
import psycopg.rows
from psycopg import sql as psql

logger = logging.getLogger(__name__)


def collect_base_metrics(conn: psycopg.Connection) -> dict[str, float]:
    """
    Coletar métricas escalares do banco via pg_stat_database e pg_settings.

    Métricas coletadas:
    - connections_active: conexões abertas agora neste banco
    - connections_max: limite total do servidor (max_connections)
    - cache_hit_ratio: % de blocos lidos do cache vs. disco (meta: > 95%)
    - db_size_bytes: tamanho total do banco em bytes
    - tup_inserted/updated/deleted/fetched: volume de operações DML
    - xact_commit/rollback: transações commitadas e abortadas
    """
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute("""
            SELECT
                d.numbackends AS connections_active,
                (
                    SELECT setting::int
                    FROM pg_settings
                    WHERE name = 'max_connections'
                ) AS connections_max,
                CASE
                    WHEN (d.blks_hit + d.blks_read) > 0
                    THEN round(
                        (d.blks_hit::numeric / (d.blks_hit + d.blks_read)) * 100,
                        2
                    )
                    ELSE 0
                END AS cache_hit_ratio,
                pg_database_size(d.datname) AS db_size_bytes,
                d.tup_inserted,
                d.tup_updated,
                d.tup_deleted,
                d.tup_fetched,
                d.xact_commit,
                d.xact_rollback
            FROM pg_stat_database d
            WHERE d.datname = current_database()
        """)
        row = cur.fetchone()
        if not row:
            return {}

        return {k: float(v) if v is not None else 0.0 for k, v in row.items()}


def collect_slow_queries(
    conn: psycopg.Connection,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Retornar as queries mais lentas via pg_stat_statements.

    Requer a extensão pg_stat_statements instalada no banco da instância.
    Em instâncias sem a extensão (provisionadas antes do Passo 1 da FASE 4),
    retorna lista vazia com log de aviso em vez de levantar exceção.

    Ordenadas por total_exec_time DESC — queries com maior impacto acumulado
    de CPU são mais relevantes para otimização que queries lentas unitárias raras.
    """
    try:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                psql.SQL("""
                    SELECT
                        query,
                        calls,
                        round(total_exec_time::numeric, 2) AS total_exec_time_ms,
                        round(mean_exec_time::numeric, 2)  AS mean_exec_time_ms,
                        rows,
                        CASE
                            WHEN (shared_blks_hit + shared_blks_read) > 0
                            THEN round(
                                (shared_blks_hit::numeric /
                                 (shared_blks_hit + shared_blks_read)) * 100,
                                2
                            )
                            ELSE 0
                        END AS cache_hit_ratio
                    FROM pg_stat_statements
                    ORDER BY total_exec_time DESC
                    LIMIT {}
                """).format(psql.Literal(limit))
            )
            return cur.fetchall()
    except Exception as exc:
        logger.warning(
            "pg_stat_statements não disponível nesta instância: %s", exc
        )
        return []


def collect_index_stats(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """
    Retornar estatísticas de uso de índices via pg_stat_user_indexes.

    unused=True (idx_scan == 0) indica índice nunca utilizado — candidato a DROP.
    Índices desnecessários aumentam tempo de escrita e consomem espaço em disco.
    """
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute("""
            SELECT
                s.schemaname                   AS schema_name,
                s.relname                      AS "table",
                s.indexrelname                 AS "index",
                s.idx_scan                     AS scans,
                s.idx_tup_read                 AS tup_read,
                s.idx_tup_fetch                AS tup_fetch,
                pg_relation_size(s.indexrelid) AS size_bytes,
                (s.idx_scan = 0)               AS unused
            FROM pg_stat_user_indexes s
            ORDER BY s.idx_scan ASC, size_bytes DESC
        """)
        return cur.fetchall()


def collect_locks(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """
    Retornar locks ativos em relações (tabelas) via pg_locks.

    granted=False indica query bloqueada aguardando lock ser liberado.
    Múltiplos False podem indicar deadlock iminente.
    Filtro locktype='relation' exibe apenas contenção em tabelas (relevante
    para o operador), excluindo locks internos do PostgreSQL (page, tuple, etc.).
    """
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute("""
            SELECT
                l.pid,
                c.relname AS "table",
                l.mode,
                l.granted,
                l.locktype
            FROM pg_locks l
            LEFT JOIN pg_class c ON c.oid = l.relation
            WHERE l.locktype = 'relation'
            ORDER BY l.granted, l.pid
        """)
        return cur.fetchall()


def collect_bloat(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """
    Estimar bloat de tabelas via pg_stat_user_tables.

    dead_ratio > 20% indica que o VACUUM está atrasado ou desabilitado.
    A FASE 6 (Manutenção Automatizada) usará este dado para disparar
    VACUUM automaticamente quando dead_ratio exceder o threshold.

    Usa contadores acumulados (leve, sem lock) — suficiente para detecção
    de tendências sem impacto na performance do banco monitorado.
    """
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute("""
            SELECT
                schemaname AS schema_name,
                relname    AS "table",
                n_live_tup AS live_rows,
                n_dead_tup AS dead_rows,
                CASE
                    WHEN (n_live_tup + n_dead_tup) > 0
                    THEN round(
                        100.0 * n_dead_tup / (n_live_tup + n_dead_tup),
                        2
                    )
                    ELSE 0
                END AS dead_ratio,
                pg_total_relation_size(schemaname || '.' || relname) AS total_bytes
            FROM pg_stat_user_tables
            ORDER BY n_dead_tup DESC
        """)
        return cur.fetchall()


def collect_explain(conn: psycopg.Connection, query: str) -> list:
    """
    Executar EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) para uma query SELECT.

    Restrito a SELECTs: EXPLAIN ANALYZE executa a query de verdade.
    Um DELETE com EXPLAIN ANALYZE causaria modificação real dos dados.
    A validação startswith("select") previne esse efeito colateral.

    FORMAT JSON retorna o plano como estrutura navegável.
    BUFFERS expõe cache hits/misses por nó — essencial para identificar
    quais partes da query forçam I/O de disco.
    """
    normalized = query.strip().lower()
    if not normalized.startswith("select"):
        raise ValueError(
            "Only SELECT queries are allowed for EXPLAIN ANALYZE. "
            f"Received: '{query[:80]}'"
        )

    with conn.cursor() as cur:
        cur.execute(
            psql.SQL("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {}").format(
                psql.SQL(query)
            )
        )
        result = cur.fetchone()
        return result[0] if result else []
