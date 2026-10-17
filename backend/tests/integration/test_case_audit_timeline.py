"""`GET /cases/{id}/audit` — the per-case timeline (FR-42, FR-45, FR-46, W-07).

Driven through a real run and real decisions, because the two properties worth
proving are about the join between the log and the domain tables: that the order
is right across both, and that the reviewer's reason text reaches the screen
*without* having been written to the append-only log (ADR-12).

Every pet and description is invented (CLAUDE.md §9).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.cookies import SESSION_COOKIE_NAME
from app.jobs.worker import run_pending_jobs_once
from app.models import AuditEntry, Case, OwnerDescription, User, UserRole
from app.services.audit_service import AuditAction
from app.services.timeline import EXTRACTION_STORED
from scripts.seed import seed
from tests.conftest import (
    csrf_headers,
    demo_cases,
    make_demo_case,
    make_user,
    sign_in,
)

CASES_URL = "/api/v1/cases"
PASSWORD = "Sampaguita2026"
REASON = "On arrival: abdomen painful, cat weak and lying down."


def signed_in(client: TestClient, session: Session, role: UserRole) -> User:
    user = make_user(session, password=PASSWORD, role=role)
    sign_in(client, user.email, PASSWORD)
    return user


@pytest.fixture
def reviewer(api_client: TestClient, db_session: Session) -> User:
    return signed_in(api_client, db_session, UserRole.VETERINARY_REVIEWER)


@pytest.fixture
def reviewer_client(api_client: TestClient, reviewer: User) -> TestClient:
    return api_client


@pytest.fixture
def ran_case(
    api_client: TestClient,
    db_session: Session,
    pipeline,
    app_session_factory: sessionmaker,
    reviewer: User,
) -> Case:
    """`DEMO_1` from intake through to `AWAITING_REVIEW`.

    Created **through the intake endpoint** rather than by a fixture row, so the
    timeline covers the whole history including `CASE_CREATED` — which is what
    W-07 opens with. Intake signs in, submits, and the reviewer signs back in
    over the same client, as the two of them would in the clinic.
    """
    seed(db_session)
    db_session.flush()
    spec = demo_cases()["DEMO_1"]
    signalment = spec["signalment"]

    signed_in(api_client, db_session, UserRole.INTAKE_STAFF)
    created = api_client.post(
        "/api/v1/cases",
        json={
            "species": spec["species"],
            "description": spec["description"],
            "intake_channel": spec.get("intake_channel", "WALK_IN"),
            "pet_name": signalment.get("pet_name"),
            "age_value": signalment.get("age_value"),
            "age_unit": signalment.get("age_unit"),
            "sex": signalment.get("sex"),
            "neutered": signalment.get("neutered"),
            "breed": signalment.get("breed"),
        },
        headers=csrf_headers(api_client),
    )
    assert created.status_code == 202, created.text

    # The triage job and the actions job it enqueues (ADR-08).
    run_pending_jobs_once(app_session_factory, pipeline)
    run_pending_jobs_once(app_session_factory, pipeline)

    sign_in(api_client, reviewer.email, PASSWORD)
    return db_session.scalars(select(Case).where(Case.case_no == created.json()["case_no"])).one()


def timeline(client: TestClient, case: Case) -> Any:
    return client.get(f"{CASES_URL}/{case.id}/audit").json()


def adjust(client: TestClient, case: Case) -> Any:
    return client.post(
        f"{CASES_URL}/{case.id}/decision",
        json={
            "type": "ADJUST",
            "final_category": "RED",
            "reason_code": "CONDITION_DIFFERS_ON_ARRIVAL",
            "reason_text": REASON,
        },
        headers=csrf_headers(client),
    )


def actions_of(body: Any) -> list[str]:
    return [item["action"] for item in body["items"]]


# --- Order and content ----------------------------------------------------


def test_the_timeline_covers_the_run_and_the_decision_in_order(
    reviewer_client: TestClient, ran_case: Case
) -> None:
    """FR-45: a chronological record of what happened to this case."""
    adjust(reviewer_client, ran_case)

    actions = actions_of(timeline(reviewer_client, ran_case))

    for expected in (
        AuditAction.CASE_CREATED.value,
        AuditAction.PIPELINE_STARTED.value,
        AuditAction.RED_FLAG_ALERT.value,
        EXTRACTION_STORED,
        AuditAction.RECOMMENDATION_CREATED.value,
        AuditAction.ACTIONS_SUGGESTED.value,
        AuditAction.DECISION_RECORDED.value,
        AuditAction.ACTIONS_FINALIZED.value,
    ):
        assert expected in actions, expected

    assert actions.index(AuditAction.CASE_CREATED.value) < actions.index(
        AuditAction.PIPELINE_STARTED.value
    )
    assert actions.index(EXTRACTION_STORED) < actions.index(
        AuditAction.RECOMMENDATION_CREATED.value
    )
    assert actions.index(AuditAction.RECOMMENDATION_CREATED.value) < actions.index(
        AuditAction.DECISION_RECORDED.value
    )


def test_the_items_are_in_non_decreasing_time_order(
    reviewer_client: TestClient, ran_case: Case
) -> None:
    adjust(reviewer_client, ran_case)
    reviewer_client.post(
        f"{CASES_URL}/{ran_case.id}/notes",
        json={"text": "Rechecked after twenty minutes."},
        headers=csrf_headers(reviewer_client),
    )

    stamps = [item["ts"] for item in timeline(reviewer_client, ran_case)["items"]]

    assert stamps == sorted(stamps)


def test_every_item_carries_a_label(reviewer_client: TestClient, ran_case: Case) -> None:
    """W-07 prints the label; an unlabelled item would read as a blank row."""
    adjust(reviewer_client, ran_case)

    for item in timeline(reviewer_client, ran_case)["items"]:
        assert item["label"]


def test_the_pipeline_s_own_entries_have_no_actor(
    reviewer_client: TestClient, ran_case: Case
) -> None:
    """The pipeline is not a person; the judgement about its output is audited
    separately (ADR-12)."""
    items = timeline(reviewer_client, ran_case)["items"]

    pipeline_items = [
        item
        for item in items
        if item["action"]
        in {
            AuditAction.PIPELINE_STARTED.value,
            AuditAction.RECOMMENDATION_CREATED.value,
            EXTRACTION_STORED,
        }
    ]
    assert pipeline_items
    assert all(item["actor_name"] is None for item in pipeline_items)
    assert all(item["actor_role"] is None for item in pipeline_items)


def test_a_decision_names_the_reviewer_and_their_role(
    reviewer_client: TestClient, ran_case: Case, reviewer: User
) -> None:
    """FR-42: the actor's name and the role they held at the time."""
    adjust(reviewer_client, ran_case)

    decision = next(
        item
        for item in timeline(reviewer_client, ran_case)["items"]
        if item["action"] == AuditAction.DECISION_RECORDED.value
    )

    assert decision["actor_name"] == reviewer.full_name
    assert decision["actor_role"] == UserRole.VETERINARY_REVIEWER.value


