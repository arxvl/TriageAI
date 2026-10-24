"""Suggested actions follow a changed category (P07 §7.2b, FR-78, ADR-18 §6).

Driven through the API and the real mocked pipeline, because what matters is that
the three things a reviewer relies on agree: the baseline set that swaps to the
new category at once, the tailored rows that are flagged outdated rather than
deleted, and the later set that "Regenerate suggestions" stores beside them.

The property most worth pinning is the last one in the module docstring of
`app.pipeline.orchestrator`: the actions job cannot touch the case. A failed
regeneration therefore leaves the decision, the finalized actions and the case
status exactly as they were (FR-77, NFR-11).

Every pet, owner and description is invented (CLAUDE.md §9).
"""

from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import MockLLMBehavior
from app.jobs.worker import run_pending_jobs_once
from app.models import (
    ActionSource,
    ActionsStatus,
    ActionSuggestion,
    AuditEntry,
    Case,
    CaseStatus,
    FinalAction,
    Job,
    JobType,
    Recommendation,
    StaffDecision,
    User,
    UserRole,
    VTLCategory,
)
from app.pipeline.orchestrator import (
    ACTIONS_JOB_CATEGORY_KEY,
    ACTIONS_JOB_GENERATION_KEY,
    ACTIONS_JOB_RECOMMENDATION_KEY,
    ActionsFailureReason,
)
from app.pipeline.types import SuggestedAction
from app.services.audit_service import AuditAction
from scripts.seed import URGENCY_ACTIONS, seed
from tests.conftest import csrf_headers, make_demo_case, make_user, sign_in

CASES_URL = "/api/v1/cases"
PASSWORD = "Sampaguita2026"

SEEDED_BASELINE = {category: list(actions) for category, _, actions in URGENCY_ACTIONS}


def signed_in(client: TestClient, session: Session, role: UserRole) -> User:
    user = make_user(session, password=PASSWORD, role=role)
    sign_in(client, user.email, PASSWORD)
    return user


@pytest.fixture
def reviewer_client(api_client: TestClient, db_session: Session) -> TestClient:
    signed_in(api_client, db_session, UserRole.VETERINARY_REVIEWER)
    return api_client


@pytest.fixture
def awaiting_review(db_session: Session, pipeline, app_session_factory: sessionmaker) -> Case:
    """`DEMO_1` run to completion with its actions: ORANGE, tailored set ready."""
    seed(db_session)
    db_session.flush()
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    run_pending_jobs_once(app_session_factory, pipeline)
    return case


@pytest.fixture
def adjusted_to_red(reviewer_client: TestClient, awaiting_review: Case) -> Case:
    """The reviewer has moved the case from ORANGE to RED: tailored rows outdated."""
    response = decide(
        reviewer_client,
        awaiting_review,
        type="ADJUST",
        final_category="RED",
        reason_code="CONDITION_DIFFERS_ON_ARRIVAL",
    )
    assert response.status_code == 200, response.text
    return awaiting_review


def decide(client: TestClient, case: Case, **body: Any) -> Any:
    return client.post(f"{CASES_URL}/{case.id}/decision", json=body, headers=csrf_headers(client))


def regenerate(client: TestClient, case: Case) -> Any:
    return client.post(f"{CASES_URL}/{case.id}/actions/regenerate", headers=csrf_headers(client))


def detail(client: TestClient, case: Case) -> Any:
    response = client.get(f"{CASES_URL}/{case.id}")
    assert response.status_code == 200, response.text
    return response.json()


def recommendation_of(session: Session, case: Case) -> Recommendation:
    recommendation = session.scalars(
        select(Recommendation)
        .where(Recommendation.case_id == case.id)
        .order_by(Recommendation.version.desc())
    ).first()
    assert recommendation is not None
    session.expire(recommendation)
    return recommendation


