import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from src.models.database_instance import InstanceStatus
from src.models.replica import ReplicationState


class ReplicaInstanceInfo(BaseModel):
    """Summary of the standby instance, embedded in ReplicaRead for the UI."""

    id: uuid.UUID
    name: str
    status: InstanceStatus
    host: str | None
    port: int | None

    model_config = ConfigDict(from_attributes=True)


class ReplicaRead(BaseModel):
    """
    Replication link returned by the API.

    `replica_instance` carries the standby's name/status/port so the Replication tab
    is self-sufficient (the service attaches it transiently before serializing).
    """

    id: uuid.UUID
    primary_instance_id: uuid.UUID
    replica_instance_id: uuid.UUID
    replication_state: ReplicationState
    lag_bytes: int | None
    lag_seconds: float | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    replica_instance: ReplicaInstanceInfo | None = None

    model_config = ConfigDict(from_attributes=True)
