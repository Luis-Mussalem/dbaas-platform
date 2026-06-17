"""
Serviço do Console SQL (FRONTEND F7) — execução read-only de SELECT.

Reúsa o guard SELECT-only (src.core.sql_guard) e a conexão segura à instância
(src.services.metrics.get_connection, que decripta a URI e impõe
statement_timeout=30s). Nada novo de conexão/segurança é introduzido aqui.
"""
from src.core.sql_guard import assert_read_only_select
from src.models.database_instance import DatabaseInstance
from src.services.metrics import get_connection

# Cap de linhas devolvidas ao cliente. O tempo de execução já é limitado pelos
# 30s de statement_timeout herdados de get_connection; este cap limita o volume.
MAX_ROWS = 1000


def execute_read_only(
    instance: DatabaseInstance, query: str
) -> tuple[list[str], list[list[str | None]], bool]:
    """
    Executar um SELECT read-only e devolver (columns, rows, truncated).

    - ``assert_read_only_select`` levanta ValueError em entrada inválida (→ 422).
    - Erros de execução do Postgres propagam como psycopg.Error (→ 400 no router).
    - As células viram str (None preservado): evita arapucas de serialização JSON
      (Decimal, datetime, bytea, json). Um console exibe texto de qualquer forma.
    - columns + rows como listas preservam a ordem e nomes duplicados (SELECT 1, 1).
    """
    assert_read_only_select(query)

    with get_connection(instance) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            if cur.description is None:
                # Statement válido que não devolve linhas (raro num SELECT puro).
                return [], [], False
            columns = [desc.name for desc in cur.description]
            raw_rows = cur.fetchmany(MAX_ROWS)
            truncated = len(raw_rows) == MAX_ROWS

    rows = [[None if value is None else str(value) for value in row] for row in raw_rows]
    return columns, rows, truncated