def suggestions_of(session: Session, case: Case, generation: int) -> list[ActionSuggestion]:
    return list(
        session.scalars(
            select(ActionSuggestion)
            .where(
                ActionSuggestion.case_id == case.id,
                ActionSuggestion.generation == generation,
            )
            .order_by(ActionSuggestion.rank)
        )
    )


def snapshot(rows: list[ActionSuggestion]) -> list[tuple[str, VTLCategory]]:
    return [(row.text, row.generated_for_category) for row in rows]


def status_of(session: Session, case: Case) -> CaseStatus:
    session.expire_all()
    return session.scalars(select(Case.status).where(Case.id == case.id)).one()


def count_of(session: Session, model: type, case: Case) -> int:
    return session.scalar(select(func.count()).select_from(model).where(model.case_id == case.id))


def actions_jobs(session: Session, case: Case) -> list[Job]:
    return list(
        session.scalars(
            select(Job)
            .where(Job.case_id == case.id, Job.type == JobType.SUGGEST_ACTIONS)
            .order_by(Job.created_at, Job.id)
        )
    )


# --- An adjusted category (FR-78) ------------------------------------------


def test_adjusting_orange_to_red_swaps_the_baseline_and_flags_the_tailored_rows(
    reviewer_client: TestClient, adjusted_to_red: Case, db_session: Session
) -> None:
    before = len(suggestions_of(db_session, adjusted_to_red, 1))

    actions = detail(reviewer_client, adjusted_to_red)["actions"]

    assert actions["baseline"] == SEEDED_BASELINE[VTLCategory.RED]
    assert actions["generated_for_category"] == VTLCategory.ORANGE.value
    assert actions["is_outdated"] is True
    assert actions["tailored"], "outdated rows are flagged, not removed"
    assert all(row["is_outdated"] is True for row in actions["tailored"])
    # Nothing was deleted to make that happen.
    assert len(suggestions_of(db_session, adjusted_to_red, 1)) == before


