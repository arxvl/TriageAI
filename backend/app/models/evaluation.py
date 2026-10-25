import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin
from app.models.enums import JobStatus, Species, VTLCategory, pg_enum


class EvaluationSet(Base, UUIDPKMixin):
    __tablename__ = "evaluation_sets"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    imported_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    # The CLI resolves a set by name, so a name means one set (migration 0007).
    __table_args__ = (UniqueConstraint("name", name="uq_evaluation_sets_name"),)


class Vignette(Base, UUIDPKMixin):
    __tablename__ = "vignettes"

    set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_sets.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    species: Mapped[Species] = mapped_column(pg_enum(Species, "species"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reference_category: Mapped[VTLCategory] = mapped_column(
        pg_enum(VTLCategory, "vtl_category"), nullable=False
    )
    relevant_entry_ids: Mapped[list | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("set_id", "external_id", name="uq_vignettes_set_id_external_id"),
    )


class EvaluationRun(Base, UUIDPKMixin, CreatedAtMixin):
    """A run of the evaluation harness over an EvaluationSet.

    `status` reuses JobStatus (QUEUED/RUNNING/DONE/FAILED) — P02 names this
    column but not its enum, and JobStatus is the closest existing fit.

    `config` is the snapshot of everything that decides what the pipeline does,
    taken when the run starts (NFR-23). `metrics` is computed once, from the
    stored results, when the run finishes.
    """

    __tablename__ = "evaluation_runs"

    set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_sets.id"), nullable=False)
    kb_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kb_versions.id"))
    config: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"), nullable=False, default=JobStatus.QUEUED
    )
    metrics: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class EvaluationResult(Base, UUIDPKMixin):
    __tablename__ = "evaluation_results"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_runs.id"), nullable=False)
    vignette_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vignettes.id"), nullable=False)
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recommendations.id"))
    extraction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("extraction_results.id"))
    predicted_category: Mapped[VTLCategory | None] = mapped_column(
        pg_enum(VTLCategory, "vtl_category")
    )
    stage_latencies: Mapped[dict | None] = mapped_column(JSONB)
    # A reason code, never a model response (CLAUDE.md §9).
    error: Mapped[str | None] = mapped_column(Text)
    # Red-flag hits, retrieved entry ids in rank order, primary complaint, and the
    # safety-floor flag (migration 0007).
    payload: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("run_id", "vignette_id", name="uq_evaluation_results_run_id_vignette_id"),
    )
