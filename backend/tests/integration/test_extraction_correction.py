"""`PATCH /cases/{id}/extraction` and the regeneration it queues (P07 §7.2, UC-09, FR-27).

Driven through the real endpoint and the real worker entry point
(`run_pending_jobs_once`), so what is asserted is a finished regeneration and not
a stub. The mock pipeline has no fixture for a corrected extraction, so a
regenerated recommendation is the generic YELLOW draft — which is what makes a
change of category visible without a model.

All data is fictitious (CLAUDE.md §9).
"""

import json
import threading
import uuid
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import MockLLMBehavior
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
    RedFlagRule,
    UserRole,
    VTLCategory,
    extraction_complaints,
)
from app.services.audit_service import AuditAction
from scripts.seed import seed
from tests.conftest import csrf_headers, make_demo_case, make_user, sign_in

CASES_URL = "/api/v1/cases"
PASSWORD = "Sampaguita2026"
GENERIC_CATEGORY = VTLCategory.YELLOW


class _Counting:
    """A stage that counts its calls and answers with the real mock."""

    model_id = "mock"
    prompt_version = "mock-0"
    last_latency_ms = 0

    def __init__(self, method: str, real: object) -> None:
        self.calls = 0
        self._method = method
        self._real = real
        setattr(self, method, self._call)

    def _call(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        return getattr(self._real, self._method)(*args, **kwargs)


def signed_in(client: TestClient, session: Session, role: UserRole):
    user = make_user(session, password=PASSWORD, role=role)
    sign_in(client, user.email, PASSWORD)
    return user


@pytest.fixture
def seeded(db_session: Session) -> None:
    seed(db_session)
    db_session.flush()


@pytest.fixture
def reviewer(api_client: TestClient, db_session: Session):
    return signed_in(api_client, db_session, UserRole.VETERINARY_REVIEWER)


@pytest.fixture
def triaged(db_session: Session, seeded: None, pipeline, app_session_factory: sessionmaker) -> Case:
    """`DEMO_3` run to completion: BLUE, recommendation v1, extraction v1."""
    case = make_demo_case(db_session, "DEMO_3")
    pipeline.run(case.id)
    run_pending_jobs_once(app_session_factory, pipeline)  # its SUGGEST_ACTIONS job
    db_session.expire_all()
    return case


def correct(client: TestClient, case: Case, body: dict[str, Any]) -> Any:
    return client.patch(
        f"{CASES_URL}/{case.id}/extraction", json=body, headers=csrf_headers(client)
    )


def regenerate_jobs(session: Session, case: Case) -> list[Job]:
    return list(
        session.scalars(
            select(Job)
            .where(Job.case_id == case.id, Job.type == JobType.REGENERATE)
            .order_by(Job.created_at)
        )
    )


def extractions(session: Session, case: Case) -> list[ExtractionResult]:
    return list(
        session.scalars(
            select(ExtractionResult)
            .where(ExtractionResult.case_id == case.id)
            .order_by(ExtractionResult.version)
        )
    )


def recommendations(session: Session, case: Case) -> list[Recommendation]:
    return list(
        session.scalars(
            select(Recommendation)
            .where(Recommendation.case_id == case.id)
            .order_by(Recommendation.version)
        )
    )


def status_of(session: Session, case: Case) -> CaseStatus:
    session.expire(case)
    return case.status


def audit_rows(session: Session, case: Case, action: AuditAction) -> list[AuditEntry]:
    return list(
        session.scalars(
            select(AuditEntry)
            .where(AuditEntry.entity_id == str(case.id), AuditEntry.action == action.value)
            .order_by(AuditEntry.id)
        )
    )


def regenerate(session_factory: sessionmaker, pipeline) -> int:
    return run_pending_jobs_once(session_factory, pipeline, max_jobs=1)


def rule_label(session: Session, code: str) -> str:
    return session.scalars(select(RedFlagRule.label).where(RedFlagRule.code == code)).one()


# --- Success: a new version, the original kept ----------------------------


def test_a_correction_is_accepted_and_queues_a_regeneration(
    api_client: TestClient, db_session: Session, reviewer, triaged: Case
) -> None:
    response = correct(api_client, triaged, {"onset_duration": "since yesterday morning"})

    assert response.status_code == 202
    assert response.json() == {
        "id": str(triaged.id),
        "case_no": triaged.case_no,
        "status": "PROCESSING",
        "extraction_version": 2,
        "changed_fields": ["onset_duration"],
    }
    assert status_of(db_session, triaged) is CaseStatus.PROCESSING
    (job,) = regenerate_jobs(db_session, triaged)
    assert job.status is JobStatus.QUEUED
    assert job.payload is not None
    assert job.payload["extraction_id"] == str(extractions(db_session, triaged)[1].id)


def test_the_original_extraction_is_preserved_and_a_new_version_is_stored(
    api_client: TestClient, db_session: Session, reviewer, triaged: Case
) -> None:
    (original,) = extractions(db_session, triaged)
    entities_before = json.loads(json.dumps(original.entities))

    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})

    db_session.expire_all()
    first, second = extractions(db_session, triaged)
    assert first.id == original.id
    assert first.entities == entities_before
    assert first.is_corrected is False and first.corrected_by is None
    assert second.version == 2
    assert second.is_corrected is True
    assert second.corrected_by == reviewer.id
    assert second.entities["onset_duration"] == "since yesterday morning"
    # Everything the reviewer left alone is carried over, evidence spans included.
    assert second.entities["evidence_spans"] == entities_before["evidence_spans"]
    assert second.entities["presenting_complaints"] == entities_before["presenting_complaints"]
    assert second.input_text == first.input_text


