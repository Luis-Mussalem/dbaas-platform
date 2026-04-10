import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.dependencies import get_current_user
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

router = APIRouter(prefix="/instances", tags=["Instances"])


@router.post("", response_model=InstanceRead, status_code=status.HTTP_201_CREATED)
def create(
    data: InstanceCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return create_instance(db, data)


@router.get("", response_model=list[InstanceRead])
def list_all(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return list_instances(db)


@router.get("/{instance_id}", response_model=InstanceRead)
def get_one(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    instance = get_instance_by_id(db, instance_id)
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    return instance


@router.patch("/{instance_id}", response_model=InstanceRead)
def update(
    instance_id: uuid.UUID,
    data: InstanceUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    instance = get_instance_by_id(db, instance_id)
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    return update_instance(db, instance, data)


@router.patch("/{instance_id}/status", response_model=InstanceRead)
def change_status(
    instance_id: uuid.UUID,
    new_status: InstanceStatus,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    instance = get_instance_by_id(db, instance_id)
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    return transition_status(db, instance, new_status)


@router.delete("/{instance_id}", response_model=InstanceRead)
def delete(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    instance = get_instance_by_id(db, instance_id)
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    return soft_delete_instance(db, instance)