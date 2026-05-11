import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class AlertCondition(str, enum.Enum):
    GT  = "gt"   # maior que (greater than)
    GTE = "gte"  # maior ou igual (greater than or equal)
    LT  = "lt"   # menor que (less than)
    LTE = "lte"  # menor ou igual (less than or equal)
    EQ  = "eq"   # igual (equal)


class AlertSeverity(str, enum.Enum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


class AlertRule(Base):
    """
    Define uma regra de detecção de problemas para uma instância específica.

    metric_type é String (não Enum no banco) para permitir novos tipos sem
    migration. O Pydantic valida os valores aceitos na camada de schema.

    Por que threshold é Float e não Int?
    Permite regras como "cache_hit_ratio < 95.5" ou "backup_age_hours > 23.5"
    sem perda de precisão. Na prática, a maioria será inteiro, mas Float não custa nada.

    Por que name é obrigatório?
    Facilita identificar o alerta no log: "[CRITICAL] Backup Overdue" é
    imediatamente compreensível, ao contrário de "backup_age_hours > 24".
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
    Registra uma ocorrência de disparo de uma AlertRule.

    Um evento fica "aberto" (resolved_at = NULL) enquanto o problema persiste.
    O avaliador automático resolve o evento quando o valor volta ao normal.
    O operador também pode resolver manualmente via API.

    Por que manter eventos resolvidos em vez de deletar?
    Audit trail: permite ver a frequência de um problema, quando foi resolvido
    e por quanto tempo a instância ficou em estado crítico.

    Índice composto (instance_id, resolved_at):
    A query mais frequente é "alertas abertos desta instância" →
    WHERE instance_id = X AND resolved_at IS NULL. O índice cobre esse filtro.
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
