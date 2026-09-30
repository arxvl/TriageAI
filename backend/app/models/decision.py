import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin
from app.models.enums import DecisionDirection, DecisionType, VTLCategory, pg_enum


class StaffDecision(Base, UUIDPKMixin):
    __tablename__ = "staff_decisions"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), nullable=False)
    type: Mapped[DecisionType] = mapped_column(
        pg_enum(DecisionType, "decision_type"), nullable=False
    )
    final_category: Mapped[VTLCategory] = mapped_column(
        pg_enum(VTLCategory, "vtl_category"), nullable=False
    )
    reason_code: Mapped[str | None] = mapped_column(String(100))
    reason_text: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[DecisionDirection] = mapped_column(
        pg_enum(DecisionDirection, "decision_direction"), nullable=False
    )
    decided_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amends_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_decisions.id"))

    __table_args__ = (
        CheckConstraint(
            "type <> 'ADJUST' OR reason_code IS NOT NULL",
            name="ck_staff_decisions_reason_code_required_for_adjust",
        ),
    )


class ClinicalNote(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "clinical_notes"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
