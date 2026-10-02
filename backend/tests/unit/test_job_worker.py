"""The worker's dispatch and its failure containment (P05 §5.4 task 2, ADR-08).

The pipeline is stubbed here. What these tests are about is the worker's own
contract: the job ends in a state that agrees with the run, an unsupported type is
refused rather than left queued, and **one bad job never stops the worker** — a
thread that died on the first unhandled exception would leave every later case in
`SUBMITTED` with nothing in the log to explain it.

The pipeline's own behaviour is proved end to end in
`tests/integration/test_pipeline_run.py`.

All data here is fictitious (CLAUDE.md §9).
"""

import uuid

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.jobs.worker import UNEXPECTED_ERROR, UNSUPPORTED_JOB_TYPE, run_pending_jobs_once
from app.models import CaseStatus, JobStatus, JobType
from app.pipeline.orchestrator import FailureReason, PipelineRunResult
from tests.conftest import make_case, make_job


class _StubPipeline:
    """Answers `run` from a script, and records what it was asked to do."""

    def __init__(self, result: object = None, raises: Exception | None = None) -> None:
        self._result = result
        self._raises = raises
        self.calls: list[tuple[uuid.UUID, uuid.UUID | None]] = []

    def run(self, case_id: uuid.UUID, *, job_id: uuid.UUID | None = None) -> object:
        self.calls.append((case_id, job_id))
        if self._raises is not None:
            raise self._raises
        return self._result or PipelineRunResult(case_id, CaseStatus.AWAITING_REVIEW)


def test_a_successful_run_completes_the_job(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    case = make_case(db_session)
    job = make_job(db_session, case=case)
    pipeline = _StubPipeline()

    ran = run_pending_jobs_once(app_session_factory, pipeline)

    assert ran == 1
    assert pipeline.calls == [(case.id, job.id)]
    db_session.refresh(job)
    assert job.status is JobStatus.DONE
    assert job.last_error is None


def test_a_failed_run_fails_the_job_with_the_reason_code(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    """The run has already sent the case to manual triage; this records it (NFR-09)."""
    case = make_case(db_session)
    job = make_job(db_session, case=case)
    pipeline = _StubPipeline(
        PipelineRunResult(
            case.id, CaseStatus.MANUAL_TRIAGE_REQUIRED, FailureReason.EXTRACTION_TIMEOUT
        )
    )

    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    db_session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith(FailureReason.EXTRACTION_TIMEOUT.value)


def test_an_unexpected_exception_is_contained(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    case = make_case(db_session)
    job = make_job(db_session, case=case)
    pipeline = _StubPipeline(raises=RuntimeError("stub blew up"))

    # Does not propagate: the worker thread has to survive it.
    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    db_session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith(UNEXPECTED_ERROR)


def test_the_queue_is_drained_in_one_pass(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    for _ in range(3):
        make_job(db_session, case=make_case(db_session))

    assert run_pending_jobs_once(app_session_factory, _StubPipeline()) == 3


def test_max_jobs_bounds_one_pass(db_session: Session, app_session_factory: sessionmaker) -> None:
    for _ in range(3):
        make_job(db_session, case=make_case(db_session))

    assert run_pending_jobs_once(app_session_factory, _StubPipeline(), max_jobs=2) == 2


def test_an_empty_queue_runs_nothing(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    pipeline = _StubPipeline()

    assert run_pending_jobs_once(app_session_factory, pipeline) == 0
    assert pipeline.calls == []


@pytest.mark.parametrize("job_type", [JobType.REGENERATE, JobType.EVAL_RUN, JobType.KB_INDEX])
def test_a_job_type_this_worker_does_not_handle_fails_loudly(
    db_session: Session, app_session_factory: sessionmaker, job_type: JobType
) -> None:
    """P07, P08 and M7 add these. Until then, failing beats sitting `QUEUED`."""
    job = make_job(db_session, case=make_case(db_session), job_type=job_type)
    pipeline = _StubPipeline()

    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    assert pipeline.calls == []
    db_session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith(UNSUPPORTED_JOB_TYPE)


def test_a_pipeline_run_job_with_no_case_fails(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    job = make_job(db_session, case=None)

    assert run_pending_jobs_once(app_session_factory, _StubPipeline()) == 1

    db_session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith("MISSING_CASE_ID")
