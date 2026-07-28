"""
SELECT-only guard — defense in depth for read-only SQL execution.

Originally embedded in ``collect_explain`` (EXPLAIN ANALYZE actually executes the
query). Extracted here to be reused by the SQL Console (FRONTEND F7), which
executes arbitrary user SELECTs against the instance's database.

The checks run BEFORE any use of the connection: on invalid input the function
raises ``ValueError`` without ever touching the database.

This is the SECOND of two layers, not the only one. The first is the PostgreSQL
role itself: the provisioner gives each instance a role with CRUD on its own
database and nothing more (no superuser, no ``pg_read_server_files``), so the
file-reading and cluster-wide functions an attacker would reach for are refused by
the server regardless of what gets past this guard. Runaway queries are capped by
the ``statement_timeout=30s`` that services.metrics.get_connection sets, and the
result volume by ``services.query.MAX_ROWS``. The guard's job is to stop a
mistyped or malicious statement early and legibly — not to be the only thing
standing between a user and their data.
"""
import re

MAX_QUERY_LEN = 8000

BLOCKED_KEYWORDS = {
    "insert", "update", "delete", "merge", "drop", "truncate",
    "create", "alter", "grant", "revoke", "copy",
    "vacuum", "reindex", "cluster",
}

# String literals and comments, so they can be blanked out before the keyword scan.
# Without this, a perfectly ordinary query is rejected for MENTIONING a keyword:
#   SELECT * FROM audit_logs WHERE action = 'create'
# ...contains the token "create" only inside a literal, where it is data and not a
# statement. The blanking is done on a COPY used solely for the keyword scan; the
# query executed is always the user's original text.
_LITERALS_AND_COMMENTS = re.compile(
    r"""
      '(?:[^']|'')*'      # single-quoted literal, '' being an escaped quote
    | "(?:[^"]|"")*"      # quoted identifier — also not a place for keywords
    | --[^\n]*            # line comment
    | /\*.*?\*/           # block comment
    """,
    re.VERBOSE | re.DOTALL,
)


def _strip_literals(query: str) -> str:
    """
    Replaces literals, quoted identifiers and comments with spaces of equal length.

    Same-length replacement keeps offsets intact, which matters for the
    ``startswith('select')`` check running on the stripped copy: a leading comment
    becomes leading whitespace rather than disappearing, so
    ``/* hi */ DELETE ...`` cannot slide a DELETE into first position.
    """
    return _LITERALS_AND_COMMENTS.sub(lambda m: " " * len(m.group(0)), query)


def assert_read_only_select(query: str) -> None:
    """
    Raises ``ValueError`` if ``query`` is not a single pure SELECT.

    The checks, in order:
    1. Max length — avoids huge queries that consume excessive memory.
    2. No semicolon — blocks multiple statements chained in one request. Checked on
       the stripped copy so a semicolon inside a literal ('a;b') is not an error.
    3. ``startswith('select')`` or ``with`` — the primary check. A CTE is a legal
       read: ``WITH x AS (...) SELECT ...`` is accepted, and its body still faces
       the keyword scan below, which rejects a writable CTE
       (``WITH d AS (DELETE ... RETURNING *) SELECT ...``).
    4. DML/DDL keyword blacklist on the stripped copy — catches the write hidden
       inside an otherwise SELECT-shaped statement.
    """
    if len(query) > MAX_QUERY_LEN:
        raise ValueError(
            f"Query too long: {len(query)} chars (max {MAX_QUERY_LEN})"
        )

    # Everything below inspects `scannable`, never the raw text: literals and
    # comments are data, and treating them as SQL is what produced false rejections.
    scannable = _strip_literals(query)

    if ";" in scannable:
        raise ValueError(
            "Semicolons are not allowed — only a single SELECT statement is permitted"
        )

    normalized = scannable.strip().lower()
    if not (normalized.startswith("select") or normalized.startswith("with")):
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
