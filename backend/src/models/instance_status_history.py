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
    Registro imutável de cada transição de status de uma instância.

    Existe para derivar o "uptime" (fração do tempo em RUNNING numa janela):
    a coluna DatabaseInstance.status guarda apenas o estado atual, sem histórico.
    Uma linha é gravada a cada mudança de status via
    services.status_history.record_status_change — nunca editada nem apagada.
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
    # Reusa o tipo enum 'instancestatus' já criado por database_instances —
    # create_type=False evita o CREATE TYPE duplicado (o tipo é criado uma vez,
    # pela tabela que o define primeiro).
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
