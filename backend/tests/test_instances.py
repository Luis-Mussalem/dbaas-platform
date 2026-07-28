"""
Tests for instances: creation (with a fake provisioner), provisioning
failure, listing, the state machine, and soft delete.

The real provisioner brings up Docker containers. Here it's replaced by a
FakeProvisioner (monkeypatch) — the tests validate the service/router LOGIC
without depending on Docker. They also cover fix #4 (internal errors don't leak into
the 503 response).
"""
import uuid
from datetime import datetime, timezone

import pytest

from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.instance_status_history import InstanceStatusHistory

API = "/api/v1/instances"


# --------------------------------------------------------------------------- #
# Fake provisioner + fixtures
# --------------------------------------------------------------------------- #


# FakeProvisioner and the `fake_provisioner` fixture live in conftest.py — creating
# an instance is a prerequisite in several modules now, not just this one.


@pytest.fixture
def make_instance(db, default_company):
    """
    Inserts an instance directly into the database, in whatever status is desired.

    Defaults to `default_company` — the same company auth_headers() puts its user
    in — so these tests exercise routing and status transitions rather than
    tripping over the tenant filter. Pass company_id=... to override.
    """
    def _make(
        name: str = "test-instance",
        status: InstanceStatus = InstanceStatus.STOPPED,
        **kwargs,
    ) -> DatabaseInstance:
        kwargs.setdefault("company_id", default_company().id)
        inst = DatabaseInstance(name=name, status=status, **kwargs)
        db.add(inst)
        db.commit()
        db.refresh(inst)
        return inst

    return _make


# --------------------------------------------------------------------------- #
# Creation
# --------------------------------------------------------------------------- #


