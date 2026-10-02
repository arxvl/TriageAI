"""The `/cases` endpoints end to end (FR-01..FR-07, FR-29, FR-39, IR-05, SR-05).

Covers what only a request can prove: the status codes, the plain-language
validation envelope with its `field`, the role rules, and — the one that matters
most — that no owner name or contact number appears anywhere in any response
(FR-07, DR-04, IR-20).

Every pet, owner and description is invented (CLAUDE.md §9).
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import MockLLMBehavior
from app.jobs.queue import JobStage
from app.jobs.worker import run_pending_jobs_once
from app.models import (
    CaseStatus,
    Job,
    JobStatus,
    JobType,
    OwnerReference,
    Species,
    User,
    UserRole,
    VTLCategory,
)
from scripts.seed import seed
from tests.conftest import (
    csrf_headers,
    make_case,
    make_recommendation,
    make_red_flag_alert,
    make_user,
    sign_in,
)

CASES_URL = "/api/v1/cases"
PASSWORD = "Sampaguita2026"

DESCRIPTION = (
    "He has been vomiting since last night, about five times, and will not drink "
    "any water this morning."
)
OWNER_NAME = "R. Bituin"
CONTACT_NUMBER = "0917-000-0000"

VALID_CASE: dict[str, Any] = {
    "species": "CAT",
    "description": DESCRIPTION,
    "intake_channel": "PHONE",
    "pet_name": "Mingming",
    "age_value": 3,
    "age_unit": "YEARS",
    "sex": "MALE",
    "neutered": False,
    "breed": "Puspin",
    "weight_kg": "4.2",
}


def signed_in(client: TestClient, session: Session, role: UserRole) -> User:
    user = make_user(session, password=PASSWORD, role=role)
    sign_in(client, user.email, PASSWORD)
    return user


@pytest.fixture
def intake_client(api_client: TestClient, db_session: Session) -> TestClient:
    signed_in(api_client, db_session, UserRole.INTAKE_STAFF)
    return api_client


def post_case(client: TestClient, **overrides: Any) -> Any:
    return client.post(CASES_URL, json={**VALID_CASE, **overrides}, headers=csrf_headers(client))


def error_of(response: Any) -> dict[str, str]:
    return response.json()["error"]


# --- POST /cases ----------------------------------------------------------


def test_creating_a_case_returns_202_and_the_case_number(intake_client: TestClient) -> None:
    """202, not 201: the triage pipeline has been accepted, not finished (FR-06)."""
    response = post_case(intake_client)

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"id", "case_no", "status"}
    assert body["status"] == CaseStatus.SUBMITTED.value
    assert body["case_no"].startswith("C-")
    uuid.UUID(body["id"])


def test_creating_a_case_enqueues_one_pipeline_run_job(
    intake_client: TestClient, db_session: Session
) -> None:
    """FR-06, ADR-08. The job is committed with the case, so it is there already."""
    case_id = uuid.UUID(post_case(intake_client).json()["id"])

    jobs = list(db_session.scalars(select(Job).where(Job.case_id == case_id)))

    assert len(jobs) == 1
    assert jobs[0].type is JobType.PIPELINE_RUN
    assert jobs[0].status is JobStatus.QUEUED
    assert jobs[0].attempts == 0


def test_an_out_of_scope_species_enqueues_nothing(
    intake_client: TestClient, db_session: Session
) -> None:
    """FR-02. No case row, and so no job to process one."""
    assert post_case(intake_client, species="OTHER").status_code == 422

    assert db_session.scalars(select(Job)).all() == []


def test_a_case_needs_only_species_and_a_description(intake_client: TestClient) -> None:
    response = intake_client.post(
        CASES_URL,
        json={"species": "DOG", "description": DESCRIPTION},
        headers=csrf_headers(intake_client),
    )

    assert response.status_code == 202


def test_other_species_is_refused_with_the_manual_triage_message(
    intake_client: TestClient,
) -> None:
    """FR-02. The message is what W-03 shows beside the species control."""
    response = post_case(intake_client, species="OTHER")

    assert response.status_code == 422
    assert error_of(response) == {
        "code": "SPECIES_OUT_OF_SCOPE",
        "message": "Other species are not processed by the AI and must be triaged manually.",
    }


def test_an_unknown_species_is_a_validation_error(intake_client: TestClient) -> None:
    response = post_case(intake_client, species="HORSE")

    assert response.status_code == 422
    assert error_of(response)["field"] == "species"


# --- FR-04, IR-05: field-level validation --------------------------------


@pytest.mark.parametrize(
    ("field", "value", "expected_message"),
    [
        ("description", "Too short.", "The description must be at least 20 characters."),
        ("description", "x" * 2001, "The description must be 2,000 characters or fewer."),
        ("weight_kg", "4,2", "Enter the weight as a number, e.g. 4.2."),
        ("weight_kg", "0.05", "Enter a weight between 0.1 and 120 kg."),
        ("weight_kg", "150", "Enter a weight between 0.1 and 120 kg."),
        ("age_value", "not a number", "Enter the age as a number, e.g. 3."),
        ("age_value", 41, "Enter an age between 0 and 40."),
        ("pet_name", "x" * 61, "The pet name can be at most 60 characters."),
        ("breed", "x" * 61, "The breed can be at most 60 characters."),
        ("owner_name", "x" * 81, "The owner name can be at most 80 characters."),
        ("contact_number", "x" * 31, "The contact number can be at most 30 characters."),
        ("age_unit", "FORTNIGHTS", "Choose whether the age is in months or years."),
        ("sex", "OTHER", "Choose the sex: male, female, or unknown."),
        ("intake_channel", "CARRIER_PIGEON", "Choose how the case arrived"),
    ],
)
def test_each_field_reports_a_plain_message_against_itself(
    intake_client: TestClient, field: str, value: Any, expected_message: str
) -> None:
    response = post_case(intake_client, **{field: value})

    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "VALIDATION_ERROR"
    assert error["field"] == field
    assert expected_message in error["message"]


def test_a_missing_description_names_the_description(intake_client: TestClient) -> None:
    response = intake_client.post(
        CASES_URL, json={"species": "CAT"}, headers=csrf_headers(intake_client)
    )

    assert response.status_code == 422
    error = error_of(response)
    assert error["field"] == "description"
    assert error["message"] == "Enter the owner's description of the problem."


def test_a_validation_message_carries_no_technical_wording(intake_client: TestClient) -> None:
    """IR-05: no error code and no field name in anything the user reads."""
    message = error_of(post_case(intake_client, weight_kg="4,2"))["message"]

    assert "_" not in message
    assert "Input should" not in message
    assert "decimal" not in message.lower()


def test_a_whitespace_only_description_is_too_short(intake_client: TestClient) -> None:
    response = post_case(intake_client, description=" " * 50)

    assert response.status_code == 422
    assert error_of(response)["field"] == "description"


# --- FR-07, DR-04, IR-20: the owner reference never comes back ------------


def test_the_owner_reference_is_stored_in_its_own_table(
    intake_client: TestClient, db_session: Session
) -> None:
    response = post_case(intake_client, owner_name=OWNER_NAME, contact_number=CONTACT_NUMBER)
    case_id = uuid.UUID(response.json()["id"])

    stored = db_session.execute(
        select(OwnerReference).where(OwnerReference.case_id == case_id)
    ).scalar_one()
    assert stored.owner_name == OWNER_NAME
    assert stored.contact_number == CONTACT_NUMBER


def test_no_response_contains_the_owner_name_or_contact_number(
    intake_client: TestClient,
) -> None:
    """Asserted on the raw response text, not on a list of expected keys.

    A field added to a response model in a later phase cannot leak an owner
    identifier past this test, which is the whole point of DR-04.
    """
    created = post_case(intake_client, owner_name=OWNER_NAME, contact_number=CONTACT_NUMBER)
    case_id = created.json()["id"]

    responses = [
        created,
        intake_client.get(CASES_URL),
        intake_client.get(f"{CASES_URL}/{case_id}/status"),
    ]

    for response in responses:
        assert response.status_code in (200, 202)
        assert OWNER_NAME not in response.text
        assert CONTACT_NUMBER not in response.text
        assert "owner_name" not in response.text
        assert "contact_number" not in response.text


# --- GET /cases -----------------------------------------------------------


def test_the_queue_lists_a_new_case_with_no_category_yet(intake_client: TestClient) -> None:
    """Through P04 no pipeline runs, so the category is empty by design."""
    post_case(intake_client)

    body = intake_client.get(CASES_URL).json()

    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["status"] == CaseStatus.SUBMITTED.value
    assert item["category"] is None
    assert item["target_minutes"] is None
    assert item["is_overdue"] is False
    assert item["has_red_flag"] is False
    assert item["primary_complaint_name"] is None
    assert item["pet_name"] == "Mingming"


def test_the_queue_returns_the_counters_and_a_timestamp(intake_client: TestClient) -> None:
    post_case(intake_client)

    body = intake_client.get(CASES_URL).json()

    assert body["counts"]["total"] == 1
    assert set(body["counts"]["by_category"]) == {c.value for c in VTLCategory}
    assert body["counts"]["manual_count"] == 0
    assert body["counts"]["awaiting_review_count"] == 0
    assert body["generated_at"]


def test_the_queue_is_in_urgency_order(api_client: TestClient, db_session: Session) -> None:
    signed_in(api_client, db_session, UserRole.VETERINARY_REVIEWER)
    for case_no, category in (
        ("C-E-BLU", VTLCategory.BLUE),
        ("C-E-RED", VTLCategory.RED),
        ("C-E-YEL", VTLCategory.YELLOW),
    ):
        case = make_case(db_session, case_no=case_no)
        make_recommendation(db_session, case=case, category=category)
    make_case(db_session, case_no="C-E-MAN", status=CaseStatus.MANUAL_TRIAGE_REQUIRED)

    body = api_client.get(CASES_URL).json()

    assert [item["case_no"] for item in body["items"]] == [
        "C-E-RED",
        "C-E-MAN",
        "C-E-YEL",
        "C-E-BLU",
    ]


def test_the_queue_accepts_the_filter_bar_parameters(
    api_client: TestClient, db_session: Session
) -> None:
    signed_in(api_client, db_session, UserRole.INTAKE_STAFF)
    make_case(db_session, case_no="C-F-CAT", species=Species.CAT, pet_name="Luna")
    make_case(db_session, case_no="C-F-DOG", species=Species.DOG, pet_name="Bantay")

    response = api_client.get(CASES_URL, params={"species": "CAT", "q": "Luna"})

    assert response.status_code == 200
    assert [item["case_no"] for item in response.json()["items"]] == ["C-F-CAT"]


def test_an_unknown_filter_is_refused(intake_client: TestClient) -> None:
    """`extra="forbid"`: a typo in a query parameter must not silently do nothing."""
    response = intake_client.get(CASES_URL, params={"specie": "CAT"})

    assert response.status_code == 422


def test_a_bad_page_size_reports_a_plain_message(intake_client: TestClient) -> None:
    response = intake_client.get(CASES_URL, params={"limit": 9999})

    assert response.status_code == 422
    error = error_of(response)
    assert error["field"] == "limit"
    assert error["message"] == "Ask for between 1 and 500 cases at a time."


def test_the_queue_carries_no_red_flag_alerts_when_there_are_none(
    intake_client: TestClient,
) -> None:
    post_case(intake_client)

    assert intake_client.get(CASES_URL).json()["red_flag_alerts"] == []


def test_the_queue_lists_an_unacknowledged_red_flag_alert(
    intake_client: TestClient, db_session: Session
) -> None:
    """FR-12, NFR-05. What the W-02 banner reads."""
    case = make_case(db_session, species=Species.CAT, pet_name="Mingming")
    make_red_flag_alert(
        db_session, case=case, rule_code="MALE_CAT_NO_URINE", min_category=VTLCategory.ORANGE
    )

    alerts = intake_client.get(CASES_URL).json()["red_flag_alerts"]

    assert len(alerts) == 1
    assert alerts[0]["case_no"] == case.case_no
    assert alerts[0]["species"] == Species.CAT.value
    assert alerts[0]["pet_name"] == "Mingming"
    assert alerts[0]["rule_code"] == "MALE_CAT_NO_URINE"
    assert alerts[0]["min_category"] == VTLCategory.ORANGE.value
    # The clinic's own wording for the rule, not the code.
    assert alerts[0]["rule_label"]
    # `matched_text` is a substring of the owner's description, so the most widely
    # visible surface in the application does not carry it (CLAUDE.md §9).
    assert "matched_text" not in alerts[0]


def test_an_alert_on_a_closed_case_is_not_announced(
    intake_client: TestClient, db_session: Session
) -> None:
    case = make_case(db_session, status=CaseStatus.CLOSED)
    make_red_flag_alert(db_session, case=case)

    assert intake_client.get(CASES_URL).json()["red_flag_alerts"] == []


# --- GET /cases/{id}/status ----------------------------------------------


def test_reading_the_status_of_a_new_case(intake_client: TestClient) -> None:
    case_id = post_case(intake_client).json()["id"]

    response = intake_client.get(f"{CASES_URL}/{case_id}/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": CaseStatus.SUBMITTED.value,
        "category": None,
        "has_red_flag": False,
        # The job exists and no worker has claimed it yet (IR-22, ADR-08).
        "pipeline_stage": JobStage.QUEUED.value,
        "updated_at": response.json()["updated_at"],
    }


def test_an_unknown_case_is_404(intake_client: TestClient) -> None:
    response = intake_client.get(f"{CASES_URL}/{uuid.uuid4()}/status")

    assert response.status_code == 404
    assert error_of(response)["code"] == "NOT_FOUND"


def test_a_malformed_case_id_is_a_validation_error(intake_client: TestClient) -> None:
    response = intake_client.get(f"{CASES_URL}/not-a-uuid/status")

    assert response.status_code == 422


# --- SR-05: who may do what ----------------------------------------------


def test_an_administrator_cannot_create_a_case(api_client: TestClient, db_session: Session) -> None:
    """Entering clinical data is not an administrator's job (BR-02, BR-05)."""
    signed_in(api_client, db_session, UserRole.ADMINISTRATOR)

    response = post_case(api_client)

    assert response.status_code == 403
    assert error_of(response)["code"] == "FORBIDDEN"


