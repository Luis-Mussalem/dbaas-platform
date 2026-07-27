import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class AlertCondition(str, enum.Enum):
    GT  = "gt"   # greater than
    GTE = "gte"  # greater than or equal
    LT  = "lt"   # less than
    LTE = "lte"  # less than or equal
    EQ  = "eq"   # equal


class AlertSeverity(str, enum.Enum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


class AlertRule(Base):
    """
    Defines a problem-detection rule for a specific instance.

    metric_type is String (not an Enum in the database) to allow new types without
    a migration. Pydantic validates the accepted values at the schema layer.

    Why is threshold a Float and not an Int?
    Allows rules like "cache_hit_ratio < 95.5" or "backup_age_hours > 23.5"
    without losing precision. In practice most will be integers, but Float costs nothing.

    Why is name required?
    Makes it easier to identify the alert in the log: "[CRITICAL] Backup Overdue" is
    immediately understandable, unlike "backup_age_hours > 24".
    """

    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("database_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    metric_type: Mapped[str] = mapped_column(String(100), nullable=False)
    condition: Mapped[AlertCondition] = mapped_column(
        SAEnum(AlertCondition, name="alertcondition"), nullable=False
    )
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        SAEnum(AlertSeverity, name="alertseverity"),
        nullable=False,
        default=AlertSeverity.WARNING,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AlertEvent(Base):
    """
    Records an occurrence of an AlertRule firing.

    An event stays "open" (resolved_at = NULL) while the problem persists.
    The automatic evaluator resolves the event when the value returns to normal.
    The operator can also resolve it manually via the API.

    Why keep resolved events instead of deleting them?
    Audit trail: lets you see how often a problem occurs, when it was resolved,
    and for how long the instance stayed in a critical state.

    Composite index (instance_id, resolved_at):
    The most frequent query is "open alerts for this instance" →
    WHERE instance_id = X AND resolved_at IS NULL. The index covers that filter.
    """

    __tablename__ = "alert_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("alert_rules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("database_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_value: Mapped[float] = mapped_column(Float, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("ix_alert_events_instance_resolved", "instance_id", "resolved_at"),
    )
