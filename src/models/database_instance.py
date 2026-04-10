import uuid
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class InstanceStatus(str, PyEnum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    STOPPED = "stopped"
    DELETING = "deleting"
    DELETED = "deleted"
    FAILED = "failed"


class DatabaseInstance(Base):
    __tablename__ = "database_instances"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    engine_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="16",
    )
    status: Mapped[InstanceStatus] = mapped_column(
        SAEnum(InstanceStatus, name="instancestatus"),
        nullable=False,
        default=InstanceStatus.PENDING,
        index=True,
    )
    host: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    port: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    db_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    db_user: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    connection_uri: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    cpu: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of vCPUs allocated",
    )
    memory_mb: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="RAM in megabytes",
    )
    storage_gb: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Disk storage in gigabytes",
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )  