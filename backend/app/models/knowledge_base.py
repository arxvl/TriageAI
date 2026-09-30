import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin
from app.models.enums import KBEntryStatus, Species, VTLCategory, pg_enum


class PresentingComplaint(Base):
    __tablename__ = "presenting_complaints"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class KBEntry(Base, UUIDPKMixin):
    __tablename__ = "kb_entries"

    complaint_code: Mapped[str] = mapped_column(
        ForeignKey("presenting_complaints.code"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    species: Mapped[list[Species]] = mapped_column(
        ARRAY(pg_enum(Species, "species")), nullable=False
    )
    source_title: Mapped[str | None] = mapped_column(String(300))
    source_publisher: Mapped[str | None] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    access_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[KBEntryStatus] = mapped_column(
        pg_enum(KBEntryStatus, "kb_entry_status"), nullable=False, default=KBEntryStatus.DRAFT
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comments: Mapped[str | None] = mapped_column(Text)


class RedFlagRule(Base, UUIDPKMixin):
    __tablename__ = "red_flag_rules"

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    min_category: Mapped[VTLCategory] = mapped_column(
        pg_enum(VTLCategory, "vtl_category"), nullable=False
    )
    species: Mapped[list[Species]] = mapped_column(
        ARRAY(pg_enum(Species, "species")), nullable=False
    )
    entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kb_entries.id"))
    is_placeholder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KBChunk(Base, UUIDPKMixin, CreatedAtMixin):
    """A chunk of a knowledge base entry.

    No `embedding` column here — it and its HNSW index are added manually
    in M4, once the embedding model is chosen (ADR-04, ADR-07).
    """

    __tablename__ = "kb_chunks"

    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_entries.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)


class KBVersion(Base, UUIDPKMixin):
    __tablename__ = "kb_versions"

    version_no: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)


kb_version_entries = Table(
    "kb_version_entries",
    Base.metadata,
    Column("kb_version_id", ForeignKey("kb_versions.id"), primary_key=True),
    Column("entry_id", ForeignKey("kb_entries.id"), primary_key=True),
)
