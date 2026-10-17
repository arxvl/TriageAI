"""`POST /cases/{id}/decision` — the human-in-the-loop decision (FR-32..FR-35).

The safety tests for this subphase (CLAUDE.md §10): who may decide, which
decisions a case's status allows, what a decision records, and the FR-48
guarantee that a recorded decision is never edited.

Every pet and description is invented (CLAUDE.md §9).
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import MockLLMBehavior
from app.jobs.worker import run_pending_jobs_once
from app.models import (
    ActionSource,
    ActionStatus,
    ActionSuggestion,
    AdjustReason,
    Case,
    CaseStatus,
    DecisionDirection,
    DecisionType,
    FinalAction,
    Recommendation,
    StaffDecision,
    User,
    UserRole,
    VTLCategory,
)
from app.services.audit_service import AuditAction
from scripts.seed import URGENCY_ACTIONS, seed
from tests.conftest import audit_actions, csrf_headers, make_demo_case, make_user, sign_in

CASES_URL = "/api/v1/cases"
PASSWORD = "Sampaguita2026"

SEEDED_BASELINE = {category: list(actions) for category, _, actions in URGENCY_ACTIONS}


def signed_in(client: TestClient, session: Session, role: UserRole) -> User:
    user = make_user(session, password=PASSWORD, role=role)
    sign_in(client, user.email, PASSWORD)
    return user


@pytest.fixture
def reviewer(api_client: TestClient, db_session: Session) -> User:
    """The signed-in Veterinary Reviewer, for the tests that assert on them."""
    return signed_in(api_client, db_session, UserRole.VETERINARY_REVIEWER)


@pytest.fixture
def reviewer_client(api_client: TestClient, reviewer: User) -> TestClient:
    """The client every decision test posts through: signed in as a reviewer."""
    return api_client


@pytest.fixture
def awaiting_review(db_session: Session, pipeline, app_session_factory: sessionmaker) -> Case:
    """`DEMO_1`, run through to `AWAITING_REVIEW` with ORANGE recommended."""
    seed(db_session)
    db_session.flush()
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    run_pending_jobs_once(app_session_factory, pipeline)
    return case


@pytest.fixture
def manual_triage_required(
    db_session: Session, pipeline_factory, app_session_factory: sessionmaker
) -> Case:
    """A case whose AI processing failed, so it has no recommendation (NFR-09)."""
    seed(db_session)
    db_session.flush()
    case = make_demo_case(db_session, "DEMO_1")
    pipeline_factory(mock_llm_behavior=MockLLMBehavior.TIMEOUT).run(case.id)
    return case


def decide(client: TestClient, case: Case, **body: Any) -> Any:
    return client.post(f"{CASES_URL}/{case.id}/decision", json=body, headers=csrf_headers(client))


def error_of(response: Any) -> dict[str, str]:
    return response.json()["error"]


def status_of(session: Session, case: Case) -> CaseStatus:
    return session.scalars(select(Case.status).where(Case.id == case.id)).one()


def decisions_of(session: Session, case: Case) -> list[StaffDecision]:
    return list(
        session.scalars(
            select(StaffDecision)
            .where(StaffDecision.case_id == case.id)
            .order_by(StaffDecision.decided_at, StaffDecision.id)
        )
    )


def final_actions_of(session: Session, case: Case) -> list[FinalAction]:
    return list(
        session.scalars(
            select(FinalAction).where(FinalAction.case_id == case.id).order_by(FinalAction.rank)
        )
    )


# --- Each decision type succeeds ------------------------------------------


def test_confirming_records_the_recommended_category(
    reviewer_client: TestClient, db_session: Session, reviewer: User, awaiting_review: Case
) -> None:
    """FR-32. The category comes from the recommendation, not the request."""
    response = decide(reviewer_client, awaiting_review, type="CONFIRM")

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == DecisionType.CONFIRM.value
    assert body["final_category"] == VTLCategory.ORANGE.value
    assert body["target_minutes"] == 15
    assert body["direction"] == DecisionDirection.SAME.value
    assert body["status"] == CaseStatus.CONFIRMED.value
    assert body["decided_by_name"] == reviewer.full_name
    assert status_of(db_session, awaiting_review) is CaseStatus.CONFIRMED


def test_confirming_ignores_a_category_the_client_sends(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """A "confirmation" that quietly disagreed with the thing it confirms would
    make the stored agreement rate meaningless."""
    response = decide(reviewer_client, awaiting_review, type="CONFIRM", final_category="BLUE")

    assert response.status_code == 200
    assert response.json()["final_category"] == VTLCategory.ORANGE.value
    assert decisions_of(db_session, awaiting_review)[0].final_category is VTLCategory.ORANGE


def test_adjusting_up_records_the_reason_and_the_direction(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """FR-33, BR-03: the staff decision prevails and the reason is recorded."""
    response = decide(
        reviewer_client,
        awaiting_review,
        type="ADJUST",
        final_category="RED",
        reason_code="CONDITION_DIFFERS_ON_ARRIVAL",
        reason_text="On arrival: abdomen painful, cat weak and lying down.",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["final_category"] == VTLCategory.RED.value
    assert body["direction"] == DecisionDirection.UP.value
    assert body["reason_code"] == AdjustReason.CONDITION_DIFFERS_ON_ARRIVAL.value
    assert body["status"] == CaseStatus.ADJUSTED.value
    assert status_of(db_session, awaiting_review) is CaseStatus.ADJUSTED


def test_adjusting_down_records_a_down_triage(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    response = decide(
        reviewer_client,
        awaiting_review,
        type="ADJUST",
        final_category="GREEN",
        reason_code="RECOMMENDATION_TOO_HIGH",
    )

    assert response.status_code == 200
    assert response.json()["direction"] == DecisionDirection.DOWN.value


def test_manual_triage_from_a_failed_case_needs_a_note(
    reviewer_client: TestClient, db_session: Session, manual_triage_required: Case
) -> None:
    """FR-34: the reviewer assigns the category by hand and says why."""
    assert status_of(db_session, manual_triage_required) is CaseStatus.MANUAL_TRIAGE_REQUIRED

    response = decide(
        reviewer_client,
        manual_triage_required,
        type="MANUAL",
        final_category="ORANGE",
        note="AI unavailable; triaged on the VTL urinary discriminators.",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["final_category"] == VTLCategory.ORANGE.value
    # No recommendation to move away from, so there is no direction (FR-46).
    assert body["direction"] == DecisionDirection.NONE.value
    assert body["status"] == CaseStatus.MANUALLY_TRIAGED.value
    assert status_of(db_session, manual_triage_required) is CaseStatus.MANUALLY_TRIAGED


def test_manual_triage_is_available_on_a_perfectly_good_recommendation(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """ADR-15 §4: at any time, not only after a failure."""
    response = decide(
        reviewer_client,
        awaiting_review,
        type="MANUAL",
        final_category="YELLOW",
        note="Outside the scope the system should be triaging.",
    )

    assert response.status_code == 200
    assert status_of(db_session, awaiting_review) is CaseStatus.MANUALLY_TRIAGED


def test_the_note_sent_with_a_decision_becomes_a_clinical_note(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    decide(
        reviewer_client,
        awaiting_review,
        type="MANUAL",
        final_category="YELLOW",
        note="Triaged by hand on arrival.",
    )

    notes = reviewer_client.get(f"{CASES_URL}/{awaiting_review.id}").json()["notes"]

    assert [note["text"] for note in notes] == ["Triaged by hand on arrival."]


# --- Invalid transitions are 409 ------------------------------------------


def test_confirming_a_case_that_is_still_processing_is_409(
    reviewer_client: TestClient, db_session: Session, reviewer: User
) -> None:
    seed(db_session)
    case = make_demo_case(db_session, "DEMO_1")
    db_session.flush()

    response = decide(reviewer_client, case, type="CONFIRM")

    assert response.status_code == 409
    assert error_of(response)["code"] == "INVALID_TRANSITION"


def test_confirming_a_case_with_no_recommendation_is_409(
    reviewer_client: TestClient, reviewer: User, manual_triage_required: Case
) -> None:
    """There is no AI category to accept; the message points at manual triage."""
    response = decide(reviewer_client, manual_triage_required, type="CONFIRM")

    assert response.status_code == 409
    assert "manual triage" in error_of(response)["message"]


def test_a_second_plain_decision_is_409_and_asks_for_an_amendment(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """FR-48: a decided case is changed by amendment, never by replacement."""
    assert decide(reviewer_client, awaiting_review, type="CONFIRM").status_code == 200

    response = decide(
        reviewer_client,
        awaiting_review,
        type="ADJUST",
        final_category="RED",
        reason_code="SIGN_NOT_CAPTURED",
    )

    assert response.status_code == 409
    assert error_of(response)["code"] == "AMENDMENT_REQUIRED"
    assert len(decisions_of(db_session, awaiting_review)) == 1


def test_a_closed_case_cannot_be_decided(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    decide(reviewer_client, awaiting_review, type="CONFIRM")
    reviewer_client.post(
        f"{CASES_URL}/{awaiting_review.id}/close", headers=csrf_headers(reviewer_client)
    )

    response = decide(
        reviewer_client,
        awaiting_review,
        type="ADJUST",
        final_category="RED",
        reason_code="SIGN_NOT_CAPTURED",
        amends_id=str(decisions_of(db_session, awaiting_review)[0].id),
    )

    assert response.status_code == 409
    assert "closed" in error_of(response)["message"].lower()


def test_a_case_that_does_not_exist_is_404(reviewer_client: TestClient, reviewer: User) -> None:
    response = reviewer_client.post(
        f"{CASES_URL}/00000000-0000-0000-0000-000000000000/decision",
        json={"type": "CONFIRM"},
        headers=csrf_headers(reviewer_client),
    )

    assert response.status_code == 404


# --- Fields that do not agree are 422 -------------------------------------


def test_adjusting_without_a_reason_is_422(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """BR-03. The reason is what makes the disagreement analysable."""
    response = decide(reviewer_client, awaiting_review, type="ADJUST", final_category="RED")

    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "VALIDATION_ERROR"
    assert error["field"] == "reason_code"
    assert decisions_of(db_session, awaiting_review) == []
    assert status_of(db_session, awaiting_review) is CaseStatus.AWAITING_REVIEW


def test_adjusting_to_the_recommended_category_is_422(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    """Not a disagreement, so it would pollute the direction statistics. The
    message points the reviewer at Confirm instead."""
    response = decide(
        reviewer_client,
        awaiting_review,
        type="ADJUST",
        final_category="ORANGE",
        reason_code="SIGN_NOT_CAPTURED",
    )

    assert response.status_code == 422
    error = error_of(response)
    assert error["field"] == "final_category"
    assert "Confirm" in error["message"]


def test_adjusting_without_a_category_is_422(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    response = decide(
        reviewer_client, awaiting_review, type="ADJUST", reason_code="SIGN_NOT_CAPTURED"
    )

    assert response.status_code == 422
    assert error_of(response)["field"] == "final_category"


def test_the_reason_other_requires_the_detail(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    """The point of `OTHER` is the free text; without it the row says nothing."""
    response = decide(
        reviewer_client,
        awaiting_review,
        type="ADJUST",
        final_category="RED",
        reason_code="OTHER",
    )

    assert response.status_code == 422
    assert error_of(response)["field"] == "reason_text"


def test_manual_triage_without_a_note_is_422(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    """FR-34 requires the note: a category assigned by hand with no reason
    recorded is exactly the gap the audit trail exists to close."""
    response = decide(reviewer_client, awaiting_review, type="MANUAL", final_category="YELLOW")

    assert response.status_code == 422
    assert error_of(response)["field"] == "note"


def test_an_unknown_reason_code_is_422(reviewer_client: TestClient, awaiting_review: Case) -> None:
    """Migration 0004 made `reason_code` an enum; the API rejects before the
    database has to."""
    response = decide(
        reviewer_client,
        awaiting_review,
        type="ADJUST",
        final_category="RED",
        reason_code="BECAUSE_I_SAID_SO",
    )

    assert response.status_code == 422
    assert error_of(response)["field"] == "reason_code"


def test_a_blank_note_counts_as_no_note(reviewer_client: TestClient, awaiting_review: Case) -> None:
    """An untouched textarea arrives as "", which is not a reason for a manual
    triage."""
    response = decide(
        reviewer_client,
        awaiting_review,
        type="MANUAL",
        final_category="YELLOW",
        note="   ",
    )

    assert response.status_code == 422
    assert error_of(response)["field"] == "note"


# --- Amendments (FR-48) ---------------------------------------------------


def test_an_amendment_keeps_the_original_decision_exactly_as_written(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """The guarantee ADR-12 rests on: a correction adds a row, never edits one."""
    decide(reviewer_client, awaiting_review, type="CONFIRM")
    original = decisions_of(db_session, awaiting_review)[0]
    original_values = (
        original.id,
        original.type,
        original.final_category,
        original.reason_code,
        original.decided_at,
    )

    response = decide(
        reviewer_client,
        awaiting_review,
        type="ADJUST",
        final_category="RED",
        reason_code="CONDITION_DIFFERS_ON_ARRIVAL",
        amends_id=str(original.id),
    )

    assert response.status_code == 200
    assert response.json()["amends_id"] == str(original.id)

    db_session.expire_all()
    rows = decisions_of(db_session, awaiting_review)
    assert len(rows) == 2
    assert (
        rows[0].id,
        rows[0].type,
        rows[0].final_category,
        rows[0].reason_code,
        rows[0].decided_at,
    ) == original_values
    assert rows[1].amends_id == original.id
    assert status_of(db_session, awaiting_review) is CaseStatus.ADJUSTED


def test_an_amendment_needs_a_reason(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """The record has to say why the earlier decision was superseded."""
    decide(reviewer_client, awaiting_review, type="CONFIRM")
    original = decisions_of(db_session, awaiting_review)[0]

    response = decide(
        reviewer_client,
        awaiting_review,
        type="CONFIRM",
        amends_id=str(original.id),
    )

    assert response.status_code == 422
    assert error_of(response)["field"] == "reason_code"


def test_an_amendment_cannot_point_at_another_case_s_decision(
    reviewer_client: TestClient,
    db_session: Session,
    awaiting_review: Case,
    pipeline,
    app_session_factory: sessionmaker,
) -> None:
    """So a malformed request cannot attach one patient's correction to
    another's record."""
    other = make_demo_case(db_session, "DEMO_3")
    pipeline.run(other.id)
    run_pending_jobs_once(app_session_factory, pipeline)
    decide(reviewer_client, other, type="CONFIRM")
    other_decision = decisions_of(db_session, other)[0]

    response = decide(
        reviewer_client,
        awaiting_review,
        type="ADJUST",
        final_category="RED",
        reason_code="SIGN_NOT_CAPTURED",
        amends_id=str(other_decision.id),
    )

    assert response.status_code == 422
    assert error_of(response)["field"] == "amends_id"


