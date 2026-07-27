from functools import lru_cache

import docker
import docker.errors

from src.services.provisioning.docker_provisioner import DockerProvisioner


@lru_cache(maxsize=1)
def get_provisioner() -> DockerProvisioner:
    """
    Returns the singleton DockerProvisioner instance.

    Why @lru_cache(maxsize=1)?
    docker.from_env() opens an HTTP connection to the Docker daemon via a Unix socket
    (/var/run/docker.sock). Opening this connection on every request would be costly and
    unnecessary. lru_cache guarantees the connection is opened ONLY ONCE
    (on the first call) and reused on every subsequent call.

    Called explicitly in FastAPI's lifespan (main.py) so that any
    failure connecting to Docker happens at startup — before any request
    arrives. This is the "fail fast" pattern: better to know Docker isn't
    available when the application starts than on the first provisioning attempt.

    If Docker isn't running, raises docker.errors.DockerException
    with a clear message about the connection problem.
    """
    client = docker.from_env()
    return DockerProvisioner(client)
