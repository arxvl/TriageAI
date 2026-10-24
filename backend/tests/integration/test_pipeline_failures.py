"""Every failure maps to one reason code, one message and one safe outcome
(P07 §7.1, FR-15, NFR-09, NFR-13, IR-19, ADR-08, ADR-10).

Each failure is injected at the stage it belongs to, through a stub swapped into
an otherwise mocked pipeline, and followed all the way out: the case, the audit
entry, the job's `last_error` and the sentence W-06 shows. The properties:

1. **Every code ends in `MANUAL_TRIAGE_REQUIRED`** with its own message, and the
   job records the same code (NFR-09).
2. **De-identification fails closed.** Nothing downstream is called (ADR-10).
3. **A cause is not lost in a wrapper.** `ExtractionFailed from LLMTimeout` reports
   the timeout.
4. **The demo toggle works in dev only** and never skips the red-flag alert.
5. **A restart never leaves a case in `PROCESSING`** (NFR-13).

All data is fictitious (CLAUDE.md §9).
"""

import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppEnv, MockLLMBehavior
from app.jobs.queue import JobQueue
from app.jobs.recovery import recover_stale_jobs
from app.jobs.worker import run_pending_jobs_once
from app.models import (
    AuditEntry,
    Case,
    CaseStatus,
    ExtractionResult,
    Job,
    JobStatus,
    JobType,
    Recommendation,
    RedFlagAlert,
    UserRole,
)
from app.pipeline.errors import (
    ExtractionFailed,
    GenerationFailed,
    LLMTimeout,
    LLMUnavailable,
    RetrievalFailed,
)
from app.pipeline.messages import failure_message
from app.pipeline.orchestrator import FailureReason
from app.services.audit_service import AuditAction
from scripts.seed import seed
from tests.conftest import make_demo_case, make_job, make_user, sign_in

CASES_URL = "/api/v1/cases"
PASSWORD = "Sampaguita2026"

# A phrase that is in DEMO_1's description, so the toggle has something to find.
DEMO_PHRASE = "nothing comes out"


