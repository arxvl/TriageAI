import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import UserRole, pg_enum


class AuditEntry(Base):
    """Append-only audit trail (FR-43, ADR-12).

    Immutability (no UPDATE/DELETE for the application role) is enforced by
    a database trigger added in subphase 2.2, not by this model.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    role: Mapped[UserRole | None] = mapped_column(pg_enum(UserRole, "user_role"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_audit_log_entity_type_entity_id_ts", "entity_type", "entity_id", "ts"),
    )
