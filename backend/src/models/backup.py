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
    Representa uma operação de backup — manual ou agendada.

    Por que separar backup_type de strategy?
    - backup_type: QUEM iniciou (operador manualmente via API ou scheduler automático)
    - strategy: COMO foi feito (pg_dump lógico ou pg_basebackup físico)
    Essas são dimensões independentes: um backup lógico pode ser manual ou agendado.

    Por que expires_at?
    A política de retenção define por quantos dias manter um backup. O poller de
    agendamento calcula expires_at = created_at + retention_days ao criar cada backup.
    O job de retenção filtra por expires_at <= now() para limpar arquivos antigos.

    Por que status DELETED em vez de deletar o registro?
    Mantemos um audit trail: sabemos que houve um backup, quando foi criado e quando
    foi apagado. Apenas o arquivo físico é removido.
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
    Configura backups automáticos para uma instância.

    Por que cron_expression?
    Cron é a forma universal de expressar schedules periódicos — toda equipe
    de engenharia entende "0 2 * * *" como "2 AM todo dia". Usamos a biblioteca
    `croniter` para validar e calcular o próximo tempo de execução.

    Como funciona o scheduler?
    O backup_scheduler.py verifica a cada 60s quais schedules têm
    next_run_at <= now(). Para cada um, dispara um backup da strategy configurada,
    atualiza last_run_at, recalcula next_run_at e aplica retenção.
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
    retention_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=7,
        comment="How many days to keep backups created by this schedule",
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