def test_there_is_nothing_to_amend_before_a_decision(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    response = decide(
        reviewer_client,
        awaiting_review,
        type="CONFIRM",
        reason_code="SIGN_NOT_CAPTURED",
        amends_id="00000000-0000-0000-0000-000000000000",
    )

    assert response.status_code == 422
    assert error_of(response)["field"] == "amends_id"


# --- Authorization (FR-35, BR-02) -----------------------------------------


@pytest.mark.parametrize("role", [UserRole.INTAKE_STAFF, UserRole.ADMINISTRATOR])
def test_only_a_veterinary_reviewer_may_decide(
    api_client: TestClient, db_session: Session, awaiting_review: Case, role: UserRole
) -> None:
    """FR-35: intake staff enter cases, administrators run the clinic; neither
    makes the clinical judgement."""
    signed_in(api_client, db_session, role)

    response = decide(api_client, awaiting_review, type="CONFIRM")

    assert response.status_code == 403
    assert error_of(response)["code"] == "FORBIDDEN"
    assert decisions_of(db_session, awaiting_review) == []
    assert status_of(db_session, awaiting_review) is CaseStatus.AWAITING_REVIEW


def test_deciding_without_the_csrf_header_is_refused(
    reviewer_client: TestClient, db_session: Session, reviewer: User, awaiting_review: Case
) -> None:
    """SR-09: the double-submit check applies to every unsafe method."""
    response = reviewer_client.post(
        f"{CASES_URL}/{awaiting_review.id}/decision", json={"type": "CONFIRM"}
    )

    assert response.status_code == 403
    assert error_of(response)["code"] == "CSRF_FAILED"
    assert decisions_of(db_session, awaiting_review) == []


def test_an_unauthenticated_decision_is_401(api_client: TestClient, awaiting_review: Case) -> None:
    response = api_client.post(
        f"{CASES_URL}/{awaiting_review.id}/decision", json={"type": "CONFIRM"}
    )

    assert response.status_code in {401, 403}


# --- Finalized actions (FR-76, DR-09) -------------------------------------


def test_a_reviewer_who_does_not_touch_the_list_still_records_what_they_kept(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """P06 §6.1: absent `final_actions` stores the baseline set plus the
    tailored actions, all KEPT."""
    decide(reviewer_client, awaiting_review, type="CONFIRM")

    rows = final_actions_of(db_session, awaiting_review)

    assert rows, "a decision always records the action list it settled"
    assert {row.status for row in rows} == {ActionStatus.KEPT}
    baseline = [row.text for row in rows if row.source is ActionSource.BASELINE]
    assert baseline == SEEDED_BASELINE[VTLCategory.ORANGE]
    assert any(row.source is ActionSource.AI for row in rows)
    assert [row.rank for row in rows] == list(range(1, len(rows) + 1))


def test_the_baseline_follows_the_category_the_reviewer_settled_on(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """ADR-18 §6: adjusting ORANGE to RED records RED's baseline set, not the
    one the recommendation was generated for."""
    decide(
        reviewer_client,
        awaiting_review,
        type="ADJUST",
        final_category="RED",
        reason_code="CONDITION_DIFFERS_ON_ARRIVAL",
    )

    rows = final_actions_of(db_session, awaiting_review)
    baseline = [row.text for row in rows if row.source is ActionSource.BASELINE]

    assert baseline == SEEDED_BASELINE[VTLCategory.RED]
    # And the ORANGE-tailored suggestions are *not* recorded as kept: FR-78
    # makes them outdated, and a reviewer who never opened the checklist gave
    # no approval to put in the permanent record.
    assert all(row.source is not ActionSource.AI for row in rows)


def test_the_tailored_actions_are_kept_when_the_category_did_not_move(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """The other half of the rule above: confirming the recommendation means
    the case-specific suggestions still apply, so they are recorded as kept."""
    reviewer_client.post(
        f"{CASES_URL}/{awaiting_review.id}/decision",
        json={"type": "CONFIRM"},
        headers=csrf_headers(reviewer_client),
    )

    rows = final_actions_of(db_session, awaiting_review)

    assert any(row.source is ActionSource.AI for row in rows)
    assert all(row.status is ActionStatus.KEPT for row in rows)


def test_an_explicit_list_is_stored_verbatim_and_in_order(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """FR-76: keep, edit, remove and add, each with its own status."""
    suggestion = db_session.scalars(
        select(ActionSuggestion)
        .where(ActionSuggestion.case_id == awaiting_review.id)
        .where(ActionSuggestion.source == ActionSource.AI)
        .order_by(ActionSuggestion.rank)
    ).first()
    assert suggestion is not None

    sent = [
        {
            "text": "Alert the veterinarian now and move the patient to treatment.",
            "source": "BASELINE",
            "status": "KEPT",
        },
        {
            "text": "Ask the owner when the cat last passed any urine.",
            "source": "AI",
            "status": "EDITED",
            "suggestion_id": str(suggestion.id),
        },
        {
            "text": "Keep the carrier covered to limit stress.",
            "source": "REVIEWER",
            "status": "ADDED",
        },
        {
            "text": suggestion.text,
            "source": "AI",
            "status": "REMOVED",
            "suggestion_id": str(suggestion.id),
        },
    ]

    response = decide(reviewer_client, awaiting_review, type="CONFIRM", final_actions=sent)

    assert response.status_code == 200
    rows = final_actions_of(db_session, awaiting_review)
    assert [row.text for row in rows] == [action["text"] for action in sent]
    assert [row.status.value for row in rows] == [action["status"] for action in sent]
    assert [row.rank for row in rows] == [1, 2, 3, 4]
    assert rows[1].suggestion_id == suggestion.id
    assert rows[2].suggestion_id is None


def test_an_empty_list_is_not_the_same_as_an_absent_one(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """Sending `[]` means the reviewer removed everything, which is a decision
    the system records by writing nothing rather than by inventing a default."""
    response = decide(reviewer_client, awaiting_review, type="CONFIRM", final_actions=[])

    assert response.status_code == 200
    assert final_actions_of(db_session, awaiting_review) == []


def test_finalizing_never_touches_the_stored_suggestions(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """DR-09, FR-76: the suggestion is the record of what was proposed, and it
    is what the keep/edit/remove rates are measured against."""
    recommendation = db_session.scalars(
        select(Recommendation).where(Recommendation.case_id == awaiting_review.id)
    ).one()
    before = {
        (row.rank, row.text, row.source)
        for row in db_session.scalars(
            select(ActionSuggestion).where(ActionSuggestion.recommendation_id == recommendation.id)
        )
    }
    assert before

    decide(
        reviewer_client,
        awaiting_review,
        type="CONFIRM",
        final_actions=[{"text": "Replaced entirely.", "source": "REVIEWER", "status": "ADDED"}],
    )

    db_session.expire_all()
    after = {
        (row.rank, row.text, row.source)
        for row in db_session.scalars(
            select(ActionSuggestion).where(ActionSuggestion.recommendation_id == recommendation.id)
        )
    }
    assert after == before


def test_an_action_longer_than_the_cap_is_422(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    response = decide(
        reviewer_client,
        awaiting_review,
        type="CONFIRM",
        final_actions=[{"text": "x" * 301, "source": "REVIEWER", "status": "ADDED"}],
    )

    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "VALIDATION_ERROR"
    assert "action" in error["message"].lower()


def test_a_list_longer_than_the_cap_is_422(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    """Bounds how many append-only rows one request can write."""
    response = decide(
        reviewer_client,
        awaiting_review,
        type="CONFIRM",
        final_actions=[
            {"text": f"Action {index}.", "source": "REVIEWER", "status": "ADDED"}
            for index in range(51)
        ],
    )

    assert response.status_code == 422


# --- The audit trail (FR-41, FR-42, SR-17) --------------------------------


def test_a_decision_audits_the_before_and_after(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """FR-42: category and status on both sides, and nothing else about them."""
    decide(
        reviewer_client,
        awaiting_review,
        type="ADJUST",
        final_category="RED",
        reason_code="CONDITION_DIFFERS_ON_ARRIVAL",
        reason_text="Deteriorated in the waiting room.",
    )

    entry = latest_entry(db_session, AuditAction.DECISION_RECORDED)
    assert entry.before["status"] == CaseStatus.AWAITING_REVIEW.value
    assert entry.before["category"] == VTLCategory.ORANGE.value
    assert entry.after["status"] == CaseStatus.ADJUSTED.value
    assert entry.after["category"] == VTLCategory.RED.value
    assert entry.after["direction"] == DecisionDirection.UP.value
    assert entry.role == UserRole.VETERINARY_REVIEWER


def test_the_reason_text_is_never_written_to_the_audit_log(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """ADR-12: the log records categories and statuses, not clinical free text —
    it cannot be corrected, and the reason lives on the decision row."""
    reason = "Deteriorated in the waiting room, gums pale."
    decide(
        reviewer_client,
        awaiting_review,
        type="ADJUST",
        final_category="RED",
        reason_code="OTHER",
        reason_text=reason,
    )

    entry = latest_entry(db_session, AuditAction.DECISION_RECORDED)
    assert reason not in str(entry.before) + str(entry.after)
    # But it is stored where a reviewer can read it.
    assert decisions_of(db_session, awaiting_review)[0].reason_text == reason


def test_finalizing_audits_counts_and_never_action_text(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """SR-17: action text is untrusted model output and the log is permanent."""
    text = "Ask the owner when the cat last passed any urine."
    decide(
        reviewer_client,
        awaiting_review,
        type="CONFIRM",
        final_actions=[{"text": text, "source": "REVIEWER", "status": "ADDED"}],
    )

    entry = latest_entry(db_session, AuditAction.ACTIONS_FINALIZED)
    assert entry.after["total"] == 1
    assert entry.after["counts_by_status"] == {ActionStatus.ADDED.value: 1}
    assert text not in str(entry.after)


def test_the_decision_and_the_action_list_are_audited_in_order(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    decide(reviewer_client, awaiting_review, type="CONFIRM")

    actions = audit_actions(db_session)
    assert actions.index(AuditAction.DECISION_RECORDED.value) < actions.index(
        AuditAction.ACTIONS_FINALIZED.value
    )


def test_a_refused_decision_leaves_nothing_behind(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """The transition and the field checks run before anything is written, so a
    rejected attempt is not recorded as an event that happened."""
    before = audit_actions(db_session)

    decide(reviewer_client, awaiting_review, type="ADJUST", final_category="RED")

    assert audit_actions(db_session) == before
    assert final_actions_of(db_session, awaiting_review) == []


def latest_entry(session: Session, action: AuditAction) -> Any:
    from app.models import AuditEntry

    return session.scalars(
        select(AuditEntry).where(AuditEntry.action == action.value).order_by(AuditEntry.id.desc())
    ).first()
