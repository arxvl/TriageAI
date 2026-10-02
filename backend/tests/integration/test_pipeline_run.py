"""The triage pipeline end to end, on mocks (P05 §5.4, FR-06, FR-12, FR-15,
FR-20–FR-24, FR-26, NFR-05, NFR-09, ADR-08, ADR-09, ADR-14).

Every run here goes through the real orchestrator, the real safety validator and
the real database. Only the AI stages are mocked, and they replay
`tests/fixtures/demo_cases.yaml` (ADR-17), so the whole path is exercised with no
API key, no model download and no network.

Six properties these tests exist to keep:

1. **`DEMO_1` ends ORANGE.** The mock generator drafts YELLOW and the pre-screen
   reports `MALE_CAT_NO_URINE` at ORANGE, so the deterministic validator must
   raise it. That is FR-23 made visible, and it is the scenario the PD8
   walkthrough shows.
2. **An alert exists before any model call.** Proved by forcing a timeout: the
   alert row is there and no extraction row ever was (NFR-05, FR-12).
3. **A case is never lost and never left in `PROCESSING`** on any failure path
   (NFR-09).
4. **Unusable output is retried once; a timeout is not** (FR-15, IR-19).
5. **Provenance is complete** — model id, prompt version and per-stage latency on
   the rows they describe (FR-26, ADR-14).
6. **No description text reaches the audit log or the log** (CLAUDE.md §9).

`seed()` runs inside the test transaction because a run needs the presenting
complaints, the red-flag rules and knowledge-base version 0 that a real deployment
seeds. All data is fictitious.
"""

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import MockLLMBehavior
from app.jobs.queue import STAGE_KEY, JobQueue, JobStage
from app.jobs.worker import run_pending_jobs_once
from app.models import (
    AuditEntry,
    Case,
    CaseStatus,
    ConfidenceLevel,
    ExtractionResult,
    JobStatus,
    JobType,
    KBVersion,
    Recommendation,
    RedFlagAlert,
    RetrievedReference,
    VTLCategory,
    extraction_complaints,
)
from app.pipeline.orchestrator import FailureReason
from app.pipeline.safety import LOW_RETRIEVAL_SCORE, UNSUPPORTED_COMPLAINT
from app.services.audit_service import AuditAction
from scripts.seed import seed
from tests.conftest import (
    demo_cases,
    make_case,
    make_demo_case,
    make_job,
    make_owner_description,
)

OWNER_NAME = "D. Placeholder"
CONTACT_NUMBER = "0917-555-0101"


@pytest.fixture
def seeded(db_session: Session) -> None:
    """The reference rows a run needs: complaints, red-flag rules, KB version 0.

    The same `seed()` a deployment runs, inside the test's transaction — so the
    rule codes and complaint codes the fixtures name are the ones the application
    really has, not a test-only subset.
    """
    seed(db_session)
    db_session.flush()


def extraction_of(session: Session, case: Case) -> ExtractionResult | None:
    return session.scalars(
        select(ExtractionResult)
        .where(ExtractionResult.case_id == case.id)
        .order_by(ExtractionResult.version.desc())
    ).first()


def recommendation_of(session: Session, case: Case) -> Recommendation | None:
    return session.scalars(
        select(Recommendation)
        .where(Recommendation.case_id == case.id)
        .order_by(Recommendation.version.desc())
    ).first()


def alerts_of(session: Session, case: Case) -> list[RedFlagAlert]:
    return list(
        session.scalars(
            select(RedFlagAlert)
            .where(RedFlagAlert.case_id == case.id)
            .order_by(RedFlagAlert.created_at, RedFlagAlert.id)
        )
    )


def audit_for(session: Session, case: Case) -> list[AuditEntry]:
    return list(
        session.scalars(
            select(AuditEntry).where(AuditEntry.entity_id == str(case.id)).order_by(AuditEntry.id)
        )
    )


def status_of(session: Session, case: Case) -> CaseStatus:
    session.expire(case)
    return case.status


# --- The happy path: DEMO_1, the FR-23 demonstration ----------------------


