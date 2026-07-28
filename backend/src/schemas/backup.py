import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.backup import BackupStatus, BackupStrategy, BackupType


class BackupRequest(BaseModel):
    """
    Body for POST /instances/{id}/backups.
    The operator only chooses the strategy — the type is always MANUAL on this endpoint.
    """

    strategy: BackupStrategy = BackupStrategy.LOGICAL


class BackupRead(BaseModel):
    """
    Representation of a backup returned by the API.
    file_path is the absolute path on the host — useful for debugging and manual restores.
    size_bytes is only filled in after completion.
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
    Body for POST /instances/{id}/schedules.
    The cron expression is validated with croniter before reaching the database.
    Cron example: "0 2 * * *" (2 AM every day), "*/30 * * * *" (every 30 min).
    retention_days: how many days to keep backups created by this schedule.
    """

    strategy: BackupStrategy = BackupStrategy.LOGICAL
    cron_expression: str
    retention_days: int | None = Field(default=7, ge=1, le=365)
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
    Body for PATCH /instances/{id}/schedules/{schedule_id}.

    All fields are optional — only the ones PROVIDED are updated, which the
    service reads from `model_fields_set` rather than from `is not None`. The
    difference is load-bearing for `retention_days`: an explicit `null` means
    "keep these backups indefinitely", while omitting the field leaves the current
    retention alone.
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
    Representation of a BackupSchedule returned by the API.
    next_run_at is computed on creation and after each run.
    """

    id: uuid.UUID
    instance_id: uuid.UUID
    strategy: BackupStrategy
    cron_expression: str
    retention_days: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None
    next_run_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
