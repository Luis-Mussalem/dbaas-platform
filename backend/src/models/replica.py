import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import BigInteger, DateTime, Index, Numeric, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class ReplicationState(str, PyEnum):
    """
    State of a standby's replication stream.

    - PENDING/PROVISIONING: the replica is being created (pg_basebackup in progress).
    - STREAMING: standby connected to the primary, receiving WAL in real time.
    - CATCHUP: connected, but still applying delayed WAL (high lag).
    - DISCONNECTED: no active stream on the primary (doesn't show up in pg_stat_replication).
    - PROMOTED: the replica was promoted to a standalone primary (end of the link).
    - FAILED: creation or promotion failed.
    """

    PENDING = "pending"
    PROVISIONING = "provisioning"
    STREAMING = "streaming"
    CATCHUP = "catchup"
    DISCONNECTED = "disconnected"
    PROMOTED = "promoted"
    FAILED = "failed"


class Replica(Base):
    """
    Replication link between a primary instance and a standby.

    The replica itself is a companion `DatabaseInstance` (reuses status, port,
    metrics, and the fleet's state machine); this row just links the two and
    stores the replication state and lag measured by the replication_poller.

    No FK on the instance columns (same pattern as Backup): multi-tenant scoping is
    enforced in the router via `get_instance_or_404` on `primary_instance_id`.
    """

    __tablename__ = "replicas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    primary_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    replica_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    replication_state: Mapped[ReplicationState] = mapped_column(
        SAEnum(ReplicationState, name="replicationstate"),
        nullable=False,
        default=ReplicationState.PENDING,
        index=True,
    )
    lag_bytes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="Bytes of WAL the standby is behind the primary (sent_lsn - replay_lsn)",
    )
    lag_seconds: Mapped[float | None] = mapped_column(
        Numeric,
        nullable=True,
        comment="Replay delay in seconds (pg_stat_replication.replay_lag)",
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_replicas_primary_state",
            "primary_instance_id",
            "replication_state",
        ),
    )
