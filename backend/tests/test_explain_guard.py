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
from src.core.sql_guard import assert_read_only_select


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


# --------------------------------------------------------------------------- #
# Literals and comments are DATA, not SQL
#
# The keyword scan used to run on the raw text, so an ordinary query was rejected
# for merely MENTIONING a blocked word inside a string. An audit console that
# cannot ask `WHERE action = 'create'` is a guard that fails its users, and users
# route around guards that get in the way.
# --------------------------------------------------------------------------- #


def test_blocked_keyword_inside_a_string_literal_is_allowed():
    assert_read_only_select("SELECT * FROM audit_logs WHERE action = 'create'")
    assert_read_only_select("SELECT * FROM jobs WHERE kind = 'delete' AND ok")
    assert_read_only_select("SELECT 'drop table users' AS example")


def test_escaped_quote_inside_a_literal_does_not_reopen_the_scan():
    """'' is one escaped quote, not the end of the literal followed by a new one."""
    assert_read_only_select("SELECT * FROM t WHERE name = 'O''Brien is a delete'")


def test_semicolon_inside_a_literal_is_allowed():
    assert_read_only_select("SELECT * FROM t WHERE csv = 'a;b;c'")


def test_semicolon_outside_a_literal_is_still_blocked():
    with pytest.raises(ValueError, match="Semicolons"):
        assert_read_only_select("SELECT 1; DROP TABLE users")


def test_quoted_identifier_may_contain_a_keyword():
    assert_read_only_select('SELECT "delete" FROM events')


def test_leading_comment_cannot_smuggle_a_write():
    """
    Comments are blanked to spaces of equal length, so a statement hidden behind
    one is still judged on what actually comes first.
    """
    with pytest.raises(ValueError):
        assert_read_only_select("/* harmless */ DELETE FROM users")
    with pytest.raises(ValueError):
        assert_read_only_select("-- comment\nUPDATE users SET is_superuser = true")


def test_keyword_in_a_comment_does_not_reject_a_valid_select():
    assert_read_only_select("SELECT id FROM users -- do not delete these rows")


# --------------------------------------------------------------------------- #
# CTEs
# --------------------------------------------------------------------------- #


def test_read_only_cte_is_allowed():
    assert_read_only_select(
        "WITH recent AS (SELECT * FROM orders WHERE created_at > now()) "
        "SELECT count(*) FROM recent"
    )


def test_writable_cte_is_still_blocked():
    """The reason the keyword scan survives alongside the startswith check."""
    with pytest.raises(ValueError, match="disallowed keyword"):
        assert_read_only_select(
            "WITH gone AS (DELETE FROM orders RETURNING *) SELECT * FROM gone"
        )
