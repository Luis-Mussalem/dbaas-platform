import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class BackupType(str, PyEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class BackupStrategy(str, PyEnum):
    LOGICAL = "logical"
    PHYSICAL = "physical"


class BackupStatus(str, PyEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"


class Backup(Base):
    """
    Represents a backup operation — manual or scheduled.

    Why separate backup_type from strategy?
    - backup_type: WHO started it (operator manually via the API, or the automatic scheduler)
    - strategy: HOW it was done (logical pg_dump or physical pg_basebackup)
    These are independent dimensions: a logical backup can be manual or scheduled.

    Why expires_at?
    The retention policy defines how many days to keep a backup. The scheduling
    poller computes expires_at = created_at + retention_days when creating each backup.
    The retention job filters by expires_at <= now() to clean up old files.

    Why a DELETED status instead of deleting the record?
    We keep an audit trail: we know a backup existed, when it was created, and when
    it was deleted. Only the physical file is removed.
    """

    __tablename__ = "backups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    backup_type: Mapped[BackupType] = mapped_column(
        SAEnum(BackupType, name="backuptype"),
        nullable=False,
        default=BackupType.MANUAL,
    )
    strategy: Mapped[BackupStrategy] = mapped_column(
        SAEnum(BackupStrategy, name="backupstrategy"),
        nullable=False,
        default=BackupStrategy.LOGICAL,
    )
    status: Mapped[BackupStatus] = mapped_column(
        SAEnum(BackupStatus, name="backupstatus"),
        nullable=False,
        default=BackupStatus.PENDING,
        index=True,
    )
    file_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Absolute path to the backup file or directory on the host",
    )
    size_bytes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When this backup should be deleted by the retention job",
    )

    __table_args__ = (
        Index(
            "ix_backups_instance_strategy_created",
            "instance_id",
            "strategy",
            "created_at",
        ),
    )


class BackupSchedule(Base):
    """
    Configures automatic backups for an instance.

    Why cron_expression?
    Cron is the universal way to express periodic schedules — every engineering
    team understands "0 2 * * *" as "2 AM every day". We use the
    `croniter` library to validate and compute the next run time.

    How does the scheduler work?
    backup_scheduler.py checks every 60s which schedules have
    next_run_at <= now(). For each one, it triggers a backup with the configured
    strategy, updates last_run_at, recomputes next_run_at, and applies retention.
    """

    __tablename__ = "backup_schedules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    strategy: Mapped[BackupStrategy] = mapped_column(
        SAEnum(BackupStrategy, name="backupstrategy"),
        nullable=False,
        default=BackupStrategy.LOGICAL,
    )
    cron_expression: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Standard 5-field cron expression, e.g. '0 2 * * *'",
    )
    retention_days: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=7,
        comment=(
            "How many days to keep backups created by this schedule; "
            "NULL = keep indefinitely"
        ),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
