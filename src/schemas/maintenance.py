import uuid
from datetime import datetime

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.maintenance import TaskStatus, TaskType


class MaintenanceTaskCreate(BaseModel):
    task_type: TaskType
    target_table: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "Tabela alvo. None = banco inteiro. "
            "Obrigatório para VACUUM_FULL — nunca rodar VACUUM FULL no banco inteiro."
        ),
    )


class MaintenanceTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    instance_id: uuid.UUID
    task_type: TaskType
    status: TaskStatus
    target_table: str | None
    scheduled_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result_summary: str | None


class MaintenanceScheduleCreate(BaseModel):
    task_type: TaskType
    cron_expression: str = Field(..., max_length=100)

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        if not croniter.is_valid(v):
            raise ValueError(f"Expressão cron inválida: '{v}'")
        return v


class MaintenanceScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    instance_id: uuid.UUID
    task_type: TaskType
    cron_expression: str
    is_active: bool
    next_run_at: datetime | None
    created_at: datetime


class ConfigRecommendation(BaseModel):
    parameter: str
    current_value: str | None
    recommended_value: str
    reason: str


class ConfigRecommendationsResponse(BaseModel):
    instance_id: uuid.UUID
    memory_mb: int | None
    cpu: int | None
    recommendations: list[ConfigRecommendation]