def test_changing_the_primary_complaint_stores_the_new_complaint_rows(
    api_client: TestClient, db_session: Session, reviewer, triaged: Case
) -> None:
    response = correct(
        api_client,
        triaged,
        {
            "presenting_complaints": [
                {"code": "URINARY_OBSTRUCTION", "is_primary": True},
                {"code": "SKIN_ITCH", "is_primary": False},
            ]
        },
    )

    assert response.status_code == 202
    assert response.json()["changed_fields"] == ["presenting_complaints"]
    _, second = extractions(db_session, triaged)
    rows = db_session.execute(
        select(extraction_complaints.c.complaint_code, extraction_complaints.c.is_primary).where(
            extraction_complaints.c.extraction_id == second.id
        )
    ).all()
    assert {(row.complaint_code, row.is_primary) for row in rows} == {
        ("URINARY_OBSTRUCTION", True),
        ("SKIN_ITCH", False),
    }


def test_the_audit_entry_lists_field_names_and_never_values(
    api_client: TestClient, db_session: Session, reviewer, triaged: Case
) -> None:
    correct(
        api_client,
        triaged,
        {
            "onset_duration": "since yesterday morning",
            "red_flags": ["a distinctive invented flag"],
        },
    )

    (entry,) = audit_rows(db_session, triaged, AuditAction.EXTRACTION_CORRECTED)
    assert entry.user_id == reviewer.id
    assert entry.role is UserRole.VETERINARY_REVIEWER
    assert entry.after is not None
    assert entry.after["changed_fields"] == ["onset_duration", "red_flags"]
    assert entry.after["extraction_version"] == 2
    assert entry.before == {
        "status": "AWAITING_REVIEW",
        "extraction_version": 1,
        "recommendation_version": 1,
    }
    serialised = json.dumps([entry.before, entry.after])
    assert "yesterday" not in serialised
    assert "distinctive" not in serialised


def test_a_sent_value_that_equals_the_stored_one_is_not_a_change(
    api_client: TestClient, db_session: Session, reviewer, triaged: Case
) -> None:
    (original,) = extractions(db_session, triaged)

    response = correct(
        api_client,
        triaged,
        {"onset_duration": original.entities["onset_duration"], "red_flags": ["x"]},
    )

    assert response.json()["changed_fields"] == ["red_flags"]


# --- Who and when ----------------------------------------------------------


@pytest.mark.parametrize("role", [UserRole.INTAKE_STAFF, UserRole.ADMINISTRATOR])
def test_only_a_veterinary_reviewer_may_correct(
    api_client: TestClient, db_session: Session, triaged: Case, role: UserRole
) -> None:
    signed_in(api_client, db_session, role)

    response = correct(api_client, triaged, {"onset_duration": "since yesterday"})

    assert response.status_code == 403
    assert len(extractions(db_session, triaged)) == 1
    assert regenerate_jobs(db_session, triaged) == []