def test_the_case_creation_item_names_the_intake_staff(
    reviewer_client: TestClient, ran_case: Case
) -> None:
    created = next(
        item
        for item in timeline(reviewer_client, ran_case)["items"]
        if item["action"] == AuditAction.CASE_CREATED.value
    )

    assert created["label"] == "Case created"
    assert "walk-in" in created["details"]


def test_the_recommendation_item_summarises_the_answer(
    reviewer_client: TestClient, ran_case: Case
) -> None:
    """W-07: "ORANGE · Confidence High · 2 references · safety floor applied"."""
    item = next(
        item
        for item in timeline(reviewer_client, ran_case)["items"]
        if item["action"] == AuditAction.RECOMMENDATION_CREATED.value
    )

    assert "ORANGE" in item["details"]
    assert "Confidence" in item["details"]
    assert "reference" in item["details"]
    assert "safety floor applied" in item["details"]


def test_the_extraction_item_names_its_version_and_prompt(
    reviewer_client: TestClient, ran_case: Case
) -> None:
    item = next(
        item
        for item in timeline(reviewer_client, ran_case)["items"]
        if item["action"] == EXTRACTION_STORED
    )

    assert item["label"] == "Extraction v1 stored"
    assert "mock-0" in item["details"]


def test_the_decision_item_shows_the_change_and_the_reason(
    reviewer_client: TestClient, ran_case: Case
) -> None:
    """W-07: "Orange → Red · up-triage · reason: …" in the reviewer's words."""
    adjust(reviewer_client, ran_case)

    item = next(
        item
        for item in timeline(reviewer_client, ran_case)["items"]
        if item["action"] == AuditAction.DECISION_RECORDED.value
    )

    assert item["label"] == "Decision: adjusted"
    assert "Orange → Red" in item["details"]
    assert "up-triage" in item["details"]
    assert REASON in item["details"]


