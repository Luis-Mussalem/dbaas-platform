import asyncio
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.dependencies import get_current_user, get_instance_or_404
from src.models.database_instance import InstanceStatus
from src.models.user import User
from src.schemas.instance import InstanceCreate, InstanceRead, InstanceUpdate
from src.services.instance import (
    create_instance,
    get_instance_by_id,
    list_instances,
    soft_delete_instance,
    transition_status,
    update_instance,
)
from src.services.provisioning import get_provisioner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/instances", tags=["Instances"])


class StatusAction(BaseModel):
    action: Literal["start", "stop"]


class InstanceLogs(BaseModel):
    logs: str


_ACTION_TO_STATUS = {
    "start": InstanceStatus.RUNNING,
    "stop": InstanceStatus.STOPPED,
}


@router.post("", response_model=InstanceRead, status_code=status.HTTP_201_CREATED)
async def create(
    data: InstanceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await create_instance(db, data, current_user)


@router.get("", response_model=list[InstanceRead])
def list_all(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_instances(db, current_user)


@router.get("/{instance_id}", response_model=InstanceRead)
def get_one(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = get_instance_by_id(db, instance_id, current_user)
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    return instance


@router.patch("/{instance_id}", response_model=InstanceRead)
def update(
    instance_id: uuid.UUID,
    data: InstanceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = get_instance_by_id(db, instance_id, current_user)
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    return update_instance(db, instance, data)


@router.patch("/{instance_id}/status", response_model=InstanceRead)
async def change_status(
    instance_id: uuid.UUID,
    body: StatusAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = get_instance_by_id(db, instance_id, current_user)
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    return await transition_status(db, instance, _ACTION_TO_STATUS[body.action])


@router.get("/{instance_id}/logs", response_model=InstanceLogs)
async def get_logs(
    instance_id: uuid.UUID,
    tail: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retorna as últimas `tail` linhas de log do container PostgreSQL da instância.

    Lê direto do Docker (stdout/stderr do container). Bloqueante — vai para o
    thread pool via asyncio.to_thread.
    """
    get_instance_or_404(instance_id, db, current_user)
    provisioner = get_provisioner()
    try:
        logs = await asyncio.to_thread(provisioner.logs, instance_id, tail)
    except RuntimeError as exc:
        logger.error("Failed to fetch logs for instance %s: %s", instance_id, exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Logs unavailable — the instance container does not exist.",
        ) from exc
    return InstanceLogs(logs=logs)


@router.delete("/{instance_id}", response_model=InstanceRead)
async def delete(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = get_instance_by_id(db, instance_id, current_user)
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    return await soft_delete_instance(db, instance)