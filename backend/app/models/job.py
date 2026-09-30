import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import JobStatus, JobType, pg_enum


class Job(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "jobs"

    type: Mapped[JobType] = mapped_column(pg_enum(JobType, "job_type"), nullable=False)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id"))
    vignette_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vignettes.id"))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"), nullable=False, default=JobStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)
