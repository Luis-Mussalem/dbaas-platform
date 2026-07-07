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
    def create(
        self,
        instance_id: uuid.UUID,
        engine_version: str,
        memory_mb: int | None = None,
        cpu: int | None = None,
    ) -> ProvisionResult:
        """
        Provisionar um novo container de banco de dados.

        Responsabilidades:
        - Iniciar o container Docker
        - Aguardar o PostgreSQL aceitar conexões
        - Criar o banco e a role dedicada com privilégios mínimos

        memory_mb: limite de RAM em MiB (None = sem limite)
        cpu: vCPUs máximas (None = sem limite; convertido para nano_cpus internamente)

        Levanta RuntimeError se o provisionamento falhar por qualquer motivo.
        """
        ...

    @abstractmethod
    def start(self, instance_id: uuid.UUID) -> int:
        """
        Iniciar um container parado e retornar a porta publicada no host.

        Portas dinâmicas mudam entre stop/start; o serviço usa o retorno para
        ressincronizar a connection_uri. Levanta RuntimeError em falha.
        """
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

    @abstractmethod
    def get_port(self, instance_id: uuid.UUID) -> int | None:
        """
        Retornar a porta publicada de um container em execução, ou None.

        O serviço usa isto para ressincronizar a connection_uri quando o Docker
        republica uma porta diferente após religar o container. Não lança exceção.
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
        Provisionar um standby que replica em streaming a partir de um primário.

        A réplica é uma cópia FÍSICA (pg_basebackup) do primário, então herda o
        mesmo banco/role/senha — por isso db_name/db_user/db_password são os do
        primário (o serviço os decripta da connection_uri) e apenas ecoados no
        ProvisionResult junto com o host/porta do novo container standby.

        Levanta RuntimeError se o primário não estiver acessível ou o basebackup falhar.
        """
        ...

    @abstractmethod
    def promote_replica(self, replica_instance_id: uuid.UUID) -> None:
        """
        Promover um standby a primário standalone (failover manual).

        Após a promoção o container deixa de aplicar WAL do primário e passa a
        aceitar escritas. Levanta RuntimeError em falha.
        """
        ...

    @abstractmethod
    def logs(self, instance_id: uuid.UUID, tail: int = 200) -> str:
        """
        Retornar as últimas `tail` linhas de log (stdout/stderr) do container.

        Levanta RuntimeError se o container não existir.
        """
        ...
