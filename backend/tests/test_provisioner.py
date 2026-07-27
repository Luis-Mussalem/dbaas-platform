"""
Tests for DockerProvisioner (PHASE 3) without real Docker or PostgreSQL.

docker.DockerClient is replaced by a stub (FakeDockerClient) that returns
controlled FakeContainers. The readiness waits and the role/database setup
(which connect via psycopg) are neutralized with monkeypatch. We validate:
- pure identifier/password helpers (no client)
- create: assigned port, ProvisionResult, and cleanup when the port is missing
- start/stop/delete/get_status: port reading, idempotency, and translation of
  NotFound → RuntimeError / NOT_FOUND.
"""
import uuid

import docker.errors
import pytest

from src.services.provisioning import docker_provisioner as dp
from src.services.provisioning.docker_provisioner import DockerProvisioner
from src.services.provisioning.types import ProvisionerStatus


# --------------------------------------------------------------------------- #
# Docker stubs
# --------------------------------------------------------------------------- #


class FakeContainer:
    def __init__(self, container_id="cid", status="running", ports=None):
        self.id = container_id
        self.status = status
        self.ports = ports if ports is not None else {"5432/tcp": [{"HostPort": "55432"}]}
        self.started = False
        self.stopped = False
        self.removed = False
        self.restart_policy = None

    def reload(self):
        pass

    def update(self, **kwargs):
        if "restart_policy" in kwargs:
            self.restart_policy = kwargs["restart_policy"]

    def start(self):
        self.started = True

    def stop(self, timeout=10):
        self.stopped = True

    def remove(self, force=False):
        self.removed = True


class _Networks:
    def get(self, name):
        return object()  # network already exists → __init__ doesn't try to create it

    def create(self, *a, **k):  # pragma: no cover
        return object()


class _Containers:
    def __init__(self, run_result=None, get_result=None, get_exc=None):
        self._run_result = run_result
        self._get_result = get_result
        self._get_exc = get_exc
        self.run_kwargs = None

    def run(self, **kwargs):
        self.run_kwargs = kwargs
        return self._run_result

    def get(self, name):
        if self._get_exc is not None:
            raise self._get_exc
        return self._get_result


class FakeDockerClient:
    def __init__(self, containers: _Containers):
        self.networks = _Networks()
        self.containers = containers


@pytest.fixture(autouse=True)
def tmp_backup_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dp.settings, "BACKUP_DIR", str(tmp_path))
    return tmp_path


def _provisioner(containers: _Containers, monkeypatch) -> DockerProvisioner:
    prov = DockerProvisioner(FakeDockerClient(containers))
    # Neutralizes the steps that would talk to a real PostgreSQL.
    monkeypatch.setattr(prov, "_wait_until_database_ready", lambda *a, **k: None)
    monkeypatch.setattr(prov, "_setup_database_and_role", lambda *a, **k: None)
    return prov


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def test_safe_identifier_normalizes():
    assert dp._safe_identifier("My DB-Name!") == "my_db_name_"
    assert dp._safe_identifier("9lives").startswith("db_")  # prefixed if it starts with a digit
    assert dp._safe_identifier("") == "db_instance"
    assert len(dp._safe_identifier("x" * 100)) == 63  # truncated to 63


def test_quote_ident_escapes_double_quotes():
    assert dp._quote_ident('my"role') == '"my""role"'


def test_pg_literal_string_escapes_quotes_and_backslashes():
    assert dp._pg_literal_string("pass'word") == "'pass''word'"
    assert dp._pg_literal_string("a\\b") == "'a\\\\b'"


def test_generate_password_is_alphanumeric_and_sized():
    pw = DockerProvisioner.__dict__  # noqa: F841  (just for clarity)
    prov = DockerProvisioner(FakeDockerClient(_Containers()))
    pwd = prov._generate_password(length=24)
    assert len(pwd) == 24
    assert pwd.isalnum()


def test_container_name_is_deterministic():
    prov = DockerProvisioner(FakeDockerClient(_Containers()))
    iid = uuid.UUID("12345678-1234-1234-1234-1234567890ab")
    name = prov._container_name(iid)
    assert name.startswith(dp._CONTAINER_PREFIX)
    assert prov._container_name(iid) == name  # deterministic


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #


def test_create_returns_provision_result(monkeypatch):
    container = FakeContainer()
    containers = _Containers(run_result=container)
    prov = _provisioner(containers, monkeypatch)

    iid = uuid.uuid4()
    result = prov.create(iid, engine_version="16", memory_mb=512, cpu=2)

    assert result.port == 55432
    assert result.host == "127.0.0.1"
    assert result.db_user.startswith("inst_")
    assert result.db_name.startswith("db_")
    # Resource limits propagated to docker run.
    assert containers.run_kwargs["mem_limit"] == "512m"
    assert containers.run_kwargs["nano_cpus"] == 2_000_000_000
    # Restart policy applied to survive a Docker/host restart.
    assert containers.run_kwargs["restart_policy"] == {"Name": "unless-stopped"}


def test_create_without_port_cleans_up_and_raises(monkeypatch):
    container = FakeContainer(ports={})  # Docker did not assign a port
    prov = _provisioner(_Containers(run_result=container), monkeypatch)

    with pytest.raises(RuntimeError, match="did not assign a port"):
        prov.create(uuid.uuid4(), engine_version="16")
    assert container.removed is True  # cleanup triggered


