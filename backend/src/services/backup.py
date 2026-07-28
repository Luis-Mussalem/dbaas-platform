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
from src.core.redaction import redact_error
from src.models.backup import Backup, BackupSchedule, BackupStatus, BackupStrategy, BackupType
from src.models.database_instance import DatabaseInstance
from src.schemas.backup import BackupScheduleCreate, BackupScheduleUpdate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------


def _backup_root() -> Path:
    """
    Returns the backup root directory as an absolute Path.
    Creates the directory if it doesn't exist.
    """
    root = Path(settings.BACKUP_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _instance_dir(instance_id: uuid.UUID) -> Path:
    """Directory dedicated to a specific instance inside BACKUP_DIR."""
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
    Decrypts and parses the instance's connection_uri.

    Returns a dict with host, port, user, password, dbname.
    decrypt_value() uses Fernet — the decrypted URI exists only in memory
    during this function's execution and is never logged.
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
    Creates an environment dict for PostgreSQL subprocesses.
    PGPASSWORD is the safe way to pass the password — it doesn't show up in 'ps aux'
    or in process logs, unlike including it in the connection string.
    """
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    return env


def _get_dir_size(path: Path) -> int:
    """Computes the total size of a directory in bytes."""
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
    Creates a logical backup using pg_dump in custom format (.dump).

    Why the custom format?
    The custom format (-Fc flag) is binary, compressed, and allows selective restore
    (specific tables, no data, etc.) via pg_restore. It's the best format
    for application backups.

    Why subprocess with PGPASSWORD instead of a direct connection URI?
    If we pass the URI directly in the command (pg_dump postgresql://...), the password
    shows up in 'ps aux' and in system logs. PGPASSWORD as an env var is invisible.

    Requires: postgresql-client-16 installed on the WSL2 host.
    Install with: sudo apt install -y postgresql-client-16
    """
    conn = _parse_connection(instance)
    output_dir = _logical_dir(instance.id)
    backup_id = uuid.uuid4()
    output_file = output_dir / f"{backup_id}.dump"

    # Compute expires_at if retention_days was provided
    expires_at = None
    if retention_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=retention_days)

    # Create the Backup record with PENDING status before executing
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

    # Update to RUNNING
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
            timeout=3600,  # 1 hour timeout
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "pg_dump exited non-zero")

        # Record the file size and mark as COMPLETED
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
        # Redacted: this column is returned to the client by BackupRead.
        backup.error_message = redact_error(str(exc))
        backup.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(backup)

        # The log keeps the UNREDACTED text — that's the operator's copy.
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
    Restores a logical backup using pg_restore.

    Why --clean --if-exists?
    --clean drops objects before recreating them, ensuring a clean restore
    even if tables with data already exist. --if-exists avoids errors if an object
    didn't exist before.

    Why --no-owner --no-privileges?
    The backup may have been made from a different role. These flags ignore
    ownership and privileges, letting the object be created by the current role.

    WARNING: restore deletes and recreates all of the database's data. Destructive operation.
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

    # pg_restore returns 1 for non-fatal warnings — accepted
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
    Creates a physical backup using pg_basebackup.

    Why pg_basebackup?
    Captures an exact copy of PostgreSQL's data files (the full data directory).
    It's the base required for PITR: recovery_target_time + WAL replay.
    A logical backup (pg_dump) doesn't allow PITR — only physical backups allow
    restoring to an arbitrary point in time.

    Why --wal-method=fetch?
    Includes all WAL generated during the backup in the backup itself. Simpler
    than --wal-method=stream (which requires an additional replication connection).
    For PITR, the separate WAL archive complements the base.

    Why --format=tar --gzip?
    Compresses the backup into tar.gz — typically a 50-80% size reduction
    vs. the raw directory. The downside is that you need to decompress to
    restore — but for a physical backup, that's always necessary anyway.

    Requires:
    - db_user with REPLICATION privilege (granted by the updated DockerProvisioner)
    - wal_level=replica on the instance's PostgreSQL (configured in the container)
    - postgresql-client-16 on the WSL2 host
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
            timeout=7200,  # 2 hour timeout for large databases
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
        # Clean up the incomplete directory
        shutil.rmtree(output_dir, ignore_errors=True)

        backup.status = BackupStatus.FAILED
        # Redacted: this column is returned to the client by BackupRead.
        backup.error_message = redact_error(str(exc))
        backup.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(backup)

        # The log keeps the UNREDACTED text — that's the operator's copy.
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
    Removes expired backups: deletes the physical file/directory and marks the
    record as DELETED (we keep the audit trail in the database).

    Returns the number of backups removed.

    Why not DELETE from the table?
    Keeping the record as DELETED preserves history: we know backups existed,
    when they were created, and when they expired. Useful for auditing.
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
    Lists all backups of an instance, excluding DELETED ones,
    ordered by created_at descending (most recent first).
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
    Manually removes a backup: deletes the physical file and marks it as DELETED.
    Equivalent to automatic retention but triggered by the operator.
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
    Computes the next run time of a cron expression.
    Returns a timezone-aware (UTC) datetime.

    croniter.get_next() returns a naive datetime by default.
    We add UTC explicitly for consistency with the database.
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
    Creates a new BackupSchedule for an instance.
    Computes next_run_at immediately so the poller can schedule it.
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
    """
    Applies a partial update to a schedule.

    Field presence is read from `model_fields_set`, not from `is not None`. PATCH
    semantics distinguish "field omitted" from "field explicitly set to null", and
    conflating them made `retention_days` a one-way door: once a retention was
    set, sending `null` to mean "keep these backups forever" was silently ignored,
    and the only way back was deleting the schedule and recreating it.
    """
    provided = data.model_fields_set

    if "cron_expression" in provided and data.cron_expression is not None:
        schedule.cron_expression = data.cron_expression
        # Recompute next_run_at if the cron changed
        if schedule.is_active:
            schedule.next_run_at = _compute_next_run(schedule.cron_expression)

    if "retention_days" in provided:
        # Explicit null = keep indefinitely. Already-created backups keep the
        # expires_at they were stamped with; this only changes future ones.
        schedule.retention_days = data.retention_days

    if "is_active" in provided and data.is_active is not None:
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
    Called after running a scheduled backup.
    Updates last_run_at and recomputes next_run_at for the next run.
    """
    schedule.last_run_at = datetime.now(timezone.utc)
    schedule.next_run_at = _compute_next_run(schedule.cron_expression)
    db.commit()
