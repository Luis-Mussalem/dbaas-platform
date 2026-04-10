import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.models.database_instance import InstanceStatus


class InstanceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    engine_version: str = Field(default="16", max_length=50)
    cpu: Optional[int] = Field(default=None, ge=1)
    memory_mb: Optional[int] = Field(default=None, ge=128)
    storage_gb: Optional[int] = Field(default=None, ge=1)
    notes: Optional[str] = None


class InstanceCreate(InstanceBase):
    pass


class InstanceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    engine_version: Optional[str] = Field(default=None, max_length=50)
    cpu: Optional[int] = Field(default=None, ge=1)
    memory_mb: Optional[int] = Field(default=None, ge=128)
    storage_gb: Optional[int] = Field(default=None, ge=1)
    notes: Optional[str] = None


class InstanceRead(InstanceBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: InstanceStatus
    host: Optional[str] = None
    port: Optional[int] = None
    db_name: Optional[str] = None
    db_user: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None