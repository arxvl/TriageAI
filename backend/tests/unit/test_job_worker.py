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

from app.jobs.worker import (
    MISSING_RECOMMENDATION_ID,
    UNEXPECTED_ERROR,
    UNSUPPORTED_JOB_TYPE,
    run_pending_jobs_once,
)
from app.models import ActionsStatus, CaseStatus, JobStatus, JobType
from app.pipeline.orchestrator import (
    ACTIONS_JOB_RECOMMENDATION_KEY,
    ActionsFailureReason,
    ActionsRunResult,
    FailureReason,
    PipelineRunResult,
)
from tests.conftest import make_case, make_job


class _StubPipeline:
    """Answers `run` and `run_actions` from a script, recording both.

    One stub for both entry points, because the worker's contract is the same
    for either: the job ends in a state that agrees with whatever the run
    reported.
    """

    def __init__(
        self,
        result: object = None,
        raises: Exception | None = None,
        actions_result: object = None,
    ) -> None:
        self._result = result
        self._raises = raises
        self._actions_result = actions_result
        self.calls: list[tuple[uuid.UUID, uuid.UUID | None]] = []
        self.actions_calls: list[tuple[uuid.UUID, uuid.UUID | None]] = []

    def run(self, case_id: uuid.UUID, *, job_id: uuid.UUID | None = None) -> object:
        self.calls.append((case_id, job_id))
        if self._raises is not None:
            raise self._raises
        return self._result or PipelineRunResult(case_id, CaseStatus.AWAITING_REVIEW)

    def run_actions(
        self, recommendation_id: uuid.UUID, *, job_id: uuid.UUID | None = None
    ) -> object:
        self.actions_calls.append((recommendation_id, job_id))
        if self._raises is not None:
            raise self._raises
        return self._actions_result or ActionsRunResult(recommendation_id, ActionsStatus.READY)


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


# --- SUGGEST_ACTIONS (P05b §5b.3, ADR-18 §3) -----------------------------


def actions_job(db_session: Session, recommendation_id: object) -> object:
    """A `SUGGEST_ACTIONS` job carrying `recommendation_id` in its payload."""
    return make_job(
        db_session,
        case=make_case(db_session),
        job_type=JobType.SUGGEST_ACTIONS,
        payload=None
        if recommendation_id is None
        else {ACTIONS_JOB_RECOMMENDATION_KEY: str(recommendation_id)},
    )


def test_an_actions_job_is_dispatched_with_its_recommendation(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    recommendation_id = uuid.uuid4()
    job = actions_job(db_session, recommendation_id)
    pipeline = _StubPipeline()

    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    assert pipeline.actions_calls == [(recommendation_id, job.id)]
    # The triage entry point is not touched: this job must not re-run a case.
    assert pipeline.calls == []
    db_session.refresh(job)
    assert job.status is JobStatus.DONE
    assert job.last_error is None


def test_a_failed_actions_run_fails_the_job_with_the_reason_code(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    """The run has already recorded it on the recommendation, never on the case
    (FR-77)."""
    recommendation_id = uuid.uuid4()
    job = actions_job(db_session, recommendation_id)
    pipeline = _StubPipeline(
        actions_result=ActionsRunResult(
            recommendation_id,
            ActionsStatus.FAILED,
            ActionsFailureReason.ACTIONS_TIMEOUT,
        )
    )

    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    db_session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith(ActionsFailureReason.ACTIONS_TIMEOUT.value)


@pytest.mark.parametrize("payload", [None, {"recommendation_id": "not-a-uuid"}, {}])
def test_an_actions_job_without_a_usable_recommendation_fails(
    db_session: Session, app_session_factory: sessionmaker, payload: dict | None
) -> None:
    """The only writer is the orchestrator, so anything else is hand-built."""
    job = make_job(
        db_session,
        case=make_case(db_session),
        job_type=JobType.SUGGEST_ACTIONS,
        payload=payload,
    )
    pipeline = _StubPipeline()

    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    assert pipeline.actions_calls == []
    db_session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith(MISSING_RECOMMENDATION_ID)


def test_an_actions_run_that_raises_is_contained(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    """One bad actions job must not take the worker down either."""
    job = actions_job(db_session, uuid.uuid4())
    pipeline = _StubPipeline(raises=RuntimeError("stub blew up"))

    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    db_session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith(UNEXPECTED_ERROR)
