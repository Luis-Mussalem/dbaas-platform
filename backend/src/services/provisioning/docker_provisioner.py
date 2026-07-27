import re
import secrets
import string
import time
import uuid
from pathlib import Path
from typing import Optional

import docker
import docker.errors
import psycopg

from src.core.config import settings
from src.services.provisioning.base import ProvisionerBase
from src.services.provisioning.types import ProvisionResult, ProvisionerStatus

# Prefix for all containers provisioned by the platform
_CONTAINER_PREFIX = "dbaas-inst-"

# Name of the isolated Docker network for the managed instances
_NETWORK_NAME = "dbaas-network"

# How many seconds to wait for PostgreSQL to accept connections before giving up
_READY_TIMEOUT_SECONDS = 90

# Interval between connection attempts in the readiness polling
_READY_POLL_INTERVAL = 2.0

# Restart policy for instance containers. "unless-stopped" makes Docker
# restart the container automatically when the daemon/host restarts (e.g. reboot,
# wsl --shutdown, Docker update) — without this, instances stay stopped after
# any Docker restart and the operator has to restart them manually.
# "unless-stopped" (and not "always") respects an intentional stop by the operator.
_RESTART_POLICY = {"Name": "unless-stopped"}


# ---------------------------------------------------------------------------
# Safe SQL helpers
# ---------------------------------------------------------------------------


def _safe_identifier(name: str) -> str:
    """
    Normalizes a name into a safe PostgreSQL identifier.

    Lowercase, replaces non-alphanumerics with underscores, prefixes if it starts
    with a digit, truncates to 63 chars (PostgreSQL's limit for identifiers).
    """
    safe = re.sub(r"[^a-z0-9_]", "_", name.lower())
    if safe and safe[0].isdigit():
        safe = "db_" + safe
    return safe[:63] or "db_instance"


def _quote_ident(ident: str) -> str:
    """
    Wraps a PostgreSQL identifier in double quotes, escaping internal quotes.

    Used for role and database names in DDL statements.
    Example: 'my"role' → '"my""role"'
    """
    return '"' + ident.replace('"', '""') + '"'


def _pg_literal_string(value: str) -> str:
    """
    Builds a PostgreSQL string literal for use in DDL.

    CRITICAL: PostgreSQL does NOT support bind parameters ($1) in the PASSWORD
    clause of CREATE ROLE / ALTER ROLE. Using psycopg's text() with :param would generate $1,
    causing a SyntaxError on the database. This function builds the literal safely:
      - Single quotes are doubled (SQL standard: '' represents one quote)
      - Backslashes are doubled for compatibility with
        standard_conforming_strings=off (legacy mode)

    Example: "pass'word" → "'pass''word'"
    """
    escaped = value.replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


# ---------------------------------------------------------------------------
# DockerProvisioner
# ---------------------------------------------------------------------------