def test_create_makes_wal_dir_writable_by_container_postgres(tmp_backup_dir, monkeypatch):
    """
    archive_command runs as postgres (uid 70) inside the container and writes to the
    /archive bind mount. Without write access for "others" it fails with Permission denied,
    pg_wal grows without limit, and PITR is left without a base — a silent regression, since
    the suite doesn't bring up a real container.
    """
    containers = _Containers(run_result=FakeContainer())
    prov = _provisioner(containers, monkeypatch)

    iid = uuid.uuid4()
    prov.create(iid, engine_version="16")

    wal_dir = tmp_backup_dir / str(iid) / "wal"
    assert wal_dir.is_dir()
    assert wal_dir.stat().st_mode & 0o007 == 0o007  # rwx for "others"
    # The directory needs to reach the container mounted at /archive.
    assert containers.run_kwargs["volumes"][str(wal_dir)] == {"bind": "/archive", "mode": "rw"}


def test_create_omits_resource_limits_when_unset(monkeypatch):
    containers = _Containers(run_result=FakeContainer())
    prov = _provisioner(containers, monkeypatch)
    prov.create(uuid.uuid4(), engine_version="16")
    assert "mem_limit" not in containers.run_kwargs
    assert "nano_cpus" not in containers.run_kwargs


# --------------------------------------------------------------------------- #
# start / stop / delete / get_status
# --------------------------------------------------------------------------- #


def test_start_returns_published_port(monkeypatch):
    container = FakeContainer(ports={"5432/tcp": [{"HostPort": "60000"}]})
    prov = _provisioner(_Containers(get_result=container), monkeypatch)
    port = prov.start(uuid.uuid4())
    assert port == 60000
    assert container.started is True


def test_start_upgrades_restart_policy_on_existing_container(monkeypatch):
    # Containers created before the policy get the upgrade when restarted.
    container = FakeContainer(ports={"5432/tcp": [{"HostPort": "60000"}]})
    prov = _provisioner(_Containers(get_result=container), monkeypatch)
    prov.start(uuid.uuid4())
    assert container.restart_policy == {"Name": "unless-stopped"}


def test_start_missing_container_raises(monkeypatch):
    prov = _provisioner(
        _Containers(get_exc=docker.errors.NotFound("missing")), monkeypatch
    )
    with pytest.raises(RuntimeError, match="not found"):
        prov.start(uuid.uuid4())


def test_stop_calls_container_stop(monkeypatch):
    container = FakeContainer()
    prov = _provisioner(_Containers(get_result=container), monkeypatch)
    prov.stop(uuid.uuid4())
    assert container.stopped is True


def test_stop_missing_container_raises(monkeypatch):
    prov = _provisioner(
        _Containers(get_exc=docker.errors.NotFound("missing")), monkeypatch
    )
    with pytest.raises(RuntimeError, match="not found"):
        prov.stop(uuid.uuid4())


def test_delete_is_idempotent_on_missing(monkeypatch):
    # NotFound → delete doesn't raise (idempotent).
    prov = _provisioner(
        _Containers(get_exc=docker.errors.NotFound("missing")), monkeypatch
    )
    prov.delete(uuid.uuid4())  # no exception


def test_delete_removes_existing(monkeypatch):
    container = FakeContainer()
    prov = _provisioner(_Containers(get_result=container), monkeypatch)
    prov.delete(uuid.uuid4())
    assert container.removed is True


@pytest.mark.parametrize(
    "status,expected",
    [
        ("running", ProvisionerStatus.RUNNING),
        ("exited", ProvisionerStatus.STOPPED),
    ],
)
def test_get_status_maps_container_state(monkeypatch, status, expected):
    container = FakeContainer(status=status)
    prov = _provisioner(_Containers(get_result=container), monkeypatch)
    assert prov.get_status(uuid.uuid4()) == expected


def test_get_status_not_found(monkeypatch):
    prov = _provisioner(
        _Containers(get_exc=docker.errors.NotFound("missing")), monkeypatch
    )
    assert prov.get_status(uuid.uuid4()) == ProvisionerStatus.NOT_FOUND


def test_get_status_unexpected_error(monkeypatch):
    prov = _provisioner(
        _Containers(get_exc=RuntimeError("docker daemon down")), monkeypatch
    )
    assert prov.get_status(uuid.uuid4()) == ProvisionerStatus.ERROR


# --------------------------------------------------------------------------- #
# get_port
# --------------------------------------------------------------------------- #


def test_get_port_returns_published_port_when_running(monkeypatch):
    container = FakeContainer(status="running", ports={"5432/tcp": [{"HostPort": "60001"}]})
    prov = _provisioner(_Containers(get_result=container), monkeypatch)
    assert prov.get_port(uuid.uuid4()) == 60001


def test_get_port_returns_none_when_stopped(monkeypatch):
    container = FakeContainer(status="exited")
    prov = _provisioner(_Containers(get_result=container), monkeypatch)
    assert prov.get_port(uuid.uuid4()) is None


def test_get_port_returns_none_when_not_found(monkeypatch):
    prov = _provisioner(
        _Containers(get_exc=docker.errors.NotFound("missing")), monkeypatch
    )
    assert prov.get_port(uuid.uuid4()) is None