def test_an_unauthenticated_correction_is_refused(
    api_client: TestClient, db_session: Session, triaged: Case
) -> None:
    response = api_client.patch(
        f"{CASES_URL}/{triaged.id}/extraction", json={"onset_duration": "since yesterday"}
    )

    assert response.status_code in (401, 403)
    assert len(extractions(db_session, triaged)) == 1


def test_an_unknown_case_is_not_found(api_client: TestClient, reviewer) -> None:
    response = api_client.patch(
        f"{CASES_URL}/{uuid.uuid4()}/extraction",
        json={"onset_duration": "since yesterday"},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 404


def test_a_second_press_while_regenerating_is_refused_and_queues_nothing(
    api_client: TestClient, db_session: Session, reviewer, triaged: Case
) -> None:
    assert correct(api_client, triaged, {"onset_duration": "since yesterday"}).status_code == 202

    second = correct(api_client, triaged, {"onset_duration": "since the day before"})

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "INVALID_TRANSITION"
    assert len(regenerate_jobs(db_session, triaged)) == 1
    assert len(extractions(db_session, triaged)) == 2


def test_a_decided_case_cannot_be_corrected(
    api_client: TestClient, db_session: Session, reviewer, triaged: Case
) -> None:
    decision = api_client.post(
        f"{CASES_URL}/{triaged.id}/decision",
        json={"type": "CONFIRM"},
        headers=csrf_headers(api_client),
    )
    assert decision.status_code == 200

    response = correct(api_client, triaged, {"onset_duration": "since yesterday"})

    assert response.status_code == 409
    assert len(extractions(db_session, triaged)) == 1
    assert status_of(db_session, triaged) is CaseStatus.CONFIRMED


def test_a_case_with_no_recommendation_cannot_be_corrected(
    api_client: TestClient, db_session: Session, reviewer, seeded: None, pipeline_factory
) -> None:
    case = make_demo_case(db_session, "DEMO_3")
    pipeline_factory(mock_llm_behavior=MockLLMBehavior.TIMEOUT).run(case.id)
    assert status_of(db_session, case) is CaseStatus.MANUAL_TRIAGE_REQUIRED

    response = correct(api_client, case, {"onset_duration": "since yesterday"})

    assert response.status_code == 409


# --- Validation ------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "field"),
    [
        (
            {"presenting_complaints": [{"code": "NOT_A_COMPLAINT", "is_primary": True}]},
            "presenting_complaints",
        ),
        ({"presenting_complaints": []}, "presenting_complaints"),
        (
            {
                "presenting_complaints": [
                    {"code": "SKIN_ITCH", "is_primary": False},
                    {"code": "COLLAPSE", "is_primary": False},
                ]
            },
            "presenting_complaints",
        ),
        (
            {
                "presenting_complaints": [
                    {"code": "SKIN_ITCH", "is_primary": True},
                    {"code": "COLLAPSE", "is_primary": True},
                ]
            },
            "presenting_complaints",
        ),
        (
            {
                "presenting_complaints": [
                    {"code": "SKIN_ITCH", "is_primary": True},
                    {"code": "SKIN_ITCH", "is_primary": False},
                ]
            },
            "presenting_complaints",
        ),
        ({"presenting_complaints": None}, "presenting_complaints"),
        ({"onset_duration": "x" * 301}, "onset_duration"),
        ({"associated_signs": ["ok", "y" * 201]}, "associated_signs.1"),
        ({"red_flags": [f"flag {n}" for n in range(21)]}, "red_flags"),
        ({"species": "CAT"}, "species"),
        ({"evidence_spans": []}, "evidence_spans"),
    ],
)
def test_an_unacceptable_correction_names_the_field(
    api_client: TestClient,
    db_session: Session,
    reviewer,
    triaged: Case,
    body: dict[str, Any],
    field: str,
) -> None:
    response = correct(api_client, triaged, body)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["field"] == field
    assert len(extractions(db_session, triaged)) == 1
    assert regenerate_jobs(db_session, triaged) == []
    assert status_of(db_session, triaged) is CaseStatus.AWAITING_REVIEW