class _Stage:
    """A stage that counts its calls and raises what it is told to, or answers
    with the real mock."""

    model_id = "mock"
    prompt_version = "mock-0"
    last_latency_ms = 0

    def __init__(
        self,
        method: str,
        real: object,
        raises: Exception | None = None,
        gate: threading.Event | None = None,
    ) -> None:
        self.calls = 0
        self._gate = gate
        self._method = method
        self._real = real
        self._raises = raises
        setattr(self, method, self._call)

    def _call(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        if self._gate is not None:
            self._gate.wait(timeout=10)
        if self._raises is not None:
            raise self._raises
        return getattr(self._real, self._method)(*args, **kwargs)


def chained(error: Exception, cause: Exception) -> Exception:
    error.__cause__ = cause
    return error


@pytest.fixture
def seeded(db_session: Session) -> None:
    seed(db_session)
    db_session.flush()


def stubbed(pipeline, field: str, method: str, raises: Exception | None):
    stub = _Stage(method, getattr(pipeline, field), raises)
    return replace(pipeline, **{field: stub}), stub


def audit_failures(session: Session, case: Case) -> list[AuditEntry]:
    return list(
        session.scalars(
            select(AuditEntry)
            .where(
                AuditEntry.entity_id == str(case.id),
                AuditEntry.action == AuditAction.PIPELINE_FAILED.value,
            )
            .order_by(AuditEntry.id)
        )
    )


def case_status(session: Session, case: Case) -> CaseStatus:
    session.expire(case)
    return case.status


# --- Each code, end to end ------------------------------------------------

# (id, how to break the pipeline, the code it must report)
CASES = [
    ("timeout", ("mock", MockLLMBehavior.TIMEOUT), FailureReason.LLM_TIMEOUT),
    ("invalid_json", ("mock", MockLLMBehavior.INVALID_JSON), FailureReason.LLM_INVALID_OUTPUT),
    (
        "unavailable",
        ("extractor", "extract", LLMUnavailable("provider refused")),
        FailureReason.LLM_UNAVAILABLE,
    ),
    (
        "retrieval",
        ("retriever", "retrieve", RetrievalFailed("vector search failed")),
        FailureReason.RETRIEVAL_FAILED,
    ),
    (
        "generation",
        ("generator", "generate", GenerationFailed("no draft")),
        FailureReason.GENERATION_FAILED,
    ),
    (
        "deidentification",
        ("deidentifier", "deidentify", RuntimeError("pattern table missing")),
        FailureReason.DEIDENTIFICATION_FAILED,
    ),
    (
        "internal",
        ("retriever", "retrieve", RuntimeError("a bug")),
        FailureReason.INTERNAL_ERROR,
    ),
]


@pytest.mark.parametrize(("breakage", "reason"), [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_every_failure_ends_in_manual_triage_with_its_code_and_message(
    db_session: Session,
    seeded: None,
    pipeline_factory,
    app_session_factory: sessionmaker,
    api_client: TestClient,
    breakage: tuple,
    reason: FailureReason,
) -> None:
    case = make_demo_case(db_session, "DEMO_1")
    job = JobQueue(db_session).enqueue(JobType.PIPELINE_RUN, case_id=case.id)
    db_session.flush()

    if breakage[0] == "mock":
        pipeline = pipeline_factory(mock_llm_behavior=breakage[1])
    else:
        pipeline, _ = stubbed(pipeline_factory(), breakage[0], breakage[1], breakage[2])

    run_pending_jobs_once(app_session_factory, pipeline, max_jobs=1)

    # The case is safe and waiting for a person.
    assert case_status(db_session, case) is CaseStatus.MANUAL_TRIAGE_REQUIRED
    # The job and the audit entry say the same thing.
    db_session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith(f"{reason.value} at ")
    (entry,) = audit_failures(db_session, case)
    assert entry.after["reason"] == reason.value

    # And the reviewer reads it in plain language, never as a code.
    reviewer = make_user(db_session, password=PASSWORD, role=UserRole.VETERINARY_REVIEWER)
    sign_in(api_client, reviewer.email, PASSWORD)
    body = api_client.get(f"{CASES_URL}/{case.id}").json()
    assert body["failure"]["reason_code"] == reason.value
    message = body["failure"]["message"]
    assert message == failure_message(
        reason.value,
        attempts=entry.after["attempts"],
        failed_at=datetime.fromisoformat(entry.after["failed_at"]),
    )
    assert message.endswith("no data was lost.")
    assert reason.value not in message
    assert body["permissions"]["can_retry"] is True


def test_unusable_output_is_retried_once_and_the_attempts_are_recorded(
    db_session: Session, seeded: None, pipeline_factory
) -> None:
    case = make_demo_case(db_session, "DEMO_1")

    pipeline_factory(mock_llm_behavior=MockLLMBehavior.INVALID_JSON).run(case.id)

    (entry,) = audit_failures(db_session, case)
    assert entry.after["attempts"] == 2


def test_a_timeout_is_not_retried(db_session: Session, seeded: None, pipeline_factory) -> None:
    case = make_demo_case(db_session, "DEMO_1")

    pipeline_factory(mock_llm_behavior=MockLLMBehavior.TIMEOUT).run(case.id)

    (entry,) = audit_failures(db_session, case)
    assert entry.after["attempts"] == 1


# --- A wrapped cause is still the cause -----------------------------------


def test_a_stage_error_chained_from_a_timeout_reports_the_timeout(
    db_session: Session, seeded: None, pipeline_factory
) -> None:
    """The real extractor raises `ExtractionFailed from <transport error>`."""
    case = make_demo_case(db_session, "DEMO_1")
    pipeline, _ = stubbed(
        pipeline_factory(),
        "extractor",
        "extract",
        chained(ExtractionFailed("gave up"), LLMTimeout("slow")),
    )

    assert pipeline.run(case.id).failure_reason is FailureReason.LLM_TIMEOUT


def test_a_bare_extraction_failure_reads_as_unusable_output(
    db_session: Session, seeded: None, pipeline_factory
) -> None:
    case = make_demo_case(db_session, "DEMO_1")
    pipeline, _ = stubbed(
        pipeline_factory(), "extractor", "extract", ExtractionFailed("no entities")
    )

    assert pipeline.run(case.id).failure_reason is FailureReason.LLM_INVALID_OUTPUT


# --- De-identification fails closed (ADR-10) ------------------------------


@pytest.mark.parametrize("error", [RuntimeError("boom"), ValueError("bad pattern")])
def test_a_deidentification_failure_calls_nothing_downstream(
    db_session: Session, seeded: None, pipeline_factory, error: Exception
) -> None:
    """No screen, no extraction, no retrieval, no generation, no actions — so no
    stage that could send text anywhere has been given any."""
    case = make_demo_case(db_session, "DEMO_1", owner_name="D. Placeholder")
    pipeline = pipeline_factory()
    pipeline, _ = stubbed(pipeline, "deidentifier", "deidentify", error)
    spies = {}
    for field, method in (
        ("red_flag_screener", "screen"),
        ("extractor", "extract"),
        ("retriever", "retrieve"),
        ("generator", "generate"),
        ("action_suggester", "suggest"),
    ):
        pipeline, spies[field] = stubbed(pipeline, field, method, None)

    result = pipeline.run(case.id)

    assert result.failure_reason is FailureReason.DEIDENTIFICATION_FAILED
    assert {field: spy.calls for field, spy in spies.items()} == dict.fromkeys(spies, 0)
    assert case_status(db_session, case) is CaseStatus.MANUAL_TRIAGE_REQUIRED
    assert db_session.scalar(select(func.count(ExtractionResult.id))) == 0


def test_a_deidentification_failure_logs_the_class_and_never_the_message(
    db_session: Session, seeded: None, pipeline_factory, caplog: pytest.LogCaptureFixture
) -> None:
    case = make_demo_case(db_session, "DEMO_1")
    pipeline, _ = stubbed(
        pipeline_factory(),
        "deidentifier",
        "deidentify",
        RuntimeError("could not clean: nothing comes out"),
    )

    with caplog.at_level("DEBUG"):
        pipeline.run(case.id)

    logged = " ".join(record.getMessage() + repr(record.__dict__) for record in caplog.records)
    assert "RuntimeError" in logged
    assert "could not clean" not in logged


# --- The demo toggle (P07 §7.1 task 7) ------------------------------------


def test_the_demo_phrase_forces_a_timeout_in_dev_without_calling_the_extractor(
    db_session: Session, seeded: None, pipeline_factory
) -> None:
    case = make_demo_case(db_session, "DEMO_1")
    pipeline, extractor = stubbed(
        pipeline_factory(app_env=AppEnv.DEV, demo_force_failure_case_text=DEMO_PHRASE.upper()),
        "extractor",
        "extract",
        None,
    )

    result = pipeline.run(case.id)

    assert result.failure_reason is FailureReason.LLM_TIMEOUT
    assert extractor.calls == 0
    assert case_status(db_session, case) is CaseStatus.MANUAL_TRIAGE_REQUIRED
    # The pre-screen ran and committed first, so the alert still reaches the queue.
    assert db_session.scalar(select(func.count(RedFlagAlert.id))) == 1


@pytest.mark.parametrize("env", [AppEnv.TEST, AppEnv.PROD])
def test_the_demo_phrase_is_ignored_outside_dev(
    db_session: Session, seeded: None, pipeline_factory, env: AppEnv
) -> None:
    case = make_demo_case(db_session, "DEMO_1")
    pipeline = pipeline_factory(app_env=env, demo_force_failure_case_text=DEMO_PHRASE)

    assert pipeline.config.demo_force_failure_phrase is None
    assert pipeline.run(case.id).succeeded


def test_a_case_without_the_phrase_is_untouched_in_dev(
    db_session: Session, seeded: None, pipeline_factory
) -> None:
    case = make_demo_case(db_session, "DEMO_2")
    pipeline = pipeline_factory(app_env=AppEnv.DEV, demo_force_failure_case_text=DEMO_PHRASE)

    assert pipeline.run(case.id).succeeded


# --- Restart safety (task 6, NFR-13) --------------------------------------


def test_a_job_abandoned_mid_run_is_recovered_and_the_case_never_stays_processing(
    db_session: Session,
    seeded: None,
    pipeline,
    app_session_factory: sessionmaker,
) -> None:
    """The backend was killed during a slow job: the case is `PROCESSING` and the
    job is `RUNNING` with nobody working on it. The startup sweep hands the job
    back and the worker finishes it."""
    case = make_demo_case(db_session, "DEMO_1")
    case.status = CaseStatus.PROCESSING
    job = make_job(
        db_session,
        case=case,
        status=JobStatus.RUNNING,
        attempts=1,
        updated_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    db_session.flush()

    assert recover_stale_jobs(app_session_factory, older_than_minutes=2) == 1
    assert run_pending_jobs_once(app_session_factory, pipeline, max_jobs=1) == 1

    db_session.refresh(job)
    assert job.status is JobStatus.DONE
    assert job.attempts == 2
    assert case_status(db_session, case) is CaseStatus.AWAITING_REVIEW
    assert db_session.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.RUNNING)) == 0


# --- The job time budget (task 5) -----------------------------------------


def test_a_job_past_its_budget_fails_the_case_and_the_late_run_writes_nothing(
    db_session: Session,
    seeded: None,
    pipeline,
    app_session_factory: sessionmaker,
) -> None:
    """The extractor does not come back within the budget. The worker fails the
    case through the ordinary path; when the extractor finally answers, the
    abandoned run stops at its next checkpoint instead of storing an extraction
    and a recommendation over the failure."""
    case = make_demo_case(db_session, "DEMO_1")
    job = JobQueue(db_session).enqueue(JobType.PIPELINE_RUN, case_id=case.id)
    db_session.flush()
    gate = threading.Event()
    stuck = _Stage("extract", pipeline.extractor, gate=gate)

    try:
        run_pending_jobs_once(
            app_session_factory, replace(pipeline, extractor=stuck), max_jobs=1, budget_s=0.3
        )
    finally:
        gate.set()
        for thread in threading.enumerate():
            if thread.name.startswith("triageai-run-"):
                thread.join(timeout=10)

    assert case_status(db_session, case) is CaseStatus.MANUAL_TRIAGE_REQUIRED
    db_session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None and job.last_error.startswith("LLM_TIMEOUT at ")
    (entry,) = audit_failures(db_session, case)
    assert entry.after["reason"] == "LLM_TIMEOUT"
    assert db_session.scalar(select(func.count(ExtractionResult.id))) == 0
    assert db_session.scalar(select(func.count(Recommendation.id))) == 0
