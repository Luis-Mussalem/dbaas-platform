"""
Tests for collect_explain's SELECT-only guard (PHASE 4).

This is the same guard the SQL Console (FRONTEND F7) will reuse for the
read-only execution of SQL — that's why it's worth locking down the behavior now, before the reuse.

The validations (length, semicolon, startswith select, DML/DDL blacklist)
run BEFORE any use of the connection. Hence we pass conn=None: on invalid
inputs the function raises ValueError without ever touching the database. There's no
dependency on Postgres here.
"""
import pytest

from src.collectors.pg_stats import _EXPLAIN_MAX_LEN, collect_explain


def test_rejects_query_over_max_length():
    huge = "select " + "a" * (_EXPLAIN_MAX_LEN + 1)
    with pytest.raises(ValueError, match="too long"):
        collect_explain(None, huge)


def test_rejects_semicolon():
    with pytest.raises(ValueError, match="[Ss]emicolon"):
        collect_explain(None, "select 1; drop table users")


@pytest.mark.parametrize(
    "query",
    [
        "delete from users",
        "update users set x = 1",
        "insert into users values (1)",
        "  drop table users  ",
        "with x as (select 1) delete from users",  # doesn't start with select
    ],
)
def test_rejects_non_select_start(query):
    with pytest.raises(ValueError):
        collect_explain(None, query)


@pytest.mark.parametrize(
    "keyword,query",
    [
        ("delete", "select * from (delete from users returning *) t"),
        ("update", "select * from foo where x in (update bar set y=1 returning id)"),
        ("drop", "select 1 where false union select drop"),
        ("truncate", "select truncate"),
        ("merge", "select * from (merge into users using t on true returning *) m"),
    ],
)
def test_rejects_blocked_keyword_inside_select(keyword, query):
    with pytest.raises(ValueError, match="disallowed keyword"):
        collect_explain(None, query)


def test_case_insensitive_and_whitespace_tolerant():
    # Uppercase SELECT with leading whitespace passes validation and only fails when
    # trying to use the None connection — proving the guard didn't block the query.
    with pytest.raises(AttributeError):
        collect_explain(None, "   SELECT 1   ")
