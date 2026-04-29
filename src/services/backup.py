import logging
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.encryption import decrypt_value
from src.models.backup import Backup, BackupSchedule, BackupStatus, BackupStrategy, BackupType
from src.models.database_instance import DatabaseInstance
from src.schemas.backup import BackupScheduleCreate, BackupScheduleUpdate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------


def _backup_root() -> Path:
    """
    Retorna o diretório raiz de backups como Path absoluto.
    Cria o diretório se não existir.
    """
    root = Path(settings.BACKUP_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _instance_dir(instance_id: uuid.UUID) -> Path:
    """Diretório dedicado a uma instância específica dentro de BACKUP_DIR."""
    d = _backup_root() / str(instance_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _logical_dir(instance_id: uuid.UUID) -> Path:
    d = _instance_dir(instance_id) / "logical"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _physical_dir(instance_id: uuid.UUID) -> Path:
    d = _instance_dir(instance_id) / "physical"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Connection parsing
# ---------------------------------------------------------------------------


def _parse_connection(instance: DatabaseInstance) -> dict:
    """
    Desencripta e parseia a connection_uri da instância.

    Retorna um dict com host, port, user, password, dbname.
    O decrypt_value() usa Fernet — a URI decriptada existe apenas em memória
    durante a execução desta função e nunca é logada.
    """
    uri = decrypt_value(instance.connection_uri)
    parsed = urlparse(uri)
    if not parsed.hostname or parsed.port is None:
        raise RuntimeError(
            f"Instance {instance.id} has an invalid or incomplete connection URI"
        )
    return {
        "host": parsed.hostname,
        "port": str(parsed.port),
        "user": parsed.username or "",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/"),
    }


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------


def _make_env(password: str) -> dict:
    """
    Cria um environment dict para subprocessos PostgreSQL.
    PGPASSWORD é a forma segura de passar a senha — não aparece em 'ps aux'
    nem em logs de processo, ao contrário de incluir na connection string.
    """
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    return env


def _get_dir_size(path: Path) -> int:
    """Calcula o tamanho total de um diretório em bytes."""
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


# ---------------------------------------------------------------------------
# Logical backup: pg_dump
# ---------------------------------------------------------------------------


def create_logical_backup(
    db: Session,
    instance: DatabaseInstance,
    backup_type: BackupType = BackupType.MANUAL,
    retention_days: int | None = None,
) -> Backup:
    """
    Cria um backup lógico usando pg_dump no formato custom (.dump).

    Por que formato custom?
    O formato custom (flag -Fc) é binário, comprimido, e permite restore seletivo
    (tabelas específicas, sem dados, etc.) via pg_restore. É o melhor formato
    para backups de aplicação.

    Por que subprocess com PGPASSWORD em vez de connection URI direto?
    Se passarmos a URI diretamente no comando (pg_dump postgresql://...), a senha
    aparece em 'ps aux' e em logs do sistema. PGPASSWORD como env var é invisível.

    Requer: postgresql-client-16 instalado no host WSL2.
    Instalar com: sudo apt install -y postgresql-client-16
    """
    conn = _parse_connection(instance)
    output_dir = _logical_dir(instance.id)
    backup_id = uuid.uuid4()
    output_file = output_dir / f"{backup_id}.dump"

    # Calcular expires_at se retention_days foi fornecido
    expires_at = None
    if retention_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=retention_days)

    # Criar o registro Backup em status PENDING antes de executar
    backup = Backup(
        id=backup_id,
        instance_id=instance.id,
        backup_type=backup_type,
        strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.PENDING,
        expires_at=expires_at,
    )
    db.add(backup)
    db.commit()
    db.refresh(backup)

    # Atualizar para RUNNING
    backup.status = BackupStatus.RUNNING
    backup.started_at = datetime.now(timezone.utc)
    db.commit()

    try:
        env = _make_env(conn["password"])
        cmd = [
            "pg_dump",
            f"--host={conn['host']}",
            f"--port={conn['port']}",
            f"--username={conn['user']}",
            "--format=custom",
            f"--file={output_file}",
            "--no-password",
            conn["dbname"],
        ]

        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hora de timeout
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "pg_dump exited non-zero")

        # Registrar tamanho do arquivo e marcar como COMPLETED
        size_bytes = output_file.stat().st_size if output_file.exists() else None
        backup.status = BackupStatus.COMPLETED
        backup.file_path = str(output_file)
        backup.size_bytes = size_bytes
        backup.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(backup)

        logger.info(
            "Logical backup %s for instance %s completed (%s bytes)",
            backup.id,
            instance.id,
            size_bytes,
        )
        return backup

    except Exception as exc:
        backup.status = BackupStatus.FAILED
        backup.error_message = str(exc)
        backup.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(backup)

        logger.error(
            "Logical backup %s for instance %s failed: %s",
            backup.id,
            instance.id,
            exc,
        )
        raise RuntimeError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Logical restore: pg_restore