def test_a_correction_that_changes_nothing_is_refused(
    api_client: TestClient, db_session: Session, reviewer, triaged: Case
) -> None:
    (original,) = extractions(db_session, triaged)

    for body in ({}, {"onset_duration": original.entities["onset_duration"]}):
        response = correct(api_client, triaged, body)
        assert response.status_code == 422

    assert len(extractions(db_session, triaged)) == 1


def test_a_blank_text_value_clears_the_field(
    api_client: TestClient, db_session: Session, reviewer, triaged: Case
) -> None:
    response = correct(api_client, triaged, {"onset_duration": "   "})

    assert response.json()["changed_fields"] == ["onset_duration"]
    assert extractions(db_session, triaged)[1].entities["onset_duration"] is None


# --- The regeneration ------------------------------------------------------


def test_regeneration_stores_the_next_version_and_keeps_the_first(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    reviewer,
    triaged: Case,
) -> None:
    (first,) = recommendations(db_session, triaged)
    assert first.category is VTLCategory.BLUE
    category, rationale = first.category, first.rationale
    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})

    assert regenerate(app_session_factory, pipeline) == 1

    db_session.expire_all()
    v1, v2 = recommendations(db_session, triaged)
    assert (v1.version, v2.version) == (1, 2)
    assert (v1.category, v1.rationale) == (category, rationale)
    assert v2.category is GENERIC_CATEGORY
    assert v2.extraction_id == extractions(db_session, triaged)[1].id
    assert v1.extraction_id == extractions(db_session, triaged)[0].id
    assert v2.params is not None and v2.params["regeneration"] is True
    assert status_of(db_session, triaged) is CaseStatus.AWAITING_REVIEW
    (job,) = regenerate_jobs(db_session, triaged)
    assert job.status is JobStatus.DONE


def test_regeneration_does_not_deidentify_screen_or_extract(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    reviewer,
    triaged: Case,
) -> None:
    spies = {
        "deidentifier": _Counting("deidentify", pipeline.deidentifier),
        "red_flag_screener": _Counting("screen", pipeline.red_flag_screener),
        "extractor": _Counting("extract", pipeline.extractor),
        "retriever": _Counting("retrieve", pipeline.retriever),
        "generator": _Counting("generate", pipeline.generator),
    }
    spied = replace(pipeline, **spies)
    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})

    regenerate(app_session_factory, spied)

    assert spies["deidentifier"].calls == 0
    assert spies["red_flag_screener"].calls == 0
    assert spies["extractor"].calls == 0
    assert spies["retriever"].calls == 1
    assert spies["generator"].calls == 1
    assert len(recommendations(db_session, triaged)) == 2


def test_a_reviewer_added_red_flag_that_names_a_rule_raises_the_category(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    reviewer,
    triaged: Case,
) -> None:
    label = rule_label(db_session, "NOT_BREATHING")
    correct(
        api_client,
        triaged,
        {
            "presenting_complaints": [{"code": "RESPIRATORY_DISTRESS", "is_primary": True}],
            "red_flags": [label],
        },
    )

    regenerate(app_session_factory, pipeline)

    db_session.expire_all()
    _, v2 = recommendations(db_session, triaged)
    assert v2.category is VTLCategory.RED
    assert v2.safety_floor_applied is True
    assert v2.safety_floor_rule_codes == ["NOT_BREATHING"]


def test_a_red_flag_that_matches_no_rule_label_is_ignored_for_the_floor(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    reviewer,
    triaged: Case,
) -> None:
    """The match is on the exact rule label: a paraphrase is only text."""
    label = rule_label(db_session, "NOT_BREATHING")
    correct(
        api_client,
        triaged,
        {"red_flags": [label.lower(), f"{label} and more", "dog is not breathing"]},
    )

    regenerate(app_session_factory, pipeline)

    db_session.expire_all()
    _, v2 = recommendations(db_session, triaged)
    assert v2.category is GENERIC_CATEGORY
    assert v2.safety_floor_applied is False
    assert v2.safety_floor_rule_codes == []


