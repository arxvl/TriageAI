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

import threading
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
from app.pipeline.config import PipelineConfig
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

    config = PipelineConfig()

    # What the watchdog test needs: a run that does not come back until released,
    # and a record of the cancel event and of the worker taking the failure path.
    block: threading.Event | None = None
    cancel_seen: threading.Event | None = None
    timed_out: list[uuid.UUID] = []

    def run(
        self,
        case_id: uuid.UUID,
        *,
        job_id: uuid.UUID | None = None,
        cancel: threading.Event | None = None,
    ) -> object:
        self.calls.append((case_id, job_id))
        if self.block is not None:
            self.cancel_seen = cancel
            self.block.wait(timeout=10)
        if self._raises is not None:
            raise self._raises
        return self._result or PipelineRunResult(case_id, CaseStatus.AWAITING_REVIEW)

    def fail_timed_out(self, case_id: uuid.UUID, *, job_id: uuid.UUID | None = None) -> object:
        self.timed_out = [*self.timed_out, case_id]
        return PipelineRunResult(
            case_id, CaseStatus.MANUAL_TRIAGE_REQUIRED, FailureReason.LLM_TIMEOUT
        )

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
        PipelineRunResult(case.id, CaseStatus.MANUAL_TRIAGE_REQUIRED, FailureReason.LLM_TIMEOUT)
    )

    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    db_session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith(FailureReason.LLM_TIMEOUT.value)


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


@pytest.mark.parametrize("job_type", [JobType.REGENERATE, JobType.EVAL_RUN])
def test_a_job_type_this_worker_does_not_handle_fails_loudly(
    db_session: Session, app_session_factory: sessionmaker, job_type: JobType
) -> None:
    """P07 and M7 add these. Until then, failing beats sitting `QUEUED`.

    `KB_INDEX` has left this list: P08 §8.1 dispatches it, and
    `tests/unit/test_kb_indexing.py` covers what it does.
    """
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


# --- The job time budget (P07 §7.1 task 5, IR-19) ---------------------------


def test_the_job_budget_is_twice_the_stage_timeout_plus_ten_seconds() -> None:
    assert PipelineConfig(timeout_s=30).job_timeout_s == 70
    assert PipelineConfig(timeout_s=5.5).job_timeout_s == 21
    # The recovery sweep must not mistake a job inside its budget for a dead one.
    assert PipelineConfig().job_timeout_s < 2 * 60


def test_a_run_that_outlives_its_budget_is_failed_through_the_failure_path(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    case = make_case(db_session)
    job = make_job(db_session, case=case)
    pipeline = _StubPipeline()
    pipeline.block = threading.Event()

    try:
        ran = run_pending_jobs_once(app_session_factory, pipeline, budget_s=0.2)
    finally:
        pipeline.block.set()

    assert ran == 1
    db_session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith(FailureReason.LLM_TIMEOUT.value)
    assert pipeline.timed_out == [case.id]
    # The abandoned run was told to stop writing.
    assert pipeline.cancel_seen is not None and pipeline.cancel_seen.is_set()


def test_a_run_inside_its_budget_is_left_alone(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    case = make_case(db_session)
    job = make_job(db_session, case=case)
    pipeline = _StubPipeline()

    run_pending_jobs_once(app_session_factory, pipeline, budget_s=5)

    db_session.refresh(job)
    assert job.status is JobStatus.DONE
    assert pipeline.timed_out == []


def test_an_exception_on_the_run_thread_still_reaches_the_workers_containment(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    case = make_case(db_session)
    job = make_job(db_session, case=case)

    run_pending_jobs_once(app_session_factory, _StubPipeline(raises=RuntimeError("boom")))

    db_session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None and job.last_error.startswith(UNEXPECTED_ERROR)
