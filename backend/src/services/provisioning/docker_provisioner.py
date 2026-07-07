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

# Prefixo para todos os containers provisionados pela plataforma
_CONTAINER_PREFIX = "dbaas-inst-"

# Nome da rede Docker isolada para as instâncias gerenciadas
_NETWORK_NAME = "dbaas-network"

# Quantos segundos esperar o PostgreSQL aceitar conexões antes de desistir
_READY_TIMEOUT_SECONDS = 90

# Intervalo entre tentativas de conexão no polling de readiness
_READY_POLL_INTERVAL = 2.0

# Política de restart dos containers de instância. "unless-stopped" faz o Docker
# religar o container automaticamente quando o daemon/host reinicia (ex: reboot,
# wsl --shutdown, update do Docker) — sem isto, as instâncias ficam paradas após
# qualquer restart do Docker e o operador precisa religar manualmente.
# "unless-stopped" (e não "always") respeita um stop intencional do operador.
_RESTART_POLICY = {"Name": "unless-stopped"}


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
    - Todos os containers ficam na rede Docker isolada dbaas-network
    """

    def __init__(self, client: docker.DockerClient) -> None:
        self._client = client
        self._ensure_network()

    def _ensure_network(self) -> None:
        """Criar a rede Docker dbaas-network se ainda não existir."""
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
                # Criar a role com LOGIN + senha (DDL — requer autocommit)
                cur.execute(
                    f"CREATE ROLE {quoted_user} WITH LOGIN PASSWORD {password_literal}"
                )
                # Criar o banco de propriedade da role
                cur.execute(
                    f"CREATE DATABASE {quoted_db} OWNER {quoted_user}"
                )

        # Passo 2: conectar ao NOVO banco para configurar privilégios de schema
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
                # Instalar pg_stat_statements no banco da instância
                # IF NOT EXISTS garante idempotência — sem erro se já existir
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")

                # Conceder pg_monitor ao db_user — acesso a pg_stat_*, pg_locks,
                # pg_stat_statements etc. sem precisar de superuser
                cur.execute(
                    f"GRANT pg_monitor TO {quoted_user}"
                )

                # Conceder pg_signal_backend — permite que o db_user chame
                # pg_terminate_backend() para encerrar conexões idle ou longas.
                # Necessário para as tarefas KILL_IDLE e KILL_LONG da FASE 6.
                # Sem esse grant, pg_terminate_backend() retornaria false silenciosamente
                # para conexões de outros usuários.
                cur.execute(
                    f"GRANT pg_signal_backend TO {quoted_user}"
                )

                # Conceder privilégio REPLICATION — necessário para pg_basebackup
                # (backup físico) conectar a esta instância via protocolo de replicação.
                cur.execute(
                    f"ALTER ROLE {quoted_user} WITH REPLICATION"
                )

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

    def create(
        self,
        instance_id: uuid.UUID,
        engine_version: str,
        memory_mb: int | None = None,
        cpu: int | None = None,
    ) -> ProvisionResult:
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

        # Criar diretório WAL archive no host antes de iniciar o container.
        # Este diretório é montado como /archive dentro do container e recebe
        # os segmentos WAL via archive_command — base para PITR no futuro.
        wal_dir = Path(settings.BACKUP_DIR).resolve() / str(instance_id) / "wal"
        wal_dir.mkdir(parents=True, exist_ok=True)

        # Iniciar container — porta None no host = Docker atribui porta livre
        # ("127.0.0.1", None) = bind em localhost com porta dinâmica
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
            "remove": False,  # Manter container após stop (necessário para restart)
            "restart_policy": _RESTART_POLICY,  # Sobreviver a restart do Docker/host
            "command": [
                "-c", "shared_preload_libraries=pg_stat_statements",
                "-c", "wal_level=replica",
                "-c", "archive_mode=on",
                "-c", "archive_command=cp %p /archive/%f",
                # Prontidão para replicação (FASE 9). max_wal_senders/slots já têm
                # default 10 no PG10+, mas explicitá-los documenta a intenção e
                # protege contra imagens com defaults menores. hot_standby não afeta
                # um primário, mas é herdado fisicamente pelo standby via basebackup.
                "-c", "max_wal_senders=10",
                "-c", "max_replication_slots=10",
                "-c", "hot_standby=on",
            ],
            "volumes": {
                str(wal_dir): {"bind": "/archive", "mode": "rw"},
            },
        }

        # Aplicar limites de recurso quando definidos na instância.
        # mem_limit: string no formato "<n>m" (ex: "512m") — equivale a --memory no docker run.
        # nano_cpus: inteiro em nanoCPUs (1 CPU = 1_000_000_000) — equivale a --cpus no docker run.
        # Usar nano_cpus (throttling por tempo) em vez de cpuset_cpus (pinning de núcleos):
        # cpu=2 significa "pode usar até 2 CPUs equivalentes", não "só pode usar os núcleos 0 e 1".
        if memory_mb is not None:
            run_kwargs["mem_limit"] = f"{memory_mb}m"
        if cpu is not None:
            run_kwargs["nano_cpus"] = int(cpu * 1_000_000_000)

        container = self._client.containers.run(**run_kwargs)

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

    def start(self, instance_id: uuid.UUID) -> int:
        """
        Iniciar um container parado e retornar a porta publicada no host.

        Portas publicadas dinamicamente (("127.0.0.1", None)) NÃO são preservadas
        pelo Docker entre stop/start — cada start pode receber uma porta nova.
        Relemos o mapeamento após o start e devolvemos a porta atual.
        """
        container_name = self._container_name(instance_id)
        try:
            container = self._client.containers.get(container_name)
            # Garantir a política de restart também em containers já existentes
            # (criados antes desta política). Idempotente — no-op se já estiver
            # definida. Aplicar aqui faz o upgrade acontecer no primeiro start.
            container.update(restart_policy=_RESTART_POLICY)
            container.start()
        except docker.errors.NotFound as exc:
            raise RuntimeError(f"Container {container_name} não encontrado") from exc

        container.reload()
        port_bindings = container.ports.get("5432/tcp")
        if not port_bindings:
            raise RuntimeError(
                "Docker não atribuiu uma porta ao container após o start"
            )
        host_port = int(port_bindings[0]["HostPort"])

        # Aguardar o PostgreSQL aceitar conexões antes de retornar. O container
        # inicia em milissegundos, mas o PG leva alguns segundos. Sem esta espera,
        # o status RUNNING seria reportado antes do banco aceitar conexões — e
        # consultas ao vivo (health, slow-queries) falhariam nessa janela.
        self._wait_until_database_ready(
            host="127.0.0.1",
            port=host_port,
            user="postgres",
            password=settings.PROVISIONER_SUPERUSER_PASSWORD,
            dbname="postgres",
        )
        return host_port

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
        # Se esta instância for um standby, remove também seu volume de PGDATA.
        # No-op para instâncias normais (usam bind mount, não volume nomeado).
        self._remove_volume_quietly(self._replica_volume_name(instance_id))

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

    def get_port(self, instance_id: uuid.UUID) -> Optional[int]:
        """
        Retornar a porta atualmente publicada por um container em execução.

        Usado pelo status_poller para detectar quando o Docker republicou uma
        porta diferente (acontece ao religar o container após restart do host) e
        ressincronizar a connection_uri. Retorna None se o container não existe,
        não está rodando, ou ainda não tem porta publicada — sem lançar exceção.
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
    # Replicação (FASE 9)
    # ---------------------------------------------------------------------------

    def _replica_volume_name(self, replica_instance_id: uuid.UUID) -> str:
        """Nome determinístico do volume Docker que guarda o PGDATA do standby."""
        return f"dbaas-replica-{str(replica_instance_id).replace('-', '')[:12]}"

    def _allow_replication_on_primary(self, primary_container) -> None:
        """
        Liberar conexões de replicação no primário.

        O pg_hba.conf padrão da imagem só permite `replication` de 127.0.0.1; o
        standby conecta pela rede bridge (172.x), então anexamos uma linha
        `host replication` cobrindo a rede interna e recarregamos o pg_hba via
        SIGHUP ao postmaster (PID 1 do container). Sem o reload, a regra nova só
        valeria após um restart e o pg_basebackup falharia com "no pg_hba.conf
        entry for replication". Idempotente (grep antes de anexar). Seguro: os
        containers publicam porta só em 127.0.0.1 no host.
        """
        line = "host replication all 0.0.0.0/0 scram-sha-256"
        # sh (alpine não tem bash). $PGDATA aponta para o data dir dentro da imagem.
        script = (
            f'grep -qF "{line}" "$PGDATA/pg_hba.conf" '
            f'|| echo "{line}" >> "$PGDATA/pg_hba.conf"'
        )
        exit_code, output = primary_container.exec_run(["sh", "-c", script])
        if exit_code != 0:
            raise RuntimeError(
                f"Falha ao ajustar pg_hba.conf do primário: {output!r}"
            )
        # SIGHUP ao postmaster recarrega pg_hba.conf/postgresql.conf sem restart.
        primary_container.kill(signal="SIGHUP")
        # Pequena espera para o reload assentar antes do pg_basebackup conectar.
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
        Criar um standby em streaming a partir de um primário existente.

        Fluxo:
        1. Localizar o container do primário e liberar replicação no pg_hba.conf
        2. `pg_basebackup` num container one-shot → volume novo (cópia física + `-R`,
           que grava standby.signal e primary_conninfo já com a senha embutida)
        3. Subir o container standby sobre esse volume (boota em recovery/hot standby)
        4. Aguardar aceitar conexões read-only e retornar as infos de conexão
        """
        primary_name = self._container_name(primary_instance_id)
        try:
            primary_container = self._client.containers.get(primary_name)
        except docker.errors.NotFound as exc:
            raise RuntimeError(
                f"Primário {primary_name} não encontrado — não é possível replicar"
            ) from exc

        self._allow_replication_on_primary(primary_container)

        image = f"postgres:{engine_version}-alpine"
        volume_name = self._replica_volume_name(replica_instance_id)
        replica_name = self._container_name(replica_instance_id)
        superuser_password = settings.PROVISIONER_SUPERUSER_PASSWORD

        # Passo 2 — pg_basebackup one-shot. -R grava a config de standby; passar a
        # conninfo completa em -d faz o primary_conninfo já incluir a senha (sem
        # isso o walreceiver do standby não autentica). -Xs = stream do WAL em
        # paralelo; -Fp = formato plain (data dir pronto para uso).
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
            # Volume parcial/sujo — remove para permitir uma nova tentativa limpa.
            self._remove_volume_quietly(volume_name)
            raise RuntimeError(f"pg_basebackup falhou: {exc}") from exc

        # Passo 3 — subir o standby sobre o data dir replicado. Como o PGDATA já
        # existe, o entrypoint pula o initdb e o PostgreSQL entra em recovery,
        # conectando ao primário via primary_conninfo.
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
            raise RuntimeError("Docker não atribuiu uma porta ao standby")
        host_port = int(port_bindings[0]["HostPort"])

        # Passo 4 — aguardar o standby aceitar conexões (recovery consistente).
        # Usa o superuser, cuja senha foi copiada fisicamente do primário.
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
        Promover o standby a primário via pg_promote().

        Conecta como superuser e chama pg_promote(); o PostgreSQL sai do modo de
        recovery, remove standby.signal e passa a aceitar escritas.
        """
        host_port = self.get_port(replica_instance_id)
        if host_port is None:
            raise RuntimeError("Standby não está em execução — não é possível promover")
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
            raise RuntimeError(f"Falha ao promover o standby: {exc}") from exc

    def _remove_volume_quietly(self, volume_name: str) -> None:
        """Remover um volume Docker ignorando ausência/erros (cleanup best-effort)."""
        try:
            self._client.volumes.get(volume_name).remove(force=True)
        except Exception:
            pass

    def logs(self, instance_id: uuid.UUID, tail: int = 200) -> str:
        """
        Retornar as últimas `tail` linhas de log do container da instância.

        timestamps=True prefixa cada linha com o horário — útil para depurar
        ordem de eventos. Decodifica com errors="replace" para nunca quebrar em
        bytes inválidos no stream de log.
        """
        container_name = self._container_name(instance_id)
        try:
            container = self._client.containers.get(container_name)
            raw = container.logs(tail=tail, timestamps=True)
            return raw.decode("utf-8", errors="replace")
        except docker.errors.NotFound as exc:
            raise RuntimeError(f"Container {container_name} não encontrado") from exc
