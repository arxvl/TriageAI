import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin
from app.models.enums import AgeUnit, CaseStatus, IntakeChannel, Sex, Species, pg_enum


class Case(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "cases"

    case_no: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    species: Mapped[Species] = mapped_column(pg_enum(Species, "species"), nullable=False)
    intake_channel: Mapped[IntakeChannel] = mapped_column(
        pg_enum(IntakeChannel, "intake_channel"), nullable=False
    )
    status: Mapped[CaseStatus] = mapped_column(pg_enum(CaseStatus, "case_status"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_cases_status_created_at", "status", "created_at"),)


class Signalment(Base, UUIDPKMixin):
    __tablename__ = "signalments"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), unique=True, nullable=False)
    pet_name: Mapped[str | None] = mapped_column(String(200))
    age_value: Mapped[float | None] = mapped_column(Numeric)
    age_unit: Mapped[AgeUnit | None] = mapped_column(pg_enum(AgeUnit, "age_unit"))
    sex: Mapped[Sex] = mapped_column(pg_enum(Sex, "sex"), nullable=False, default=Sex.UNKNOWN)
    neutered: Mapped[bool | None] = mapped_column(Boolean)
    breed: Mapped[str | None] = mapped_column(String(200))
    weight_kg: Mapped[float | None] = mapped_column(Numeric)


class OwnerDescription(Base, UUIDPKMixin):
    """The owner's verbatim symptom description.

    `text` is never updated after insert (FR-05). That immutability is
    enforced by a database trigger added in subphase 2.2, not here.
    """

    __tablename__ = "owner_descriptions"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), unique=True, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OwnerReference(Base, UUIDPKMixin):
    """Owner personal identifiers, isolated from clinical text.

    Never read by pipeline code (DR-04) — an implementation-discipline rule
    for callers, not something expressible as a schema constraint.
    """

    __tablename__ = "owner_references"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), unique=True, nullable=False)
    owner_name: Mapped[str | None] = mapped_column(String(200))
    contact_number: Mapped[str | None] = mapped_column(String(50))
