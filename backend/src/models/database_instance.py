import uuid
from enum import Enum as PyEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.models.company import Company


class InstanceStatus(str, PyEnum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    STOPPED = "stopped"
    DELETING = "deleting"
    DELETED = "deleted"
    FAILED = "failed"


class Environment(str, PyEnum):
    """
    Logical environment of the instance — used to group/filter in the dashboard.

    Canonical values are in English; the UI translates them into the displayed
    labels (production / staging / development). Nullable: older instances
    or ones without a classification are left without an environment.
    """

    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


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
    region: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Region code, e.g. sa-east-1 / us-east-1 / eu-west-1",
    )
    environment: Mapped[Environment | None] = mapped_column(
        SAEnum(Environment, name="environment"),
        nullable=True,
    )
    # Company that owns the instance (multi-tenant). Root of the scoping: backups,
    # alerts and maintenance inherit the owner via instance_id. Nullable: system/legacy
    # instances and ones created by a superuser with no company are visible only to the
    # superuser. Same pattern as users.company_id (optional FK, SET NULL).
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    company: Mapped["Company | None"] = relationship("Company", lazy="joined")
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