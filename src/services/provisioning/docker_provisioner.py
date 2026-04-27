import re
import secrets
import string
import time
import uuid
from typing import Optional

import docker
import docker.errors
import psycopg

from src.core.config import settings
from src.services.provisioning.base import ProvisionerBase
from src.services.provisioning.types import ProvisionResult, ProvisionerStatus

# Prefixo para todos os containers provisionados pela plataforma
_CONTAINER_PREFIX = "palmtreedb-inst-"

# Nome da rede Docker isolada para as instâncias gerenciadas
_NETWORK_NAME = "palmtreedb-network"

# Quantos segundos esperar o PostgreSQL aceitar conexões antes de desistir
_READY_TIMEOUT_SECONDS = 90

# Intervalo entre tentativas de conexão no polling de readiness
_READY_POLL_INTERVAL = 2.0


# ---------------------------------------------------------------------------
# Helpers de SQL seguro
# ---------------------------------------------------------------------------


def _safe_identifier(name: str) -> str:
    """
    Normalizar um nome para um identificador PostgreSQL seguro.

    Lowercase, substitui não-alfanuméricos por underscores, prefixo se começar
    com dígito, trunca em 63 chars (limite do PostgreSQL para identificadores).
    """
    safe = re.sub(r"[^a-z0-9_]", "_", name.lower())
    if safe and safe[0].isdigit():
        safe = "db_" + safe
    return safe[:63] or "db_instance"


def _quote_ident(ident: str) -> str:
    """
    Envolver um identificador PostgreSQL em aspas duplas, escapando aspas internas.

    Usado para nomes de role e banco em instruções DDL.
    Exemplo: 'my"role' → '"my""role"'
    """
    return '"' + ident.replace('"', '""') + '"'


def _pg_literal_string(value: str) -> str:
    """
    Construir um literal de string PostgreSQL para uso em DDL.

    CRÍTICO: PostgreSQL NÃO suporta parâmetros bind ($1) na cláusula PASSWORD
    de CREATE ROLE / ALTER ROLE. Usar text() do psycopg com :param geraria $1,
    causando SyntaxError no banco. Esta função constrói o literal de forma segura:
      - Aspas simples são duplicadas (padrão SQL: '' representa uma aspas)
      - Barras invertidas são duplicadas para compatibilidade com
        standard_conforming_strings=off (modo legado)

    Exemplo: "pass'word" → "'pass''word'"
    """
    escaped = value.replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


# ---------------------------------------------------------------------------
# DockerProvisioner
# ---------------------------------------------------------------------------


class DockerProvisioner(ProvisionerBase):
    """
    Provisiona bancos PostgreSQL como containers Docker isolados.

    Para cada DatabaseInstance criada, este provisionador:
    1. Inicia um container postgres:<version>-alpine com nome único
    2. Aguarda o PostgreSQL aceitar conexões (polling)
    3. Conecta como superuser e cria:
       - Uma role dedicada (db_user) com LOGIN e senha aleatória
       - Um banco dedicado (db_name) de propriedade dessa role
       - Privilégios mínimos no schema public
    4. Retorna ProvisionResult com todas as informações de conexão

    Segurança:
    - PROVISIONER_SUPERUSER_PASSWORD usado apenas no setup, nunca armazenado
    - A role da instância tem apenas CONNECT + CRUD no próprio banco
    - Containers publicam porta apenas em 127.0.0.1 (localhost WSL2)
    - Todos os containers ficam na rede Docker isolada palmtreedb-network
    """

    def __init__(self, client: docker.DockerClient) -> None:
        self._client = client
        self._ensure_network()

    def _ensure_network(self) -> None:
        """Criar a rede Docker palmtreedb-network se ainda não existir."""
        try:
            self._client.networks.get(_NETWORK_NAME)
        except docker.errors.NotFound:
            self._client.networks.create(
                _NETWORK_NAME,
                driver="bridge",
                check_duplicate=True,
            )

    def _container_name(self, instance_id: uuid.UUID) -> str:
        """Gerar nome de container determinístico a partir do UUID da instância."""
        return f"{_CONTAINER_PREFIX}{str(instance_id).replace('-', '')[:12]}"

    def _generate_password(self, length: int = 32) -> str:
        """
        Gerar uma senha criptograficamente segura usando secrets (CSPRNG).

        Usa apenas alfanuméricos para evitar qualquer problema de escaping SQL,
        mantendo alta entropia: 62^32 ≈ 2^190 bits.
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
        Fazer polling até o PostgreSQL aceitar conexões ou o timeout ser atingido.

        Por que polling e não sleep fixo?
        O container inicia em milissegundos, mas o PostgreSQL dentro dele precisa
        de alguns segundos para: inicializar o data directory, recuperar o WAL
        (se necessário), e começar a aceitar conexões. Um sleep fixo seria
        não confiável — muito curto em máquina carregada, desperdício em máquina rápida.
        """
        dsn = (
            f"host={host} port={port} user={user} password={password} "
            f"dbname={dbname} connect_timeout=2"
        )
        deadline = time.monotonic() + timeout
        last_error: Optional[Exception] = None

        while time.monotonic() < deadline:
            try:
                with psycopg.connect(dsn):
                    return  # Conexão bem-sucedida — PostgreSQL pronto
            except Exception as exc:
                last_error = exc
                time.sleep(_READY_POLL_INTERVAL)

        raise RuntimeError(
            f"PostgreSQL não ficou pronto em {timeout}s. Último erro: {last_error}"
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
        Conectar como superuser e criar a role + banco com privilégios mínimos.

        Estratégia de privilégios (princípio do menor privilégio):
        1. Criar role com LOGIN e senha (só pode logar — ainda sem banco)
        2. Criar banco de propriedade dessa role (CREATE DATABASE — AUTOCOMMIT obrigatório)
        3. Dentro do novo banco: GRANT USAGE, CREATE no schema public
        4. DEFAULT PRIVILEGES: futuras tabelas/sequências acessíveis pela role

        Por que AUTOCOMMIT=True?
        CREATE DATABASE não pode rodar dentro de um bloco de transação no
        PostgreSQL. A conexão psycopg abre uma transação implícita por padrão,
        então precisa desativá-la com autocommit=True para esse statement.
        """
        quoted_user = _quote_ident(db_user)
        quoted_db = _quote_ident(db_name)
        password_literal = _pg_literal_string(db_password)

        # Passo 1: conectar ao banco padrão 'postgres' como superuser
        admin_dsn = (
            f"host={host} port={port} user=postgres "
            f"password={superuser_password} dbname=postgres connect_timeout=5"
        )
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                # Criar a role com LOGIN + senha (DDL — requer autocommit)
                cur.execute(
                    f"CREATE ROLE {quoted_user} WITH LOGIN PASSWORD {password_literal}"
                )
                # Criar o banco de propriedade da role
                cur.execute(
                    f"CREATE DATABASE {quoted_db} OWNER {quoted_user}"
                )

        # Passo 2: conectar ao NOVO banco para configurar privilégios de schema
        app_dsn = (
            f"host={host} port={port} user=postgres "
            f"password={superuser_password} dbname={db_name} connect_timeout=5"
        )
        with psycopg.connect(app_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                # Permitir uso e criação de objetos no schema public
                cur.execute(
                    f"GRANT USAGE, CREATE ON SCHEMA public TO {quoted_user}"
                )
                # DEFAULT PRIVILEGES: tabelas criadas no futuro já são acessíveis
                cur.execute(
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {quoted_user}"
                )
                cur.execute(
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    f"GRANT USAGE, SELECT ON SEQUENCES TO {quoted_user}"
                )

    # ---------------------------------------------------------------------------
    # Implementação da interface ProvisionerBase
    # ---------------------------------------------------------------------------

    def create(self, instance_id: uuid.UUID, engine_version: str) -> ProvisionResult:
        """
        Provisionar um container PostgreSQL completo para uma instância.

        Fluxo:
        1. Gerar nomes únicos para container, role e banco
        2. Gerar senha aleatória para a role
        3. Iniciar container Docker com porta dinâmica em 127.0.0.1
        4. Aguardar PostgreSQL ficar pronto (polling)
        5. Criar role + banco com privilégios mínimos
        6. Retornar ProvisionResult com todas as informações de conexão

        Em qualquer falha após o container subir, ele é removido (cleanup).
        """
        container_name = self._container_name(instance_id)
        instance_hex = str(instance_id).replace("-", "")
        db_user = f"inst_{instance_hex[:16]}"
        db_name = f"db_{instance_hex[:16]}"
        db_password = self._generate_password()

        # Iniciar container — porta None no host = Docker atribui porta livre
        # ("127.0.0.1", None) = bind em localhost com porta dinâmica
        container = self._client.containers.run(
            image=f"postgres:{engine_version}-alpine",
            name=container_name,
            environment={
                "POSTGRES_USER": "postgres",
                "POSTGRES_PASSWORD": settings.PROVISIONER_SUPERUSER_PASSWORD,
                "POSTGRES_DB": "postgres",
            },
            ports={"5432/tcp": ("127.0.0.1", None)},
            network=_NETWORK_NAME,
            detach=True,
            remove=False,  # Manter container após stop (necessário para restart)
        )

        # Recarregar metadados do container para obter a porta atribuída
        container.reload()
        port_bindings = container.ports.get("5432/tcp")
        if not port_bindings:
            container.remove(force=True)
            raise RuntimeError("Docker não atribuiu uma porta ao container")

        host_port = int(port_bindings[0]["HostPort"])
        host = "127.0.0.1"

        # Aguardar PostgreSQL aceitar conexões
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

        # Criar role dedicada + banco com privilégios mínimos
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
            raise RuntimeError(f"Setup do banco falhou: {exc}") from exc

        return ProvisionResult(
            container_id=container.id,
            host=host,
            port=host_port,
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
            container_name=container_name,
        )

    def start(self, instance_id: uuid.UUID) -> None:
        """Iniciar um container parado."""
        container_name = self._container_name(instance_id)
        try:
            container = self._client.containers.get(container_name)
            container.start()
        except docker.errors.NotFound as exc:
            raise RuntimeError(f"Container {container_name} não encontrado") from exc

    def stop(self, instance_id: uuid.UUID) -> None:
        """Parar um container em execução com timeout de 10 segundos."""
        container_name = self._container_name(instance_id)
        try:
            container = self._client.containers.get(container_name)
            container.stop(timeout=10)
        except docker.errors.NotFound as exc:
            raise RuntimeError(f"Container {container_name} não encontrado") from exc

    def delete(self, instance_id: uuid.UUID) -> None:
        """
        Remover um container permanentemente.

        Idempotente: se o container já não existir, a operação é bem-sucedida
        (pass on NotFound). Isso garante que uma segunda chamada a delete()
        não vai levantar erro se o container já foi removido.
        """
        container_name = self._container_name(instance_id)
        try:
            container = self._client.containers.get(container_name)
            container.remove(force=True)
        except docker.errors.NotFound:
            pass  # Já removido — comportamento idempotente correto

    def get_status(self, instance_id: uuid.UUID) -> ProvisionerStatus:
        """
        Retornar o status de infra do container sem lançar exceção.

        Usado pelo status_poller para detectar containers que pararam
        inesperadamente (ex: OOM, crash, reinicialização do host Docker).
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
