from functools import lru_cache

import docker
import docker.errors

from src.services.provisioning.docker_provisioner import DockerProvisioner


@lru_cache(maxsize=1)
def get_provisioner() -> DockerProvisioner:
    """
    Retornar a instância singleton do DockerProvisioner.

    Por que @lru_cache(maxsize=1)?
    docker.from_env() abre uma conexão HTTP com o daemon Docker via socket Unix
    (/var/run/docker.sock). Abrir essa conexão a cada request seria custoso e
    desnecessário. O lru_cache garante que a conexão é aberta UMA ÚNICA VEZ
    (na primeira chamada) e reutilizada em todas as chamadas subsequentes.

    Chamado explicitamente no lifespan do FastAPI (main.py) para que qualquer
    falha na conexão com o Docker aconteça no startup — antes de qualquer request
    chegar. Isso é o padrão "fail fast": melhor saber que o Docker não está
    disponível ao iniciar a aplicação do que na primeira tentativa de provisionar.

    Se o Docker não estiver rodando, levanta docker.errors.DockerException
    com mensagem clara sobre o problema de conexão.
    """
    client = docker.from_env()
    return DockerProvisioner(client)
