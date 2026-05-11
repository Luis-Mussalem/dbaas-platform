import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class AuditLog(Base):
    """
    Registro imutável de ações realizadas na plataforma.

    user_id é nullable por dois motivos:
    1. Login e register não possuem JWT no request — o usuário ainda não está
       autenticado quando o request chega, portanto não há como extrair o ID.
    2. Ações de background tasks (backup agendado, maintenance) não têm usuário.

    resource_id é String (não UUID) para suportar ações onde não existe um
    recurso específico — e.g. action="login", resource_type="auth".

    details armazena contexto adicional (method, path, response status) sem
    parsear o body do request. O middleware não pode consumir o body — isso
    quebraria o handler que processa o request depois.

    Índice composto (user_id, timestamp): a query mais comum é
    "todas as ações deste usuário, ordenadas por data".
    Índice simples em timestamp: cobre paginação global sem filtro de usuário.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("ix_audit_logs_user_timestamp", "user_id", "timestamp"),
    )
