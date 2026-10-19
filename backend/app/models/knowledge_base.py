import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin
from app.models.enums import KBEntryKind, KBEntryStatus, Species, VTLCategory, pg_enum


class PresentingComplaint(Base):
    __tablename__ = "presenting_complaints"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class KBEntry(Base, UUIDPKMixin):
    """One knowledge-base entry: clinical content, or a baseline action set.

    `kind` splits the two (ADR-18). A `COMPLAINT` entry is retrievable and hangs
    off a presenting complaint; an `URGENCY_ACTIONS` entry holds the baseline
    actions for one VTL category and is looked up by category, never
    similarity-searched. The two check constraints make that exclusive, so a
    row cannot be both or neither.

    Storing baseline actions here rather than in a config file is deliberate:
    they then inherit the citation, approval and versioning machinery of
    ADR-14 like any other clinical content (BR-04, BR-10).
    """

    __tablename__ = "kb_entries"

    kind: Mapped[KBEntryKind] = mapped_column(
        pg_enum(KBEntryKind, "kb_entry_kind"),
        nullable=False,
        default=KBEntryKind.COMPLAINT,
        server_default=KBEntryKind.COMPLAINT.value,
    )
    # The name of the file this entry was imported from, and the key a re-import
    # upserts on (FR-56). Null for an entry that was never imported — the five
    # seeded urgency-action sets, and anything typed into W-08.
    slug: Mapped[str | None] = mapped_column(String(120))
    # The ACTIVE entry this draft supersedes. An ACTIVE entry is never edited in
    # place; a change becomes a new DRAFT revision that goes through approval
    # again (ADR-14).
    revises_entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kb_entries.id"))
    # Null on an URGENCY_ACTIONS entry, which belongs to a category, not a
    # complaint (ck_kb_entries_complaint_code_iff_complaint).
    complaint_code: Mapped[str | None] = mapped_column(ForeignKey("presenting_complaints.code"))
    urgency_category: Mapped[VTLCategory | None] = mapped_column(
        pg_enum(VTLCategory, "vtl_category")
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

    __table_args__ = (
        CheckConstraint(
            "(urgency_category IS NOT NULL) = (kind = 'URGENCY_ACTIONS')",
            name="ck_kb_entries_urgency_category_iff_urgency_actions",
        ),
        CheckConstraint(
            "(complaint_code IS NOT NULL) = (kind = 'COMPLAINT')",
            name="ck_kb_entries_complaint_code_iff_complaint",
        ),
        # At most one ACTIVE baseline set per category, so the lookup in
        # `baseline_actions()` can never be ambiguous (FR-72). Partial, so
        # superseded DRAFT or RETIRED revisions still coexist.
        Index(
            "uq_kb_entries_active_urgency_actions",
            "urgency_category",
            unique=True,
            postgresql_where=text("kind = 'URGENCY_ACTIONS' AND status = 'ACTIVE'"),
        ),
        # One entry per imported file. Unique, and nullable: an entry that was
        # never imported — the five seeded urgency-action sets — has no slug, and
        # PostgreSQL treats NULLs in a unique index as distinct (FR-56).
        # Declared here rather than as `unique=True` on the column so the name
        # matches migration 0005.
        Index("uq_kb_entries_slug", "slug", unique=True),
        # W-08's four status tabs, and the kind filter that separates the five
        # urgency-action sets from the clinical entries (P08 §8.3).
        Index("ix_kb_entries_status_kind", "status", "kind"),
    )


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
    # The key in `knowledge_base/red_flag_phrases.yaml` holding this rule's
    # phrases. The phrases are maintained by hand (M1); only the category and the
    # species live here, so the safety floor has one source of truth.
    phrases_ref: Mapped[str | None] = mapped_column(Text)
    # Set when the rule is retired. Retired, never deleted: a recommendation
    # whose safety floor cited this rule must stay explainable (FR-23, ADR-14).
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KBChunk(Base, UUIDPKMixin, CreatedAtMixin):
    """A chunk of a knowledge base entry."""

    __tablename__ = "kb_chunks"

    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_entries.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(nullable=True)


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
