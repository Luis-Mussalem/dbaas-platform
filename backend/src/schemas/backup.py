import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.backup import BackupStatus, BackupStrategy, BackupType


class BackupRequest(BaseModel):
    """
    Body para POST /instances/{id}/backups.
    O operador escolhe apenas a strategy — o tipo é sempre MANUAL neste endpoint.
    """

    strategy: BackupStrategy = BackupStrategy.LOGICAL


class BackupRead(BaseModel):
    """
    Representação de um backup retornada pela API.
    file_path é o caminho absoluto no host — útil para debug e para restore manual.
    size_bytes é preenchido apenas após conclusão.
    """

    id: uuid.UUID
    instance_id: uuid.UUID
    backup_type: BackupType
    strategy: BackupStrategy
    status: BackupStatus
    file_path: str | None
    size_bytes: int | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class BackupScheduleCreate(BaseModel):
    """
    Body para POST /instances/{id}/schedules.
    A cron expression é validada com croniter antes de chegar ao banco.
    Exemplo de cron: "0 2 * * *" (2 AM todo dia), "*/30 * * * *" (a cada 30 min).
    retention_days: quantos dias manter os backups criados por este schedule.
    """

    strategy: BackupStrategy = BackupStrategy.LOGICAL
    cron_expression: str
    retention_days: int = Field(default=7, ge=1, le=365)
    is_active: bool = True

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        try:
            from croniter import croniter  # noqa: PLC0415

            if not croniter.is_valid(v):
                raise ValueError(f"Invalid cron expression: '{v}'")
        except ImportError as exc:
            raise ValueError("croniter is not installed") from exc
        return v


class BackupScheduleUpdate(BaseModel):
    """
    Body para PATCH /instances/{id}/schedules/{schedule_id}.
    Todos os campos são opcionais — apenas os fornecidos são atualizados.
    """

    cron_expression: str | None = None
    retention_days: int | None = Field(default=None, ge=1, le=365)
    is_active: bool | None = None

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            from croniter import croniter  # noqa: PLC0415

            if not croniter.is_valid(v):
                raise ValueError(f"Invalid cron expression: '{v}'")
        except ImportError as exc:
            raise ValueError("croniter is not installed") from exc
        return v


class BackupScheduleRead(BaseModel):
    """
    Representação de um BackupSchedule retornada pela API.
    next_run_at é calculado ao criar e após cada execução.
    """

    id: uuid.UUID
    instance_id: uuid.UUID
    strategy: BackupStrategy
    cron_expression: str
    retention_days: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None
    next_run_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
