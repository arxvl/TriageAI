import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin
from app.models.enums import ConfidenceLevel, VTLCategory, pg_enum


class ExtractionResult(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "extraction_results"

    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id"))
    vignette_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vignettes.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    entities: Mapped[dict] = mapped_column(JSONB, nullable=False)
    red_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    missing_information: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    corrected_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint(
            "(case_id IS NULL) <> (vignette_id IS NULL)",
            name="ck_extraction_results_case_xor_vignette",
        ),
    )


extraction_complaints = Table(
    "extraction_complaints",
    Base.metadata,
    Column("extraction_id", ForeignKey("extraction_results.id"), primary_key=True),
    Column("complaint_code", ForeignKey("presenting_complaints.code"), primary_key=True),
    Column("is_primary", Boolean, nullable=False, default=False),
)


class Recommendation(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "recommendations"

    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id"))
    vignette_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vignettes.id"))
    extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extraction_results.id"), nullable=False
    )
    kb_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kb_versions.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[VTLCategory] = mapped_column(
        pg_enum(VTLCategory, "vtl_category"), nullable=False
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[ConfidenceLevel] = mapped_column(
        pg_enum(ConfidenceLevel, "confidence_level"), nullable=False
    )
    safety_floor_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    safety_floor_rule_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    low_confidence_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    params: Mapped[dict | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint(
            "(case_id IS NULL) <> (vignette_id IS NULL)",
            name="ck_recommendations_case_xor_vignette",
        ),
        Index("ix_recommendations_case_id_version", "case_id", text("version DESC")),
    )


class RetrievedReference(Base, UUIDPKMixin):
    __tablename__ = "retrieved_references"

    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recommendations.id"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kb_chunks.id"))
    score: Mapped[float | None] = mapped_column(Numeric)
    is_cited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    entry_title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_title: Mapped[str | None] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    passage_text: Mapped[str] = mapped_column(Text, nullable=False)
