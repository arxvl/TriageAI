"""Reads and writes for the knowledge base: entries, rules and versions.

Queries and row writes only — no workflow rules (CLAUDE.md §7). Which
transition is allowed lives in `services/kb_transitions.py`, and who may ask for
it lives in the router.

Two methods are worth reading before changing them.

**`next_version_no` is `max + 1` and nothing cleverer.** `kb_versions.version_no`
is unique, so two publications racing for the same number produce an integrity
error rather than two versions numbered alike; the service turns that into a 409
and the caller retries (FR-54, DR-05).

**`link_version_entries` inserts and never updates.** `kb_version_entries` is
append-only at the database level (migration 0002), so a published version's
entry list cannot be corrected — a change is a new version.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.jobs.queue import KB_INDEX_ENTRY_KEY
from app.models import (
    Job,
    JobType,
    KBEntry,
    KBEntryKind,
    KBEntryStatus,
    KBVersion,
    PresentingComplaint,
    RedFlagRule,
    Species,
    User,
    VTLCategory,
    kb_version_entries,
)

__all__ = ["KBRepository"]


class KBRepository:
    """Knowledge-base persistence for one session. Flushes; never commits."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- Entries -----------------------------------------------------------

    def get_entry(self, entry_id: uuid.UUID) -> KBEntry | None:
        return self._session.get(KBEntry, entry_id)

    def get_entry_by_slug(self, slug: str) -> KBEntry | None:
        return self._session.scalars(select(KBEntry).where(KBEntry.slug == slug)).first()

    def draft_revision_of(self, entry_id: uuid.UUID) -> KBEntry | None:
        """The open DRAFT that supersedes this entry, if one exists (ADR-14).

        An ACTIVE entry is never edited, so a changed file becomes a new draft
        revision pointing back at it. This is how a *second* import of the same
        changed file finds that revision instead of inserting another one — the
        importer's idempotency rests on it (FR-56).

        Only DRAFT: once the revision has been submitted or approved it is no
        longer the row an import may touch.
        """
        return self._session.scalars(
            select(KBEntry)
            .where(
                KBEntry.revises_entry_id == entry_id,
                KBEntry.status == KBEntryStatus.DRAFT,
            )
            .order_by(KBEntry.id)
        ).first()

    def revision_slugs(self, slug: str) -> list[str]:
        """Every slug already taken by a revision of `slug` — `<slug>-rev2`, ….

        Used to pick the next revision number. `uq_kb_entries_slug` is unique, so
        a revision cannot reuse the base slug; the suffix is what keeps the index
        intact and the revision nameable in W-08.
        """
        return list(
            self._session.scalars(select(KBEntry.slug).where(KBEntry.slug.like(f"{slug}-rev%")))
        )

    def active_urgency_actions_entry(
        self, category: VTLCategory, *, exclude_id: uuid.UUID | None = None
    ) -> KBEntry | None:
        """The ACTIVE baseline action set for one category, or None (ADR-18).

        `uq_kb_entries_active_urgency_actions` guarantees there is at most one, so
        this is a lookup and not a list. Two callers need it: the approval gate,
        which refuses a second set for a category the service can name, and the
        importer, which treats a changed `actions-<category>.yaml` as a revision
        of the set it replaces.

        `exclude_id` leaves the entry being acted on out, so an entry does not
        collide with itself.
        """
        statement = select(KBEntry).where(
            KBEntry.kind == KBEntryKind.URGENCY_ACTIONS,
            KBEntry.status == KBEntryStatus.ACTIVE,
            KBEntry.urgency_category == category,
        )
        if exclude_id is not None:
            statement = statement.where(KBEntry.id != exclude_id)
        return self._session.scalars(statement).first()

    def complaint_exists(self, code: str) -> bool:
        return self._session.get(PresentingComplaint, code) is not None

    def list_complaints(self) -> list[PresentingComplaint]:
        """The fixed presenting-complaint list, in the order W-08 offers it (FR-10).

        `sort_order` is the clinical ordering seeded with the table, which puts
        the emergencies first and OTHER last; the name breaks a tie so the list
        is stable whatever the seed did.
        """
        return list(
            self._session.scalars(
                select(PresentingComplaint).order_by(
                    PresentingComplaint.sort_order, PresentingComplaint.name
                )
            )
        )

    def list_entries(
        self,
        *,
        status: KBEntryStatus | None = None,
        kind: KBEntryKind | None = None,
    ) -> list[KBEntry]:
        """Entries for the W-08 list, newest first within a status.

        Ordered by title rather than by creation, because the list is read as a
        catalogue: an administrator looking for an entry knows its subject, not
        when somebody wrote it.
        """
        statement = select(KBEntry).order_by(KBEntry.title)
        if status is not None:
            statement = statement.where(KBEntry.status == status)
        if kind is not None:
            statement = statement.where(KBEntry.kind == kind)
        return list(self._session.scalars(statement))

    def entry_counts_by_status(self) -> dict[KBEntryStatus, int]:
        """How many entries sit in each status, for the four W-08 tabs."""
        rows = self._session.execute(
            select(KBEntry.status, func.count()).group_by(KBEntry.status)
        ).all()
        counts = dict.fromkeys(KBEntryStatus, 0)
        for status, count in rows:
            counts[KBEntryStatus(status)] = count
        return counts

    def active_entry_ids(self) -> list[uuid.UUID]:
        """Every currently ACTIVE entry, in a stable order.

        This is the membership of the next published version (FR-54): *all*
        active entries, of both kinds, not only the one being approved.
        """
        return list(
            self._session.scalars(
                select(KBEntry.id)
                .where(KBEntry.status == KBEntryStatus.ACTIVE)
                .order_by(KBEntry.id)
            )
        )

    def insert_entry(
        self,
        *,
        kind: KBEntryKind,
        title: str,
        content: str,
        species: list[Species],
        created_by: uuid.UUID,
        slug: str | None = None,
        complaint_code: str | None = None,
        urgency_category: VTLCategory | None = None,
        source_title: str | None = None,
        source_publisher: str | None = None,
        source_url: str | None = None,
        access_date: object = None,
        revises_entry_id: uuid.UUID | None = None,
    ) -> KBEntry:
        entry = KBEntry(
            kind=kind,
            slug=slug,
            complaint_code=complaint_code,
            urgency_category=urgency_category,
            title=title,
            content=content,
            species=species,
            source_title=source_title,
            source_publisher=source_publisher,
            source_url=source_url,
            access_date=access_date,
            status=KBEntryStatus.DRAFT,
            created_by=created_by,
            revises_entry_id=revises_entry_id,
        )
        self._session.add(entry)
        self._session.flush()
        return entry

    def apply_entry_changes(self, entry: KBEntry, changes: dict[str, object]) -> KBEntry:
        """Write the fields an edit sent, and nothing else."""
        for field, value in changes.items():
            setattr(entry, field, value)
        self._session.flush()
        return entry

    def set_entry_status(
        self,
        entry: KBEntry,
        status: KBEntryStatus,
        *,
        review_comments: str | None = None,
        approved_by: uuid.UUID | None = None,
        approved_at: datetime | None = None,
    ) -> KBEntry:
        """Move an entry, and set what that move records.

        `review_comments` is cleared on any move that is not a rejection, so a
        draft that has been revised does not keep showing the comments it was
        sent back with.
        """
        entry.status = status
        entry.review_comments = review_comments
        if approved_by is not None:
            entry.approved_by = approved_by
        if approved_at is not None:
            entry.approved_at = approved_at
        self._session.flush()
        return entry

    def user_names(self, user_ids: list[uuid.UUID | None]) -> dict[uuid.UUID, str]:
        """Full names for the ids an entry's author, approver or publisher columns hold.

        One query for the whole page rather than a lazy relationship per row,
        and `None`s are dropped on the way in so callers can pass the columns
        straight through.
        """
        wanted = {user_id for user_id in user_ids if user_id is not None}
        if not wanted:
            return {}
        rows = self._session.execute(
            select(User.id, User.full_name).where(User.id.in_(wanted))
        ).all()
        return {row.id: row.full_name for row in rows}

    def latest_index_job(self, entry_id: uuid.UUID) -> Job | None:
        """The newest `KB_INDEX` job for this entry, or None.

        The entry id lives in the job's JSONB payload rather than a column — a
        `KB_INDEX` job is about an entry, and `jobs` has `case_id` and
        `vignette_id` only.
        """
        return self._session.scalars(
            select(Job)
            .where(
                Job.type == JobType.KB_INDEX,
                Job.payload[KB_INDEX_ENTRY_KEY].astext == str(entry_id),
            )
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(1)
        ).first()

    # --- Red-flag rules ----------------------------------------------------

    def get_rule(self, rule_id: uuid.UUID) -> RedFlagRule | None:
        return self._session.get(RedFlagRule, rule_id)

    def get_rule_by_code(self, code: str) -> RedFlagRule | None:
        return self._session.scalars(select(RedFlagRule).where(RedFlagRule.code == code)).first()

    def list_rules(self) -> list[RedFlagRule]:
        return list(self._session.scalars(select(RedFlagRule).order_by(RedFlagRule.code)))

    def rules_for_entry(self, entry_id: uuid.UUID) -> list[RedFlagRule]:
        return list(
            self._session.scalars(
                select(RedFlagRule)
                .where(RedFlagRule.entry_id == entry_id)
                .order_by(RedFlagRule.code)
            )
        )

    def insert_rule(
        self,
        *,
        code: str,
        label: str,
        min_category: VTLCategory,
        species: list[Species],
        phrases_ref: str | None,
        is_placeholder: bool,
    ) -> RedFlagRule:
        rule = RedFlagRule(
            code=code,
            label=label,
            min_category=min_category,
            species=species,
            phrases_ref=phrases_ref,
            is_placeholder=is_placeholder,
            entry_id=None,
            approved_by=None,
            approved_at=None,
            retired_at=None,
        )
        self._session.add(rule)
        self._session.flush()
        return rule

    def apply_rule_changes(self, rule: RedFlagRule, changes: dict[str, object]) -> RedFlagRule:
        for field, value in changes.items():
            setattr(rule, field, value)
        self._session.flush()
        return rule

    def set_rule_entry(self, rule: RedFlagRule, entry_id: uuid.UUID | None) -> None:
        rule.entry_id = entry_id
        self._session.flush()

    def approve_rule(
        self, rule: RedFlagRule, *, approved_by: uuid.UUID, at: datetime
    ) -> RedFlagRule:
        """Record the approval that lets a rule screen cases (NFR-08, BR-04).

        `is_placeholder` is cleared by the same write: a rule a veterinarian has
        approved is no longer a placeholder, and leaving the flag set would keep
        it out of `get_active_rules` outside development.
        """
        rule.approved_by = approved_by
        rule.approved_at = at
        rule.is_placeholder = False
        self._session.flush()
        return rule

    def retire_rule(self, rule: RedFlagRule, *, at: datetime) -> RedFlagRule:
        rule.retired_at = at
        self._session.flush()
        return rule

    # --- Versions (FR-54, DR-05) -------------------------------------------

    def next_version_no(self) -> int:
        current = self._session.scalars(select(func.max(KBVersion.version_no))).first()
        return (current or 0) + 1

    def insert_version(
        self, *, version_no: int, published_by: uuid.UUID | None, at: datetime, note: str | None
    ) -> KBVersion:
        version = KBVersion(
            version_no=version_no, published_at=at, published_by=published_by, note=note
        )
        self._session.add(version)
        self._session.flush()
        return version

    def link_version_entries(self, version_id: uuid.UUID, entry_ids: list[uuid.UUID]) -> int:
        """Record which entries this version contains; returns how many.

        Insert-only, because the table is append-only (migration 0002, DR-05).
        """
        if not entry_ids:
            return 0
        self._session.execute(
            insert(kb_version_entries),
            [{"kb_version_id": version_id, "entry_id": entry_id} for entry_id in entry_ids],
        )
        self._session.flush()
        return len(entry_ids)

    def get_version(self, version_id: uuid.UUID) -> KBVersion | None:
        return self._session.get(KBVersion, version_id)

    def list_versions(self) -> list[KBVersion]:
        return list(self._session.scalars(select(KBVersion).order_by(KBVersion.version_no.desc())))

    def version_entry_counts(self) -> dict[uuid.UUID, int]:
        rows = self._session.execute(
            select(kb_version_entries.c.kb_version_id, func.count()).group_by(
                kb_version_entries.c.kb_version_id
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    def version_entries(self, version_id: uuid.UUID) -> list[KBEntry]:
        return list(
            self._session.scalars(
                select(KBEntry)
                .join(kb_version_entries, kb_version_entries.c.entry_id == KBEntry.id)
                .where(kb_version_entries.c.kb_version_id == version_id)
                .order_by(KBEntry.title)
            )
        )

    def latest_published_version_no(self) -> int | None:
        """The version number W-08's header and W-04's footnote show.

        Published only: a version with no `published_at` is the seeded
        placeholder version 0, which no approval produced.
        """
        return self._session.scalars(
            select(KBVersion.version_no)
            .where(KBVersion.published_at.is_not(None))
            .order_by(KBVersion.version_no.desc())
            .limit(1)
        ).first()