def test_the_reason_reaches_the_timeline_without_entering_the_audit_log(
    reviewer_client: TestClient, db_session: Session, ran_case: Case
) -> None:
    """The point of joining the domain tables: ADR-12 keeps clinical free text
    out of the log, and W-07 still shows it."""
    adjust(reviewer_client, ran_case)

    assert REASON in str(timeline(reviewer_client, ran_case))

    logged = db_session.scalars(
        select(AuditEntry).where(AuditEntry.entity_id == str(ran_case.id))
    ).all()
    assert logged
    for entry in logged:
        assert REASON not in str(entry.before) + str(entry.after)


def test_an_amendment_is_marked_as_one(
    reviewer_client: TestClient, db_session: Session, ran_case: Case
) -> None:
    """FR-48: both decisions appear, and the second says what it is."""
    reviewer_client.post(
        f"{CASES_URL}/{ran_case.id}/decision",
        json={"type": "CONFIRM"},
        headers=csrf_headers(reviewer_client),
    )
    from app.models import StaffDecision

    original = db_session.scalars(
        select(StaffDecision).where(StaffDecision.case_id == ran_case.id)
    ).one()
    reviewer_client.post(
        f"{CASES_URL}/{ran_case.id}/decision",
        json={
            "type": "ADJUST",
            "final_category": "RED",
            "reason_code": "SIGN_NOT_CAPTURED",
            "amends_id": str(original.id),
        },
        headers=csrf_headers(reviewer_client),
    )

    decisions = [
        item
        for item in timeline(reviewer_client, ran_case)["items"]
        if item["action"] == AuditAction.DECISION_RECORDED.value
    ]

    assert len(decisions) == 2
    assert "amends an earlier decision" not in (decisions[0]["details"] or "")
    assert "amends an earlier decision" in decisions[1]["details"]


def test_the_finalized_action_item_carries_counts_and_no_text(
    reviewer_client: TestClient, ran_case: Case
) -> None:
    """SR-17: the timeline reports how many, never what they said."""
    text = "Ask the owner when the cat last passed any urine."
    reviewer_client.post(
        f"{CASES_URL}/{ran_case.id}/decision",
        json={
            "type": "CONFIRM",
            "final_actions": [{"text": text, "source": "REVIEWER", "status": "ADDED"}],
        },
        headers=csrf_headers(reviewer_client),
    )

    body = timeline(reviewer_client, ran_case)
    item = next(
        item for item in body["items"] if item["action"] == AuditAction.ACTIONS_FINALIZED.value
    )

    assert "1 action" in item["details"]
    assert "added" in item["details"]
    assert text not in str(body)


def test_the_caption_s_claim_is_returned_as_data(
    reviewer_client: TestClient, ran_case: Case
) -> None:
    """W-07 states append-only as fact; it is a property of the database
    (FR-43, ADR-12), so the server asserts it rather than the frontend."""
    assert timeline(reviewer_client, ran_case)["append_only"] is True


# --- The FR-46 intervals --------------------------------------------------


def test_both_intervals_are_computed(reviewer_client: TestClient, ran_case: Case) -> None:
    """FR-46: submission to recommendation, and recommendation to decision."""
    adjust(reviewer_client, ran_case)

    body = timeline(reviewer_client, ran_case)

    assert body["submission_to_recommendation_s"] is not None
    assert body["submission_to_recommendation_s"] >= 0
    assert body["recommendation_to_decision_s"] is not None
    assert body["recommendation_to_decision_s"] >= 0


def test_the_first_interval_measures_from_the_description_s_arrival(
    reviewer_client: TestClient,
    db_session: Session,
    pipeline,
    app_session_factory: sessionmaker,
) -> None:
    """Measured against the stored `submitted_at`, which is the same instant as
    the case's arrival (FR-46, DR-03).

    The arrival is set when the case is inserted, not afterwards: a case that
    arrived half a minute ago is the only way to get a non-trivial interval,
    and `owner_descriptions` cannot be updated at all (FR-05).
    """
    seed(db_session)
    db_session.flush()
    arrived_at = datetime.now(UTC) - timedelta(seconds=30)
    case = make_demo_case(db_session, "DEMO_1", created_at=arrived_at)
    pipeline.run(case.id)
    run_pending_jobs_once(app_session_factory, pipeline)

    stored = db_session.scalars(
        select(OwnerDescription.submitted_at).where(OwnerDescription.case_id == case.id)
    ).one()
    assert stored == arrived_at

    body = timeline(reviewer_client, case)

    # A window rather than an exact value: `submitted_at` comes from the
    # application's clock and the recommendation's `created_at` from the
    # database's, so the two differ by the transaction's own skew.
    assert 25 <= body["submission_to_recommendation_s"] <= 60