def test_the_stored_alerts_still_raise_the_floor_after_a_regeneration(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    reviewer,
    seeded: None,
) -> None:
    """`DEMO_1` has a stored MALE_CAT_NO_URINE alert (ORANGE); the generic draft is YELLOW."""
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    run_pending_jobs_once(app_session_factory, pipeline)
    db_session.expire_all()
    correct(api_client, case, {"onset_duration": "since yesterday evening"})

    regenerate(app_session_factory, pipeline)

    db_session.expire_all()
    _, v2 = recommendations(db_session, case)
    assert v2.category is VTLCategory.ORANGE
    assert v2.safety_floor_applied is True
    assert v2.safety_floor_rule_codes == ["MALE_CAT_NO_URINE"]


def test_the_new_version_gets_its_own_suggested_actions_job(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    reviewer,
    triaged: Case,
) -> None:
    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})

    run_pending_jobs_once(app_session_factory, pipeline)  # REGENERATE, then SUGGEST_ACTIONS

    db_session.expire_all()
    v1, v2 = recommendations(db_session, triaged)
    jobs = list(
        db_session.scalars(
            select(Job).where(Job.case_id == triaged.id, Job.type == JobType.SUGGEST_ACTIONS)
        )
    )
    assert {job.payload["recommendation_id"] for job in jobs if job.payload} == {
        str(v1.id),
        str(v2.id),
    }
    assert v2.actions_status.value == "READY"


def test_decisions_apply_to_the_latest_version_only(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    reviewer,
    triaged: Case,
) -> None:
    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})

    # While the new version is being made nothing can be decided on the old one.
    blocked = api_client.post(
        f"{CASES_URL}/{triaged.id}/decision",
        json={"type": "CONFIRM"},
        headers=csrf_headers(api_client),
    )
    assert blocked.status_code == 409

    regenerate(app_session_factory, pipeline)
    decision = api_client.post(
        f"{CASES_URL}/{triaged.id}/decision",
        json={"type": "CONFIRM"},
        headers=csrf_headers(api_client),
    )

    assert decision.status_code == 200
    assert decision.json()["final_category"] == GENERIC_CATEGORY.value
    (entry,) = audit_rows(db_session, triaged, AuditAction.DECISION_RECORDED)
    assert entry.before is not None
    assert entry.before["recommendation_version"] == 2
    assert entry.before["category"] == GENERIC_CATEGORY.value


def test_a_rerun_of_the_same_job_after_a_crash_adds_nothing(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    reviewer,
    triaged: Case,
) -> None:
    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})
    regenerate(app_session_factory, pipeline)
    # The worker died after the recommendation was stored and before the job was
    # marked done; the recovery sweep puts it back in the queue (ADR-08).
    (job,) = regenerate_jobs(db_session, triaged)
    job.status = JobStatus.QUEUED
    triaged.status = CaseStatus.PROCESSING
    db_session.flush()

    # Two jobs are queued: this one and the SUGGEST_ACTIONS job its first run
    # enqueued. Both were created in one transaction, so which is claimed first is
    # not defined; allowing two makes the test about the re-run, not the order.
    run_pending_jobs_once(app_session_factory, pipeline, max_jobs=2)

    db_session.expire_all()
    assert len(recommendations(db_session, triaged)) == 2
    assert status_of(db_session, triaged) is CaseStatus.AWAITING_REVIEW


def test_a_regeneration_never_moves_a_decided_case(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    reviewer,
    triaged: Case,
) -> None:
    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})
    # A job left over for a case somebody then decided by hand (NFR-11).
    triaged.status = CaseStatus.MANUALLY_TRIAGED
    db_session.flush()

    regenerate(app_session_factory, pipeline)

    db_session.expire_all()
    assert len(recommendations(db_session, triaged)) == 1
    assert status_of(db_session, triaged) is CaseStatus.MANUALLY_TRIAGED


# --- Failure: the previous recommendation stays ---------------------------


