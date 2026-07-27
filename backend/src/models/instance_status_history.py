import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.models.database_instance import InstanceStatus


class InstanceStatusHistory(Base):
    """
    Immutable record of each status transition of an instance.

    Exists to derive "uptime" (the fraction of time spent RUNNING in a window):
    the DatabaseInstance.status column only holds the current state, with no history.
    A row is written on every status change via
    services.status_history.record_status_change — never edited or deleted.
    """

    __tablename__ = "instance_status_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("database_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Reuses the 'instancestatus' enum type already created by database_instances —
    # create_type=False avoids a duplicate CREATE TYPE (the type is created once,
    # by whichever table defines it first).
    status: Mapped[InstanceStatus] = mapped_column(
        SAEnum(InstanceStatus, name="instancestatus", create_type=False),
        nullable=False,
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("ix_instance_status_history_instance_changed", "instance_id", "changed_at"),
    )
