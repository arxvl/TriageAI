"""Bulk import of knowledge-base drafts from YAML files (P08 §8.2, FR-56).

What this service is for: a curator edits a file under `knowledge_base/`, runs
the importer, and the content appears in W-08's Draft tab ready to be submitted.
It is the bulk path into the 8.1 workflow and is not a way around any part of it.

Four rules it enforces, each of which is the reason a plain upsert would not do.

**An ACTIVE entry is never modified.** Retrieval cites entries by id and a
recommendation made last week must still mean what it said, so a changed file for
a live entry inserts a new DRAFT revision with `revises_entry_id` set and the
slug `<slug>-rev2`, and leaves every column of the live row alone (ADR-14,
DR-05). A RETIRED entry is treated the same way: a published version still lists
it.

**Nothing is imported past the state machine.** An entry waiting for review is
skipped rather than edited underneath its approver, and an *approved* red-flag
rule is skipped rather than silently re-pointed — `require_rule_not_approved` is
the 8.1 rule, and lowering the safety floor by editing a text file is exactly
what NFR-08 exists to prevent.

**Re-importing an unchanged file does nothing at all.** No row write, no audit
entry. The comparison is field by field against the stored row, which is what
makes the script safe to run from a Makefile or on every deploy (FR-56).

**A baseline action set is matched by category as well as by slug.** An
`URGENCY_ACTIONS` file names the category it is for, and only one ACTIVE set may
hold a category (ADR-18). The five sets `scripts/seed.py` writes have no slug at
all, so matching on the slug alone would import `actions-red.yaml` as an
unrelated draft rather than as the revision of the set it replaces. The lookup
falls back to the ACTIVE set for the category, and the file then follows the
ordinary ACTIVE path: a new DRAFT revision, pointing back, with the live row
untouched (8.2b).

**Every problem is reported; none is raised.** The caller gets an `ImportReport`
holding one row per file, so one run names every error in every file rather than
stopping at the first.

The audit payloads carry slugs, codes, field *names* and word counts. Never an
entry's content: the log cannot be corrected, and the content is curated clinical
text that belongs on the row where it can be revised (FR-43, ADR-12,
CLAUDE.md §9).

Flushes; never commits. The caller owns the transaction, which is what makes
`--dry-run` a rollback rather than a second code path.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import KBEntry, KBEntryKind, KBEntryStatus, RedFlagRule, User
from app.repositories.kb_repository import KBRepository
from app.schemas.kb import word_count
from app.schemas.kb_import import (
    ENTRY_FILE_GLOB,
    ENTRY_SUBDIR,
    RULES_FILENAME,
    FileError,
    KBEntryFile,
    RedFlagRuleFile,
    parse_entry_file,
    parse_rules_file,
)
from app.services.audit_service import (
    KB_ENTRY_ENTITY,
    RED_FLAG_RULE_ENTITY,
    AuditAction,
    AuditService,
)

__all__ = [
    "ImportOutcome",
    "ImportReport",
    "ImportRow",
    "KBImporter",
    "entry_files",
    "parse_all",
    "revision_slug",
    "rules_file",
]

Clock = Callable[[], datetime]

# The entry fields an imported file owns. Everything else on the row — status,
# created_by, approved_by, revises_entry_id — belongs to the workflow, not to
# the file, and is never written by a comparison.
ENTRY_FILE_FIELDS: tuple[str, ...] = (
    "title",
    "complaint_code",
    "urgency_category",
    "species",
    "content",
    "source_title",
    "source_publisher",
    "source_url",
    "access_date",
)

# The rule fields a file owns. `code` is the key and is never a change;
# `approved_by`, `approved_at` and `retired_at` belong to the approver.
RULE_FILE_FIELDS: tuple[str, ...] = (
    "label",
    "min_category",
    "species",
    "phrases_ref",
    "is_placeholder",
)

# The statuses in which a stored entry may not be touched at all, with the
# reason the curator is told.
_UNTOUCHABLE: dict[KBEntryStatus, str] = {
    KBEntryStatus.PENDING_REVIEW: (
        "is waiting for review. Ask the approver to send it back before re-importing it."
    ),
}


class ImportOutcome(StrEnum):
    """What the importer did with one file, or one rule inside one file."""

    CREATED = "created"
    UPDATED = "updated"
    # A changed file for an ACTIVE or RETIRED entry: a new draft revision.
    REVISED = "revised"
    UNCHANGED = "unchanged"
    # The workflow forbids touching this row right now. Not an error: the file
    # is valid and the curator is told why nothing happened.
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(frozen=True)
class ImportRow:
    """One line of the summary: what happened to one entry or one rule."""

    name: str  # the slug, or the rule code
    outcome: ImportOutcome
    detail: str | None = None

    def line(self) -> str:
        suffix = f" — {self.detail}" if self.detail else ""
        return f"  {self.outcome.value:<9} {self.name}{suffix}"


@dataclass
class ImportReport:
    """Everything one run did, for the summary table and the exit code."""

    rules: list[ImportRow] = field(default_factory=list)
    entries: list[ImportRow] = field(default_factory=list)

    @property
    def rows(self) -> list[ImportRow]:
        return [*self.rules, *self.entries]

    @property
    def has_errors(self) -> bool:
        return any(row.outcome is ImportOutcome.ERROR for row in self.rows)

    def counts(self, rows: list[ImportRow]) -> dict[ImportOutcome, int]:
        tally = dict.fromkeys(ImportOutcome, 0)
        for row in rows:
            tally[row.outcome] += 1
        return tally

    def lines(self) -> list[str]:
        """The summary P08 §8.2 asks for, with one line per file underneath.

        The counters are always printed, zeros included, so a run that changed
        nothing says so in the same shape as a run that changed everything.
        """
        reported = []
        for label, rows in (("Red-flag rules", self.rules), ("Entries", self.entries)):
            if not rows:
                continue
            tally = self.counts(rows)
            summary = "  ".join(f"{outcome.value} {tally[outcome]:>3}" for outcome in ImportOutcome)
            reported.append(f"{label}: {summary}")
            reported.extend(row.line() for row in rows)
        return reported


def revision_slug(base: str, taken: list[str]) -> str:
    """The next free `<base>-revN`, starting at 2.

    `base` itself is revision 1 — the entry the file first created — so the first
    revision of it is `-rev2`. Numbers already taken are skipped rather than
    reused, because `uq_kb_entries_slug` would reject a collision and a retired
    revision still holds its name.
    """
    used = set(taken)
    number = 2
    while f"{base}-rev{number}" in used:
        number += 1
    return f"{base}-rev{number}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class KBImporter:
    """Upserts the parsed files into `kb_entries` and `red_flag_rules`.

    `author` is the account the created drafts are attributed to:
    `kb_entries.created_by` is not nullable and an import is somebody's act, so
    the script resolves an administrator and passes it in.
    """

    def __init__(self, session: Session, *, author: User, now: Clock | None = None) -> None:
        self._session = session
        self._kb = KBRepository(session)
        self._audit = AuditService(session)
        self._author = author
        self._now = now or _utc_now

    # --- Red-flag rules (FR-12, NFR-08) -----------------------------------

    def import_rules(self, rules: list[RedFlagRuleFile], report: ImportReport) -> None:
        """Upsert every rule in the file, by `code`.

        Rules are imported before entries, because an entry's `red_flag_codes`
        can only be linked to rules that exist.
        """
        for parsed in rules:
            report.rules.append(self._import_rule(parsed))

    def _import_rule(self, parsed: RedFlagRuleFile) -> ImportRow:
        existing = self._kb.get_rule_by_code(parsed.code)
        if existing is None:
            rule = self._kb.insert_rule(
                code=parsed.code,
                label=parsed.label,
                min_category=parsed.min_category,
                species=list(parsed.species),
                phrases_ref=parsed.phrases_ref,
                is_placeholder=parsed.is_placeholder,
            )
            self._record_rule(AuditAction.RED_FLAG_RULE_CREATED, rule, fields=RULE_FILE_FIELDS)
            return ImportRow(rule.code, ImportOutcome.CREATED)

        if existing.retired_at is not None:
            return ImportRow(
                existing.code,
                ImportOutcome.SKIPPED,
                "has been retired. Import a replacement under a new code.",
            )

        changes = self._rule_changes(existing, parsed)
        if not changes:
            return ImportRow(existing.code, ImportOutcome.UNCHANGED)

        if existing.approved_at is not None:
            # Editing an approved rule would change the safety floor a
            # veterinarian signed off, which is the one change NFR-08 puts behind
            # a person rather than a file (ADR-09).
            return ImportRow(
                existing.code,
                ImportOutcome.SKIPPED,
                "has been approved; retire it in the Knowledge Base screen and import a "
                f"replacement instead. Unapplied changes: {', '.join(sorted(changes))}.",
            )

        self._kb.apply_rule_changes(existing, changes)
        self._record_rule(AuditAction.RED_FLAG_RULE_UPDATED, existing, fields=sorted(changes))
        return ImportRow(existing.code, ImportOutcome.UPDATED, ", ".join(sorted(changes)))

    def _rule_changes(self, rule: RedFlagRule, parsed: RedFlagRuleFile) -> dict[str, object]:
        """The columns this file would change on `rule`, by name."""
        wanted: dict[str, object] = {
            "label": parsed.label,
            "min_category": parsed.min_category,
            "species": list(parsed.species),
            "phrases_ref": parsed.phrases_ref,
            "is_placeholder": parsed.is_placeholder,
        }
        if rule.approved_at is not None:
            # Approval is what clears `is_placeholder`, so on an approved rule the
            # database is authoritative and the file's default `true` is not a
            # request to un-approve it. Without this, every approved rule would
            # report a pending change forever (NFR-08).
            wanted.pop("is_placeholder")
        return {
            name: value
            for name, value in wanted.items()
            if name in RULE_FILE_FIELDS and getattr(rule, name) != value
        }

    # --- Entries (FR-49, FR-50, FR-56, ADR-14) ----------------------------

    def import_entries(self, entries: list[KBEntryFile], report: ImportReport) -> None:
        for parsed in entries:
            report.entries.append(self._import_entry(parsed))

    def _import_entry(self, parsed: KBEntryFile) -> ImportRow:
        problem = self._unimportable(parsed)
        if problem is not None:
            return ImportRow(parsed.slug, ImportOutcome.ERROR, problem)

        existing = self._stored_entry(parsed)
        if existing is None:
            return self._create(parsed)

        if existing.kind is not parsed.kind:
            # The stored row and the file disagree about what this entry *is*.
            # Not something to resolve by writing: `kb_entries` makes the two
            # kinds exclusive, and whichever name is wrong, the fix is a rename
            # or a new file (ADR-18).
            return ImportRow(
                parsed.slug,
                ImportOutcome.ERROR,
                f"is a {parsed.kind.value} entry in the file but "
                f"{existing.kind.value} in the database. An entry cannot change kind: "
                f"rename the file, or correct `kind`.",
            )

        reason = _UNTOUCHABLE.get(existing.status)
        if reason is not None:
            return ImportRow(parsed.slug, ImportOutcome.SKIPPED, reason)

        if existing.status is KBEntryStatus.DRAFT:
            return self._update(existing, parsed, outcome=ImportOutcome.UPDATED)

        # ACTIVE or RETIRED: never modified in place. The file is compared
        # against the open draft revision if there is one, so a second import of
        # the same change updates that revision rather than stacking another.
        revision = self._kb.draft_revision_of(existing.id)
        if revision is not None:
            return self._update(revision, parsed, outcome=ImportOutcome.UPDATED)
        if not self._entry_changes(existing, parsed) and not self._codes_changed(existing, parsed):
            return ImportRow(parsed.slug, ImportOutcome.UNCHANGED)
        return self._revise(existing, parsed)

    def _stored_entry(self, parsed: KBEntryFile) -> KBEntry | None:
        """The row this file upserts: by slug, then by category (8.2b).

        The slug is the key (FR-56). The category is the fallback for a baseline
        action set, and only for one, because a category can hold just one ACTIVE
        set: a file for a category that already has one is a revision of it, even
        when that set was seeded and has no slug at all.
        """
        by_slug = self._kb.get_entry_by_slug(parsed.slug)
        if by_slug is not None or parsed.kind is not KBEntryKind.URGENCY_ACTIONS:
            return by_slug
        if parsed.urgency_category is None:
            return None
        return self._kb.active_urgency_actions_entry(parsed.urgency_category)

    def _unimportable(self, parsed: KBEntryFile) -> str | None:
        """Why this file cannot be imported at all, or None.

        Both checks need the database, which is why they are here and not in
        `schemas/kb_import.py`. The complaint check does not apply to a baseline
        action set, which belongs to a category and carries no complaint code.
        """
        if parsed.complaint_code is not None and not self._kb.complaint_exists(
            parsed.complaint_code
        ):
            return (
                f"complaint_code {parsed.complaint_code!r} is not one of the presenting "
                f"complaints. Run `python -m scripts.seed` first, or correct the code."
            )
        missing = [
            code for code in parsed.red_flag_codes if self._kb.get_rule_by_code(code) is None
        ]
        if missing:
            return (
                f"red_flag_codes names no such rule: {', '.join(missing)}. "
                f"Import the rules first (`--rules`)."
            )
        return None

    def _create(self, parsed: KBEntryFile) -> ImportRow:
        entry = self._insert(parsed, slug=parsed.slug, revises_entry_id=None)
        self._link_rules(entry, parsed.red_flag_codes)
        self._record_entry(AuditAction.KB_ENTRY_CREATED, entry, fields=ENTRY_FILE_FIELDS)
        return ImportRow(entry.slug or parsed.slug, ImportOutcome.CREATED)

    def _revise(self, active: KBEntry, parsed: KBEntryFile) -> ImportRow:
        """Insert a new draft revision of a live entry (ADR-14).

        The revision takes the file's own slug when nothing holds it — which
        happens when the entry being revised was matched by category and was
        seeded without a slug — and the next free `-revN` otherwise. An entry
        matched by slug always holds it, so a clinical entry is always `-revN`.
        """
        slug = (
            parsed.slug
            if self._kb.get_entry_by_slug(parsed.slug) is None
            else revision_slug(parsed.slug, self._kb.revision_slugs(parsed.slug))
        )
        superseded = active.slug or active.title
        revision = self._insert(parsed, slug=slug, revises_entry_id=active.id)
        self._link_rules(revision, parsed.red_flag_codes)
        self._record_entry(
            AuditAction.KB_ENTRY_CREATED,
            revision,
            fields=ENTRY_FILE_FIELDS,
            extra={"revises_entry_id": str(active.id), "revises_slug": active.slug},
        )
        return ImportRow(
            slug,
            ImportOutcome.REVISED,
            f"{superseded} is {active.status.value.lower()} and was not changed; "
            f"submit this draft for approval.",
        )

    def _insert(
        self, parsed: KBEntryFile, *, slug: str, revises_entry_id: uuid.UUID | None
    ) -> KBEntry:
        return self._kb.insert_entry(
            kind=parsed.kind,
            slug=slug,
            complaint_code=parsed.complaint_code,
            urgency_category=parsed.urgency_category,
            title=parsed.title,
            content=parsed.content,
            species=list(parsed.species),
            source_title=parsed.source.title,
            source_publisher=parsed.source.publisher,
            source_url=parsed.source.url,
            access_date=parsed.source.access_date,
            created_by=self._author.id,
            revises_entry_id=revises_entry_id,
        )

    def _update(self, entry: KBEntry, parsed: KBEntryFile, *, outcome: ImportOutcome) -> ImportRow:
        changes = self._entry_changes(entry, parsed)
        codes_changed = self._codes_changed(entry, parsed)
        if not changes and not codes_changed:
            return ImportRow(entry.slug or parsed.slug, ImportOutcome.UNCHANGED)

        self._kb.apply_entry_changes(entry, changes)
        if codes_changed:
            self._link_rules(entry, parsed.red_flag_codes)
        self._record_entry(
            AuditAction.KB_ENTRY_UPDATED,
            entry,
            fields=sorted(changes),
            extra={"red_flag_codes_changed": codes_changed},
        )
        detail = ", ".join(sorted(changes) + (["red_flag_codes"] if codes_changed else []))
        return ImportRow(entry.slug or parsed.slug, outcome, detail)

    def _entry_changes(self, entry: KBEntry, parsed: KBEntryFile) -> dict[str, object]:
        """The columns this file would change on `entry`, by name.

        `slug` is not compared: it is the lookup key for a first import and a
        derived name for a revision, never something the comparison may write.
        `kind` is not compared either — the caller has already refused a file
        whose kind differs from the stored row's.

        Of `complaint_code` and `urgency_category`, only the one this kind owns
        is compared. Including both would report the other as a change on every
        single run, because it is `None` on either side by construction
        (`ck_kb_entries_complaint_code_iff_complaint`).
        """
        wanted: dict[str, object] = {
            "title": parsed.title,
            "species": list(parsed.species),
            "content": parsed.content,
            "source_title": parsed.source.title,
            "source_publisher": parsed.source.publisher,
            "source_url": parsed.source.url,
            "access_date": parsed.source.access_date,
        }
        if parsed.kind is KBEntryKind.URGENCY_ACTIONS:
            wanted["urgency_category"] = parsed.urgency_category
        else:
            wanted["complaint_code"] = parsed.complaint_code
        return {
            name: value
            for name, value in wanted.items()
            if name in ENTRY_FILE_FIELDS and getattr(entry, name) != value
        }

    def _codes_changed(self, entry: KBEntry, parsed: KBEntryFile) -> bool:
        stored = {rule.code for rule in self._kb.rules_for_entry(entry.id)}
        return stored != set(parsed.red_flag_codes)

    def _link_rules(self, entry: KBEntry, codes: list[str]) -> None:
        """Point the named rules at this entry, and unpoint the ones dropped.

        The same `red_flag_rules.entry_id` pointer `KBService` uses, so a rule
        belongs to at most one entry — the entry that explains it (FR-49). Every
        code was proved to exist by `_unimportable`.
        """
        wanted = list(dict.fromkeys(codes))
        for rule in self._kb.rules_for_entry(entry.id):
            if rule.code not in wanted:
                self._kb.set_rule_entry(rule, None)
        for code in wanted:
            rule = self._kb.get_rule_by_code(code)
            if rule is not None:
                self._kb.set_rule_entry(rule, entry.id)

    # --- Audit (FR-43, ADR-12) --------------------------------------------

    def _record_entry(
        self,
        action: AuditAction,
        entry: KBEntry,
        *,
        fields: tuple[str, ...] | list[str],
        extra: dict[str, object] | None = None,
    ) -> None:
        self._audit.record(
            action=action,
            entity_type=KB_ENTRY_ENTITY,
            entity_id=str(entry.id),
            user_id=self._author.id,
            role=self._author.role,
            after={
                # `source: import` is what separates a bulk import from an edit
                # somebody made in W-08, which the per-entry history shows.
                "source": "import",
                "status": entry.status.value,
                "kind": str(entry.kind),
                "slug": entry.slug,
                "complaint_code": entry.complaint_code,
                "urgency_category": (
                    None if entry.urgency_category is None else entry.urgency_category.value
                ),
                "fields": sorted(fields),
                "word_count": word_count(entry.content or ""),
                **(extra or {}),
            },
        )

    def _record_rule(
        self, action: AuditAction, rule: RedFlagRule, *, fields: tuple[str, ...] | list[str]
    ) -> None:
        self._audit.record(
            action=action,
            entity_type=RED_FLAG_RULE_ENTITY,
            entity_id=str(rule.id),
            user_id=self._author.id,
            role=self._author.role,
            after={
                "source": "import",
                "code": rule.code,
                "fields": sorted(fields),
                "min_category": str(rule.min_category),
                "species": [str(species) for species in rule.species],
                "is_placeholder": rule.is_placeholder,
                "approved": rule.approved_at is not None,
            },
        )


# --- Reading the directory -------------------------------------------------


def entry_files(knowledge_base_dir: Path) -> list[Path]:
    """Every entry file, in filename order so a run is reproducible."""
    return sorted((knowledge_base_dir / ENTRY_SUBDIR).glob(ENTRY_FILE_GLOB))


def rules_file(knowledge_base_dir: Path) -> Path:
    return knowledge_base_dir / RULES_FILENAME


def parse_all(
    knowledge_base_dir: Path, *, with_entries: bool, with_rules: bool
) -> tuple[list[RedFlagRuleFile], list[KBEntryFile], list[FileError]]:
    """Parse the requested files. Collects every error rather than raising.

    Here rather than in the script so the parse step is testable without argparse,
    and so the script stays a thin shell (CLAUDE.md §7).
    """
    rules: list[RedFlagRuleFile] = []
    entries: list[KBEntryFile] = []
    failures: list[FileError] = []

    if with_rules:
        path = rules_file(knowledge_base_dir)
        if not path.is_file():
            failures.append(FileError(path, None, "was not found."))
        else:
            parsed, errors = parse_rules_file(path)
            rules.extend(parsed)
            failures.extend(errors)

    if with_entries:
        found = entry_files(knowledge_base_dir)
        if not found:
            failures.append(
                FileError(
                    knowledge_base_dir / "entries",
                    None,
                    "holds no .yaml files; there is nothing to import.",
                )
            )
        for path in found:
            parsed_entry, errors = parse_entry_file(path)
            if parsed_entry is not None:
                entries.append(parsed_entry)
            failures.extend(errors)

    return rules, entries, failures
