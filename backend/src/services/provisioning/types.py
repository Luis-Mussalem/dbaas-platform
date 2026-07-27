from dataclasses import dataclass
from enum import Enum as PyEnum


class ProvisionerStatus(str, PyEnum):
    """
    Infra-level states the provisioner reports about a container.

    Deliberately separate from InstanceStatus (the application's domain):
    InstanceStatus represents what the USER sees (running, stopped, failed…);
    ProvisionerStatus represents what DOCKER reports.

    The status_poller bridges the two: if InstanceStatus is RUNNING but
    ProvisionerStatus is NOT_FOUND or ERROR, the poller marks the instance as FAILED.
    """

    RUNNING = "running"
    STOPPED = "stopped"
    NOT_FOUND = "not_found"
    ERROR = "error"


@dataclass
class ProvisionResult:
    """
    Object returned by ProvisionerBase.create() once the container is ready.

    It's transient — exists only in memory during the creation operation.
    The db_password field is plaintext here and is NEVER stored directly.

    db_password's lifecycle:
        provisioner.create() → ProvisionResult.db_password (memory)
        → builds connection_uri as a string
        → encrypt_value(connection_uri) → encrypted string (Fernet)
        → stored in DatabaseInstance.connection_uri (database)
        → ProvisionResult discarded by the garbage collector

    The password never appears in logs, HTTP responses, or in the database in plaintext.
    """

    container_id: str       # Short hexadecimal hash of the Docker container
    host: str               # Host IP to connect to (127.0.0.1 on WSL2)
    port: int               # Host port dynamically assigned by Docker
    db_name: str            # Name of the database created inside the container
    db_user: str            # Dedicated role with minimal privileges
    db_password: str        # Plaintext password — used once, then discarded
    container_name: str     # Human-readable name of the Docker container