def test_demo_1_ends_awaiting_review_with_the_safety_floor_applied(
    db_session: Session, seeded: None, pipeline
) -> None:
    """FR-23, ADR-09. The draft is YELLOW; ORANGE is the validator's doing."""
    case = make_demo_case(db_session, "DEMO_1")

    result = pipeline.run(case.id)

    assert result.succeeded
    assert status_of(db_session, case) is CaseStatus.AWAITING_REVIEW

    recommendation = recommendation_of(db_session, case)
    assert recommendation is not None
    assert recommendation.category is VTLCategory.ORANGE
    assert recommendation.safety_floor_applied is True
    assert recommendation.safety_floor_rule_codes == ["MALE_CAT_NO_URINE"]
    # The drafted category, for contrast: the fixture records YELLOW.
    assert demo_cases()["DEMO_1"]["mock_draft"]["category"] == VTLCategory.YELLOW.value
    # And the fixture's own expectation of the finished case.
    assert demo_cases()["DEMO_1"]["expected_category"] == VTLCategory.ORANGE.value


def test_demo_1_stores_the_extraction_and_its_primary_complaint(
    db_session: Session, seeded: None, pipeline
) -> None:
    case = make_demo_case(db_session, "DEMO_1")

    pipeline.run(case.id)

    extraction = extraction_of(db_session, case)
    assert extraction is not None
    assert extraction.version == 1
    assert extraction.entities["species"] == "CAT"
    assert extraction.missing_information == ["water intake", "vomiting", "previous episodes"]

    complaints = dict(
        db_session.execute(
            select(
                extraction_complaints.c.complaint_code, extraction_complaints.c.is_primary
            ).where(extraction_complaints.c.extraction_id == extraction.id)
        ).all()
    )
    assert complaints["URINARY_OBSTRUCTION"] is True
    assert complaints["INAPPETENCE"] is False


def test_demo_1_stores_one_reference_per_passage_with_validated_citations(
    db_session: Session, seeded: None, pipeline
) -> None:
    """FR-22, ADR-14. The text is copied, and `is_cited` is the validator's answer."""
    case = make_demo_case(db_session, "DEMO_1")
    expected = demo_cases()["DEMO_1"]["mock_passages"]
    cited_ranks = set(demo_cases()["DEMO_1"]["mock_draft"]["cited_ranks"])

    pipeline.run(case.id)

    recommendation = recommendation_of(db_session, case)
    assert recommendation is not None
    references = list(
        db_session.scalars(
            select(RetrievedReference)
            .where(RetrievedReference.recommendation_id == recommendation.id)
            .order_by(RetrievedReference.rank)
        )
    )

    assert [reference.rank for reference in references] == list(range(1, len(expected) + 1))
    assert [reference.is_cited for reference in references] == [
        rank in cited_ranks for rank in range(1, len(expected) + 1)
    ]
    assert [reference.passage_text for reference in references] == [
        passage["text"] for passage in expected
    ]
    # No `kb_chunks` row exists for a mock passage, so the pointer is NULL while
    # the passage itself is kept in full (see PipelineRepository's docstring).
    assert all(reference.chunk_id is None for reference in references)


def test_demo_1_records_its_provenance(db_session: Session, seeded: None, pipeline) -> None:
    """FR-26, NFR-23, ADR-14. A mock run fills the same columns a real one does."""
    case = make_demo_case(db_session, "DEMO_1")

    pipeline.run(case.id)

    extraction = extraction_of(db_session, case)
    recommendation = recommendation_of(db_session, case)
    assert extraction is not None and recommendation is not None

    assert extraction.model_id == "mock"
    assert extraction.prompt_version == "mock-0"
    assert extraction.latency_ms is not None
    assert recommendation.model_id == "mock"
    assert recommendation.prompt_version == "mock-0"

    assert recommendation.kb_version_id == db_session.scalars(select(KBVersion.id)).one()
    params = recommendation.params
    assert params is not None
    assert params["top_k"] == pipeline.config.top_k
    assert params["temperature"] == pipeline.config.temperature
    assert params["retrieval_min_score"] == pipeline.config.retrieval_min_score
    # Every stage, including the ones that are not model calls: FR-68 reports p50
    # and p95 per stage from these.
    assert set(params["stage_ms"]) == {
        "deidentify",
        "screen",
        "extract",
        "retrieve",
        "generate",
    }


def test_demo_1_writes_its_audit_trail_in_order(
    db_session: Session, seeded: None, pipeline
) -> None:
    case = make_demo_case(db_session, "DEMO_1")

    pipeline.run(case.id)

    assert [entry.action for entry in audit_for(db_session, case)] == [
        AuditAction.PIPELINE_STARTED.value,
        AuditAction.RED_FLAG_ALERT.value,
        AuditAction.RECOMMENDATION_CREATED.value,
    ]
    created = audit_for(db_session, case)[-1]
    assert created.after["category"] == VTLCategory.ORANGE.value
    assert created.after["safety_floor_applied"] is True
    # The pipeline is not a person; the reviewer's decision is audited in P06.
    assert created.user_id is None
    assert created.role is None