class DockerProvisioner(ProvisionerBase):
    """
    Provisions PostgreSQL databases as isolated Docker containers.

    For each DatabaseInstance created, this provisioner:
    1. Starts a postgres:<version>-alpine container with a unique name
    2. Waits for PostgreSQL to accept connections (polling)
    3. Connects as superuser and creates:
       - A dedicated role (db_user) with LOGIN and a random password
       - A dedicated database (db_name) owned by that role
       - Minimal privileges on the public schema
    4. Returns a ProvisionResult with all the connection information

    Security:
    - PROVISIONER_SUPERUSER_PASSWORD used only during setup, never stored
    - The instance's role has only CONNECT + CRUD on its own database
    - Containers publish their port only on 127.0.0.1 (localhost WSL2)
    - All containers live on the isolated dbaas-network
    """

    def __init__(self, client: docker.DockerClient) -> None:
        self._client = client
        self._ensure_network()

    def _ensure_network(self) -> None:
        """Creates the dbaas-network Docker network if it doesn't already exist."""
        try:
            self._client.networks.get(_NETWORK_NAME)
        except docker.errors.NotFound:
            self._client.networks.create(
                _NETWORK_NAME,
                driver="bridge",
                check_duplicate=True,
            )

    def _container_name(self, instance_id: uuid.UUID) -> str:
        """Generates a deterministic container name from the instance's UUID."""
        return f"{_CONTAINER_PREFIX}{str(instance_id).replace('-', '')[:12]}"

    def _generate_password(self, length: int = 32) -> str:
        """
        Generates a cryptographically secure password using secrets (CSPRNG).

        Uses only alphanumerics to avoid any SQL-escaping issue,
        while keeping high entropy: 62^32 ≈ 2^190 bits.
        """
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def _wait_until_database_ready(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        dbname: str,
        timeout: int = _READY_TIMEOUT_SECONDS,
    ) -> None:
        """
        Polls until PostgreSQL accepts connections or the timeout is reached.

        Why polling instead of a fixed sleep?
        The container starts in milliseconds, but the PostgreSQL inside it needs
        a few seconds to: initialize the data directory, recover the WAL
        (if needed), and start accepting connections. A fixed sleep would be
        unreliable — too short on a loaded machine, wasteful on a fast one.
        """
        deadline = time.monotonic() + timeout
        last_error: Optional[Exception] = None

        while time.monotonic() < deadline:
            try:
                with psycopg.connect(
                    host=host,
                    port=port,
                    user=user,
                    password=password,
                    dbname=dbname,
                    connect_timeout=2,
                ):
                    return  # Successful connection — PostgreSQL ready
            except Exception as exc:
                last_error = exc
                time.sleep(_READY_POLL_INTERVAL)

        raise RuntimeError(
            f"PostgreSQL was not ready within {timeout}s. Last error: {last_error}"
        )

    def _setup_database_and_role(
        self,
        host: str,
        port: int,
        superuser_password: str,
        db_name: str,
        db_user: str,
        db_password: str,
    ) -> None:
        """
        Connects as superuser and creates the role + database with minimal privileges.

        Privilege strategy (principle of least privilege):
        1. Create the role with LOGIN and a password (can only log in — no database yet)
        2. Create a database owned by that role (CREATE DATABASE — requires AUTOCOMMIT)
        3. Inside the new database: GRANT USAGE, CREATE on the public schema
        4. DEFAULT PRIVILEGES: future tables/sequences accessible by the role

        Why AUTOCOMMIT=True?
        CREATE DATABASE cannot run inside a transaction block in
        PostgreSQL. The psycopg connection opens an implicit transaction by default,
        so it needs to be disabled with autocommit=True for that statement.
        """
        quoted_user = _quote_ident(db_user)
        quoted_db = _quote_ident(db_name)
        password_literal = _pg_literal_string(db_password)

        # Step 1: connect to the default 'postgres' database as superuser
        with psycopg.connect(
            host=host,
            port=port,
            user="postgres",
            password=superuser_password,
            dbname="postgres",
            connect_timeout=5,
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                # Create the role with LOGIN + password (DDL — requires autocommit)
                cur.execute(
                    f"CREATE ROLE {quoted_user} WITH LOGIN PASSWORD {password_literal}"
                )
                # Create the database owned by the role
                cur.execute(
                    f"CREATE DATABASE {quoted_db} OWNER {quoted_user}"
                )

        # Step 2: connect to the NEW database to configure schema privileges
        with psycopg.connect(
            host=host,
            port=port,
            user="postgres",
            password=superuser_password,
            dbname=db_name,
            connect_timeout=5,
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                # Install pg_stat_statements on the instance's database
                # IF NOT EXISTS guarantees idempotency — no error if it already exists
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")

                # Grant pg_monitor to db_user — access to pg_stat_*, pg_locks,
                # pg_stat_statements etc. without needing superuser
                cur.execute(
                    f"GRANT pg_monitor TO {quoted_user}"
                )

                # Grant pg_signal_backend — lets db_user call
                # pg_terminate_backend() to end idle or long-running connections.
                # Required for the KILL_IDLE and KILL_LONG tasks from PHASE 6.
                # Without this grant, pg_terminate_backend() would silently return false
                # for other users' connections.
                cur.execute(
                    f"GRANT pg_signal_backend TO {quoted_user}"
                )

                # Allows resetting query statistics. pg_monitor only grants
                # READ access to pg_stat_statements; without this EXECUTE, the instance's
                # user can't reset the view — and the heavy provisioning queries
                # (dataset COPY, initial load) would stay forever in the
                # p99, describing the seed instead of the service.
                # The signature is explicit because the function has three parameters
                # with defaults: GRANT ... ON FUNCTION f() wouldn't match it.
                cur.execute(
                    f"GRANT EXECUTE ON FUNCTION "
                    f"pg_stat_statements_reset(oid, oid, bigint) TO {quoted_user}"
                )

                # Grant the REPLICATION privilege — required for pg_basebackup
                # (physical backup) to connect to this instance via the replication protocol.
                cur.execute(
                    f"ALTER ROLE {quoted_user} WITH REPLICATION"
                )

                # Allow using and creating objects in the public schema
                cur.execute(
                    f"GRANT USAGE, CREATE ON SCHEMA public TO {quoted_user}"
                )
                # DEFAULT PRIVILEGES: tables created in the future are already accessible
                cur.execute(
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {quoted_user}"
                )
                cur.execute(
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    f"GRANT USAGE, SELECT ON SEQUENCES TO {quoted_user}"
                )

    # ---------------------------------------------------------------------------
    # ProvisionerBase interface implementation
    # ---------------------------------------------------------------------------

    def create(
        self,
        instance_id: uuid.UUID,
        engine_version: str,
        memory_mb: int | None = None,
        cpu: int | None = None,
    ) -> ProvisionResult:
        """
        Provisions a complete PostgreSQL container for an instance.

        Flow:
        1. Generate unique names for the container, role, and database
        2. Generate a random password for the role
        3. Start the Docker container with a dynamic port on 127.0.0.1
        4. Wait for PostgreSQL to become ready (polling)
        5. Create the role + database with minimal privileges
        6. Return a ProvisionResult with all the connection information

        On any failure after the container comes up, it is removed (cleanup).
        """
        container_name = self._container_name(instance_id)
        instance_hex = str(instance_id).replace("-", "")
        db_user = f"inst_{instance_hex[:16]}"
        db_name = f"db_{instance_hex[:16]}"
        db_password = self._generate_password()

        # Create the WAL archive directory on the host before starting the container.
        # This directory is mounted as /archive inside the container and receives
        # the WAL segments via archive_command — the basis for future PITR.
        wal_dir = Path(settings.BACKUP_DIR).resolve() / str(instance_id) / "wal"
        wal_dir.mkdir(parents=True, exist_ok=True)
        # The bind mount preserves the host's owner/mode, but the one writing to /archive is
        # postgres INSIDE the container (uid 70 in the alpine image) — a uid that doesn't exist
        # on the host and never matches the directory's owner. Without write permission for
        # "others", every archive_command fails with "Permission denied": Postgres
        # never recycles the WAL (pg_wal grows until it fills the disk) and PITR is left without
        # a base. Explicit chmod because mkdir applies the process's umask (0755).
        wal_dir.chmod(0o777)

        # Start the container — port None on the host = Docker assigns a free port
        # ("127.0.0.1", None) = bind on localhost with a dynamic port
        run_kwargs: dict = {
            "image": f"postgres:{engine_version}-alpine",
            "name": container_name,
            "environment": {
                "POSTGRES_USER": "postgres",
                "POSTGRES_PASSWORD": settings.PROVISIONER_SUPERUSER_PASSWORD,
                "POSTGRES_DB": "postgres",
            },
            "ports": {"5432/tcp": ("127.0.0.1", None)},
            "network": _NETWORK_NAME,
            "detach": True,
            "remove": False,  # Keep the container after stop (needed for restart)
            "restart_policy": _RESTART_POLICY,  # Survive a Docker/host restart
            "command": [
                "-c", "shared_preload_libraries=pg_stat_statements",
                "-c", "wal_level=replica",
                "-c", "archive_mode=on",
                "-c", "archive_command=cp %p /archive/%f",
                # Readiness for replication (PHASE 9). max_wal_senders/slots already have a
                # default of 10 on PG10+, but making them explicit documents the intent and
                # protects against images with lower defaults. hot_standby doesn't affect
                # a primary, but is physically inherited by the standby via basebackup.
                "-c", "max_wal_senders=10",
                "-c", "max_replication_slots=10",
                "-c", "hot_standby=on",
            ],
            "volumes": {
                str(wal_dir): {"bind": "/archive", "mode": "rw"},
            },
        }

        # Apply resource limits when set on the instance.
        # mem_limit: string in "<n>m" format (e.g. "512m") — equivalent to --memory in docker run.
        # nano_cpus: integer in nanoCPUs (1 CPU = 1_000_000_000) — equivalent to --cpus in docker run.
        # Use nano_cpus (time-based throttling) instead of cpuset_cpus (core pinning):
        # cpu=2 means "can use up to the equivalent of 2 CPUs", not "can only use cores 0 and 1".
        if memory_mb is not None:
            run_kwargs["mem_limit"] = f"{memory_mb}m"
        if cpu is not None:
            run_kwargs["nano_cpus"] = int(cpu * 1_000_000_000)

        container = self._client.containers.run(**run_kwargs)

        # Reload the container's metadata to get the assigned port
        container.reload()
        port_bindings = container.ports.get("5432/tcp")
        if not port_bindings:
            container.remove(force=True)
            raise RuntimeError("Docker did not assign a port to the container")

        host_port = int(port_bindings[0]["HostPort"])
        host = "127.0.0.1"

        # Wait for PostgreSQL to accept connections
        try:
            self._wait_until_database_ready(
                host=host,
                port=host_port,
                user="postgres",
                password=settings.PROVISIONER_SUPERUSER_PASSWORD,
                dbname="postgres",
            )
        except RuntimeError:
            container.remove(force=True)
            raise

        # Create the dedicated role + database with minimal privileges
        try:
            self._setup_database_and_role(
                host=host,
                port=host_port,
                superuser_password=settings.PROVISIONER_SUPERUSER_PASSWORD,
                db_name=db_name,
                db_user=db_user,
                db_password=db_password,
            )
        except Exception as exc:
            container.remove(force=True)
            raise RuntimeError(f"Database setup failed: {exc}") from exc

        return ProvisionResult(
            container_id=container.id,
            host=host,
            port=host_port,
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
            container_name=container_name,
        )

    def start(self, instance_id: uuid.UUID) -> int:
        """
        Starts a stopped container and returns the port published on the host.

        Dynamically published ports (("127.0.0.1", None)) are NOT preserved
        by Docker between stop/start — each start can get a new port.
        We re-read the mapping after the start and return the current port.
        """
        container_name = self._container_name(instance_id)
        try:
            container = self._client.containers.get(container_name)
            # Also ensure the restart policy on already-existing containers
            # (created before this policy). Idempotent — a no-op if it's already
            # set. Applying it here makes the upgrade happen on the first start.
            container.update(restart_policy=_RESTART_POLICY)
            container.start()
        except docker.errors.NotFound as exc:
            raise RuntimeError(f"Container {container_name} not found") from exc

        container.reload()
        port_bindings = container.ports.get("5432/tcp")
        if not port_bindings:
            raise RuntimeError(
                "Docker did not assign a port to the container after start"
            )
        host_port = int(port_bindings[0]["HostPort"])

        # Wait for PostgreSQL to accept connections before returning. The container
        # starts in milliseconds, but PG takes a few seconds. Without this wait,
        # the RUNNING status would be reported before the database accepts connections — and
        # live queries (health, slow-queries) would fail in that window.
        self._wait_until_database_ready(
            host="127.0.0.1",
            port=host_port,
            user="postgres",
            password=settings.PROVISIONER_SUPERUSER_PASSWORD,
            dbname="postgres",
        )
        return host_port

    def stop(self, instance_id: uuid.UUID) -> None:
        """Stops a running container with a 10-second timeout."""
        container_name = self._container_name(instance_id)
        try:
            container = self._client.containers.get(container_name)
            container.stop(timeout=10)
        except docker.errors.NotFound as exc:
            raise RuntimeError(f"Container {container_name} not found") from exc

    def delete(self, instance_id: uuid.UUID) -> None:
        """
        Permanently removes a container.

        Idempotent: if the container no longer exists, the operation succeeds
        (pass on NotFound). This guarantees a second call to delete()
        won't raise an error if the container was already removed.
        """
        container_name = self._container_name(instance_id)
        try:
            container = self._client.containers.get(container_name)
            container.remove(force=True)
        except docker.errors.NotFound:
            pass  # Already removed — correct idempotent behavior
        # If this instance is a standby, also remove its PGDATA volume.
        # A no-op for normal instances (they use a bind mount, not a named volume).
        self._remove_volume_quietly(self._replica_volume_name(instance_id))

    def get_status(self, instance_id: uuid.UUID) -> ProvisionerStatus:
        """
        Returns the container's infra status without raising an exception.

        Used by the status_poller to detect containers that stopped
        unexpectedly (e.g. OOM, crash, Docker host restart).
        """
        container_name = self._container_name(instance_id)
        try:
            container = self._client.containers.get(container_name)
            if container.status == "running":
                return ProvisionerStatus.RUNNING
            return ProvisionerStatus.STOPPED
        except docker.errors.NotFound:
            return ProvisionerStatus.NOT_FOUND
        except Exception:
            return ProvisionerStatus.ERROR

    def get_port(self, instance_id: uuid.UUID) -> Optional[int]:
        """
        Returns the port currently published by a running container.

        Used by the status_poller to detect when Docker republished a
        different port (happens when the container restarts after a host restart) and
        resync connection_uri. Returns None if the container doesn't exist,
        isn't running, or doesn't have a published port yet — without raising an exception.
        """
        container_name = self._container_name(instance_id)
        try:
            container = self._client.containers.get(container_name)
            container.reload()
            if container.status != "running":
                return None
            port_bindings = container.ports.get("5432/tcp")
            if not port_bindings:
                return None
            return int(port_bindings[0]["HostPort"])
        except docker.errors.NotFound:
            return None
        except Exception:
            return None

    # ---------------------------------------------------------------------------
    # Replication (PHASE 9)
    # ---------------------------------------------------------------------------

    def _replica_volume_name(self, replica_instance_id: uuid.UUID) -> str:
        """Deterministic name of the Docker volume that holds the standby's PGDATA."""
        return f"dbaas-replica-{str(replica_instance_id).replace('-', '')[:12]}"

    def _allow_replication_on_primary(self, primary_container) -> None:
        """
        Allows replication connections on the primary.

        The image's default pg_hba.conf only allows `replication` from 127.0.0.1; the
        standby connects over the bridge network (172.x), so we append a
        `host replication` line covering the internal network and reload pg_hba via
        SIGHUP to the postmaster (PID 1 of the container). Without the reload, the new
        rule would only apply after a restart and pg_basebackup would fail with "no pg_hba.conf
        entry for replication". Idempotent (grep before appending). Safe: the
        containers only publish their port on 127.0.0.1 on the host.
        """
        line = "host replication all 0.0.0.0/0 scram-sha-256"
        # sh (alpine has no bash). $PGDATA points to the data dir inside the image.
        script = (
            f'grep -qF "{line}" "$PGDATA/pg_hba.conf" '
            f'|| echo "{line}" >> "$PGDATA/pg_hba.conf"'
        )
        exit_code, output = primary_container.exec_run(["sh", "-c", script])
        if exit_code != 0:
            raise RuntimeError(
                f"Failed to adjust the primary's pg_hba.conf: {output!r}"
            )
        # SIGHUP to the postmaster reloads pg_hba.conf/postgresql.conf without a restart.
        primary_container.kill(signal="SIGHUP")
        # Small wait for the reload to settle before pg_basebackup connects.
        time.sleep(1.5)

    def create_replica(
        self,
        replica_instance_id: uuid.UUID,
        primary_instance_id: uuid.UUID,
        engine_version: str,
        db_name: str,
        db_user: str,
        db_password: str,
        memory_mb: Optional[int] = None,
        cpu: Optional[int] = None,
    ) -> ProvisionResult:
        """
        Creates a streaming standby from an existing primary.

        Flow:
        1. Locate the primary's container and allow replication in pg_hba.conf
        2. `pg_basebackup` in a one-shot container → new volume (physical copy + `-R`,
           which writes standby.signal and primary_conninfo already with the password embedded)
        3. Bring up the standby container on top of that volume (boots into recovery/hot standby)
        4. Wait for it to accept read-only connections and return the connection info
        """
        primary_name = self._container_name(primary_instance_id)
        try:
            primary_container = self._client.containers.get(primary_name)
        except docker.errors.NotFound as exc:
            raise RuntimeError(
                f"Primary {primary_name} not found — cannot replicate"
            ) from exc

        self._allow_replication_on_primary(primary_container)

        image = f"postgres:{engine_version}-alpine"
        volume_name = self._replica_volume_name(replica_instance_id)
        replica_name = self._container_name(replica_instance_id)
        superuser_password = settings.PROVISIONER_SUPERUSER_PASSWORD

        # Step 2 — one-shot pg_basebackup. -R writes the standby config; passing the
        # full conninfo via -d means primary_conninfo already includes the password (without
        # this, the standby's walreceiver wouldn't authenticate). -Xs = stream the WAL in
        # parallel; -Fp = plain format (data dir ready to use).
        conninfo = (
            f"host={primary_name} port=5432 user=postgres "
            f"password={superuser_password} dbname=postgres"
        )
        try:
            self._client.containers.run(
                image=image,
                remove=True,
                network=_NETWORK_NAME,
                environment={"PGPASSWORD": superuser_password},
                volumes={volume_name: {"bind": "/target", "mode": "rw"}},
                entrypoint=["pg_basebackup"],
                command=[
                    "-D", "/target",
                    "-Fp", "-Xs", "-R", "-P",
                    "-d", conninfo,
                ],
            )
        except docker.errors.ContainerError as exc:
            # Partial/dirty volume — remove it to allow a clean retry.
            self._remove_volume_quietly(volume_name)
            raise RuntimeError(f"pg_basebackup failed: {exc}") from exc

        # Step 3 — bring up the standby on top of the replicated data dir. Since PGDATA
        # already exists, the entrypoint skips initdb and PostgreSQL enters recovery,
        # connecting to the primary via primary_conninfo.
        run_kwargs: dict = {
            "image": image,
            "name": replica_name,
            "ports": {"5432/tcp": ("127.0.0.1", None)},
            "network": _NETWORK_NAME,
            "detach": True,
            "remove": False,
            "restart_policy": _RESTART_POLICY,
            "volumes": {
                volume_name: {"bind": "/var/lib/postgresql/data", "mode": "rw"},
            },
            "command": ["-c", "hot_standby=on"],
        }
        if memory_mb is not None:
            run_kwargs["mem_limit"] = f"{memory_mb}m"
        if cpu is not None:
            run_kwargs["nano_cpus"] = int(cpu * 1_000_000_000)

        container = self._client.containers.run(**run_kwargs)
        container.reload()
        port_bindings = container.ports.get("5432/tcp")
        if not port_bindings:
            container.remove(force=True)
            self._remove_volume_quietly(volume_name)
            raise RuntimeError("Docker did not assign a port to the standby")
        host_port = int(port_bindings[0]["HostPort"])

        # Step 4 — wait for the standby to accept connections (consistent recovery).
        # Uses the superuser, whose password was physically copied from the primary.
        try:
            self._wait_until_database_ready(
                host="127.0.0.1",
                port=host_port,
                user="postgres",
                password=superuser_password,
                dbname="postgres",
            )
        except RuntimeError:
            container.remove(force=True)
            self._remove_volume_quietly(volume_name)
            raise

        return ProvisionResult(
            container_id=container.id,
            host="127.0.0.1",
            port=host_port,
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
            container_name=replica_name,
        )

    def promote_replica(self, replica_instance_id: uuid.UUID) -> None:
        """
        Promotes the standby to primary via pg_promote().

        Connects as superuser and calls pg_promote(); PostgreSQL exits
        recovery mode, removes standby.signal, and starts accepting writes.
        """
        host_port = self.get_port(replica_instance_id)
        if host_port is None:
            raise RuntimeError("Standby is not running — cannot promote")
        try:
            with psycopg.connect(
                host="127.0.0.1",
                port=host_port,
                user="postgres",
                password=settings.PROVISIONER_SUPERUSER_PASSWORD,
                dbname="postgres",
                connect_timeout=5,
                autocommit=True,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_promote(wait => true)")
        except Exception as exc:
            raise RuntimeError(f"Failed to promote the standby: {exc}") from exc

    def _remove_volume_quietly(self, volume_name: str) -> None:
        """Removes a Docker volume, ignoring absence/errors (best-effort cleanup)."""
        try:
            self._client.volumes.get(volume_name).remove(force=True)
        except Exception:
            pass

    def logs(self, instance_id: uuid.UUID, tail: int = 200) -> str:
        """
        Returns the last `tail` log lines of the instance's container.

        timestamps=True prefixes each line with the time — useful for debugging
        event order. Decodes with errors="replace" so it never breaks on
        invalid bytes in the log stream.
        """
        container_name = self._container_name(instance_id)
        try:
            container = self._client.containers.get(container_name)
            raw = container.logs(tail=tail, timestamps=True)
            return raw.decode("utf-8", errors="replace")
        except docker.errors.NotFound as exc:
            raise RuntimeError(f"Container {container_name} not found") from exc
