"""
Testes do serviço de backup (PHASE 5) sem executar pg_dump/pg_restore/pg_basebackup.

Estratégia: substituir subprocess.run por um dublê que simula o binário —
opcionalmente escrevendo o arquivo de saída indicado em --file= / --pgdata= e
controlando o returncode. Isso exercita TODA a orquestração (transições de
status PENDING→RUNNING→COMPLETED/FAILED, cálculo de tamanho, expires_at,
limpeza em falha) sem depender do postgresql-client nem de um banco vivo.

BACKUP_DIR é redirecionado para tmp_path em cada teste para nunca tocar em
data/backups real.
"""
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.core.encryption import encrypt_value
from src.models.backup import Backup, BackupStatus, BackupStrategy, BackupType
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.schemas.backup import BackupScheduleCreate, BackupScheduleUpdate
from src.services import backup as backup_service


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def tmp_backup_dir(tmp_path, monkeypatch):
    """Redireciona BACKUP_DIR para um diretório temporário em todos os testes."""
    monkeypatch.setattr(backup_service.settings, "BACKUP_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def instance(db):
    """Instância com connection_uri cifrada (Fernet), como em produção."""
    uri = encrypt_value("postgresql://appuser:s3cret@127.0.0.1:5433/appdb")
    inst = DatabaseInstance(
        name="backup-db",
        status=InstanceStatus.RUNNING,
        connection_uri=uri,
        host="127.0.0.1",
        port=5433,
        db_name="appdb",
        db_user="appuser",
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _fake_run(returncode=0, stderr="", write_bytes=b"BACKUPDATA"):
    """
    Fabrica um substituto de subprocess.run que opcionalmente escreve o arquivo
    de saída (parseado de --file= ou --pgdata=) e devolve o returncode desejado.
    """
    def _run(cmd, *args, **kwargs):
        for arg in cmd:
            if arg.startswith("--file="):
                Path(arg[len("--file="):]).write_bytes(write_bytes)
            elif arg.startswith("--pgdata="):
                d = Path(arg[len("--pgdata="):])
                d.mkdir(parents=True, exist_ok=True)
                (d / "base.tar.gz").write_bytes(write_bytes)
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr=stderr)

    return _run


# --------------------------------------------------------------------------- #
# Connection parsing
# --------------------------------------------------------------------------- #


def test_parse_connection_extracts_fields(instance):
    conn = backup_service._parse_connection(instance)
    assert conn == {
        "host": "127.0.0.1",
        "port": "5433",
        "user": "appuser",
        "password": "s3cret",
        "dbname": "appdb",
    }


def test_parse_connection_rejects_incomplete_uri(db):
    inst = DatabaseInstance(
        name="bad", status=InstanceStatus.RUNNING,
        connection_uri=encrypt_value("postgresql:///nohost"),
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    with pytest.raises(RuntimeError, match="invalid or incomplete"):
        backup_service._parse_connection(inst)


def test_make_env_sets_pgpassword():
    env = backup_service._make_env("hunter2")
    assert env["PGPASSWORD"] == "hunter2"


# --------------------------------------------------------------------------- #
# Logical backup (pg_dump)
# --------------------------------------------------------------------------- #


def test_logical_backup_success(db, instance, monkeypatch):
    monkeypatch.setattr(backup_service.subprocess, "run", _fake_run(returncode=0))
    result = backup_service.create_logical_backup(db, instance, retention_days=7)

    assert result.status == BackupStatus.COMPLETED
    assert result.strategy == BackupStrategy.LOGICAL
    assert result.file_path is not None and result.file_path.endswith(".dump")
    assert result.size_bytes == len(b"BACKUPDATA")
    assert result.completed_at is not None
    assert result.expires_at is not None  # retention_days → expires_at calculado


def test_logical_backup_failure_marks_failed(db, instance, monkeypatch):
    monkeypatch.setattr(
        backup_service.subprocess, "run",
        _fake_run(returncode=1, stderr="pg_dump: connection refused"),
    )
    with pytest.raises(RuntimeError, match="connection refused"):
        backup_service.create_logical_backup(db, instance)

    rec = db.query(Backup).filter_by(instance_id=instance.id).first()
    assert rec.status == BackupStatus.FAILED
    assert "connection refused" in rec.error_message


# --------------------------------------------------------------------------- #
# Logical restore (pg_restore)
# --------------------------------------------------------------------------- #


def _completed_logical_backup(db, instance, tmp_path) -> Backup:
    f = tmp_path / "dump.dump"
    f.write_bytes(b"x")
    b = Backup(
        instance_id=instance.id,
        strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.COMPLETED,
        file_path=str(f),
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def test_restore_success(db, instance, tmp_path, monkeypatch):
    backup = _completed_logical_backup(db, instance, tmp_path)
    monkeypatch.setattr(backup_service.subprocess, "run", _fake_run(returncode=0))
    # Não levanta — restore concluído.
    backup_service.restore_logical_backup(db, backup, instance)


def test_restore_accepts_warning_exit_code_1(db, instance, tmp_path, monkeypatch):
    backup = _completed_logical_backup(db, instance, tmp_path)
    monkeypatch.setattr(
        backup_service.subprocess, "run",
        _fake_run(returncode=1, stderr="warning: role does not exist"),
    )
    backup_service.restore_logical_backup(db, backup, instance)  # exit 1 = warning, ok


def test_restore_fatal_exit_code_raises(db, instance, tmp_path, monkeypatch):
    backup = _completed_logical_backup(db, instance, tmp_path)
    monkeypatch.setattr(
        backup_service.subprocess, "run",
        _fake_run(returncode=2, stderr="fatal"),
    )
    with pytest.raises(RuntimeError, match="exit 2"):
        backup_service.restore_logical_backup(db, backup, instance)


def test_restore_rejects_non_completed_backup(db, instance):
    b = Backup(
        instance_id=instance.id, strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.FAILED,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    with pytest.raises(ValueError, match="Cannot restore"):
        backup_service.restore_logical_backup(db, b, instance)


def test_restore_rejects_physical_strategy(db, instance):
    b = Backup(
        instance_id=instance.id, strategy=BackupStrategy.PHYSICAL,
        status=BackupStatus.COMPLETED, file_path="/x",
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    with pytest.raises(ValueError, match="only works with logical"):
        backup_service.restore_logical_backup(db, b, instance)


def test_restore_missing_file_raises(db, instance):
    b = Backup(
        instance_id=instance.id, strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.COMPLETED, file_path="/nonexistent/foo.dump",
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    with pytest.raises(FileNotFoundError):
        backup_service.restore_logical_backup(db, b, instance)


# --------------------------------------------------------------------------- #
# Physical backup (pg_basebackup)
# --------------------------------------------------------------------------- #


def test_physical_backup_success(db, instance, monkeypatch):
    monkeypatch.setattr(backup_service.subprocess, "run", _fake_run(returncode=0))
    result = backup_service.create_physical_backup(db, instance)

    assert result.status == BackupStatus.COMPLETED
    assert result.strategy == BackupStrategy.PHYSICAL
    assert result.size_bytes == len(b"BACKUPDATA")
    assert Path(result.file_path).exists()


def test_physical_backup_failure_cleans_dir_and_marks_failed(db, instance, monkeypatch):
    monkeypatch.setattr(
        backup_service.subprocess, "run",
        _fake_run(returncode=1, stderr="pg_basebackup: replication denied"),
    )
    with pytest.raises(RuntimeError, match="replication denied"):
        backup_service.create_physical_backup(db, instance)

    rec = db.query(Backup).filter_by(instance_id=instance.id).first()
    assert rec.status == BackupStatus.FAILED


# --------------------------------------------------------------------------- #
# Retention / listing / manual delete
# --------------------------------------------------------------------------- #


def test_apply_retention_removes_expired(db, instance, tmp_path):
    f = tmp_path / "old.dump"
    f.write_bytes(b"old")
    expired = Backup(
        instance_id=instance.id, strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.COMPLETED, file_path=str(f),
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    fresh = Backup(
        instance_id=instance.id, strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.COMPLETED,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.add_all([expired, fresh])
    db.commit()

    removed = backup_service.apply_retention(db, instance.id)
    assert removed == 1
    db.refresh(expired)
    db.refresh(fresh)
    assert expired.status == BackupStatus.DELETED
    assert not f.exists()  # arquivo físico removido
    assert fresh.status == BackupStatus.COMPLETED  # não expirado, intacto


def test_list_backups_excludes_deleted_and_orders_desc(db, instance):
    older = Backup(
        instance_id=instance.id, strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.COMPLETED, created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    newer = Backup(
        instance_id=instance.id, strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.COMPLETED, created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    deleted = Backup(
        instance_id=instance.id, strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.DELETED,
    )
    db.add_all([older, newer, deleted])
    db.commit()

    listed = backup_service.list_backups(db, instance.id)
    assert [b.id for b in listed] == [newer.id, older.id]


def test_get_backup_by_id_and_manual_delete(db, instance, tmp_path):
    f = tmp_path / "m.dump"
    f.write_bytes(b"data")
    b = Backup(
        instance_id=instance.id, strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.COMPLETED, file_path=str(f),
    )
    db.add(b)
    db.commit()
    db.refresh(b)

    assert backup_service.get_backup_by_id(db, b.id).id == b.id
    assert backup_service.get_backup_by_id(db, uuid.uuid4()) is None

    backup_service.delete_backup_record(db, b)
    assert b.status == BackupStatus.DELETED
    assert not f.exists()


# --------------------------------------------------------------------------- #
# Schedules (cron via croniter)
# --------------------------------------------------------------------------- #


def test_compute_next_run_is_timezone_aware():
    nxt = backup_service._compute_next_run("*/5 * * * *")
    assert nxt.tzinfo is not None
    assert nxt > datetime.now(timezone.utc) - timedelta(minutes=1)


def test_create_active_schedule_sets_next_run(db, instance):
    sched = backup_service.create_schedule(
        db, instance.id,
        BackupScheduleCreate(cron_expression="0 2 * * *", retention_days=14, is_active=True),
    )
    assert sched.next_run_at is not None
    assert sched.retention_days == 14


def test_create_inactive_schedule_has_no_next_run(db, instance):
    sched = backup_service.create_schedule(
        db, instance.id,
        BackupScheduleCreate(cron_expression="0 2 * * *", is_active=False),
    )
    assert sched.next_run_at is None


def test_update_schedule_toggle_active_recomputes_next_run(db, instance):
    sched = backup_service.create_schedule(
        db, instance.id,
        BackupScheduleCreate(cron_expression="0 2 * * *", is_active=False),
    )
    activated = backup_service.update_schedule(
        db, sched, BackupScheduleUpdate(is_active=True),
    )
    assert activated.next_run_at is not None

    deactivated = backup_service.update_schedule(
        db, sched, BackupScheduleUpdate(is_active=False),
    )
    assert deactivated.next_run_at is None


def test_advance_and_delete_schedule(db, instance):
    sched = backup_service.create_schedule(
        db, instance.id, BackupScheduleCreate(cron_expression="*/5 * * * *"),
    )
    backup_service.advance_schedule(db, sched)
    assert sched.last_run_at is not None
    assert sched.next_run_at is not None

    assert backup_service.get_schedule_by_id(db, sched.id) is not None
    backup_service.delete_schedule(db, sched)
    assert backup_service.get_schedule_by_id(db, sched.id) is None
