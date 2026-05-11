import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.models.backup import BackupStatus, BackupStrategy
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.user import User
from src.schemas.backup import (
    BackupRead,
    BackupRequest,
    BackupScheduleCreate,
    BackupScheduleRead,
    BackupScheduleUpdate,
)
from src.services.backup import (
    create_logical_backup,
    create_physical_backup,
    create_schedule,
    delete_backup_record,
    delete_schedule,
    get_backup_by_id,
    get_schedule_by_id,
    list_backups,
    list_schedules,
    restore_logical_backup,
    update_schedule,
)

router = APIRouter(tags=["Backups"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_instance(instance_id: uuid.UUID, db: Session) -> DatabaseInstance:
    """
    Retorna a instância se existir e não estiver deletada.
    Levanta 404 se não encontrada.
    """
    instance = (
        db.query(DatabaseInstance)
        .filter(
            DatabaseInstance.id == instance_id,
            DatabaseInstance.deleted_at.is_(None),
        )
        .first()
    )
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instance not found",
        )
    return instance


def _require_running(instance_id: uuid.UUID, db: Session) -> DatabaseInstance:
    """
    Retorna a instância apenas se estiver em status RUNNING.
    Levanta 404 se não encontrada, 409 se não estiver RUNNING.
    """
    instance = _require_instance(instance_id, db)
    if instance.status != InstanceStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Instance is not RUNNING (current status: {instance.status})",
        )
    return instance


# ---------------------------------------------------------------------------
# Backup endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/instances/{instance_id}/backups",
    response_model=BackupRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_backup(
    instance_id: uuid.UUID,
    data: BackupRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Dispara um backup manual para a instância especificada.

    strategy=logical: pg_dump (custom format) — rápido, portátil, permite restore seletivo.
    strategy=physical: pg_basebackup — backup completo dos data files, base para PITR.

    A instância precisa estar em status RUNNING.
    Operação bloqueante — aguarda a conclusão do backup antes de retornar.
    Para bancos grandes, pode levar vários minutos.
    """
    instance = _require_running(instance_id, db)

    if not instance.connection_uri:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Instance has no connection URI — cannot backup",
        )

    try:
        if data.strategy == BackupStrategy.LOGICAL:
            backup = await asyncio.to_thread(
                create_logical_backup, db, instance
            )
        else:
            backup = await asyncio.to_thread(
                create_physical_backup, db, instance
            )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return backup


@router.get(
    "/instances/{instance_id}/backups",
    response_model=list[BackupRead],
)
def list_instance_backups(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Lista todos os backups não-deletados de uma instância, mais recentes primeiro.
    """
    _require_instance(instance_id, db)
    return list_backups(db, instance_id)


@router.get(
    "/backups/{backup_id}",
    response_model=BackupRead,
)
def get_backup(
    backup_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Retorna os detalhes de um backup específico."""
    backup = get_backup_by_id(db, backup_id)
    if not backup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup not found",
        )
    return backup


@router.delete(
    "/backups/{backup_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_backup(
    backup_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Remove um backup: apaga o arquivo físico e marca o registro como DELETED.
    O registro permanece no banco para auditoria.
    """
    backup = get_backup_by_id(db, backup_id)
    if not backup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup not found",
        )
    if backup.status == BackupStatus.DELETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Backup is already deleted",
        )
    delete_backup_record(db, backup)


@router.post(
    "/backups/{backup_id}/restore",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def restore_backup(
    backup_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Restaura um backup lógico (pg_restore) na instância de origem.

    ATENÇÃO: operação destrutiva — todos os dados atuais do banco são substituídos
    pelo conteúdo do backup. Confirme que você tem o backup certo antes de executar.

    Apenas backups com strategy=logical e status=completed podem ser restaurados.
    A instância precisa estar em status RUNNING.
    """
    backup = get_backup_by_id(db, backup_id)
    if not backup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup not found",
        )

    if backup.status != BackupStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot restore backup with status '{backup.status}'",
        )

    if backup.strategy != BackupStrategy.LOGICAL:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only logical backups can be restored via this endpoint",
        )

    instance = _require_running(backup.instance_id, db)

    try:
        await asyncio.to_thread(restore_logical_backup, db, backup, instance)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# Schedule endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/instances/{instance_id}/schedules",
    response_model=BackupScheduleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_backup_schedule(
    instance_id: uuid.UUID,
    data: BackupScheduleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Cria um schedule de backup automático para a instância.
    A cron expression é validada antes de salvar.
    next_run_at é calculado automaticamente.
    """
    _require_instance(instance_id, db)
    return create_schedule(db, instance_id, data)


@router.get(
    "/instances/{instance_id}/schedules",
    response_model=list[BackupScheduleRead],
)
def list_backup_schedules(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Lista todos os schedules de backup de uma instância."""
    _require_instance(instance_id, db)
    return list_schedules(db, instance_id)


@router.patch(
    "/instances/{instance_id}/schedules/{schedule_id}",
    response_model=BackupScheduleRead,
)
def update_backup_schedule(
    instance_id: uuid.UUID,
    schedule_id: uuid.UUID,
    data: BackupScheduleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Atualiza um schedule existente.
    Se a cron expression mudar, next_run_at é recalculado automaticamente.
    Se is_active for desativado, next_run_at é anulado (pausa o schedule).
    """
    _require_instance(instance_id, db)
    schedule = get_schedule_by_id(db, schedule_id)
    if not schedule or schedule.instance_id != instance_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Schedule not found",
        )
    return update_schedule(db, schedule, data)


@router.delete(
    "/instances/{instance_id}/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_backup_schedule(
    instance_id: uuid.UUID,
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Remove um schedule de backup. Os backups já criados não são afetados."""
    _require_instance(instance_id, db)
    schedule = get_schedule_by_id(db, schedule_id)
    if not schedule or schedule.instance_id != instance_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Schedule not found",
        )
    delete_schedule(db, schedule)
