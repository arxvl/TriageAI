"""The job queue's bookkeeping (P05 §5.4 task 1, ADR-08).

Against a real PostgreSQL connection, because the two properties that matter are
database properties: `FOR UPDATE SKIP LOCKED` and the staleness comparison on
`updated_at`. A fake would prove neither.

All data here is fictitious (CLAUDE.md §9).
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs.queue import STAGE_KEY, JobQueue, JobStage
from app.models import Job, JobStatus, JobType
from tests.conftest import make_case, make_job


def test_enqueue_creates_a_queued_job_with_no_attempts(db_session: Session) -> None:
    case = make_case(db_session)

    job = JobQueue(db_session).enqueue(JobType.PIPELINE_RUN, case_id=case.id)

    assert job.status is JobStatus.QUEUED
    assert job.attempts == 0
    assert job.case_id == case.id
    assert job.last_error is None


def test_enqueue_does_not_commit(db_session: Session) -> None:
    """The caller owns the transaction: a case and its job commit together (ADR-08)."""
    case = make_case(db_session)

    JobQueue(db_session).enqueue(JobType.PIPELINE_RUN, case_id=case.id)
    db_session.rollback()

    assert db_session.scalars(select(Job)).all() == []


def test_claim_next_takes_the_oldest_job_and_marks_it_running(db_session: Session) -> None:
    older = make_job(db_session, created_at=datetime.now(UTC) - timedelta(minutes=5))
    make_job(db_session, created_at=datetime.now(UTC))

    claimed = JobQueue(db_session).claim_next()

    assert claimed is not None
    assert claimed.id == older.id
    assert claimed.status is JobStatus.RUNNING
    # Counted on the way in, so a job lost to a crash has still been attempted.
    assert claimed.attempts == 1


def test_claim_next_returns_none_on_an_empty_queue(db_session: Session) -> None:
    assert JobQueue(db_session).claim_next() is None


def test_claim_next_ignores_a_job_scheduled_for_later(db_session: Session) -> None:
    """`run_after` is how P07's retry backoff defers an attempt."""
    make_job(db_session, run_after=datetime.now(UTC) + timedelta(hours=1))

    assert JobQueue(db_session).claim_next() is None


def test_claim_next_takes_a_job_whose_run_after_has_passed(db_session: Session) -> None:
    make_job(db_session, run_after=datetime.now(UTC) - timedelta(seconds=1))

    assert JobQueue(db_session).claim_next() is not None


def test_claim_next_ignores_a_job_of_another_type_when_filtered(db_session: Session) -> None:
    make_job(db_session, job_type=JobType.EVAL_RUN)

    assert JobQueue(db_session).claim_next(types=[JobType.PIPELINE_RUN]) is None


def test_claim_next_skips_jobs_that_are_not_queued(db_session: Session) -> None:
    make_job(db_session, status=JobStatus.RUNNING)
    make_job(db_session, status=JobStatus.DONE)
    make_job(db_session, status=JobStatus.FAILED)

    assert JobQueue(db_session).claim_next() is None


def test_complete_marks_a_job_done(db_session: Session) -> None:
    job = make_job(db_session, status=JobStatus.RUNNING)

    JobQueue(db_session).complete(job)

    assert job.status is JobStatus.DONE
    assert job.last_error is None


def test_fail_records_the_reason_code_and_the_time(db_session: Session) -> None:
    """NFR-09. A code and a timestamp — never a model response (CLAUDE.md §9)."""
    job = make_job(db_session, status=JobStatus.RUNNING)

    JobQueue(db_session).fail(job, "EXTRACTION_TIMEOUT")

    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith("EXTRACTION_TIMEOUT at ")
    # Parses, so P07 can read the time back rather than only display it.
    datetime.fromisoformat(job.last_error.removeprefix("EXTRACTION_TIMEOUT at "))


def test_set_stage_records_progress_without_losing_the_payload(db_session: Session) -> None:
    job = make_job(db_session, status=JobStatus.RUNNING, payload={"source": "fixture"})

    JobQueue(db_session).set_stage(job.id, JobStage.EXTRACT)

    db_session.refresh(job)
    assert job.payload == {"source": "fixture", STAGE_KEY: JobStage.EXTRACT.value}


def test_set_stage_on_a_missing_job_is_not_an_error(db_session: Session) -> None:
    """The pipeline can be driven without the queue — the harness does (M7)."""
    case = make_case(db_session)

    JobQueue(db_session).set_stage(case.id, JobStage.EXTRACT)


def test_recover_stale_requeues_a_job_left_running(db_session: Session) -> None:
    """ADR-08, NFR-13: the case it was working on is otherwise stuck forever."""
    stale = make_job(
        db_session,
        status=JobStatus.RUNNING,
        attempts=1,
        updated_at=datetime.now(UTC) - timedelta(minutes=10),
    )

    recovered = JobQueue(db_session).recover_stale(older_than_minutes=2)

    assert recovered == 1
    db_session.refresh(stale)
    assert stale.status is JobStatus.QUEUED
    # The attempt happened. Forgetting it would let a job that crashes the worker
    # do so indefinitely.
    assert stale.attempts == 1


def test_recover_stale_leaves_a_job_that_is_still_running(db_session: Session) -> None:
    fresh = make_job(db_session, status=JobStatus.RUNNING, updated_at=datetime.now(UTC))

    assert JobQueue(db_session).recover_stale(older_than_minutes=2) == 0

    db_session.refresh(fresh)
    assert fresh.status is JobStatus.RUNNING


def test_recover_stale_ignores_finished_jobs(db_session: Session) -> None:
    long_ago = datetime.now(UTC) - timedelta(days=1)
    make_job(db_session, status=JobStatus.DONE, updated_at=long_ago)
    make_job(db_session, status=JobStatus.FAILED, updated_at=long_ago)

    assert JobQueue(db_session).recover_stale(older_than_minutes=2) == 0
