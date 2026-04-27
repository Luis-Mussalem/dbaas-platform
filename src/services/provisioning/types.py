from dataclasses import dataclass
from enum import Enum as PyEnum


class ProvisionerStatus(str, PyEnum):
    """
    Infra-level estados que o provisionador reporta sobre um container.

    Separado do InstanceStatus (domínio da aplicação) intencionalmente:
    o InstanceStatus representa o que o USUÁRIO vê (running, stopped, failed…);
    o ProvisionerStatus representa o que o DOCKER reporta.

    O status_poller faz a ponte: se o InstanceStatus é RUNNING mas o
    ProvisionerStatus é NOT_FOUND ou ERROR, o poller marca a instância como FAILED.
    """

    RUNNING = "running"
    STOPPED = "stopped"
    NOT_FOUND = "not_found"
    ERROR = "error"


@dataclass
class ProvisionResult:
    """
    Objeto retornado pelo ProvisionerBase.create() após o container estar pronto.

    É transiente — existe apenas na memória durante a operação de criação.
    O campo db_password é plaintext aqui e NUNCA é armazenado diretamente.

    Fluxo de vida do db_password:
        provisioner.create() → ProvisionResult.db_password (memória)
        → constrói connection_uri como string
        → encrypt_value(connection_uri) → string cifrada (Fernet)
        → armazenada em DatabaseInstance.connection_uri (banco)
        → ProvisionResult descartado pelo garbage collector

    O password nunca aparece em logs, respostas HTTP, ou no banco em texto claro.
    """

    container_id: str       # Hash hexadecimal curto do container Docker
    host: str               # IP do host para conectar (127.0.0.1 no WSL2)
    port: int               # Porta do host atribuída dinamicamente pelo Docker
    db_name: str            # Nome do banco criado dentro do container
    db_user: str            # Role dedicada com privilégios mínimos
    db_password: str        # Senha em plaintext — usada uma vez, depois descartada
    container_name: str     # Nome human-readable do container Docker