def test_demo_2_and_demo_3_end_at_their_recorded_categories(
    db_session: Session, seeded: None, pipeline
) -> None:
    """The other two working scenarios, which give the queue its RED and BLUE rows."""
    for fixture_id in ("DEMO_2", "DEMO_3"):
        case = make_demo_case(db_session, fixture_id)

        pipeline.run(case.id)

        recommendation = recommendation_of(db_session, case)
        assert recommendation is not None
        assert recommendation.category.value == demo_cases()[fixture_id]["expected_category"]
        assert status_of(db_session, case) is CaseStatus.AWAITING_REVIEW


def test_a_description_no_fixture_matches_gets_the_generic_answers(
    db_session: Session, seeded: None, pipeline
) -> None:
    """P05 §5.3 rules 3 and 4, through the mocks' generic fallback.

    `make_owner_description`'s text is not in the fixture file, so the extractor
    reports a primary complaint of `OTHER` and the retriever returns passages
    scored 0.20 — under the 0.30 floor. The case is still triaged rather than
    failed, at LOW confidence, with both reasons recorded, which is what sends it
    to a reviewer instead of presenting it as supported.
    """
    case = make_case(db_session)
    make_owner_description(db_session, case=case)

    result = pipeline.run(case.id)

    assert result.succeeded
    recommendation = recommendation_of(db_session, case)
    assert recommendation is not None
    assert recommendation.category is VTLCategory.YELLOW
    assert recommendation.confidence is ConfidenceLevel.LOW
    assert set(recommendation.low_confidence_reasons) == {
        LOW_RETRIEVAL_SCORE,
        UNSUPPORTED_COMPLAINT,
    }
    assert recommendation.safety_floor_applied is False


# --- The failure paths (FR-15, NFR-09, IR-19) ----------------------------


def test_a_timeout_sends_the_case_to_manual_triage(
    db_session: Session, seeded: None, pipeline_factory
) -> None:
    case = make_demo_case(db_session, "DEMO_1")
    pipeline = pipeline_factory(mock_llm_behavior=MockLLMBehavior.TIMEOUT)

    result = pipeline.run(case.id)

    assert result.failure_reason is FailureReason.EXTRACTION_TIMEOUT
    assert status_of(db_session, case) is CaseStatus.MANUAL_TRIAGE_REQUIRED
    assert recommendation_of(db_session, case) is None
    assert audit_for(db_session, case)[-1].action == AuditAction.PIPELINE_FAILED.value


def test_the_red_flag_alert_is_written_before_any_model_call(
    db_session: Session, seeded: None, pipeline_factory
) -> None:
    """NFR-05, FR-12 — the reason step 3 commits.

    With extraction timing out, the alert row exists and no extraction row ever
    did: the alert cannot have been written after the model call, because the model
    call never produced anything.
    """
    case = make_demo_case(db_session, "DEMO_1")

    pipeline_factory(mock_llm_behavior=MockLLMBehavior.TIMEOUT).run(case.id)

    alerts = alerts_of(db_session, case)
    assert [alert.rule_code for alert in alerts] == ["MALE_CAT_NO_URINE"]
    assert alerts[0].min_category is VTLCategory.ORANGE
    assert extraction_of(db_session, case) is None


def test_the_alert_row_exists_by_the_time_the_extractor_is_called(
    db_session: Session, seeded: None, pipeline
) -> None:
    """NFR-05, FR-12, on the successful path.

    Asserted from inside the extraction stage rather than from the two rows'
    timestamps: `created_at` is `now()`, which in PostgreSQL is the *transaction*
    timestamp, and the whole test runs in one transaction — so the two would be
    equal here however the orchestrator was ordered. Wrapping the stage proves the
    ordering directly.
    """
    case = make_demo_case(db_session, "DEMO_1")
    seen: list[list[str]] = []

    class _Watching:
        model_id = pipeline.extractor.model_id
        prompt_version = pipeline.extractor.prompt_version
        last_latency_ms = 0

        def extract(self, text, species, signalment=None):
            seen.append([alert.rule_code for alert in alerts_of(db_session, case)])
            return pipeline.extractor.extract(text, species, signalment)

    replace(pipeline, extractor=_Watching()).run(case.id)

    assert seen == [["MALE_CAT_NO_URINE"]]
    assert extraction_of(db_session, case) is not None


