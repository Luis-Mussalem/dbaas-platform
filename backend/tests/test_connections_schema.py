"""
Tests for the instance-detail live endpoints (PHASE B):
GET /instances/{id}/connections (pg_stat_activity) and
GET /instances/{id}/schema (tables per schema).

The happy path connects to the monitored database (not testable without a live
target Postgres) — so we cover what does NOT need a connection: authentication, 404, the 409 for
"instance is not RUNNING", and the service's pure schema-grouping
logic (with get_connection/collect_schema stubbed out).
"""
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

from src.core.encryption import encrypt_value
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.services import metrics as metrics_service


def _make(db, status=InstanceStatus.STOPPED, with_uri=True):
    inst = DatabaseInstance(
        name="detail-db",
        status=status,
        connection_uri=encrypt_value("postgresql://u:p@127.0.0.1:5433/appdb") if with_uri else None,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


# --------------------------------------------------------------------------- #
# Active connections (router)
# --------------------------------------------------------------------------- #


def test_connections_requires_auth(client, db):
    inst = _make(db)
    assert client.get(f"/api/v1/instances/{inst.id}/connections").status_code == 401


def test_connections_unknown_instance_404(client, auth_headers):
    headers, _ = auth_headers()
    resp = client.get(f"/api/v1/instances/{uuid.uuid4()}/connections", headers=headers)
    assert resp.status_code == 404


def test_connections_not_running_returns_409(client, auth_headers, db):
    headers, _ = auth_headers()
    inst = _make(db, status=InstanceStatus.STOPPED)
    resp = client.get(f"/api/v1/instances/{inst.id}/connections", headers=headers)
    assert resp.status_code == 409


def test_connections_running_without_uri_returns_409(client, auth_headers, db):
    headers, _ = auth_headers()
    inst = _make(db, status=InstanceStatus.RUNNING, with_uri=False)
    resp = client.get(f"/api/v1/instances/{inst.id}/connections", headers=headers)
    assert resp.status_code == 409


# --------------------------------------------------------------------------- #
# Schema explorer (router)
# --------------------------------------------------------------------------- #


def test_schema_requires_auth(client, db):
    inst = _make(db)
    assert client.get(f"/api/v1/instances/{inst.id}/schema").status_code == 401


def test_schema_not_running_returns_409(client, auth_headers, db):
    headers, _ = auth_headers()
    inst = _make(db, status=InstanceStatus.STOPPED)
    resp = client.get(f"/api/v1/instances/{inst.id}/schema", headers=headers)
    assert resp.status_code == 409


# --------------------------------------------------------------------------- #
# Grouping by schema (service — pure logic)
# --------------------------------------------------------------------------- #


def test_get_schema_groups_tables_by_schema(monkeypatch):
    @contextmanager
    def fake_conn(instance):
        yield object()

    monkeypatch.setattr(metrics_service, "get_connection", fake_conn)
    monkeypatch.setattr(metrics_service, "collect_schema", lambda conn: [
        {"schema_name": "public", "table": "users", "estimated_rows": 10},
        {"schema_name": "public", "table": "orders", "estimated_rows": 20},
        {"schema_name": "auth", "table": "tokens", "estimated_rows": 5},
    ])

    groups = metrics_service.get_schema(SimpleNamespace())
    assert [g["name"] for g in groups] == ["public", "auth"]
    assert [t["table"] for t in groups[0]["tables"]] == ["users", "orders"]
    assert groups[1]["tables"][0]["estimated_rows"] == 5
