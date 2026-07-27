import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class AuditLog(Base):
    """
    Immutable record of actions performed on the platform.

    user_id is nullable for two reasons:
    1. Login and register have no JWT in the request — the user isn't
       authenticated yet when the request arrives, so there's no way to extract the ID.
    2. Background task actions (scheduled backup, maintenance) have no user.

    resource_id is String (not UUID) to support actions where there is no
    specific resource — e.g. action="login", resource_type="auth".

    details stores additional context (method, path, response status) without
    parsing the request body. The middleware cannot consume the body — that
    would break the handler that processes the request afterward.

    Composite index (user_id, timestamp): the most common query is
    "all actions of this user, ordered by date".
    Simple index on timestamp: covers global pagination without a user filter.
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
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("ix_audit_logs_user_timestamp", "user_id", "timestamp"),
        Index("ix_audit_logs_company_timestamp", "company_id", "timestamp"),
    )
