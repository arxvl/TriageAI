"""The knowledge-base workflow (P08 §8.1, FR-49..FR-56, NFR-08, BR-04, ADR-14).

This service owns the gate on clinical content, and none of it may be reachable
around:

* **Nothing becomes retrievable without an approval.** `approve_entry` only
  enqueues a `KB_INDEX` job; the entry reaches `ACTIVE` inside that job, after
  indexing succeeded (FR-52, FR-53). Who may call it is `can_approve_kb`,
  enforced by the router's `require_role(..., kb_approver=True)` (BR-04).
* **An ACTIVE entry is never edited.** `kb_transitions` allows `EDIT` from
  `DRAFT` alone, so a change to live content has to be a new draft revision
  (ADR-14, DR-05).
* **Every approval and retirement publishes a version.** Entries and red-flag
  rules alike, through `publish_version`, so the safety floor is versioned with
  the content it floors (FR-54, NFR-08).
* **An entry cannot be submitted without its source.** FR-50 is checked again
  here on submit, not only in `KBEntryCreate`, because the importer writes
  drafts straight to the table (8.2).

The audit payloads carry ids, slugs, codes, statuses, kinds and counts. Never an
entry's content and never an approver's rejection comments: the log cannot be
corrected, and both are curated clinical text that belongs on the row where it
can be read and revised (FR-43, ADR-12, CLAUDE.md §9).

`now` and `app_env` are injectable so a test can place an approval at an exact
instant and ask what production would do. `indexer` is needed only by
`retire_entry`, which drops the retired entry's chunks; every other method
leaves indexing to the `KB_INDEX` job. The service raises `AppError`
subclasses and knows nothing about HTTP (CLAUDE.md §7).
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import AppEnv, get_settings
from app.core.errors import InvalidKBEntry, KBNotFound
from app.jobs.queue import KB_INDEX_APPROVER_KEY, KB_INDEX_ENTRY_KEY, JobQueue
from app.models import (
    Job,
    JobType,
    KBEntry,
    KBEntryKind,
    KBEntryStatus,
    KBVersion,
    RedFlagRule,
    User,
)
from app.pipeline.stages import KBIndexer
from app.repositories.kb_repository import KBRepository
from app.schemas.kb import (
    CONTENT_MAX_WORDS,
    CONTENT_MIN_WORDS,
    IndexingState,
    KBEntryActionResult,
    KBEntryCreate,
    KBEntryDetail,
    KBEntryFilters,
    KBEntryListResponse,
    KBEntrySummary,
    KBEntryUpdate,
    KBRejection,
    KBVersionDetail,
    KBVersionSummary,
    RedFlagRuleActionResult,
    RedFlagRuleCreate,
    RedFlagRuleOut,
    RedFlagRuleUpdate,
    SourceCitation,
    word_count,
)
from app.services.audit_service import (
    KB_ENTRY_ENTITY,
    RED_FLAG_RULE_ENTITY,
    AuditAction,
    AuditService,
)
from app.services.kb_transitions import (
    KBEntryAction,
    require_entry_action_allowed,
    require_rule_editable,
    require_rule_retirable,
)
from app.services.kb_versions import publish_version
from app.services.red_flag_rules import is_active_rule

Clock = Callable[[], datetime]

# The four citation fields FR-50 makes mandatory, with the wording each one's
# absence is reported with.
REQUIRED_SOURCE_FIELDS: tuple[tuple[str, str], ...] = (
    ("source_title", "Enter the title of the source this entry is written from."),
    ("source_publisher", "Enter the publisher of the source."),
    ("source_url", "Enter the link to the source."),
    ("access_date", "Enter the date you read the source."),
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _reject_cleared_fields(
    changes: dict[str, object], clearable: frozenset[str] | set[str] = frozenset()
) -> None:
    """Refuse an edit that sends `null` for a field that must have a value.

    Every field on an entry is required once it exists, so `{"title": null}` has
    no meaning — and left alone it would reach the database as a NOT NULL
    violation, which is a 500 and names nothing the editor can act on. This
    answers 422 with the field instead (IR-05).
    """
    for field, value in changes.items():
        if value is None and field not in clearable:
            raise InvalidKBEntry(
                "This field cannot be left empty. Enter a value or leave it unchanged.",
                field=field,
            )


class KBService:
    def __init__(
        self,
        session: Session,
        *,
        indexer: KBIndexer | None = None,
        app_env: AppEnv | None = None,
        now: Clock | None = None,
    ) -> None:
        self._session = session
        self._kb = KBRepository(session)
        self._audit = AuditService(session)
        self._jobs = JobQueue(session)
        self._indexer = indexer
        self._app_env = app_env or get_settings().app_env
        self._now = now or _utc_now

    # --- Reads (FR-51, FR-54) ---------------------------------------------

    def list_entries(self, filters: KBEntryFilters) -> KBEntryListResponse:
        """The W-08 entry list, with the tab counters and the published version.

        The counters describe the whole knowledge base rather than the filtered
        rows, so switching tabs never changes the numbers beside them (the same
        contract as the Triage Queue's counts, FR-39).
        """
        entries = self._kb.list_entries(status=filters.status, kind=filters.kind)
        counts = self._kb.entry_counts_by_status()
        return KBEntryListResponse(
            items=[self._summary(entry) for entry in entries],
            counts=counts,
            published_version_no=self._kb.latest_published_version_no(),
            active_entry_count=counts[KBEntryStatus.ACTIVE],
        )

    def get_entry(self, entry_id: uuid.UUID) -> KBEntryDetail:
        return self._detail(self._require_entry(entry_id))

    def list_versions(self) -> list[KBVersionSummary]:
        versions = self._kb.list_versions()
        counts = self._kb.version_entry_counts()
        names = self._kb.user_names([version.published_by for version in versions])
        return [self._version_summary(version, counts, names) for version in versions]

    def get_version(self, version_id: uuid.UUID) -> KBVersionDetail:
        """One version and the entries it contains (FR-54, DR-05).

        What a reviewer reopening an old case needs: the knowledge as it was,
        including entries that have since been retired.
        """
        version = self._kb.get_version(version_id)
        if version is None:
            raise KBNotFound("That knowledge-base version could not be found.")
        entries = self._kb.version_entries(version_id)
        names = self._kb.user_names([version.published_by])
        summary = self._version_summary(version, {version_id: len(entries)}, names)
        return KBVersionDetail(
            **summary.model_dump(),
            entries=[self._summary(entry) for entry in entries],
        )

    # --- Authoring (FR-49, FR-50) -----------------------------------------

    def create_entry(self, payload: KBEntryCreate, user: User) -> KBEntryDetail:
        """Write a new draft. One transaction.

        `COMPLAINT` only in this subphase: the five `URGENCY_ACTIONS` sets are
        seeded, and authoring one through the API arrives with the importer's
        support for them (8.2b, ADR-18).
        """
        self._require_complaint(payload.complaint_code)
        self._require_free_slug(payload.slug)

        entry = self._kb.insert_entry(
            kind=KBEntryKind.COMPLAINT,
            slug=payload.slug,
            complaint_code=payload.complaint_code,
            title=payload.title,
            content=payload.content,
            species=list(payload.species),
            source_title=payload.source_title,
            source_publisher=payload.source_publisher,
            source_url=payload.source_url,
            access_date=payload.access_date,
            created_by=user.id,
        )
        self._link_red_flag_rules(entry, payload.red_flag_codes)

        self._record(
            AuditAction.KB_ENTRY_CREATED,
            entry,
            user,
            after={
                "status": KBEntryStatus.DRAFT.value,
                "kind": str(entry.kind),
                "slug": entry.slug,
                "complaint_code": entry.complaint_code,
                "word_count": word_count(entry.content),
            },
        )
        self._session.commit()
        return self._detail(entry)

    def update_entry(
        self, entry_id: uuid.UUID, payload: KBEntryUpdate, user: User
    ) -> KBEntryDetail:
        """Edit a draft. Allowed while `DRAFT` and at no other time."""
        entry = self._require_entry(entry_id)
        require_entry_action_allowed(entry.status, KBEntryAction.EDIT)

        changes = payload.model_dump(exclude_unset=True, exclude={"red_flag_codes"})
        _reject_cleared_fields(changes)
        if "complaint_code" in changes:
            self._require_complaint(changes["complaint_code"])
        if "species" in changes:
            changes["species"] = list(changes["species"])

        self._kb.apply_entry_changes(entry, changes)
        if payload.red_flag_codes is not None:
            self._link_red_flag_rules(entry, payload.red_flag_codes)

        # The fields that changed, by name. Not their values: an entry's content
        # is curated clinical text and the log cannot be corrected (FR-43).
        self._record(
            AuditAction.KB_ENTRY_UPDATED,
            entry,
            user,
            after={
                "status": entry.status.value,
                "fields": sorted(changes),
                "red_flag_codes_changed": payload.red_flag_codes is not None,
                "word_count": word_count(entry.content),
            },
        )
        self._session.commit()
        return self._detail(entry)

    # --- The workflow (FR-51, FR-52, FR-53, FR-54) ------------------------

    def submit_entry(self, entry_id: uuid.UUID, user: User) -> KBEntryActionResult:
        """`DRAFT` → `PENDING_REVIEW`, if the entry is complete (FR-50).

        The completeness check runs against the stored row rather than a request
        body, because a draft can also arrive from the YAML importer (8.2), which
        never passed through `KBEntryCreate`.
        """
        entry = self._require_entry(entry_id)
        next_status = require_entry_action_allowed(entry.status, KBEntryAction.SUBMIT)
        self._require_complete(entry)

        self._kb.set_entry_status(entry, next_status or KBEntryStatus.PENDING_REVIEW)
        self._record(
            AuditAction.KB_ENTRY_SUBMITTED,
            entry,
            user,
            before={"status": KBEntryStatus.DRAFT.value},
            after={"status": entry.status.value, "word_count": word_count(entry.content)},
        )
        self._session.commit()
        return KBEntryActionResult(id=entry.id, status=entry.status)

    def approve_entry(self, entry_id: uuid.UUID, user: User) -> KBEntryActionResult:
        """Approve an entry and enqueue its indexing (FR-52, FR-53, BR-04).

        The entry stays `PENDING_REVIEW` here. It becomes `ACTIVE` — and version
        N+1 is published — inside the `KB_INDEX` job, once the chunks exist: an
        entry that retrieval cannot reach must not be presented as active, and
        chunking and embedding are model work that does not belong in a request
        (ADR-08).

        The approver travels with the job, because by the time it runs they are
        gone and both `approved_by` and the version's `published_by` are theirs.
        """
        entry = self._require_entry(entry_id)
        require_entry_action_allowed(entry.status, KBEntryAction.APPROVE)

        job = self._jobs.enqueue(
            JobType.KB_INDEX,
            payload={
                KB_INDEX_ENTRY_KEY: str(entry.id),
                KB_INDEX_APPROVER_KEY: str(user.id),
            },
        )
        self._record(
            AuditAction.KB_ENTRY_APPROVED,
            entry,
            user,
            before={"status": KBEntryStatus.PENDING_REVIEW.value},
            after={"status": KBEntryStatus.PENDING_REVIEW.value, "job_id": str(job.id)},
        )
        # The job and the audit entry commit together, so there can be no
        # approval nobody will act on and no indexing job nobody approved.
        self._session.commit()
        return KBEntryActionResult(id=entry.id, status=entry.status, job_id=job.id)

    def reject_entry(
        self, entry_id: uuid.UUID, payload: KBRejection, user: User
    ) -> KBEntryActionResult:
        """Send an entry back to its author with comments (FR-51).

        The comments are stored on the entry, where the author reads them and
        the next submission replaces them. The log records that a rejection
        happened and how long the comments were — not the comments themselves,
        which are clinical feedback that must stay correctable (FR-43).
        """
        entry = self._require_entry(entry_id)
        next_status = require_entry_action_allowed(entry.status, KBEntryAction.REJECT)

        self._kb.set_entry_status(
            entry, next_status or KBEntryStatus.DRAFT, review_comments=payload.comments
        )
        self._record(
            AuditAction.KB_ENTRY_REJECTED,
            entry,
            user,
            before={"status": KBEntryStatus.PENDING_REVIEW.value},
            after={"status": entry.status.value, "comment_char_count": len(payload.comments)},
        )
        self._session.commit()
        return KBEntryActionResult(id=entry.id, status=entry.status)

    def retire_entry(self, entry_id: uuid.UUID, user: User) -> KBEntryActionResult:
        """`ACTIVE` → `RETIRED`: drop the chunks and publish a version (FR-53, FR-54).

        Synchronously, unlike approval. Removing an entry's chunks is a delete
        rather than model work, and a retirement that only took effect once a
        worker got to it would leave content retrievable that a veterinarian has
        just withdrawn.

        The entry and its history stay: a recommendation that cited it must
        remain explainable, and the version it belonged to still lists it
        (ADR-14, DR-05).
        """
        entry = self._require_entry(entry_id)
        next_status = require_entry_action_allowed(entry.status, KBEntryAction.RETIRE)

        if self._indexer is None:
            # A programming error, not a user error: retiring without dropping
            # the chunks would leave withdrawn content retrievable, which is the
            # one outcome this endpoint exists to prevent (FR-53).
            raise RuntimeError(
                "retire_entry needs a KBIndexer. Build the service with "
                "KBService(session, indexer=...); the router injects it from the pipeline."
            )
        # TODO(manual:M5): with `MockKBIndexer` this does nothing. The real
        # indexer deletes the entry's rows from `kb_chunks` so retrieval can no
        # longer return them.
        self._indexer.remove_entry(entry.id)

        self._kb.set_entry_status(entry, next_status or KBEntryStatus.RETIRED)
        self._record(
            AuditAction.KB_ENTRY_RETIRED,
            entry,
            user,
            before={"status": KBEntryStatus.ACTIVE.value},
            after={"status": entry.status.value, "slug": entry.slug, "kind": str(entry.kind)},
        )
        published = publish_version(
            self._session,
            published_by=user.id,
            role=user.role,
            at=self._now(),
            note=f"Retired entry {entry.slug or entry.id}",
            reason={"trigger": "ENTRY_RETIRED", "entry_id": str(entry.id)},
        )
        self._session.commit()
        return KBEntryActionResult(
            id=entry.id, status=entry.status, version_no=published.version_no
        )

    # --- Red-flag rules (FR-12, FR-23, NFR-08) ----------------------------

    def list_rules(self) -> list[RedFlagRuleOut]:
        rules = self._kb.list_rules()
        names = self._kb.user_names([rule.approved_by for rule in rules])
        return [self._rule_out(rule, names) for rule in rules]

    def create_rule(self, payload: RedFlagRuleCreate, user: User) -> RedFlagRuleOut:
        """Create a rule, unapproved.

        Unapproved whoever asks: a rule that changed the safety floor the moment
        one person typed it would defeat the point of NFR-08.
        """
        if self._kb.get_rule_by_code(payload.code) is not None:
            raise InvalidKBEntry(
                "A rule with that code already exists. Edit or retire it instead.", field="code"
            )

        rule = self._kb.insert_rule(
            code=payload.code,
            label=payload.label,
            min_category=payload.min_category,
            species=list(payload.species),
            phrases_ref=payload.phrases_ref,
            is_placeholder=payload.is_placeholder,
        )
        self._audit.record(
            action=AuditAction.RED_FLAG_RULE_CREATED,
            entity_type=RED_FLAG_RULE_ENTITY,
            entity_id=str(rule.id),
            user_id=user.id,
            role=user.role,
            after={
                "code": rule.code,
                "min_category": str(rule.min_category),
                "species": [str(species) for species in rule.species],
                "is_placeholder": rule.is_placeholder,
                "approved": False,
            },
        )
        self._session.commit()
        return self._rule_out(rule, {})

    def update_rule(
        self, rule_id: uuid.UUID, payload: RedFlagRuleUpdate, user: User
    ) -> RedFlagRuleOut:
        """Edit a rule that has not been approved yet (P08 §8.1 task 4)."""
        rule = self._require_rule(rule_id)
        require_rule_editable(rule)

        changes = payload.model_dump(exclude_unset=True)
        # `phrases_ref` is the one field a rule may be left without: the phrases
        # are maintained by hand (M1) and a rule may not have a key yet.
        _reject_cleared_fields(changes, clearable={"phrases_ref"})
        if "species" in changes:
            changes["species"] = list(changes["species"])
        self._kb.apply_rule_changes(rule, changes)

        self._audit.record(
            action=AuditAction.RED_FLAG_RULE_UPDATED,
            entity_type=RED_FLAG_RULE_ENTITY,
            entity_id=str(rule.id),
            user_id=user.id,
            role=user.role,
            after={
                "code": rule.code,
                "fields": sorted(changes),
                "min_category": str(rule.min_category),
            },
        )
        self._session.commit()
        return self._rule_out(rule, self._kb.user_names([rule.approved_by]))

    def approve_rule(self, rule_id: uuid.UUID, user: User) -> RedFlagRuleActionResult:
        """Approve a rule and publish a version (NFR-08, BR-04, FR-54).

        A version, although no entry changed: the safety floor is part of what a
        recommendation was produced under, so a change to it has to be datable
        the same way a change to the content is (ADR-14).
        """
        rule = self._require_rule(rule_id)
        require_rule_editable(rule)

        at = self._now()
        self._kb.approve_rule(rule, approved_by=user.id, at=at)
        self._audit.record(
            action=AuditAction.RED_FLAG_RULE_APPROVED,
            entity_type=RED_FLAG_RULE_ENTITY,
            entity_id=str(rule.id),
            user_id=user.id,
            role=user.role,
            before={"approved": False, "is_placeholder": True},
            after={
                "code": rule.code,
                "approved": True,
                "is_placeholder": False,
                "min_category": str(rule.min_category),
            },
        )
        published = publish_version(
            self._session,
            published_by=user.id,
            role=user.role,
            at=at,
            note=f"Approved red-flag rule {rule.code}",
            reason={"trigger": "RULE_APPROVED", "rule_code": rule.code},
        )
        self._session.commit()
        return RedFlagRuleActionResult(id=rule.id, code=rule.code, version_no=published.version_no)

    def retire_rule(self, rule_id: uuid.UUID, user: User) -> RedFlagRuleActionResult:
        """Retire a rule and publish a version.

        The approver's call, not an administrator's: retiring a rule lowers the
        safety floor, and NFR-08 puts every change to the red-flag rules behind
        veterinary approval.
        """
        rule = self._require_rule(rule_id)
        require_rule_retirable(rule)

        at = self._now()
        self._kb.retire_rule(rule, at=at)
        self._audit.record(
            action=AuditAction.RED_FLAG_RULE_RETIRED,
            entity_type=RED_FLAG_RULE_ENTITY,
            entity_id=str(rule.id),
            user_id=user.id,
            role=user.role,
            before={"retired": False},
            after={"code": rule.code, "retired": True, "retired_at": at.isoformat()},
        )
        published = publish_version(
            self._session,
            published_by=user.id,
            role=user.role,
            at=at,
            note=f"Retired red-flag rule {rule.code}",
            reason={"trigger": "RULE_RETIRED", "rule_code": rule.code},
        )
        self._session.commit()
        return RedFlagRuleActionResult(id=rule.id, code=rule.code, version_no=published.version_no)

    # --- Validation (FR-50) -----------------------------------------------

    def _require_entry(self, entry_id: uuid.UUID) -> KBEntry:
        entry = self._kb.get_entry(entry_id)
        if entry is None:
            raise KBNotFound("That knowledge-base entry could not be found.")
        return entry

    def _require_rule(self, rule_id: uuid.UUID) -> RedFlagRule:
        rule = self._kb.get_rule(rule_id)
        if rule is None:
            raise KBNotFound("That red-flag rule could not be found.")
        return rule

    def _require_complaint(self, code: str | None) -> None:
        if code is not None and not self._kb.complaint_exists(code):
            raise InvalidKBEntry(
                "Choose the presenting complaint from the list.", field="complaint_code"
            )

    def _require_free_slug(self, slug: str | None) -> None:
        if slug is not None and self._kb.get_entry_by_slug(slug) is not None:
            raise InvalidKBEntry(
                "An entry with that short name already exists. Choose another.", field="slug"
            )

    def _require_complete(self, entry: KBEntry) -> None:
        """Everything FR-49 and FR-50 require before an entry may be reviewed."""
        if not entry.title:
            raise InvalidKBEntry("Enter a title for this entry.", field="title")
        if entry.kind is KBEntryKind.COMPLAINT and not entry.complaint_code:
            raise InvalidKBEntry(
                "Choose the presenting complaint from the list.", field="complaint_code"
            )
        if not entry.species:
            raise InvalidKBEntry("Choose at least one species: dog, cat, or both.", field="species")
        words = word_count(entry.content or "")
        if not CONTENT_MIN_WORDS <= words <= CONTENT_MAX_WORDS:
            raise InvalidKBEntry(
                f"The content must be between {CONTENT_MIN_WORDS} and "
                f"{CONTENT_MAX_WORDS:,} words; this entry has {words:,}.",
                field="content",
            )
        for field, message in REQUIRED_SOURCE_FIELDS:
            if getattr(entry, field) is None:
                raise InvalidKBEntry(message, field=field)

    def _link_red_flag_rules(self, entry: KBEntry, codes: list[str]) -> None:
        """Point the named rules at this entry, and unpoint the ones dropped.

        `red_flag_rules.entry_id` is the link, so a rule belongs to at most one
        entry — the entry that explains it (FR-49).
        """
        wanted = list(dict.fromkeys(codes))
        rules = []
        for code in wanted:
            rule = self._kb.get_rule_by_code(code)
            if rule is None:
                raise InvalidKBEntry(
                    f"There is no red-flag rule with the code {code}.", field="red_flag_codes"
                )
            rules.append(rule)

        for rule in self._kb.rules_for_entry(entry.id):
            if rule.code not in wanted:
                self._kb.set_rule_entry(rule, None)
        for rule in rules:
            self._kb.set_rule_entry(rule, entry.id)

    # --- Response building -------------------------------------------------

    def _record(
        self,
        action: AuditAction,
        entry: KBEntry,
        user: User,
        *,
        before: dict | None = None,
        after: dict | None = None,
    ) -> None:
        self._audit.record(
            action=action,
            entity_type=KB_ENTRY_ENTITY,
            entity_id=str(entry.id),
            user_id=user.id,
            role=user.role,
            before=before,
            after=after,
        )

    def _summary(self, entry: KBEntry) -> KBEntrySummary:
        return KBEntrySummary(
            id=entry.id,
            slug=entry.slug,
            kind=entry.kind,
            title=entry.title,
            complaint_code=entry.complaint_code,
            urgency_category=entry.urgency_category,
            species=list(entry.species),
            status=entry.status,
            word_count=word_count(entry.content or ""),
        )

    def _detail(self, entry: KBEntry) -> KBEntryDetail:
        names = self._kb.user_names([entry.created_by, entry.approved_by])
        return KBEntryDetail(
            id=entry.id,
            slug=entry.slug,
            kind=entry.kind,
            title=entry.title,
            complaint_code=entry.complaint_code,
            urgency_category=entry.urgency_category,
            species=list(entry.species),
            content=entry.content,
            word_count=word_count(entry.content or ""),
            status=entry.status,
            source=SourceCitation(
                title=entry.source_title,
                publisher=entry.source_publisher,
                url=entry.source_url,
                access_date=entry.access_date,
            ),
            red_flag_codes=[rule.code for rule in self._kb.rules_for_entry(entry.id)],
            created_by_name=names.get(entry.created_by),
            approved_by_name=names.get(entry.approved_by) if entry.approved_by else None,
            approved_at=entry.approved_at,
            review_comments=entry.review_comments,
            revises_entry_id=entry.revises_entry_id,
            indexing=self._indexing_state(entry.id),
        )

    def _indexing_state(self, entry_id: uuid.UUID) -> IndexingState | None:
        """What the newest `KB_INDEX` job for this entry reports (FR-53).

        `None` until the entry has been approved once. The error is the job's
        reason code, which is what W-08 turns into the approver's wording.
        """
        job: Job | None = self._kb.latest_index_job(entry_id)
        if job is None:
            return None
        return IndexingState(status=job.status, error=job.last_error, queued_at=job.created_at)

    def _version_summary(
        self,
        version: KBVersion,
        counts: dict[uuid.UUID, int],
        names: dict[uuid.UUID, str],
    ) -> KBVersionSummary:
        return KBVersionSummary(
            id=version.id,
            version_no=version.version_no,
            published_at=version.published_at,
            published_by_name=(names.get(version.published_by) if version.published_by else None),
            note=version.note,
            entry_count=counts.get(version.id, 0),
        )

    def _rule_out(self, rule: RedFlagRule, names: dict[uuid.UUID, str]) -> RedFlagRuleOut:
        return RedFlagRuleOut(
            id=rule.id,
            code=rule.code,
            label=rule.label,
            min_category=rule.min_category,
            species=list(rule.species),
            phrases_ref=rule.phrases_ref,
            is_placeholder=rule.is_placeholder,
            approved_by_name=names.get(rule.approved_by) if rule.approved_by else None,
            approved_at=rule.approved_at,
            retired_at=rule.retired_at,
            is_active=is_active_rule(rule, self._app_env),
        )
