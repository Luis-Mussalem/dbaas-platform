import uuid
from abc import ABC, abstractmethod

from src.services.provisioning.types import ProvisionResult, ProvisionerStatus


class ProvisionerBase(ABC):
    """
    Interface abstrata para todos os provedores de infraestrutura.

    Por que uma interface aqui?
    O restante da aplicação (instance service, status poller) fala APENAS
    com esta interface. Isso significa que podemos trocar a implementação
    (Docker local → servidor remoto → cloud managed) sem alterar nenhuma
    linha de código de negócio.

    Todos os métodos são SÍNCRONOS porque usamos SQLAlchemy sync em toda
    a aplicação. Os métodos são chamados a partir de rotas FastAPI async
    via asyncio.to_thread() para não bloquear o event loop.
    """

    @abstractmethod
    def create(self, instance_id: uuid.UUID, engine_version: str) -> ProvisionResult:
        """
        Provisionar um novo container de banco de dados.

        Responsabilidades:
        - Iniciar o container Docker
        - Aguardar o PostgreSQL aceitar conexões
        - Criar o banco e a role dedicada com privilégios mínimos

        Levanta RuntimeError se o provisionamento falhar por qualquer motivo.
        """
        ...

    @abstractmethod
    def start(self, instance_id: uuid.UUID) -> None:
        """Iniciar um container parado. Levanta RuntimeError em falha."""
        ...

    @abstractmethod
    def stop(self, instance_id: uuid.UUID) -> None:
        """Parar um container em execução graciosamente. Levanta RuntimeError em falha."""
        ...

    @abstractmethod
    def delete(self, instance_id: uuid.UUID) -> None:
        """Remover o container permanentemente. Idempotente (not found = ok)."""
        ...

    @abstractmethod
    def get_status(self, instance_id: uuid.UUID) -> ProvisionerStatus:
        """Retornar o status atual de infra do container sem lançar exceção."""
        ...