# ---------------------------------------------------------------------------


def restore_logical_backup(
    db: Session,
    backup: Backup,
    instance: DatabaseInstance,
) -> None:
    """
    Restaura um backup lógico usando pg_restore.

    Por que --clean --if-exists?
    --clean faz DROP dos objetos antes de recriar, garantindo um restore limpo
    mesmo que existam tabelas com dados. --if-exists evita erros se um objeto
    não existia antes.

    Por que --no-owner --no-privileges?
    O backup pode ter sido feito de um role diferente. Estas flags ignoram
    ownership e privileges, deixando o objeto ser criado pelo role atual.

    ATENÇÃO: restore apaga e recria todos os dados do banco. Operação destrutiva.
    """
    if backup.status != BackupStatus.COMPLETED:
        raise ValueError(f"Cannot restore backup with status '{backup.status}'")

    if backup.strategy != BackupStrategy.LOGICAL:
        raise ValueError("restore_logical_backup only works with logical backups")

    if not backup.file_path:
        raise RuntimeError("Backup has no file_path — cannot restore")

    backup_file = Path(backup.file_path)
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup.file_path}")

    conn = _parse_connection(instance)
    env = _make_env(conn["password"])

    cmd = [
        "pg_restore",
        f"--host={conn['host']}",
        f"--port={conn['port']}",
        f"--username={conn['user']}",
        f"--dbname={conn['dbname']}",
        "--no-owner",
        "--no-privileges",
        "--clean",
        "--if-exists",
        "--no-password",
        str(backup_file),
    ]

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"pg_restore timed out after {exc.timeout}s") from exc
    except OSError as exc:
        raise RuntimeError(f"Failed to run pg_restore: {exc}") from exc

    # pg_restore retorna 1 para warnings não-fatais — aceito
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"pg_restore failed (exit {result.returncode}): {result.stderr.strip()}"
        )

    if result.returncode == 1:
        logger.warning("pg_restore completed with warnings: %s", result.stderr.strip())
    else:
        logger.info(
            "Logical restore of backup %s to instance %s completed",
            backup.id,
            instance.id,
        )


# ---------------------------------------------------------------------------
# Physical backup: pg_basebackup
# ---------------------------------------------------------------------------


