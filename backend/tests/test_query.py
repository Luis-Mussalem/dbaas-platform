"""
Testes do Console SQL (FRONTEND F7) — endpoint POST /instances/{id}/query.

O guard SELECT-only em si já é coberto por tests/test_explain_guard.py (mesmo
sql_guard.assert_read_only_select). Aqui focamos no nível de router/serviço:
rejeição 422, scoping multi-tenant, status 409, erro do Postgres 400, e o caminho
feliz com conexão dublada (monkeypatch) — sem depender de um Postgres real.
"""
from contextlib import contextmanager

import psycopg
import pytest

from src.core.encryption import encrypt_value
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.services import query as query_service

API = "/api/v1/instances"


# --------------------------------------------------------------------------- #
# Helpers / dublês
# --------------------------------------------------------------------------- #


def _seed_instance(db, company_id=None, name="qdb", status=InstanceStatus.RUNNING):
    inst = DatabaseInstance(
        name=name,
        status=status,
        company_id=company_id,
        connection_uri=encrypt_value("postgresql://u:p@127.0.0.1:5433/appdb"),
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


class _Col:
    """Mínimo do que o serviço lê de cursor.description: o atributo .name."""

    def __init__(self, name: str):
        self.name = name


class _FakeCursor:
    def __init__(self, description, rows, error=None):
        self._description = description
        self._rows = rows
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query):
        if self._error is not None:
            raise self._error

    @property
    def description(self):
        return self._description

    def fetchmany(self, size):
        return self._rows[:size]


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def _patch_connection(monkeypatch, *, description, rows, error=None):
    """Substitui get_connection por um context manager que devolve um cursor dublê."""
    cursor = _FakeCursor(description, rows, error)

    @contextmanager
    def _fake_get_connection(instance):
        yield _FakeConn(cursor)

    monkeypatch.setattr(query_service, "get_connection", _fake_get_connection)


# --------------------------------------------------------------------------- #
# Guard SELECT-only → 422 (a conexão nunca é aberta)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "query",
    [
        "delete from users",
        "update users set x = 1",
        "insert into users values (1)",
        "select 1; drop table users",
        "with t as (select 1) delete from users",
    ],
)
def test_non_select_rejected_with_422(client, auth_headers, db, query):
    headers, _ = auth_headers(email="root@example.com", is_superuser=True)
    inst = _seed_instance(db)

    resp = client.post(f"{API}/{inst.id}/query", headers=headers, json={"query": query})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Caminho feliz + truncamento
# --------------------------------------------------------------------------- #


def test_valid_select_returns_rows(client, auth_headers, db, monkeypatch):
    headers, _ = auth_headers(email="root@example.com", is_superuser=True)
    inst = _seed_instance(db)
    _patch_connection(
        monkeypatch,
        description=[_Col("id"), _Col("name")],
        rows=[(1, "alice"), (2, None)],
    )

    resp = client.post(
        f"{API}/{inst.id}/query",
        headers=headers,
        json={"query": "select id, name from customers"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["columns"] == ["id", "name"]
    assert body["rows"] == [["1", "alice"], ["2", None]]  # células viram str; None preservado
    assert body["row_count"] == 2
    assert body["truncated"] is False


def test_result_truncated_at_max_rows(client, auth_headers, db, monkeypatch):
    headers, _ = auth_headers(email="root@example.com", is_superuser=True)
    inst = _seed_instance(db)
    rows = [(i,) for i in range(query_service.MAX_ROWS + 5)]
    _patch_connection(monkeypatch, description=[_Col("n")], rows=rows)

    resp = client.post(
        f"{API}/{inst.id}/query", headers=headers, json={"query": "select n from t"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["row_count"] == query_service.MAX_ROWS
    assert body["truncated"] is True


# --------------------------------------------------------------------------- #
# Erro de execução do Postgres → 400
# --------------------------------------------------------------------------- #


def test_postgres_error_returns_400(client, auth_headers, db, monkeypatch):
    headers, _ = auth_headers(email="root@example.com", is_superuser=True)
    inst = _seed_instance(db)
    _patch_connection(
        monkeypatch,
        description=None,
        rows=[],
        error=psycopg.OperationalError('relation "nope" does not exist'),
    )

    resp = client.post(
        f"{API}/{inst.id}/query",
        headers=headers,
        json={"query": "select * from nope"},
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Scoping multi-tenant e estado da instância
# --------------------------------------------------------------------------- #


def test_other_company_instance_returns_404(client, auth_headers, make_company, db):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    headers, _ = auth_headers(email="a@example.com", company_id=company_a.id)
    b_inst = _seed_instance(db, company_id=company_b.id, name="b1")

    resp = client.post(
        f"{API}/{b_inst.id}/query", headers=headers, json={"query": "select 1"}
    )
    assert resp.status_code == 404


def test_non_running_instance_returns_409(client, auth_headers, db):
    headers, _ = auth_headers(email="root@example.com", is_superuser=True)
    inst = _seed_instance(db, status=InstanceStatus.STOPPED)

    resp = client.post(
        f"{API}/{inst.id}/query", headers=headers, json={"query": "select 1"}
    )
    assert resp.status_code == 409
