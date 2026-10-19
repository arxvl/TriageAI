"""The `KB_INDEX` job: indexing, activation and publication (P08 §8.1 task 3).

The order in `run_kb_index` is a safety property, so these tests assert the
whole outcome rather than each step:

* **success** — the entry is ACTIVE with its approver recorded, and version N+1
  lists every ACTIVE entry (FR-52, FR-53, FR-54);
* **failure** — the entry is still PENDING_REVIEW, nothing is published, and the
  audit log says the approval did not take effect.

The indexer is a stub. `MockKBIndexer` cannot fail, which is exactly why a test
about failure has to supply its own (ADR-17).
"""

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.jobs.queue import KB_INDEX_APPROVER_KEY, KB_INDEX_ENTRY_KEY, JobQueue
from app.jobs.worker import MISSING_ENTRY_ID, run_pending_jobs_once
from app.models import (
    JobStatus,
    JobType,
    KBEntryStatus,
    KBVersion,
    UserRole,
    kb_version_entries,
)
from app.services.kb_indexing import (
    KBIndexFailureReason,
    kb_index_job_target,
    run_kb_index,
)
from tests.conftest import (
    audit_actions,
    kb_entry_content,
    make_job,
    make_kb_entry,
    make_kb_version,
    make_user,
)


class _FailingIndexer:
    """An indexer whose chunking fails, as a missing model or a dead database would."""

    model_id = "failing"
    prompt_version = "mock-0"
    last_latency_ms = 0

    def index_entry(self, entry_id: uuid.UUID) -> int:
        raise RuntimeError("indexing is unavailable")

    def remove_entry(self, entry_id: uuid.UUID) -> None:
        return None


class _CountingIndexer:
    """Answers a fixed chunk count, so the stored provenance can be asserted."""

    def __init__(self, chunks: int = 3) -> None:
        self.chunks = chunks
        self.indexed: list[uuid.UUID] = []

    def index_entry(self, entry_id: uuid.UUID) -> int:
        self.indexed.append(entry_id)
        return self.chunks

    def remove_entry(self, entry_id: uuid.UUID) -> None:
        return None


def _approver(session: Session):
    return make_user(
        session, role=UserRole.VETERINARY_REVIEWER, can_approve_kb=True, full_name="A Approver"
    )


def _pending_entry(session: Session, **kwargs: object):
    return make_kb_entry(
        session,
        status=KBEntryStatus.PENDING_REVIEW,
        content=kb_entry_content(),
        with_source=True,
        **kwargs,  # type: ignore[arg-type]
    )


def _version_count(session: Session) -> int:
    return session.scalars(select(func.count()).select_from(KBVersion)).one()


# --- The success path -----------------------------------------------------


def test_indexing_activates_the_entry_and_publishes_a_version(db_session: Session) -> None:
    make_kb_version(db_session)  # the seeded version 0
    approver = _approver(db_session)
    entry = _pending_entry(db_session, slug="fixture-indexed")
    indexer = _CountingIndexer(chunks=4)

    result = run_kb_index(db_session, indexer, entry_id=entry.id, approver_id=approver.id)

    assert result.succeeded
    assert result.chunk_count == 4
    assert result.version_no == 1
    assert indexer.indexed == [entry.id]
    db_session.refresh(entry)
    assert entry.status is KBEntryStatus.ACTIVE
    assert entry.approved_by == approver.id
    assert entry.approved_at is not None


def test_the_published_version_lists_every_active_entry(db_session: Session) -> None:
    """A version is a snapshot of the whole knowledge base, not of one change."""
    already_active = make_kb_entry(
        db_session, status=KBEntryStatus.ACTIVE, slug="fixture-already-active"
    )
    draft = make_kb_entry(db_session, status=KBEntryStatus.DRAFT, slug="fixture-still-draft")
    approver = _approver(db_session)
    entry = _pending_entry(db_session, slug="fixture-being-approved")

    result = run_kb_index(
        db_session, _CountingIndexer(), entry_id=entry.id, approver_id=approver.id
    )

    version_id = db_session.scalars(
        select(KBVersion.id).where(KBVersion.version_no == result.version_no)
    ).one()
    members = set(
        db_session.scalars(
            select(kb_version_entries.c.entry_id).where(
                kb_version_entries.c.kb_version_id == version_id
            )
        )
    )

    assert members == {already_active.id, entry.id}
    assert draft.id not in members


def test_the_version_records_who_published_it(db_session: Session) -> None:
    approver = _approver(db_session)
    entry = _pending_entry(db_session, slug="fixture-publisher")

    result = run_kb_index(
        db_session, _CountingIndexer(), entry_id=entry.id, approver_id=approver.id
    )

    version = db_session.scalars(
        select(KBVersion).where(KBVersion.version_no == result.version_no)
    ).one()

    assert version.published_by == approver.id
    assert version.published_at is not None
    assert "fixture-publisher" in (version.note or "")


def test_the_version_number_increments(db_session: Session) -> None:
    approver = _approver(db_session)
    first = _pending_entry(db_session, slug="fixture-first")
    second = _pending_entry(db_session, slug="fixture-second")

    one = run_kb_index(db_session, _CountingIndexer(), entry_id=first.id, approver_id=approver.id)
    two = run_kb_index(db_session, _CountingIndexer(), entry_id=second.id, approver_id=approver.id)

    assert (one.version_no, two.version_no) == (1, 2)


def test_the_activation_and_the_publication_are_both_audited(db_session: Session) -> None:
    approver = _approver(db_session)
    entry = _pending_entry(db_session, slug="fixture-audited")

    run_kb_index(db_session, _CountingIndexer(), entry_id=entry.id, approver_id=approver.id)

    actions = audit_actions(db_session)

    assert "KB_ENTRY_ACTIVATED" in actions
    assert "KB_VERSION_PUBLISHED" in actions


