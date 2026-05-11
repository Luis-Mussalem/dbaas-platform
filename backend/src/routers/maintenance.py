import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.maintenance import MaintenanceSchedule
from src.models.user import User
from src.schemas.maintenance import (
    ConfigRecommendationsResponse,
    MaintenanceScheduleCreate,
    MaintenanceScheduleRead,
    MaintenanceTaskCreate,
    MaintenanceTaskRead,
)
from src.services import maintenance as svc

router = APIRouter(prefix="/instances", tags=["Maintenance"])


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _require_instance(instance_id: uuid.UUID, db: Session) -> DatabaseInstance:
    """Retorna a instância ou levanta 404."""
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
    """Retorna a instância somente se estiver RUNNING; 404 ou 409 caso contrário."""
    instance = _require_instance(instance_id, db)
    if instance.status != InstanceStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Instance is '{instance.status.value}' — "
                "maintenance tasks require RUNNING status"
            ),
        )
    return instance


def _require_schedule(
    schedule_id: uuid.UUID,
    instance_id: uuid.UUID,
    db: Session,
) -> MaintenanceSchedule:
    """Retorna o schedule ou 404."""
    schedule = (
        db.query(MaintenanceSchedule)
        .filter(
            MaintenanceSchedule.id == schedule_id,
            MaintenanceSchedule.instance_id == instance_id,
        )
        .first()
    )
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance schedule not found",
        )
    return schedule


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/{instance_id}/maintenance/run",
    response_model=MaintenanceTaskRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Executar tarefa de manutenção manual",
)
def run_maintenance(
    instance_id: uuid.UUID,
    data: MaintenanceTaskCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Executar uma tarefa de manutenção imediatamente na instância.

    - **VACUUM** / **ANALYZE** / **REINDEX**: opcionalmente em uma tabela específica
    - **VACUUM_FULL**: `target_table` é obrigatório (lock exclusivo — nunca no banco inteiro)
    - **KILL_IDLE** / **KILL_LONG**: `target_table` é ignorado (operam sobre conexões)

    Requer que a instância esteja `RUNNING`.
    """
    instance = _require_running(instance_id, db)
    try:
        return svc.run_task(db, instance, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )


@router.get(
    "/{instance_id}/maintenance",
    response_model=list[MaintenanceTaskRead],
    summary="Histórico de tarefas de manutenção",
)
def list_maintenance_history(
    instance_id: uuid.UUID,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Retornar histórico das últimas tarefas de manutenção da instância.
    Ordenado por `scheduled_at` decrescente.
    """
    _require_instance(instance_id, db)
    return svc.get_task_history(db, instance_id, limit=limit)


@router.post(
    "/{instance_id}/maintenance/schedules",
    response_model=MaintenanceScheduleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Criar agendamento de manutenção",
)
def create_schedule(
    instance_id: uuid.UUID,
    data: MaintenanceScheduleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Criar um agendamento recorrente de manutenção com expressão cron.

    Exemplo de `cron_expression`:
    - `"0 3 * * 0"` — toda segunda-feira às 3:00 UTC
    - `"30 1 * * *"` — todo dia às 01:30 UTC

    `VACUUM_FULL` não pode ser agendado automaticamente (usa lock exclusivo).
    Execute-o manualmente via `POST /maintenance/run`.
    """
    _require_instance(instance_id, db)
    return svc.create_schedule(db, instance_id, data)


@router.get(
    "/{instance_id}/maintenance/schedules",
    response_model=list[MaintenanceScheduleRead],
    summary="Listar agendamentos de manutenção",
)
def list_schedules(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Retornar todos os agendamentos de manutenção da instância."""
    _require_instance(instance_id, db)
    return svc.list_schedules(db, instance_id)


@router.delete(
    "/{instance_id}/maintenance/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover agendamento de manutenção",
)
def delete_schedule(
    instance_id: uuid.UUID,
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Remover permanentemente um agendamento de manutenção."""
    _require_instance(instance_id, db)
    schedule = _require_schedule(schedule_id, instance_id, db)
    svc.delete_schedule(db, schedule)


@router.get(
    "/{instance_id}/config-recommendations",
    response_model=ConfigRecommendationsResponse,
    summary="Recomendações de configuração PostgreSQL",
)
def get_config_recommendations(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Retornar recomendações de parâmetros PostgreSQL baseadas nos recursos da instância.

    Calculado offline — não requer conexão com o banco.
    Funciona mesmo quando a instância está `STOPPED`.

    As fórmulas seguem as recomendações do [wiki.postgresql.org](https://wiki.postgresql.org/wiki/Tuning_Your_PostgreSQL_Server)
    e do pgTune para cargas OLTP.
    """
    instance = _require_instance(instance_id, db)
    return svc.get_config_recommendations(instance)