@pytest.mark.parametrize(
    ("behavior", "reason"),
    [
        (MockLLMBehavior.TIMEOUT, "LLM_TIMEOUT"),
        (MockLLMBehavior.INVALID_JSON, "LLM_INVALID_OUTPUT"),
    ],
)
def test_a_failed_regeneration_keeps_the_previous_recommendation_decidable(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline_factory,
    reviewer,
    triaged: Case,
    behavior: MockLLMBehavior,
    reason: str,
) -> None:
    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})

    regenerate(app_session_factory, pipeline_factory(mock_llm_behavior=behavior))

    db_session.expire_all()
    assert status_of(db_session, triaged) is CaseStatus.AWAITING_REVIEW
    (only,) = recommendations(db_session, triaged)
    assert only.version == 1
    (job,) = regenerate_jobs(db_session, triaged)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None and job.last_error.startswith(reason)
    (entry,) = audit_rows(db_session, triaged, AuditAction.REGENERATE_FAILED)
    assert entry.after is not None and entry.after["reason"] == reason

    body = api_client.get(f"{CASES_URL}/{triaged.id}").json()
    assert body["status"] == "AWAITING_REVIEW"
    assert body["recommendation"]["version"] == 1
    assert body["permissions"]["can_decide"] is True
    assert body["regeneration_failure"]["reason_code"] == reason
    assert "unchanged" in body["regeneration_failure"]["message"]
    # The case was not sent to manual triage.
    assert body["failure"] is None


def test_saving_again_after_a_failure_retries_without_a_duplicate_extraction(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    pipeline_factory,
    reviewer,
    triaged: Case,
) -> None:
    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})
    regenerate(app_session_factory, pipeline_factory(mock_llm_behavior=MockLLMBehavior.TIMEOUT))

    retry = correct(api_client, triaged, {})

    assert retry.status_code == 202
    assert retry.json()["changed_fields"] == []
    assert retry.json()["extraction_version"] == 2
    assert len(extractions(db_session, triaged)) == 2
    regenerate(app_session_factory, pipeline)

    db_session.expire_all()
    assert len(recommendations(db_session, triaged)) == 2
    assert status_of(db_session, triaged) is CaseStatus.AWAITING_REVIEW
    body = api_client.get(f"{CASES_URL}/{triaged.id}").json()
    assert body["regeneration_failure"] is None
    assert body["recommendation"]["version"] == 2


def test_a_regeneration_over_its_budget_leaves_the_previous_recommendation_standing(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    reviewer,
    triaged: Case,
) -> None:
    gate = threading.Event()
    slow = replace(pipeline, retriever=_Gated(pipeline.retriever, gate))
    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})

    try:
        run_pending_jobs_once(app_session_factory, slow, max_jobs=1, budget_s=0.3)
    finally:
        gate.set()

    db_session.expire_all()
    assert status_of(db_session, triaged) is CaseStatus.AWAITING_REVIEW
    assert len(recommendations(db_session, triaged)) == 1
    (job,) = regenerate_jobs(db_session, triaged)
    assert job.status is JobStatus.FAILED
    (entry,) = audit_rows(db_session, triaged, AuditAction.REGENERATE_FAILED)
    assert entry.after is not None and entry.after["reason"] == "LLM_TIMEOUT"


class _Gated:
    """A retriever that does not answer until released."""

    model_id = "mock"
    prompt_version = "mock-0"
    last_latency_ms = 0

    def __init__(self, real: Any, gate: threading.Event) -> None:
        self._real = real
        self._gate = gate

    def retrieve(self, *args: Any, **kwargs: Any) -> Any:
        self._gate.wait(timeout=10)
        return self._real.retrieve(*args, **kwargs)


# --- What the case detail reports ------------------------------------------


def test_the_detail_lists_every_version_and_marks_the_current_one(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    reviewer,
    triaged: Case,
) -> None:
    before = api_client.get(f"{CASES_URL}/{triaged.id}").json()
    assert [v["version"] for v in before["recommendation_versions"]] == [1]
    assert before["recommendation_versions"][0]["is_current"] is True

    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})
    regenerate(app_session_factory, pipeline)
    body = api_client.get(f"{CASES_URL}/{triaged.id}").json()

    assert [
        (v["version"], v["category"], v["is_current"]) for v in body["recommendation_versions"]
    ] == [
        (1, "BLUE", False),
        (2, GENERIC_CATEGORY.value, True),
    ]
    assert body["recommendation"]["version"] == 2
    assert body["extraction"]["version"] == 2
    assert body["extraction"]["is_corrected"] is True
    assert body["extraction"]["corrected_by_name"] == reviewer.full_name