# --- The failure path (FR-53) --------------------------------------------


def test_a_failed_index_leaves_the_entry_awaiting_review(db_session: Session) -> None:
    approver = _approver(db_session)
    entry = _pending_entry(db_session, slug="fixture-failed")
    # Committed first, as the approval request commits them: the failure path
    # rolls back whatever the indexer wrote, and the entry it is about has to
    # survive that rollback.
    db_session.commit()
    before = _version_count(db_session)

    result = run_kb_index(db_session, _FailingIndexer(), entry_id=entry.id, approver_id=approver.id)

    assert result.succeeded is False
    assert result.failure_reason is KBIndexFailureReason.INDEXING_FAILED
    db_session.refresh(entry)
    assert entry.status is KBEntryStatus.PENDING_REVIEW
    assert entry.approved_at is None
    assert _version_count(db_session) == before


def test_a_failed_index_is_audited_so_the_approval_is_visibly_ineffective(
    db_session: Session,
) -> None:
    approver = _approver(db_session)
    entry = _pending_entry(db_session, slug="fixture-failed-audit")
    db_session.commit()

    run_kb_index(db_session, _FailingIndexer(), entry_id=entry.id, approver_id=approver.id)

    assert "KB_INDEX_FAILED" in audit_actions(db_session)
    assert "KB_VERSION_PUBLISHED" not in audit_actions(db_session)


def test_an_entry_that_does_not_exist_fails_without_publishing(db_session: Session) -> None:
    before = _version_count(db_session)

    result = run_kb_index(db_session, _CountingIndexer(), entry_id=uuid.uuid4(), approver_id=None)

    assert result.failure_reason is KBIndexFailureReason.ENTRY_NOT_FOUND
    assert _version_count(db_session) == before


@pytest.mark.parametrize(
    "status", [KBEntryStatus.DRAFT, KBEntryStatus.ACTIVE, KBEntryStatus.RETIRED]
)
def test_an_entry_that_is_not_awaiting_review_is_not_indexed_again(
    db_session: Session, status: KBEntryStatus
) -> None:
    """A job that ran twice, or an entry rejected while the job queued."""
    approver = _approver(db_session)
    entry = make_kb_entry(db_session, status=status, slug=f"fixture-{status.value.lower()}")
    indexer = _CountingIndexer()
    before = _version_count(db_session)

    result = run_kb_index(db_session, indexer, entry_id=entry.id, approver_id=approver.id)

    assert result.failure_reason is KBIndexFailureReason.ENTRY_NOT_PENDING_REVIEW
    assert indexer.indexed == []
    assert _version_count(db_session) == before


# --- The payload the job carries -----------------------------------------


def test_the_payload_names_the_entry_and_the_approver(db_session: Session) -> None:
    entry_id, approver_id = uuid.uuid4(), uuid.uuid4()
    job = make_job(
        db_session,
        job_type=JobType.KB_INDEX,
        payload={KB_INDEX_ENTRY_KEY: str(entry_id), KB_INDEX_APPROVER_KEY: str(approver_id)},
    )

    assert kb_index_job_target(job) == (entry_id, approver_id)


@pytest.mark.parametrize("payload", [None, {}, {KB_INDEX_ENTRY_KEY: "not-a-uuid"}])
def test_a_payload_without_a_usable_entry_id_reads_as_missing(
    db_session: Session, payload: dict | None
) -> None:
    job = make_job(db_session, job_type=JobType.KB_INDEX, payload=payload)

    assert kb_index_job_target(job)[0] is None


# --- Dispatch from the worker (ADR-08) -----------------------------------


def test_the_worker_runs_a_kb_index_job(
    db_session: Session, app_session_factory: sessionmaker, pipeline
) -> None:
    """The job type the approval endpoint enqueues is dispatched, not refused."""
    approver = _approver(db_session)
    entry = _pending_entry(db_session, slug="fixture-worker")
    job = JobQueue(db_session).enqueue(
        JobType.KB_INDEX,
        payload={KB_INDEX_ENTRY_KEY: str(entry.id), KB_INDEX_APPROVER_KEY: str(approver.id)},
    )
    db_session.commit()

    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    db_session.refresh(job)
    db_session.refresh(entry)
    assert job.status is JobStatus.DONE
    assert entry.status is KBEntryStatus.ACTIVE


def test_the_worker_fails_a_kb_index_job_whose_indexing_fails(
    db_session: Session, app_session_factory: sessionmaker, pipeline
) -> None:
    """`last_error` is the reason code, never model output (CLAUDE.md §9)."""
    approver = _approver(db_session)
    entry = _pending_entry(db_session, slug="fixture-worker-failed")
    job = JobQueue(db_session).enqueue(
        JobType.KB_INDEX,
        payload={KB_INDEX_ENTRY_KEY: str(entry.id), KB_INDEX_APPROVER_KEY: str(approver.id)},
    )
    db_session.commit()

    run_pending_jobs_once(app_session_factory, replace(pipeline, kb_indexer=_FailingIndexer()))

    db_session.refresh(job)
    db_session.refresh(entry)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith(KBIndexFailureReason.INDEXING_FAILED.value)
    assert entry.status is KBEntryStatus.PENDING_REVIEW


def test_a_kb_index_job_with_no_entry_fails_loudly(
    db_session: Session, app_session_factory: sessionmaker, pipeline
) -> None:
    job = JobQueue(db_session).enqueue(JobType.KB_INDEX, payload={})
    db_session.commit()

    run_pending_jobs_once(app_session_factory, pipeline)

    db_session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith(MISSING_ENTRY_ID)
