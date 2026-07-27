import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.models.alert import AlertSeverity
from src.models.backup import BackupStatus
from src.models.database_instance import Environment, InstanceStatus


SUPPORTED_ENGINE_VERSIONS = Literal["14", "15", "16", "17"]


class InstanceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    engine_version: SUPPORTED_ENGINE_VERSIONS = "16"
    cpu: Optional[int] = Field(default=None, ge=1)
    memory_mb: Optional[int] = Field(default=None, ge=128)
    storage_gb: Optional[int] = Field(default=None, ge=1)
    region: Optional[str] = Field(default=None, max_length=64)
    environment: Optional[Environment] = None
    notes: Optional[str] = None


class InstanceCreate(InstanceBase):
    pass


class InstanceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    engine_version: Optional[SUPPORTED_ENGINE_VERSIONS] = None
    cpu: Optional[int] = Field(default=None, ge=1)
    memory_mb: Optional[int] = Field(default=None, ge=128)
    storage_gb: Optional[int] = Field(default=None, ge=1)
    region: Optional[str] = Field(default=None, max_length=64)
    environment: Optional[Environment] = None
    notes: Optional[str] = None


class InstanceRead(InstanceBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: InstanceStatus
    # Owning company (multi-tenant). NULL for superuser instances with no company.
    company_id: Optional[uuid.UUID] = None
    host: Optional[str] = None
    port: Optional[int] = None
    db_name: Optional[str] = None
    db_user: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


class InstanceSummary(BaseModel):
    """
    Aggregated state of an instance for the fleet card.

    Every field is optional because a newly created (or stopped) instance
    doesn't yet have collection, alerts, or a backup: the card shows "—" instead
    of zero, which would be a false statement about the instance.
    """

    instance_id: uuid.UUID
    connections_active: Optional[float] = None
    connections_max: Optional[float] = None
    queries_per_second: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    db_size_bytes: Optional[float] = None
    # Growth over the last 24h; can be negative (after VACUUM FULL/DROP).
    size_delta_24h_bytes: Optional[float] = None
    open_alerts: int = 0
    max_alert_severity: Optional[AlertSeverity] = None
    last_backup_at: Optional[datetime] = None
    last_backup_status: Optional[BackupStatus] = None
    uptime_30d_pct: Optional[float] = None


class FleetSummaryResponse(BaseModel):
    instances: list[InstanceSummary]