"""
Guard SELECT-only — defesa em profundidade para execução de SQL read-only.

Originalmente embutido em ``collect_explain`` (EXPLAIN ANALYZE executa a query
de verdade). Extraído aqui para ser reusado pelo Console SQL (FRONTEND F7), que
executa SELECTs arbitrários do usuário contra o banco da instância.

As 4 checagens rodam ANTES de qualquer uso da conexão: numa entrada inválida a
função levanta ``ValueError`` sem nunca tocar no banco.
"""
import re

MAX_QUERY_LEN = 8000

BLOCKED_KEYWORDS = {
    "insert", "update", "delete", "drop", "truncate",
    "create", "alter", "grant", "revoke", "copy",
    "vacuum", "reindex", "cluster",
}


def assert_read_only_select(query: str) -> None:
    """
    Levanta ``ValueError`` se ``query`` não for um único SELECT puro.

    Defesa em profundidade:
    1. Tamanho máximo: evita queries enormes que consumam memória excessiva.
    2. Ponto-e-vírgula proibido: bloqueia múltiplos statements em sequência.
    3. ``startswith('select')``: verificação primária.
    4. Blacklist de keywords DML/DDL: bloqueia SELECT ... FROM (DELETE ...) etc.
    """
    if len(query) > MAX_QUERY_LEN:
        raise ValueError(
            f"Query too long: {len(query)} chars (max {MAX_QUERY_LEN})"
        )

    if ";" in query:
        raise ValueError(
            "Semicolons are not allowed — only a single SELECT statement is permitted"
        )

    normalized = query.strip().lower()
    if not normalized.startswith("select"):
        raise ValueError(
            "Only SELECT queries are allowed. "
            f"Received: '{query[:80]}'"
        )

    # Bloquear keywords destrutivos mesmo dentro de SELECT
    # (ex: SELECT * FROM (DELETE ... RETURNING *) t)
    tokens = set(re.findall(r"[a-z]+", normalized))
    blocked = tokens & BLOCKED_KEYWORDS
    if blocked:
        raise ValueError(
            f"Query contains disallowed keyword(s): {', '.join(sorted(blocked))}. "
            "Only pure SELECT queries are permitted."
        )