def test_a_reviewer_can_create_a_case(api_client: TestClient, db_session: Session) -> None:
    signed_in(api_client, db_session, UserRole.VETERINARY_REVIEWER)

    assert post_case(api_client).status_code == 202


@pytest.mark.parametrize(
    "role",
    [UserRole.INTAKE_STAFF, UserRole.VETERINARY_REVIEWER, UserRole.ADMINISTRATOR],
)
def test_every_role_can_read_the_queue(
    api_client: TestClient, db_session: Session, role: UserRole
) -> None:
    signed_in(api_client, db_session, role)

    assert api_client.get(CASES_URL).status_code == 200


def test_an_administrator_cannot_poll_a_case_status(
    api_client: TestClient, db_session: Session
) -> None:
    signed_in(api_client, db_session, UserRole.ADMINISTRATOR)

    response = api_client.get(f"{CASES_URL}/{uuid.uuid4()}/status")

    assert response.status_code == 403


@pytest.mark.parametrize("path", ["", "/00000000-0000-0000-0000-000000000000/status"])
def test_an_unauthenticated_request_is_401(api_client: TestClient, path: str) -> None:
    assert api_client.get(f"{CASES_URL}{path}").status_code == 401


def test_creating_a_case_without_the_csrf_header_is_refused(
    api_client: TestClient, db_session: Session
) -> None:
    """SR-09: the double-submit check applies to every unsafe method."""
    signed_in(api_client, db_session, UserRole.INTAKE_STAFF)

    response = api_client.post(CASES_URL, json=VALID_CASE)

    assert response.status_code == 403
    assert error_of(response)["code"] == "CSRF_FAILED"