def create_physical_backup(
    db: Session,
    instance: DatabaseInstance,
    backup_type: BackupType = BackupType.MANUAL,
    retention_days: int | None = None,
) -> Backup:
    """
    Cria um backup físico usando pg_basebackup.

    Por que pg_basebackup?
    Captura uma cópia exata dos arquivos de dados do PostgreSQL (o data directory
    completo). É a base necessária para PITR: recovery_target_time + WAL replay.
    Backup lógico (pg_dump) não permite PITR — apenas backups físicos permitem
    restaurar para um ponto arbitrário no tempo.

    Por que --wal-method=fetch?
    Inclui todos os WAL gerados durante o backup no próprio backup. Mais simples
    que --wal-method=stream (que requer uma conexão de replicação adicional).
    Para PITR, o WAL archive separado complementa a base.

    Por que --format=tar --gzip?
    Comprime o backup em tar.gz — tipicamente 50-80% de redução de tamanho
    vs. o diretório raw. A desvantagem é que é necessário descompactar para
    restaurar — mas para um backup físico, isso é sempre necessário de qualquer forma.

    Requer:
    - db_user com privilégio REPLICATION (concedido pelo DockerProvisioner atualizado)
    - wal_level=replica no PostgreSQL da instância (configurado no container)
    - postgresql-client-16 no host WSL2
    """
    conn = _parse_connection(instance)
    output_dir = _physical_dir(instance.id) / str(uuid.uuid4())
    output_dir.mkdir(parents=True, exist_ok=True)

    expires_at = None
    if retention_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=retention_days)

    backup = Backup(
        instance_id=instance.id,
        backup_type=backup_type,
        strategy=BackupStrategy.PHYSICAL,
        status=BackupStatus.PENDING,
        expires_at=expires_at,
    )
    db.add(backup)
    db.commit()
    db.refresh(backup)

    backup.status = BackupStatus.RUNNING
    backup.started_at = datetime.now(timezone.utc)
    db.commit()

    try:
        env = _make_env(conn["password"])
        cmd = [
            "pg_basebackup",
            f"--host={conn['host']}",
            f"--port={conn['port']}",
            f"--username={conn['user']}",
            f"--pgdata={output_dir}",
            "--format=tar",
            "--gzip",
            "--wal-method=fetch",
            "--checkpoint=fast",
            "--no-password",
        ]

        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=7200,  # 2 horas de timeout para bancos grandes
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "pg_basebackup exited non-zero")

        size_bytes = _get_dir_size(output_dir)
        backup.status = BackupStatus.COMPLETED
        backup.file_path = str(output_dir)
        backup.size_bytes = size_bytes
        backup.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(backup)

        logger.info(
            "Physical backup %s for instance %s completed (%s bytes)",
            backup.id,
            instance.id,
            size_bytes,
        )
        return backup

    except Exception as exc:
        # Limpar o diretório incompleto
        shutil.rmtree(output_dir, ignore_errors=True)

        backup.status = BackupStatus.FAILED
        backup.error_message = str(exc)
        backup.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(backup)

        logger.error(
            "Physical backup %s for instance %s failed: %s",
            backup.id,
            instance.id,
            exc,
        )
        raise RuntimeError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def apply_retention(db: Session, instance_id: uuid.UUID) -> int:
    """
    Remove backups expirados: apaga o arquivo/diretório físico e marca o
    registro como DELETED (mantemos o audit trail no banco).

    Retorna o número de backups removidos.

    Por que não DELETE da tabela?
    Manter o registro como DELETED preserva histórico: sabemos que houve backups,
    quando foram criados e quando expiraram. Útil para auditoria.
    """
    now = datetime.now(timezone.utc)
    expired_backups = (
        db.query(Backup)
        .filter(
            Backup.instance_id == instance_id,
            Backup.expires_at.isnot(None),
            Backup.expires_at <= now,
            Backup.status == BackupStatus.COMPLETED,
        )
        .all()
    )

    count = 0
    for backup in expired_backups:
        if backup.file_path:
            file_path = Path(backup.file_path)
            if file_path.exists():
                if file_path.is_dir():
                    shutil.rmtree(file_path, ignore_errors=True)
                else:
                    file_path.unlink(missing_ok=True)

        backup.status = BackupStatus.DELETED
        count += 1

    if count > 0:
        db.commit()
        logger.info("Retention removed %d expired backups for instance %s", count, instance_id)

    return count


# ---------------------------------------------------------------------------
# Backup listing
# ---------------------------------------------------------------------------