def test_can_regenerate_follows_role_and_status(
    api_client: TestClient, db_session: Session, reviewer, triaged: Case
) -> None:
    url = f"{CASES_URL}/{triaged.id}"
    assert api_client.get(url).json()["permissions"]["can_regenerate"] is True

    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})
    assert api_client.get(url).json()["permissions"]["can_regenerate"] is False


@pytest.mark.parametrize("role", [UserRole.INTAKE_STAFF, UserRole.ADMINISTRATOR])
def test_other_roles_never_see_can_regenerate(
    api_client: TestClient, db_session: Session, triaged: Case, role: UserRole
) -> None:
    signed_in(api_client, db_session, role)

    assert (
        api_client.get(f"{CASES_URL}/{triaged.id}").json()["permissions"]["can_regenerate"] is False
    )


@pytest.mark.parametrize(
    "role", [UserRole.VETERINARY_REVIEWER, UserRole.INTAKE_STAFF, UserRole.ADMINISTRATOR]
)
def test_an_older_version_can_be_read_by_every_role(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    triaged: Case,
    role: UserRole,
) -> None:
    reviewer_user = signed_in(api_client, db_session, UserRole.VETERINARY_REVIEWER)
    assert reviewer_user.role is UserRole.VETERINARY_REVIEWER
    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})
    regenerate(app_session_factory, pipeline)
    if role is not UserRole.VETERINARY_REVIEWER:
        signed_in(api_client, db_session, role)

    old = api_client.get(f"{CASES_URL}/{triaged.id}/recommendations/1")
    current = api_client.get(f"{CASES_URL}/{triaged.id}/recommendations/2")

    assert old.status_code == 200
    body = old.json()
    assert body["is_current"] is False
    assert body["extraction_version"] == 1
    assert body["recommendation"]["version"] == 1
    assert body["recommendation"]["category"] == "BLUE"
    assert body["references"], "the passages version 1 was made from are kept"
    assert body["configuration"]["model_id"]
    assert current.json()["is_current"] is True
    assert current.json()["extraction_version"] == 2


def test_an_unknown_version_is_not_found(api_client: TestClient, reviewer, triaged: Case) -> None:
    assert api_client.get(f"{CASES_URL}/{triaged.id}/recommendations/9").status_code == 404
    assert api_client.get(f"{CASES_URL}/{uuid.uuid4()}/recommendations/1").status_code == 404


def test_the_status_endpoint_reports_a_regeneration_in_progress(
    api_client: TestClient, db_session: Session, reviewer, triaged: Case
) -> None:
    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})

    body = api_client.get(f"{CASES_URL}/{triaged.id}/status").json()

    assert body["status"] == "PROCESSING"
    assert body["pipeline_stage"] == "queued"


def test_the_timeline_records_the_correction_and_the_regeneration(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    reviewer,
    triaged: Case,
) -> None:
    correct(api_client, triaged, {"onset_duration": "since yesterday morning"})
    regenerate(app_session_factory, pipeline)

    items = api_client.get(f"{CASES_URL}/{triaged.id}/audit").json()["items"]

    by_action = {item["action"]: item for item in items}
    assert by_action["EXTRACTION_CORRECTED"]["label"] == "Extraction corrected by a reviewer"
    assert by_action["EXTRACTION_CORRECTED"]["details"] == "Extraction v2 · changed: onset_duration"
    assert by_action["RECOMMENDATION_REGENERATED"]["label"].startswith("Recommendation regenerated")
    assert GENERIC_CATEGORY.value in by_action["RECOMMENDATION_REGENERATED"]["details"]


def test_nothing_in_the_log_or_the_extraction_count_changes_for_a_refused_request(
    api_client: TestClient, db_session: Session, reviewer, triaged: Case
) -> None:
    before = db_session.scalar(select(func.count(AuditEntry.id)))

    correct(api_client, triaged, {"presenting_complaints": []})

    assert db_session.scalar(select(func.count(AuditEntry.id))) == before