def test_unusable_output_on_every_attempt_sends_the_case_to_manual_triage(
    db_session: Session, seeded: None, pipeline_factory
) -> None:
    """FR-15: validation fails, one retry, then manual triage."""
    case = make_demo_case(db_session, "DEMO_1")

    result = pipeline_factory(mock_llm_behavior=MockLLMBehavior.INVALID_JSON).run(case.id)

    assert result.failure_reason is FailureReason.EXTRACTION_INVALID_OUTPUT
    assert status_of(db_session, case) is CaseStatus.MANUAL_TRIAGE_REQUIRED
    assert extraction_of(db_session, case) is None


def test_a_first_attempt_failure_succeeds_on_the_retry(
    db_session: Session, seeded: None, pipeline_factory
) -> None:
    """FR-15, IR-19. One extraction row, not two: the failed attempt stored nothing."""
    case = make_demo_case(db_session, "DEMO_1")

    result = pipeline_factory(mock_llm_behavior=MockLLMBehavior.FLAKY).run(case.id)

    assert result.succeeded
    assert status_of(db_session, case) is CaseStatus.AWAITING_REVIEW
    stored = db_session.scalars(
        select(func.count())
        .select_from(ExtractionResult)
        .where(ExtractionResult.case_id == case.id)
    ).one()
    assert stored == 1


def test_a_slow_run_still_succeeds_and_records_the_latency(
    db_session: Session, seeded: None, pipeline_factory
) -> None:
    """`slow` means late, not timed out, and the delay shows up in `stage_ms`."""
    case = make_demo_case(db_session, "DEMO_1")

    result = pipeline_factory(mock_llm_behavior=MockLLMBehavior.SLOW).run(case.id)

    assert result.succeeded
    recommendation = recommendation_of(db_session, case)
    assert recommendation is not None
    assert recommendation.params["stage_ms"]["extract"] > 0


def test_demo_4_fails_on_its_own_without_changing_the_configuration(
    db_session: Session, seeded: None, pipeline
) -> None:
    """The walkthrough shows the failure path beside three working cases (FR-15)."""
    case = make_demo_case(db_session, "DEMO_4")

    result = pipeline.run(case.id)

    assert result.failure_reason is FailureReason.EXTRACTION_INVALID_OUTPUT
    assert status_of(db_session, case) is CaseStatus.MANUAL_TRIAGE_REQUIRED
    assert demo_cases()["DEMO_4"]["expected_status"] == CaseStatus.MANUAL_TRIAGE_REQUIRED.value


def test_a_run_with_no_knowledge_base_version_fails_rather_than_inventing_one(
    db_session: Session, pipeline
) -> None:
    """FR-22, FR-54. Nothing to retrieve from means nothing to cite.

    Deliberately not `seeded`: this is the un-seeded database. The red-flag rules
    are missing too, so the pre-screen's hit is skipped — which is the other half
    of the behaviour, an alert that cannot be stored must not lose the case.
    """
    case = make_demo_case(db_session, "DEMO_1")

    result = pipeline.run(case.id)

    assert result.failure_reason is FailureReason.KB_VERSION_MISSING
    assert status_of(db_session, case) is CaseStatus.MANUAL_TRIAGE_REQUIRED
    assert alerts_of(db_session, case) == []


def test_a_job_for_a_case_that_does_not_exist_is_reported_not_crashed(
    db_session: Session, seeded: None, pipeline
) -> None:
    result = pipeline.run(uuid.uuid4())

    assert result.failure_reason is FailureReason.CASE_NOT_FOUND
    assert result.status is None


def test_no_failure_path_leaves_a_case_in_processing(
    db_session: Session, seeded: None, pipeline_factory
) -> None:
    """NFR-09, stated once over every behaviour the mocks can simulate."""
    for behavior in MockLLMBehavior:
        case = make_demo_case(db_session, "DEMO_1")

        pipeline_factory(mock_llm_behavior=behavior).run(case.id)

        assert status_of(db_session, case) in (
            CaseStatus.AWAITING_REVIEW,
            CaseStatus.MANUAL_TRIAGE_REQUIRED,
        ), behavior


# --- Through the worker and the queue (ADR-08) ---------------------------


def test_the_worker_runs_a_queued_job_and_completes_it(
    db_session: Session, seeded: None, app_session_factory: sessionmaker, pipeline
) -> None:
    case = make_demo_case(db_session, "DEMO_1")
    job = JobQueue(db_session).enqueue(JobType.PIPELINE_RUN, case_id=case.id)
    db_session.flush()

    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    db_session.refresh(job)
    assert job.status is JobStatus.DONE
    assert job.attempts == 1
    assert job.payload == {STAGE_KEY: JobStage.DONE.value}
    assert status_of(db_session, case) is CaseStatus.AWAITING_REVIEW