def test_a_user_with_a_temporary_password_cannot_create_a_case(
    api_client: TestClient, db_session: Session
) -> None:
    """FR-61: everything outside /auth waits for the password change."""
    user = make_user(
        db_session, password=PASSWORD, role=UserRole.INTAKE_STAFF, must_change_password=True
    )
    sign_in(api_client, user.email, PASSWORD)

    response = post_case(api_client)

    assert response.status_code == 403
    assert error_of(response)["code"] == "PASSWORD_CHANGE_REQUIRED"


# --- Submit, then let the worker run it (FR-06, ADR-08) ------------------


def test_a_submitted_case_is_triaged_by_the_worker(
    intake_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    """The whole path a clinic sees: 202, a queued job, then a category.

    `VALID_CASE`'s description is not one of the demo fixtures, so the mocks answer
    generically and the case comes back YELLOW at LOW confidence — triaged, with
    the reasons recorded, which is the honest answer from a mock (ADR-17).
    """
    seed(db_session)
    db_session.flush()
    case_id = post_case(intake_client).json()["id"]

    before = intake_client.get(f"{CASES_URL}/{case_id}/status").json()
    assert before["status"] == CaseStatus.SUBMITTED.value
    assert before["pipeline_stage"] == JobStage.QUEUED.value

    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    after = intake_client.get(f"{CASES_URL}/{case_id}/status").json()
    assert after["status"] == CaseStatus.AWAITING_REVIEW.value
    assert after["category"] == VTLCategory.YELLOW.value
    assert after["pipeline_stage"] == JobStage.DONE.value

    item = intake_client.get(CASES_URL).json()["items"][0]
    assert item["category"] == VTLCategory.YELLOW.value
    assert item["recommended_category"] == VTLCategory.YELLOW.value
    # IR-04: a category exists and is explicitly not final until a reviewer decides.
    assert item["confirmed_category"] is None
    assert item["status"] == CaseStatus.AWAITING_REVIEW.value


def test_a_failing_pipeline_leaves_the_case_in_manual_triage(
    intake_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline_factory,
) -> None:
    """NFR-09: the case is still in the queue, marked for a human."""
    seed(db_session)
    db_session.flush()
    case_id = post_case(intake_client).json()["id"]

    run_pending_jobs_once(
        app_session_factory, pipeline_factory(mock_llm_behavior=MockLLMBehavior.TIMEOUT)
    )

    status = intake_client.get(f"{CASES_URL}/{case_id}/status").json()
    assert status["status"] == CaseStatus.MANUAL_TRIAGE_REQUIRED.value
    assert status["category"] is None
    assert status["pipeline_stage"] == JobStage.FAILED.value

    item = intake_client.get(CASES_URL).json()["items"][0]
    assert item["status"] == CaseStatus.MANUAL_TRIAGE_REQUIRED.value
    assert item["category"] is None
