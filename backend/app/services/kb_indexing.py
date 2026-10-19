"""The `KB_INDEX` job: index an approved entry, then publish it (P08 §8.1 task 3).

Approval is deliberately two steps. The request records *that* an approver
approved and enqueues this job; this job does the work that makes the entry
retrievable and publishes the version. The split is ADR-08 — chunking and
embedding an entry is model work and must not happen inside a request — and it
is also what FR-53 asks for: an entry goes live only once its chunks exist.

The order inside `run_kb_index` is the whole safety property:

1. index the entry (the only step that can fail for reasons outside our control),
2. set it ACTIVE with its approver and the moment of approval,
3. publish version N+1 listing every ACTIVE entry.

One transaction, committed once at the end. So a failure anywhere leaves the
entry `PENDING_REVIEW`, publishes nothing, and leaves the approver's own audit
entry standing — an approval that visibly did not take effect, which is the
honest state. The error is a reason **code** on the job row, never a traceback
or model output (CLAUDE.md §9); `GET /kb/entries/{id}` reads it back.

An `URGENCY_ACTIONS` entry skips step 1 entirely. It holds the baseline actions
for one VTL category, is looked up by category and must never come back from a
similarity search, so it is not chunked or embedded at all and its chunk count is
0 (ADR-18 §2, P08 §8.2b task 3). It is still activated and still published in the
version, like any other ACTIVE entry. Its category is re-checked first: only one
ACTIVE set may hold a category, and another approval can have been committed
while this job sat in the queue.

The indexer is passed in rather than built here. It comes from the registry
(`KB_INDEXER`), is `MockKBIndexer` until M5, and is the only thing in this file
that will change when the real one arrives.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from app.jobs.queue import KB_INDEX_APPROVER_KEY, KB_INDEX_ENTRY_KEY
from app.models import Job, KBEntry, KBEntryKind, KBEntryStatus, User, UserRole
from app.pipeline.stages import KBIndexer
from app.repositories.kb_repository import KBRepository
from app.services.audit_service import KB_ENTRY_ENTITY, AuditAction, AuditService
from app.services.kb_versions import publish_version

logger = logging.getLogger(__name__)

__all__ = [
    "KB_INDEX_APPROVER_KEY",
    "KB_INDEX_ENTRY_KEY",
    "KBIndexFailureReason",
    "KBIndexRunResult",
    "kb_index_job_target",
    "run_kb_index",
]


class KBIndexFailureReason(StrEnum):
    """Why an indexing run did not publish. Stored in `jobs.last_error`.

    Codes, not prose: the W-08 approver view turns them into wording, and P07's
    retry endpoint reads them back. The same contract as the pipeline's
    `FailureReason`.
    """

    ENTRY_NOT_FOUND = "KB_ENTRY_NOT_FOUND"
    ENTRY_NOT_PENDING_REVIEW = "KB_ENTRY_NOT_PENDING_REVIEW"
    INDEXING_FAILED = "KB_INDEXING_FAILED"
    # A second ACTIVE baseline action set for one category, approved while this
    # job waited (FR-72, ADR-18). `KBService.approve_entry` refuses it at request
    # time; this is the race the queue leaves open.
    URGENCY_ACTIONS_CATEGORY_TAKEN = "KB_URGENCY_ACTIONS_CATEGORY_TAKEN"


@dataclass(frozen=True)
class KBIndexRunResult:
    """What one indexing run did, in the shape `jobs/worker.py` already consumes."""

    entry_id: uuid.UUID | None
    chunk_count: int = 0
    version_no: int | None = None
    failure_reason: KBIndexFailureReason | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure_reason is None


def kb_index_job_target(job: Job) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """The entry and the approver a `KB_INDEX` job names, or `(None, None)`.

    Read out of the payload; see `KB_INDEX_ENTRY_KEY`. A value that is not a
    uuid is treated as missing — the only writer is `KBService.approve_entry`,
    so anything else is a job somebody built by hand.
    """
    payload = job.payload or {}
    return _as_uuid(payload.get(KB_INDEX_ENTRY_KEY)), _as_uuid(payload.get(KB_INDEX_APPROVER_KEY))


def _as_uuid(raw: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None


def run_kb_index(
    session: Session,
    indexer: KBIndexer,
    *,
    entry_id: uuid.UUID,
    approver_id: uuid.UUID | None,
    now: datetime | None = None,
) -> KBIndexRunResult:
    """Index an approved entry, activate it and publish a version. Never raises.

    Commits on success. On failure it rolls back, records `KB_INDEX_FAILED` in
    the audit log and commits *that* — the log is the only account of an
    approval that did not take effect, so it must survive the rollback.
    """
    at = now or datetime.now(UTC)
    repository = KBRepository(session)
    role = _role_of(session, approver_id)

    entry = repository.get_entry(entry_id)
    if entry is None:
        logger.error(
            "KB_INDEX job for an entry that does not exist", extra={"entry_id": str(entry_id)}
        )
        return KBIndexRunResult(entry_id, failure_reason=KBIndexFailureReason.ENTRY_NOT_FOUND)

    if entry.status is not KBEntryStatus.PENDING_REVIEW:
        # Already indexed by an earlier attempt, or rejected while the job sat in
        # the queue. Not an error to retry: publishing again would produce a
        # version nobody asked for.
        logger.warning(
            "KB_INDEX job for an entry that is not awaiting review",
            extra={"entry_id": str(entry_id), "status": str(entry.status)},
        )
        return KBIndexRunResult(
            entry_id, failure_reason=KBIndexFailureReason.ENTRY_NOT_PENDING_REVIEW
        )

    slug_or_id = entry.slug or str(entry.id)

    if _category_taken(repository, entry):
        logger.warning(
            "KB_INDEX job for a baseline action set whose category is taken",
            extra={"entry_id": str(entry_id), "urgency_category": str(entry.urgency_category)},
        )
        _record_failure(
            session,
            entry_id,
            approver_id=approver_id,
            role=role,
            reason=KBIndexFailureReason.URGENCY_ACTIONS_CATEGORY_TAKEN,
        )
        return KBIndexRunResult(
            entry_id, failure_reason=KBIndexFailureReason.URGENCY_ACTIONS_CATEGORY_TAKEN
        )

    if entry.kind is KBEntryKind.URGENCY_ACTIONS:
        # Not chunked, not embedded, never similarity-searched: the baseline set
        # is read by category (ADR-18 §2, P08 §8.2b task 3).
        # TODO(manual:M5): `PgVectorKBIndexer` is deliberately never handed one of
        # these, so it does not need a kind check of its own.
        chunk_count = 0
    else:
        try:
            # TODO(manual:M5): `MockKBIndexer` indexes nothing and answers 0. The real
            # chunking-and-embedding indexer is
            # `app.kb.indexer_pgvector:PgVectorKBIndexer`, selected by KB_INDEXER.
            chunk_count = indexer.index_entry(entry_id)
        except Exception:
            session.rollback()
            # No model output and no exception text in the log record: a stage's
            # message may quote content, and this line is written at ERROR level
            # (CLAUDE.md §9). The traceback goes to the operator's log only.
            logger.exception("indexing an approved entry failed", extra={"entry_id": str(entry_id)})
            _record_failure(
                session,
                entry_id,
                approver_id=approver_id,
                role=role,
                reason=KBIndexFailureReason.INDEXING_FAILED,
            )
            return KBIndexRunResult(entry_id, failure_reason=KBIndexFailureReason.INDEXING_FAILED)

    repository.set_entry_status(
        entry,
        KBEntryStatus.ACTIVE,
        approved_by=approver_id,
        approved_at=at,
    )
    AuditService(session).record(
        action=AuditAction.KB_ENTRY_ACTIVATED,
        entity_type=KB_ENTRY_ENTITY,
        entity_id=str(entry_id),
        user_id=approver_id,
        role=role,
        before={"status": KBEntryStatus.PENDING_REVIEW.value},
        after={
            "status": KBEntryStatus.ACTIVE.value,
            "slug": entry.slug,
            "kind": str(entry.kind),
            "chunk_count": chunk_count,
            # False for a baseline action set, which is why its chunk count is 0:
            # 0 on its own would read as an indexer that found nothing to chunk.
            "indexed": entry.kind is not KBEntryKind.URGENCY_ACTIONS,
        },
    )

    published = publish_version(
        session,
        published_by=approver_id,
        role=role,
        at=at,
        note=f"Approved entry {slug_or_id}",
        reason={"trigger": "ENTRY_APPROVED", "entry_id": str(entry_id)},
    )
    session.commit()
    return KBIndexRunResult(entry_id, chunk_count=chunk_count, version_no=published.version_no)


def _category_taken(repository: KBRepository, entry: KBEntry) -> bool:
    """Whether another ACTIVE baseline set already holds this entry's category.

    Always false for a `COMPLAINT` entry. For a baseline set it is the last gate
    before `uq_kb_entries_active_urgency_actions` would raise, which inside a
    worker is an unexplained failed job rather than a reason code (FR-72).
    """
    if entry.kind is not KBEntryKind.URGENCY_ACTIONS or entry.urgency_category is None:
        return False
    return (
        repository.active_urgency_actions_entry(entry.urgency_category, exclude_id=entry.id)
        is not None
    )


def _record_failure(
    session: Session,
    entry_id: uuid.UUID,
    *,
    approver_id: uuid.UUID | None,
    role: UserRole | None,
    reason: KBIndexFailureReason,
) -> None:
    """Record an approval that did not take effect, and commit that alone.

    Committed on its own because the log is the only account of it: the entry is
    still `PENDING_REVIEW`, no version was published, and the approver's own
    entry a moment earlier says they approved (FR-43, ADR-12).
    """
    AuditService(session).record(
        action=AuditAction.KB_INDEX_FAILED,
        entity_type=KB_ENTRY_ENTITY,
        entity_id=str(entry_id),
        user_id=approver_id,
        role=role,
        before={"status": KBEntryStatus.PENDING_REVIEW.value},
        after={"status": KBEntryStatus.PENDING_REVIEW.value, "reason": reason.value},
    )
    session.commit()


def _role_of(session: Session, user_id: uuid.UUID | None) -> UserRole | None:
    """The approver's role, for the audit entries this job writes.

    The job runs long after the request, so the person is not in hand — only
    their id, carried on the payload. Their role is read from their account so
    the log says who acted in what capacity, exactly as a request-time entry
    does (FR-43).
    """
    if user_id is None:
        return None
    user = session.get(User, user_id)
    return None if user is None else user.role
