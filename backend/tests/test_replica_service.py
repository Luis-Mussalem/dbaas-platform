"""
Tests for replication (PHASE 9) without touching Docker/pg_basebackup.

Strategy: a fake provisioner (create_replica/promote_replica) via
monkeypatch, exercising the service's entire orchestration — creation of the
companion instance, the Replica row, the status cycle, and promotion — through the HTTP API.
Multi-tenant scoping is covered at the end (a replica from another company → 404).
"""
import pytest

from src.core.encryption import encrypt_value
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.replica import Replica, ReplicationState
from src.services.provisioning.types import ProvisionResult

API = "/api/v1"


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _seed_primary(db, company_id, name="primary", status=InstanceStatus.RUNNING):
    """RUNNING primary with an encrypted connection_uri, as in production."""
    uri = encrypt_value(f"postgresql://appuser:s3cret@127.0.0.1:5433/{name}_db")
    inst = DatabaseInstance(
        name=name,
        status=status,
        connection_uri=uri,
        host="127.0.0.1",
        port=5433,
        db_name=f"{name}_db",
        db_user="appuser",
        company_id=company_id,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


class _FakeReplicaProvisioner:
    """Stub: echoes back the received credentials, without touching Docker."""

    def create_replica(
        self, replica_instance_id, primary_instance_id, engine_version,
        db_name, db_user, db_password, memory_mb=None, cpu=None,
    ):
        return ProvisionResult(
            container_id="fake-replica-id",
            host="127.0.0.1",
            port=55499,
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
            container_name="dbaas-inst-fakereplica",
        )

    def promote_replica(self, replica_instance_id):
        return None


class _FailingReplicaProvisioner:
    def create_replica(self, *args, **kwargs):
        raise RuntimeError("basebackup blew up")

    def promote_replica(self, replica_instance_id):
        raise RuntimeError("promote blew up")


@pytest.fixture
def fake_provisioner(monkeypatch):
    monkeypatch.setattr(
        "src.services.replica.get_provisioner", lambda: _FakeReplicaProvisioner()
    )


@pytest.fixture
def failing_provisioner(monkeypatch):
    monkeypatch.setattr(
        "src.services.replica.get_provisioner", lambda: _FailingReplicaProvisioner()
    )


# --------------------------------------------------------------------------- #
# Creation
# --------------------------------------------------------------------------- #


def test_create_replica_success(client, auth_headers, make_company, db, fake_provisioner):
    company = make_company(name="Acme")
    headers, _ = auth_headers(email="a@example.com", company_id=company.id)
    primary = _seed_primary(db, company.id)

    resp = client.post(f"{API}/instances/{primary.id}/replicas", headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["replication_state"] == "streaming"
    assert body["primary_instance_id"] == str(primary.id)
    # The companion instance is born RUNNING and shows up in the fleet.
    assert body["replica_instance"]["status"] == "running"
    assert body["replica_instance"]["name"].endswith("(replica)")

    # Persistence: one Replica row + the standby instance with an encrypted URI.
    replica = db.query(Replica).filter(Replica.primary_instance_id == primary.id).one()
    assert replica.replication_state == ReplicationState.STREAMING
    standby = db.query(DatabaseInstance).filter(
        DatabaseInstance.id == replica.replica_instance_id
    ).one()
    assert standby.status == InstanceStatus.RUNNING
    assert standby.connection_uri  # encrypted, not empty


def test_create_replica_requires_running_primary(client, auth_headers, make_company, db, fake_provisioner):
    company = make_company(name="Acme")
    headers, _ = auth_headers(email="a@example.com", company_id=company.id)
    primary = _seed_primary(db, company.id, status=InstanceStatus.STOPPED)

    resp = client.post(f"{API}/instances/{primary.id}/replicas", headers=headers)
    assert resp.status_code == 409  # get_instance_if_running


def test_create_replica_provisioner_failure_marks_failed(
    client, auth_headers, make_company, db, failing_provisioner
):
    company = make_company(name="Acme")
    headers, _ = auth_headers(email="a@example.com", company_id=company.id)
    primary = _seed_primary(db, company.id)

    resp = client.post(f"{API}/instances/{primary.id}/replicas", headers=headers)
    assert resp.status_code == 503

    replica = db.query(Replica).filter(Replica.primary_instance_id == primary.id).one()
    assert replica.replication_state == ReplicationState.FAILED
    assert replica.error_message
    standby = db.query(DatabaseInstance).filter(
        DatabaseInstance.id == replica.replica_instance_id
    ).one()
    assert standby.status == InstanceStatus.FAILED


# --------------------------------------------------------------------------- #
# Listing / promotion
# --------------------------------------------------------------------------- #


def test_list_replicas(client, auth_headers, make_company, db, fake_provisioner):
    company = make_company(name="Acme")
    headers, _ = auth_headers(email="a@example.com", company_id=company.id)
    primary = _seed_primary(db, company.id)
    client.post(f"{API}/instances/{primary.id}/replicas", headers=headers)

    resp = client.get(f"{API}/instances/{primary.id}/replicas", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_promote_replica(client, auth_headers, make_company, db, fake_provisioner):
    company = make_company(name="Acme")
    headers, _ = auth_headers(email="a@example.com", company_id=company.id)
    primary = _seed_primary(db, company.id)
    created = client.post(f"{API}/instances/{primary.id}/replicas", headers=headers).json()

    resp = client.post(f"{API}/replicas/{created['id']}/promote", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["replication_state"] == "promoted"

    # Promoting again is a conflict (already promoted).
    again = client.post(f"{API}/replicas/{created['id']}/promote", headers=headers)
    assert again.status_code == 409


# --------------------------------------------------------------------------- #
# Multi-tenant scoping
# --------------------------------------------------------------------------- #


def test_create_replica_cross_company_returns_404(
    client, auth_headers, make_company, db, fake_provisioner
):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    headers, _ = auth_headers(email="a@example.com", company_id=company_a.id)
    b_primary = _seed_primary(db, company_b.id, name="bprimary")

    resp = client.post(f"{API}/instances/{b_primary.id}/replicas", headers=headers)
    assert resp.status_code == 404


def test_list_replicas_cross_company_returns_404(
    client, auth_headers, make_company, db
):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    headers, _ = auth_headers(email="a@example.com", company_id=company_a.id)
    b_primary = _seed_primary(db, company_b.id, name="bprimary")

    resp = client.get(f"{API}/instances/{b_primary.id}/replicas", headers=headers)
    assert resp.status_code == 404