def list_backups(db: Session, instance_id: uuid.UUID) -> list[Backup]:
    """
    Lista todos os backups de uma instância, excluindo os DELETED,
    ordenados por created_at decrescente (mais recente primeiro).
    """
    return (
        db.query(Backup)
        .filter(
            Backup.instance_id == instance_id,
            Backup.status != BackupStatus.DELETED,
        )
        .order_by(Backup.created_at.desc())
        .all()
    )


def get_backup_by_id(db: Session, backup_id: uuid.UUID) -> Backup | None:
    return db.query(Backup).filter(Backup.id == backup_id).first()


def delete_backup_record(db: Session, backup: Backup) -> None:
    """
    Remove manualmente um backup: apaga o arquivo físico e marca como DELETED.
    Equivalente à retenção automática mas disparado pelo operador.
    """
    if backup.file_path:
        file_path = Path(backup.file_path)
        if file_path.exists():
            if file_path.is_dir():
                shutil.rmtree(file_path, ignore_errors=True)
            else:
                file_path.unlink(missing_ok=True)

    backup.status = BackupStatus.DELETED
    db.commit()


# ---------------------------------------------------------------------------
# Schedule management
# ---------------------------------------------------------------------------


def _compute_next_run(cron_expression: str) -> datetime:
    """
    Calcula o próximo tempo de execução de uma cron expression.
    Retorna um datetime timezone-aware (UTC).

    croniter.get_next() retorna um datetime sem timezone por padrão.
    Adicionamos UTC explicitamente para consistência com o banco.
    """
    from croniter import croniter  # noqa: PLC0415

    cron = croniter(cron_expression, datetime.now(timezone.utc))
    next_dt = cron.get_next(datetime)
    if next_dt.tzinfo is None:
        next_dt = next_dt.replace(tzinfo=timezone.utc)
    return next_dt


def create_schedule(
    db: Session,
    instance_id: uuid.UUID,
    data: BackupScheduleCreate,
) -> BackupSchedule:
    """
    Cria um novo BackupSchedule para uma instância.
    Calcula next_run_at imediatamente para que o poller possa agendá-lo.
    """
    schedule = BackupSchedule(
        instance_id=instance_id,
        strategy=data.strategy,
        cron_expression=data.cron_expression,
        retention_days=data.retention_days,
        is_active=data.is_active,
        next_run_at=_compute_next_run(data.cron_expression) if data.is_active else None,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


def update_schedule(
    db: Session,
    schedule: BackupSchedule,
    data: BackupScheduleUpdate,
) -> BackupSchedule:
    if data.cron_expression is not None:
        schedule.cron_expression = data.cron_expression
        # Recalcular next_run_at se cron mudou
        if schedule.is_active:
            schedule.next_run_at = _compute_next_run(schedule.cron_expression)

    if data.retention_days is not None:
        schedule.retention_days = data.retention_days

    if data.is_active is not None:
        schedule.is_active = data.is_active
        if data.is_active and schedule.next_run_at is None:
            schedule.next_run_at = _compute_next_run(schedule.cron_expression)
        elif not data.is_active:
            schedule.next_run_at = None

    db.commit()
    db.refresh(schedule)
    return schedule


def list_schedules(db: Session, instance_id: uuid.UUID) -> list[BackupSchedule]:
    return (
        db.query(BackupSchedule)
        .filter(BackupSchedule.instance_id == instance_id)
        .order_by(BackupSchedule.created_at.desc())
        .all()
    )


def get_schedule_by_id(db: Session, schedule_id: uuid.UUID) -> BackupSchedule | None:
    return db.query(BackupSchedule).filter(BackupSchedule.id == schedule_id).first()


def delete_schedule(db: Session, schedule: BackupSchedule) -> None:
    db.delete(schedule)
    db.commit()


def advance_schedule(db: Session, schedule: BackupSchedule) -> None:
    """
    Chamado após executar um backup agendado.
    Atualiza last_run_at e recalcula next_run_at para a próxima execução.
    """
    schedule.last_run_at = datetime.now(timezone.utc)
    schedule.next_run_at = _compute_next_run(schedule.cron_expression)
    db.commit()
