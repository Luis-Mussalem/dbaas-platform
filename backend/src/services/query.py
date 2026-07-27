"""
SQL Console service (FRONTEND F7) — read-only SELECT execution.

Reuses the SELECT-only guard (src.core.sql_guard) and the secure connection to the
instance (src.services.metrics.get_connection, which decrypts the URI and enforces
statement_timeout=30s). Nothing new about connections/security is introduced here.
"""
from src.core.sql_guard import assert_read_only_select
from src.models.database_instance import DatabaseInstance
from src.services.metrics import get_connection

# Cap on rows returned to the client. Execution time is already limited by the
# 30s statement_timeout inherited from get_connection; this cap limits the volume.
MAX_ROWS = 1000


def execute_read_only(
    instance: DatabaseInstance, query: str
) -> tuple[list[str], list[list[str | None]], bool]:
    """
    Executes a read-only SELECT and returns (columns, rows, truncated).

    - ``assert_read_only_select`` raises ValueError on invalid input (→ 422).
    - Postgres execution errors propagate as psycopg.Error (→ 400 in the router).
    - Cells become str (None preserved): avoids JSON serialization pitfalls
      (Decimal, datetime, bytea, json). A console displays text either way.
    - columns + rows as lists preserve order and duplicate names (SELECT 1, 1).
    """
    assert_read_only_select(query)

    with get_connection(instance) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            if cur.description is None:
                # Valid statement that returns no rows (rare in a pure SELECT).
                return [], [], False
            columns = [desc.name for desc in cur.description]
            raw_rows = cur.fetchmany(MAX_ROWS)
            truncated = len(raw_rows) == MAX_ROWS

    rows = [[None if value is None else str(value) for value in row] for row in raw_rows]
    return columns, rows, truncated
