import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.dependencies import (
    get_current_user,
    get_db,
    get_instance_if_running,
    get_instance_or_404,
)
from src.models.user import User
from src.schemas.replica import ReplicaRead
from src.services.replica import (
    create_replica,
    get_replica,
    list_replicas,
    promote_replica,
)

router = APIRouter(tags=["Replication"])


@router.post(
    "/instances/{instance_id}/replicas",
    response_model=ReplicaRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_instance_replica(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Cria um standby em streaming a partir de uma instância primária RUNNING.

    Operação bloqueante — faz pg_basebackup do primário e sobe o container do
    standby antes de retornar (pode levar de alguns segundos a minutos).
    """
    primary = get_instance_if_running(instance_id, db, current_user)
    return await create_replica(db, primary, current_user)


@router.get(
    "/instances/{instance_id}/replicas",
    response_model=list[ReplicaRead],
)
def list_instance_replicas(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista as réplicas de uma instância primária, mais recentes primeiro."""
    get_instance_or_404(instance_id, db, current_user)
    return list_replicas(db, instance_id)


@router.post(
    "/replicas/{replica_id}/promote",
    response_model=ReplicaRead,
)
async def promote_instance_replica(
    replica_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Promove um standby a primário standalone (failover manual)."""
    replica = get_replica(db, replica_id)
    if not replica:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Replica not found",
        )
    # Scoping por empresa: se o primário não é visível ao usuário, 404.
    get_instance_or_404(replica.primary_instance_id, db, current_user)
    return await promote_replica(db, replica, current_user)