def test_create_instance_succeeds(client, auth_headers, fake_provisioner):
    headers, _ = auth_headers()
    resp = client.post(
        API,
        headers=headers,
        json={
            "name": "my-db",
            "engine_version": "16",
            "cpu": 1,
            "memory_mb": 512,
            "storage_gb": 1,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "running"
    assert body["host"] == "127.0.0.1"
    assert body["port"] == 55432
    assert body["db_name"] == "db_fakeinstance"
    # connection_uri (an encrypted secret) must NEVER appear in the response.
    assert "connection_uri" not in body
    assert "fake-plaintext-password" not in resp.text
    assert fake_provisioner.created  # the provisioner was actually called


def test_create_instance_records_status_history(client, auth_headers, fake_provisioner, db):
    headers, _ = auth_headers()
    resp = client.post(API, headers=headers, json={"name": "hist-db", "engine_version": "16"})
    assert resp.status_code == 201

    inst = db.query(DatabaseInstance).filter_by(name="hist-db").first()
    statuses = [
        h.status
        for h in db.query(InstanceStatusHistory)
        .filter_by(instance_id=inst.id)
        .order_by(InstanceStatusHistory.changed_at.asc())
        .all()
    ]
    # A successful creation goes through PENDING (seed) → PROVISIONING → RUNNING.
    assert statuses == [
        InstanceStatus.PENDING,
        InstanceStatus.PROVISIONING,
        InstanceStatus.RUNNING,
    ]


def test_create_instance_requires_auth(client):
    resp = client.post(API, json={"name": "no-auth"})
    assert resp.status_code == 401


def test_create_instance_persists_region_and_environment(
    client, auth_headers, fake_provisioner, db
):
    headers, _ = auth_headers()
    resp = client.post(
        API,
        headers=headers,
        json={
            "name": "prod-db",
            "engine_version": "16",
            "region": "sa-east-1",
            "environment": "production",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["region"] == "sa-east-1"
    assert body["environment"] == "production"

    inst = db.query(DatabaseInstance).filter_by(name="prod-db").first()
    assert inst.region == "sa-east-1"
    assert inst.environment.value == "production"


def test_create_instance_rejects_invalid_environment(client, auth_headers, fake_provisioner):
    headers, _ = auth_headers()
    resp = client.post(
        API,
        headers=headers,
        json={"name": "bad-env", "environment": "qa"},  # not production/staging/development
    )
    assert resp.status_code == 422


def test_create_instance_provisioning_failure_returns_generic_503(
    client, auth_headers, fake_provisioner, db
):
    # Fix #4: on failure, the client gets a generic 503 — no internal detail.
    fake_provisioner.fail_create = True
    headers, _ = auth_headers()

    resp = client.post(API, headers=headers, json={"name": "boom"})
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail == "Provisioning failed. See server logs for details."
    assert "internal-host" not in detail  # internal error didn't leak
    assert "internal-host" not in resp.text

    # And the instance stays persisted as FAILED (an audit record).
    inst = db.query(DatabaseInstance).filter_by(name="boom").first()
    assert inst is not None
    assert inst.status == InstanceStatus.FAILED


# --------------------------------------------------------------------------- #
# Listing / detail
# --------------------------------------------------------------------------- #


def test_list_instances(client, auth_headers, make_instance):
    headers, _ = auth_headers()
    make_instance(name="alpha", status=InstanceStatus.RUNNING)
    make_instance(name="beta", status=InstanceStatus.STOPPED)

    resp = client.get(API, headers=headers)
    assert resp.status_code == 200
    names = {i["name"] for i in resp.json()}
    assert {"alpha", "beta"} <= names


def test_list_excludes_soft_deleted(client, auth_headers, make_instance):
    headers, _ = auth_headers()
    make_instance(
        name="gone",
        status=InstanceStatus.DELETED,
        deleted_at=datetime.now(timezone.utc),
    )
    make_instance(name="here", status=InstanceStatus.RUNNING)

    resp = client.get(API, headers=headers)
    names = {i["name"] for i in resp.json()}
    assert "here" in names
    assert "gone" not in names


def test_get_instance_not_found_returns_404(client, auth_headers):
    headers, _ = auth_headers()
    resp = client.get(f"{API}/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# State machine (start/stop)
# --------------------------------------------------------------------------- #


def test_stop_running_instance(client, auth_headers, make_instance, fake_provisioner):
    headers, _ = auth_headers()
    inst = make_instance(status=InstanceStatus.RUNNING)

    resp = client.patch(
        f"{API}/{inst.id}/status", headers=headers, json={"action": "stop"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
    assert inst.id in fake_provisioner.stopped


def test_start_stopped_instance_resyncs_port(
    client, auth_headers, make_instance, fake_provisioner
):
    headers, _ = auth_headers()
    inst = make_instance(status=InstanceStatus.STOPPED, port=55432)

    resp = client.patch(
        f"{API}/{inst.id}/status", headers=headers, json={"action": "start"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    # Docker republishes on a new port on start; the service resyncs.
    assert body["port"] == 55433
    assert inst.id in fake_provisioner.started


def test_invalid_transition_returns_409(
    client, auth_headers, make_instance, fake_provisioner
):
    headers, _ = auth_headers()
    # RUNNING → start (target RUNNING) is an invalid transition.
    inst = make_instance(status=InstanceStatus.RUNNING)

    resp = client.patch(
        f"{API}/{inst.id}/status", headers=headers, json={"action": "start"}
    )
    assert resp.status_code == 409


# --------------------------------------------------------------------------- #
# Soft delete
# --------------------------------------------------------------------------- #


def test_delete_running_instance_conflicts(
    client, auth_headers, make_instance, fake_provisioner
):
    headers, _ = auth_headers()
    inst = make_instance(status=InstanceStatus.RUNNING)

    resp = client.delete(f"{API}/{inst.id}", headers=headers)
    assert resp.status_code == 409
    assert inst.id not in fake_provisioner.deleted


def test_delete_stopped_instance(
    client, auth_headers, make_instance, fake_provisioner
):
    headers, _ = auth_headers()
    inst = make_instance(status=InstanceStatus.STOPPED)

    resp = client.delete(f"{API}/{inst.id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert inst.id in fake_provisioner.deleted

    # After the soft delete, the instance disappears from queries (404).
    assert client.get(f"{API}/{inst.id}", headers=headers).status_code == 404


# --------------------------------------------------------------------------- #
# Logs (PHASE 10)
# --------------------------------------------------------------------------- #


def test_get_instance_logs(client, auth_headers, make_instance, monkeypatch):
    class _LogProvisioner:
        def logs(self, instance_id, tail=200):
            return f"line1\nline2 (tail={tail})\n"

    # The router uses get_provisioner imported into its own module.
    monkeypatch.setattr(
        "src.routers.instances.get_provisioner", lambda: _LogProvisioner()
    )
    headers, _ = auth_headers()
    inst = make_instance(status=InstanceStatus.RUNNING)

    resp = client.get(f"{API}/{inst.id}/logs?tail=50", headers=headers)
    assert resp.status_code == 200
    assert "line1" in resp.json()["logs"]
    assert "tail=50" in resp.json()["logs"]


def test_get_instance_logs_container_missing(client, auth_headers, make_instance, monkeypatch):
    class _MissingProvisioner:
        def logs(self, instance_id, tail=200):
            raise RuntimeError("Container not found")

    monkeypatch.setattr(
        "src.routers.instances.get_provisioner", lambda: _MissingProvisioner()
    )
    headers, _ = auth_headers()
    inst = make_instance(status=InstanceStatus.RUNNING)

    resp = client.get(f"{API}/{inst.id}/logs", headers=headers)
    assert resp.status_code == 409