def test_confirming_the_category_leaves_the_tailored_rows_current(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    assert decide(reviewer_client, awaiting_review, type="CONFIRM").status_code == 200

    actions = detail(reviewer_client, awaiting_review)["actions"]

    assert actions["is_outdated"] is False
    assert actions["tailored"]
    assert all(row["is_outdated"] is False for row in actions["tailored"])


def test_an_undecided_case_has_no_outdated_rows(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    actions = detail(reviewer_client, awaiting_review)["actions"]

    assert all(row["is_outdated"] is False for row in actions["tailored"])


# --- Regenerating (FR-78) --------------------------------------------------


def test_regenerating_queues_a_job_for_the_new_category(
    reviewer_client: TestClient, adjusted_to_red: Case, db_session: Session
) -> None:
    recommendation = recommendation_of(db_session, adjusted_to_red)

    response = regenerate(reviewer_client, adjusted_to_red)

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["category"] == VTLCategory.RED.value
    assert body["generation"] == 2
    assert body["actions_status"] == ActionsStatus.PENDING.value

    # Created in one transaction, so `created_at` cannot say which is newest:
    # the regeneration is the job that names a category.
    (job,) = [
        job
        for job in actions_jobs(db_session, adjusted_to_red)
        if ACTIONS_JOB_CATEGORY_KEY in (job.payload or {})
    ]
    assert job.payload == {
        ACTIONS_JOB_RECOMMENDATION_KEY: str(recommendation.id),
        ACTIONS_JOB_CATEGORY_KEY: VTLCategory.RED.value,
        ACTIONS_JOB_GENERATION_KEY: 2,
    }
    assert recommendation_of(db_session, adjusted_to_red).actions_status is ActionsStatus.PENDING


def test_asking_audits_the_category_and_set_number_and_nothing_else(
    reviewer_client: TestClient, adjusted_to_red: Case, db_session: Session
) -> None:
    regenerate(reviewer_client, adjusted_to_red)

    entry = db_session.scalars(
        select(AuditEntry).where(
            AuditEntry.entity_id == str(adjusted_to_red.id),
            AuditEntry.action == AuditAction.ACTIONS_REGENERATION_REQUESTED.value,
        )
    ).one()

    assert entry.user_id is not None
    assert set(entry.after) == {"category", "generation", "recommendation_id"}
    assert entry.after["category"] == VTLCategory.RED.value
    assert entry.after["generation"] == 2


def test_the_new_set_is_stored_beside_the_old_one(
    reviewer_client: TestClient,
    adjusted_to_red: Case,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    first = snapshot(suggestions_of(db_session, adjusted_to_red, 1))
    regenerate(reviewer_client, adjusted_to_red)

    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    # The earlier set is exactly as it was.
    assert snapshot(suggestions_of(db_session, adjusted_to_red, 1)) == first
    second = suggestions_of(db_session, adjusted_to_red, 2)
    assert second
    assert {row.generated_for_category for row in second} == {VTLCategory.RED}
    baseline = [row.text for row in second if row.source is ActionSource.BASELINE]
    assert baseline == SEEDED_BASELINE[VTLCategory.RED]

    actions = detail(reviewer_client, adjusted_to_red)["actions"]
    assert actions["status"] == ActionsStatus.READY.value
    assert actions["generated_for_category"] == VTLCategory.RED.value
    assert actions["is_outdated"] is False
    assert [row["text"] for row in actions["tailored"]] == [
        row.text for row in second if row.source is not ActionSource.BASELINE
    ]
    assert all(row["is_outdated"] is False for row in actions["tailored"])


def test_running_the_same_job_again_replaces_its_own_set_only(
    reviewer_client: TestClient, adjusted_to_red: Case, db_session: Session, pipeline
) -> None:
    """Crash recovery re-runs a job (ADR-08); it must not add a third set."""
    regenerate(reviewer_client, adjusted_to_red)
    recommendation = recommendation_of(db_session, adjusted_to_red)
    first = len(suggestions_of(db_session, adjusted_to_red, 1))

    for _ in range(2):
        pipeline.run_actions(recommendation.id, category=VTLCategory.RED, generation=2)

    assert len(suggestions_of(db_session, adjusted_to_red, 1)) == first
    assert len(suggestions_of(db_session, adjusted_to_red, 2)) > 0
    assert suggestions_of(db_session, adjusted_to_red, 3) == []


def test_a_second_press_while_the_job_runs_is_refused(
    reviewer_client: TestClient, adjusted_to_red: Case, db_session: Session
) -> None:
    assert regenerate(reviewer_client, adjusted_to_red).status_code == 202

    response = regenerate(reviewer_client, adjusted_to_red)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"
    assert len(actions_jobs(db_session, adjusted_to_red)) == 2


def test_the_old_rows_are_shown_flagged_while_the_new_set_is_pending(
    reviewer_client: TestClient, adjusted_to_red: Case
) -> None:
    regenerate(reviewer_client, adjusted_to_red)

    actions = detail(reviewer_client, adjusted_to_red)["actions"]

    assert actions["status"] == ActionsStatus.PENDING.value
    assert actions["is_outdated"] is True
    assert actions["tailored"]
    permissions = detail(reviewer_client, adjusted_to_red)["permissions"]
    assert permissions["can_regenerate_actions"] is False


# --- A failed regeneration leaves the decision alone (FR-77, NFR-11) -------


@pytest.mark.parametrize(
    ("behavior", "reason"),
    [
        (MockLLMBehavior.TIMEOUT, ActionsFailureReason.ACTIONS_TIMEOUT),
        (MockLLMBehavior.INVALID_JSON, ActionsFailureReason.ACTIONS_INVALID_OUTPUT),
    ],
)
def test_a_failed_regeneration_changes_neither_the_decision_nor_the_case(
    reviewer_client: TestClient,
    adjusted_to_red: Case,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline_factory,
    behavior: MockLLMBehavior,
    reason: ActionsFailureReason,
) -> None:
    decisions = count_of(db_session, StaffDecision, adjusted_to_red)
    finalized = count_of(db_session, FinalAction, adjusted_to_red)
    status = status_of(db_session, adjusted_to_red)
    regenerate(reviewer_client, adjusted_to_red)

    run_pending_jobs_once(app_session_factory, pipeline_factory(mock_llm_behavior=behavior))

    assert count_of(db_session, StaffDecision, adjusted_to_red) == decisions
    assert count_of(db_session, FinalAction, adjusted_to_red) == finalized
    assert status_of(db_session, adjusted_to_red) is status

    recommendation = recommendation_of(db_session, adjusted_to_red)
    assert recommendation.actions_status is ActionsStatus.FAILED
    assert recommendation.actions_error == reason.value

    body = detail(reviewer_client, adjusted_to_red)
    actions = body["actions"]
    assert actions["status"] == ActionsStatus.FAILED.value
    assert actions["failure_message"].endswith("the category and your decision are unchanged.")
    assert body["category"] == VTLCategory.RED.value
    # The earlier set is still there, still flagged, and the button is back.
    assert actions["tailored"]
    assert actions["is_outdated"] is True
    assert body["permissions"]["can_regenerate_actions"] is True
    assert suggestions_of(db_session, adjusted_to_red, 2) == []


class _Suggester:
    """A stage that proposes only what the validator must refuse (FR-74)."""

    model_id = "stub"
    prompt_version = "stub-0"
    last_latency_ms = 0

    def suggest(self, extraction, category, passages, max_items) -> list[SuggestedAction]:
        return [
            SuggestedAction(
                text="Give butorphanol 0.2 mg/kg IV", cited_ranks=[1], source=ActionSource.AI
            )
        ]


def test_when_every_action_is_rejected_the_message_says_so(
    reviewer_client: TestClient, adjusted_to_red: Case, db_session: Session, pipeline
) -> None:
    regenerate(reviewer_client, adjusted_to_red)
    recommendation = recommendation_of(db_session, adjusted_to_red)

    replace(pipeline, action_suggester=_Suggester()).run_actions(
        recommendation.id, category=VTLCategory.RED, generation=2
    )

    actions = detail(reviewer_client, adjusted_to_red)["actions"]
    assert actions["status"] == ActionsStatus.FAILED.value
    assert "safety checks" in actions["failure_message"]
    # The model's text is never echoed back (SR-17).
    assert "butorphanol" not in actions["failure_message"]
    assert status_of(db_session, adjusted_to_red) is CaseStatus.ADJUSTED


# --- Finalizing after a regeneration ---------------------------------------


def _amend(client: TestClient, case: Case, db_session: Session) -> list[FinalAction]:
    first = db_session.scalars(
        select(StaffDecision)
        .where(StaffDecision.case_id == case.id)
        .order_by(StaffDecision.decided_at.desc())
    ).first()
    assert first is not None
    response = decide(
        client,
        case,
        type="ADJUST",
        final_category="RED",
        reason_code="CONDITION_DIFFERS_ON_ARRIVAL",
        amends_id=str(first.id),
    )
    assert response.status_code == 200, response.text
    newest = db_session.scalars(
        select(StaffDecision)
        .where(StaffDecision.case_id == case.id)
        .order_by(StaffDecision.decided_at.desc(), StaffDecision.id.desc())
    ).first()
    assert newest is not None
    return list(
        db_session.scalars(
            select(FinalAction)
            .where(FinalAction.decision_id == newest.id)
            .order_by(FinalAction.rank)
        )
    )


def test_an_amendment_after_regenerating_records_the_new_tailored_set(
    reviewer_client: TestClient,
    adjusted_to_red: Case,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    regenerate(reviewer_client, adjusted_to_red)
    run_pending_jobs_once(app_session_factory, pipeline)
    new_ids = {
        row.id
        for row in suggestions_of(db_session, adjusted_to_red, 2)
        if row.source is not ActionSource.BASELINE
    }

    rows = _amend(reviewer_client, adjusted_to_red, db_session)

    tailored = [row for row in rows if row.source is not ActionSource.BASELINE]
    assert tailored
    assert {row.suggestion_id for row in tailored} == new_ids


def test_an_amendment_without_regenerating_records_the_baseline_only(
    reviewer_client: TestClient, adjusted_to_red: Case, db_session: Session
) -> None:
    rows = _amend(reviewer_client, adjusted_to_red, db_session)

    assert rows
    assert all(row.source is ActionSource.BASELINE for row in rows)


# --- Who may ask, and when -------------------------------------------------


@pytest.mark.parametrize("role", [UserRole.INTAKE_STAFF, UserRole.ADMINISTRATOR])
def test_only_a_reviewer_may_regenerate_actions(
    api_client: TestClient, db_session: Session, awaiting_review: Case, role: UserRole
) -> None:
    signed_in(api_client, db_session, role)

    response = regenerate(api_client, awaiting_review)

    assert response.status_code == 403
    assert len(actions_jobs(db_session, awaiting_review)) == 1


def test_regenerating_needs_a_signed_in_user(api_client: TestClient, awaiting_review: Case) -> None:
    response = api_client.post(f"{CASES_URL}/{awaiting_review.id}/actions/regenerate")

    assert response.status_code in (401, 403)


def test_regenerating_needs_the_csrf_header(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    response = reviewer_client.post(f"{CASES_URL}/{awaiting_review.id}/actions/regenerate")

    assert response.status_code == 403


def test_regenerating_for_an_unknown_case_is_404(reviewer_client: TestClient) -> None:
    response = reviewer_client.post(
        f"{CASES_URL}/00000000-0000-0000-0000-000000000000/actions/regenerate",
        headers=csrf_headers(reviewer_client),
    )

    assert response.status_code == 404


def test_a_case_waiting_for_manual_triage_cannot_regenerate_actions(
    reviewer_client: TestClient,
    db_session: Session,
    pipeline_factory,
    app_session_factory: sessionmaker,
) -> None:
    seed(db_session)
    db_session.flush()
    case = make_demo_case(db_session, "DEMO_1")
    pipeline_factory(mock_llm_behavior=MockLLMBehavior.TIMEOUT).run(case.id)

    response = regenerate(reviewer_client, case)

    assert response.status_code == 409
    assert status_of(db_session, case) is CaseStatus.MANUAL_TRIAGE_REQUIRED
    assert detail(reviewer_client, case)["permissions"]["can_regenerate_actions"] is False


def test_a_closed_case_cannot_regenerate_actions(
    reviewer_client: TestClient, adjusted_to_red: Case, db_session: Session
) -> None:
    assert (
        reviewer_client.post(
            f"{CASES_URL}/{adjusted_to_red.id}/close", headers=csrf_headers(reviewer_client)
        ).status_code
        == 200
    )

    response = regenerate(reviewer_client, adjusted_to_red)

    assert response.status_code == 409
    permissions = detail(reviewer_client, adjusted_to_red)["permissions"]
    assert permissions["can_regenerate_actions"] is False


def test_the_button_is_offered_to_a_reviewer_on_a_decided_case(
    reviewer_client: TestClient, adjusted_to_red: Case
) -> None:
    assert detail(reviewer_client, adjusted_to_red)["permissions"]["can_regenerate_actions"] is True


# --- Reviewers only see the tailored rows (FR-79) --------------------------


def test_a_non_reviewer_never_sees_tailored_rows_after_a_regeneration(
    reviewer_client: TestClient,
    adjusted_to_red: Case,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    regenerate(reviewer_client, adjusted_to_red)
    run_pending_jobs_once(app_session_factory, pipeline)
    reviewer_client.cookies.clear()
    signed_in(reviewer_client, db_session, UserRole.INTAKE_STAFF)

    body = detail(reviewer_client, adjusted_to_red)

    assert body["actions"]["tailored"] == []
    assert body["actions"]["baseline"] == SEEDED_BASELINE[VTLCategory.RED]
    assert body["permissions"]["can_regenerate_actions"] is False
