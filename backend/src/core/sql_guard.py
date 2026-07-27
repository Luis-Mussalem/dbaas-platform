"""
SELECT-only guard — defense in depth for read-only SQL execution.

Originally embedded in ``collect_explain`` (EXPLAIN ANALYZE actually executes the
query). Extracted here to be reused by the SQL Console (FRONTEND F7), which
executes arbitrary user SELECTs against the instance's database.

The 4 checks run BEFORE any use of the connection: on invalid input the
function raises ``ValueError`` without ever touching the database.
"""
import re

MAX_QUERY_LEN = 8000

BLOCKED_KEYWORDS = {
    "insert", "update", "delete", "merge", "drop", "truncate",
    "create", "alter", "grant", "revoke", "copy",
    "vacuum", "reindex", "cluster",
}


def assert_read_only_select(query: str) -> None:
    """
    Raises ``ValueError`` if ``query`` is not a single pure SELECT.

    Defense in depth:
    1. Max length: avoids huge queries that consume excessive memory.
    2. Semicolon forbidden: blocks multiple statements in sequence.
    3. ``startswith('select')``: primary check.
    4. DML/DDL keyword blacklist: blocks SELECT ... FROM (DELETE ...) etc.
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

    # Block destructive keywords even inside a SELECT
    # (e.g.: SELECT * FROM (DELETE ... RETURNING *) t)
    tokens = set(re.findall(r"[a-z]+", normalized))
    blocked = tokens & BLOCKED_KEYWORDS
    if blocked:
        raise ValueError(
            f"Query contains disallowed keyword(s): {', '.join(sorted(blocked))}. "
            "Only pure SELECT queries are permitted."
        )
