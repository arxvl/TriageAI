import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin
from app.models.enums import VTLCategory, pg_enum


class RedFlagAlert(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "red_flag_alerts"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), nullable=False)
    rule_code: Mapped[str] = mapped_column(ForeignKey("red_flag_rules.code"), nullable=False)
    matched_text: Mapped[str] = mapped_column(Text, nullable=False)
    min_category: Mapped[VTLCategory] = mapped_column(
        pg_enum(VTLCategory, "vtl_category"), nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