def test_a_failed_run_marks_the_job_failed_with_the_reason(
    db_session: Session, seeded: None, app_session_factory: sessionmaker, pipeline_factory
) -> None:
    case = make_demo_case(db_session, "DEMO_1")
    job = JobQueue(db_session).enqueue(JobType.PIPELINE_RUN, case_id=case.id)
    db_session.flush()

    run_pending_jobs_once(
        app_session_factory, pipeline_factory(mock_llm_behavior=MockLLMBehavior.TIMEOUT)
    )

    db_session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith(FailureReason.EXTRACTION_TIMEOUT.value)
    assert job.payload == {STAGE_KEY: JobStage.FAILED.value}
    assert status_of(db_session, case) is CaseStatus.MANUAL_TRIAGE_REQUIRED


def test_recovery_requeues_a_stale_job_and_the_worker_then_runs_it(
    db_session: Session, seeded: None, app_session_factory: sessionmaker, pipeline
) -> None:
    """ADR-08, NFR-13: a crash mid-pipeline, then a restart."""
    case = make_demo_case(db_session, "DEMO_1")
    job = make_job(
        db_session,
        case=case,
        status=JobStatus.RUNNING,
        attempts=1,
        updated_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    assert JobQueue(db_session).recover_stale(older_than_minutes=2) == 1
    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    db_session.refresh(job)
    assert job.status is JobStatus.DONE
    # The first attempt is not forgotten.
    assert job.attempts == 2
    assert status_of(db_session, case) is CaseStatus.AWAITING_REVIEW


def test_a_second_run_adds_a_version_rather_than_overwriting(
    db_session: Session, seeded: None, pipeline
) -> None:
    """ADR-14. A re-run after recovery must not erase what a reviewer was shown."""
    case = make_demo_case(db_session, "DEMO_1")

    pipeline.run(case.id)
    pipeline.run(case.id)

    versions = list(
        db_session.scalars(
            select(Recommendation.version)
            .where(Recommendation.case_id == case.id)
            .order_by(Recommendation.version)
        )
    )
    assert versions == [1, 2]


# --- Privacy (CLAUDE.md §9, DR-04) ---------------------------------------


def test_no_description_or_owner_detail_reaches_the_audit_log_or_the_log(
    db_session: Session,
    seeded: None,
    pipeline,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The one test that reads every audit payload and every log record.

    The owner reference exists on this case, so the de-identifier is handed a name
    and a number — and neither may appear anywhere afterwards (DR-04, ADR-10).
    """
    case = make_demo_case(
        db_session, "DEMO_1", owner_name=OWNER_NAME, contact_number=CONTACT_NUMBER
    )
    spec = demo_cases()["DEMO_1"]
    secrets = [
        OWNER_NAME,
        CONTACT_NUMBER,
        spec["signalment"]["pet_name"],
        # A distinctive phrase from the description, and the matched text the
        # pre-screen reports.
        "nothing comes out",
        spec["mock_red_flags"][0]["matched_text"],
        spec["mock_draft"]["rationale"][:40],
    ]

    with caplog.at_level(logging.DEBUG):
        pipeline.run(case.id)

    audited = repr(
        [(entry.action, entry.before, entry.after) for entry in audit_for(db_session, case)]
    )
    logged = repr([record.getMessage() + repr(record.__dict__) for record in caplog.records])

    for secret in secrets:
        assert secret not in audited, secret
        assert secret not in logged, secret

    # The rationale is stored where it belongs, so the test above is about the log
    # and the audit trail, not about having dropped it.
    recommendation = recommendation_of(db_session, case)
    assert recommendation is not None
    assert recommendation.rationale == spec["mock_draft"]["rationale"]


def test_the_matched_text_is_stored_on_the_alert_but_not_audited(
    db_session: Session, seeded: None, pipeline
) -> None:
    """The reviewer needs the match; the permanent audit log does not (FR-43)."""
    case = make_demo_case(db_session, "DEMO_1")
    expected = demo_cases()["DEMO_1"]["mock_red_flags"][0]["matched_text"]

    pipeline.run(case.id)

    assert alerts_of(db_session, case)[0].matched_text == expected
    alert_entries = [
        entry
        for entry in audit_for(db_session, case)
        if entry.action == AuditAction.RED_FLAG_ALERT.value
    ]
    assert alert_entries[0].after == {
        "rule_code": "MALE_CAT_NO_URINE",
        "min_category": VTLCategory.ORANGE.value,
    }
