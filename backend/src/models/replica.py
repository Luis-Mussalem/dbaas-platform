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
    Estado do fluxo de replicação de um standby.

    - PENDING/PROVISIONING: a réplica está sendo criada (pg_basebackup em curso).
    - STREAMING: standby conectado ao primário, recebendo WAL em tempo real.
    - CATCHUP: conectado, mas ainda aplicando WAL atrasado (lag alto).
    - DISCONNECTED: sem stream ativo no primário (não aparece em pg_stat_replication).
    - PROMOTED: a réplica foi promovida a primário standalone (fim do vínculo).
    - FAILED: a criação ou a promoção falhou.
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
    Vínculo de replicação entre uma instância primária e um standby.

    A réplica em si é uma `DatabaseInstance` companheira (reusa status, porta,
    métricas e a máquina de estados da frota); esta linha só liga as duas e
    guarda o estado de replicação e o lag medido pelo replication_poller.

    Sem FK nas colunas de instância (padrão do Backup): o scoping multi-tenant é
    imposto no router via `get_instance_or_404` sobre o `primary_instance_id`.
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
