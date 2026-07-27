import uuid
from abc import ABC, abstractmethod

from src.services.provisioning.types import ProvisionResult, ProvisionerStatus


class ProvisionerBase(ABC):
    """
    Abstract interface for all infrastructure providers.

    Why an interface here?
    The rest of the application (instance service, status poller) talks ONLY
    to this interface. That means we can swap the implementation
    (local Docker → remote server → managed cloud) without changing a single
    line of business code.

    All methods are SYNCHRONOUS because we use sync SQLAlchemy throughout
    the application. The methods are called from async FastAPI routes
    via asyncio.to_thread() so as not to block the event loop.
    """

    @abstractmethod
    def create(
        self,
        instance_id: uuid.UUID,
        engine_version: str,
        memory_mb: int | None = None,
        cpu: int | None = None,
    ) -> ProvisionResult:
        """
        Provisions a new database container.

        Responsibilities:
        - Start the Docker container
        - Wait for PostgreSQL to accept connections
        - Create the database and the dedicated role with minimal privileges

        memory_mb: RAM limit in MiB (None = no limit)
        cpu: max vCPUs (None = no limit; converted to nano_cpus internally)

        Raises RuntimeError if provisioning fails for any reason.
        """
        ...

    @abstractmethod
    def start(self, instance_id: uuid.UUID) -> int:
        """
        Starts a stopped container and returns the port published on the host.

        Dynamic ports change between stop/start; the service uses the return value to
        resync connection_uri. Raises RuntimeError on failure.
        """
        ...

    @abstractmethod
    def stop(self, instance_id: uuid.UUID) -> None:
        """Gracefully stops a running container. Raises RuntimeError on failure."""
        ...

    @abstractmethod
    def delete(self, instance_id: uuid.UUID) -> None:
        """Permanently removes the container. Idempotent (not found = ok)."""
        ...

    @abstractmethod
    def get_status(self, instance_id: uuid.UUID) -> ProvisionerStatus:
        """Returns the container's current infra status without raising an exception."""
        ...

    @abstractmethod
    def get_port(self, instance_id: uuid.UUID) -> int | None:
        """
        Returns the published port of a running container, or None.

        The service uses this to resync connection_uri when Docker
        republishes a different port after restarting the container. Does not raise an exception.
        """
        ...

    @abstractmethod
    def create_replica(
        self,
        replica_instance_id: uuid.UUID,
        primary_instance_id: uuid.UUID,
        engine_version: str,
        db_name: str,
        db_user: str,
        db_password: str,
        memory_mb: int | None = None,
        cpu: int | None = None,
    ) -> ProvisionResult:
        """
        Provisions a standby that streams replication from a primary.

        The replica is a PHYSICAL copy (pg_basebackup) of the primary, so it inherits the
        same database/role/password — that's why db_name/db_user/db_password are the
        primary's (the service decrypts them from connection_uri) and are just echoed back
        in the ProvisionResult along with the host/port of the new standby container.

        Raises RuntimeError if the primary is unreachable or the basebackup fails.
        """
        ...

    @abstractmethod
    def promote_replica(self, replica_instance_id: uuid.UUID) -> None:
        """
        Promotes a standby to a standalone primary (manual failover).

        After promotion the container stops applying WAL from the primary and
        starts accepting writes. Raises RuntimeError on failure.
        """
        ...

    @abstractmethod
    def logs(self, instance_id: uuid.UUID, tail: int = 200) -> str:
        """
        Returns the last `tail` log lines (stdout/stderr) of the container.

        Raises RuntimeError if the container doesn't exist.
        """
        ...
