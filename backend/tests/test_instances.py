"""
Testes de instâncias: criação (com provisioner falso), falha de
provisionamento, listagem, máquina de estados e soft delete.

O provisioner real sobe containers Docker. Aqui ele é substituído por um
FakeProvisioner (monkeypatch) — os testes validam a LÓGICA do service/router
sem depender de Docker. Cobrem também o fix #4 (erros internos não vazam na
resposta 503).
"""
import uuid
from datetime import datetime, timezone

import pytest

from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.services.provisioning.types import ProvisionResult

API = "/api/v1/instances"


# --------------------------------------------------------------------------- #
# Provisioner falso + fixtures
# --------------------------------------------------------------------------- #


class FakeProvisioner:
    """Dublê do provisioner: registra chamadas, não toca em Docker."""

    def __init__(self) -> None:
        self.fail_create = False
        self.created: list[uuid.UUID] = []
        self.started: list[uuid.UUID] = []
        self.stopped: list[uuid.UUID] = []
        self.deleted: list[uuid.UUID] = []

    def create(self, instance_id, engine_version, memory_mb=None, cpu=None):
        if self.fail_create:
            # Mensagem com "segredo" interno — os testes garantem que NÃO vaza.
            raise RuntimeError("docker daemon error at internal-host:5432")
        self.created.append(instance_id)
        return ProvisionResult(
            container_id="fake-container-id",
            host="127.0.0.1",
            port=55432,
            db_name="db_fakeinstance",
            db_user="inst_fakeinstance",
            db_password="fake-plaintext-password",
            container_name="dbaas-inst-fake",
        )

    def start(self, instance_id):
        self.started.append(instance_id)
        return 55433  # nova porta após restart (Docker republica dinamicamente)

    def stop(self, instance_id):
        self.stopped.append(instance_id)

    def delete(self, instance_id):
        self.deleted.append(instance_id)


@pytest.fixture
def fake_provisioner(monkeypatch):
    """Substitui get_provisioner no service por um FakeProvisioner."""
    fake = FakeProvisioner()
    monkeypatch.setattr("src.services.instance.get_provisioner", lambda: fake)
    return fake


@pytest.fixture
def make_instance(db):
    """Insere uma instância direto no banco, em qualquer status desejado."""
    def _make(
        name: str = "test-instance",
        status: InstanceStatus = InstanceStatus.STOPPED,
        **kwargs,
    ) -> DatabaseInstance:
        inst = DatabaseInstance(name=name, status=status, **kwargs)
        db.add(inst)
        db.commit()
        db.refresh(inst)
        return inst

    return _make


# --------------------------------------------------------------------------- #
# Criação
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
    # A connection_uri (segredo cifrado) NUNCA deve aparecer na resposta.
    assert "connection_uri" not in body
    assert "fake-plaintext-password" not in resp.text
    assert fake_provisioner.created  # o provisioner foi de fato chamado


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
        json={"name": "bad-env", "environment": "qa"},  # não é production/staging/development
    )
    assert resp.status_code == 422


def test_create_instance_provisioning_failure_returns_generic_503(
    client, auth_headers, fake_provisioner, db
):
    # Fix #4: na falha, o cliente recebe 503 genérico — sem detalhe interno.
    fake_provisioner.fail_create = True
    headers, _ = auth_headers()

    resp = client.post(API, headers=headers, json={"name": "boom"})
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail == "Provisioning failed. See server logs for details."
    assert "internal-host" not in detail  # erro interno não vazou
    assert "internal-host" not in resp.text

    # E a instância fica persistida como FAILED (registro de auditoria).
    inst = db.query(DatabaseInstance).filter_by(name="boom").first()
    assert inst is not None
    assert inst.status == InstanceStatus.FAILED


# --------------------------------------------------------------------------- #
# Listagem / detalhe
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
# Máquina de estados (start/stop)
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
    # Docker republica em nova porta no start; o service ressincroniza.
    assert body["port"] == 55433
    assert inst.id in fake_provisioner.started


def test_invalid_transition_returns_409(
    client, auth_headers, make_instance, fake_provisioner
):
    headers, _ = auth_headers()
    # RUNNING → start (alvo RUNNING) é transição inválida.
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

    # Depois do soft delete, a instância some das consultas (404).
    assert client.get(f"{API}/{inst.id}", headers=headers).status_code == 404