def test_an_undecided_case_has_no_second_interval(
    reviewer_client: TestClient, ran_case: Case
) -> None:
    body = timeline(reviewer_client, ran_case)

    assert body["submission_to_recommendation_s"] is not None
    assert body["recommendation_to_decision_s"] is None


def test_a_case_with_no_recommendation_has_neither_interval(
    reviewer_client: TestClient, db_session: Session
) -> None:
    """A case still in SUBMITTED: nothing has been answered or decided."""
    seed(db_session)
    case = make_demo_case(db_session, "DEMO_3")
    db_session.flush()

    body = timeline(reviewer_client, case)

    assert body["submission_to_recommendation_s"] is None
    assert body["recommendation_to_decision_s"] is None
    assert actions_of(body) == []


def test_an_amendment_does_not_reopen_the_decision_interval(
    reviewer_client: TestClient, db_session: Session, ran_case: Case
) -> None:
    """The metric is how long the reviewer took the first time; a later
    correction is a different event."""
    reviewer_client.post(
        f"{CASES_URL}/{ran_case.id}/decision",
        json={"type": "CONFIRM"},
        headers=csrf_headers(reviewer_client),
    )
    before = timeline(reviewer_client, ran_case)["recommendation_to_decision_s"]

    from app.models import StaffDecision

    original = db_session.scalars(
        select(StaffDecision).where(StaffDecision.case_id == ran_case.id)
    ).one()
    reviewer_client.post(
        f"{CASES_URL}/{ran_case.id}/decision",
        json={
            "type": "ADJUST",
            "final_category": "RED",
            "reason_code": "SIGN_NOT_CAPTURED",
            "amends_id": str(original.id),
        },
        headers=csrf_headers(reviewer_client),
    )

    assert timeline(reviewer_client, ran_case)["recommendation_to_decision_s"] == before


# --- Access ---------------------------------------------------------------


@pytest.mark.parametrize(
    "role",
    [UserRole.INTAKE_STAFF, UserRole.VETERINARY_REVIEWER, UserRole.ADMINISTRATOR],
)
def test_all_three_roles_may_read_the_timeline(
    api_client: TestClient, db_session: Session, ran_case: Case, role: UserRole
) -> None:
    """FR-41, ADR-12: the audit trail is what makes the system accountable, and
    reporting on it is one of the reasons it exists."""
    signed_in(api_client, db_session, role)

    response = api_client.get(f"{CASES_URL}/{ran_case.id}/audit")

    assert response.status_code == 200
    assert response.json()["items"]


def test_the_timeline_of_a_case_that_does_not_exist_is_404(
    reviewer_client: TestClient,
) -> None:
    response = reviewer_client.get(f"{CASES_URL}/00000000-0000-0000-0000-000000000000/audit")

    assert response.status_code == 404


def test_an_unauthenticated_read_is_401(api_client: TestClient, ran_case: Case) -> None:
    """The fixture leaves the reviewer signed in, so the cookie is dropped
    first — this is about the guard, not about the setup."""
    api_client.cookies.delete(SESSION_COOKIE_NAME)

    assert api_client.get(f"{CASES_URL}/{ran_case.id}/audit").status_code == 401


def test_the_timeline_carries_no_owner_identifiers(
    reviewer_client: TestClient, db_session: Session, pipeline, app_session_factory
) -> None:
    """FR-07, DR-04: the audit trail is the most widely readable surface here."""
    seed(db_session)
    db_session.flush()
    case = make_demo_case(
        db_session, "DEMO_1", owner_name="R. Bituin", contact_number="0917-000-0000"
    )
    pipeline.run(case.id)
    run_pending_jobs_once(app_session_factory, pipeline)

    raw = reviewer_client.get(f"{CASES_URL}/{case.id}/audit").text

    assert "R. Bituin" not in raw
    assert "0917-000-0000" not in raw
