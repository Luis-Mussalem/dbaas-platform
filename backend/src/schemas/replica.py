import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from src.models.database_instance import InstanceStatus
from src.models.replica import ReplicationState


class ReplicaInstanceInfo(BaseModel):
    """Resumo da instância standby, embutido no ReplicaRead para a UI."""

    id: uuid.UUID
    name: str
    status: InstanceStatus
    host: str | None
    port: int | None

    model_config = ConfigDict(from_attributes=True)


class ReplicaRead(BaseModel):
    """
    Vínculo de replicação retornado pela API.

    `replica_instance` traz nome/status/porta do standby para a aba de Replicação
    ser autossuficiente (o serviço o anexa transitoriamente antes de serializar).
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
