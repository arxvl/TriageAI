"""`POST /cases/{id}/notes` and `POST /cases/{id}/close` (FR-37, FR-38).

Every pet and description is invented (CLAUDE.md §9).
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.jobs.worker import run_pending_jobs_once
from app.models import Case, CaseStatus, ClinicalNote, User, UserRole
from app.services.audit_service import AuditAction
from scripts.seed import seed
from tests.conftest import audit_actions, csrf_headers, make_demo_case, make_user, sign_in

CASES_URL = "/api/v1/cases"
PASSWORD = "Sampaguita2026"


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
def awaiting_review(db_session: Session, pipeline, app_session_factory: sessionmaker) -> Case:
    seed(db_session)
    db_session.flush()
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    run_pending_jobs_once(app_session_factory, pipeline)
    return case


def add_note(client: TestClient, case: Case, text: str) -> Any:
    return client.post(
        f"{CASES_URL}/{case.id}/notes",
        json={"text": text},
        headers=csrf_headers(client),
    )


def close(client: TestClient, case: Case) -> Any:
    return client.post(f"{CASES_URL}/{case.id}/close", headers=csrf_headers(client))


def confirm(client: TestClient, case: Case) -> Any:
    return client.post(
        f"{CASES_URL}/{case.id}/decision",
        json={"type": "CONFIRM"},
        headers=csrf_headers(client),
    )


def error_of(response: Any) -> dict[str, str]:
    return response.json()["error"]


def notes_of(session: Session, case: Case) -> list[ClinicalNote]:
    return list(
        session.scalars(
            select(ClinicalNote)
            .where(ClinicalNote.case_id == case.id)
            .order_by(ClinicalNote.created_at, ClinicalNote.id)
        )
    )


# --- Notes (FR-37) --------------------------------------------------------


def test_a_reviewer_can_add_a_note(
    reviewer_client: TestClient, db_session: Session, reviewer: User, awaiting_review: Case
) -> None:
    response = add_note(reviewer_client, awaiting_review, "Gums pink, bladder tense.")

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Gums pink, bladder tense."
    assert body["author_name"] == reviewer.full_name
    assert body["created_at"]
    assert [note.text for note in notes_of(db_session, awaiting_review)] == [
        "Gums pink, bladder tense."
    ]


def test_a_note_appears_on_the_case(reviewer_client: TestClient, awaiting_review: Case) -> None:
    add_note(reviewer_client, awaiting_review, "Owner called back.")

    notes = reviewer_client.get(f"{CASES_URL}/{awaiting_review.id}").json()["notes"]

    assert [note["text"] for note in notes] == ["Owner called back."]


def test_a_note_is_trimmed_and_an_empty_one_is_refused(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    assert add_note(reviewer_client, awaiting_review, "  Trimmed.  ").json()["text"] == "Trimmed."

    response = add_note(reviewer_client, awaiting_review, "   ")

    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "VALIDATION_ERROR"
    assert error["message"] == "Enter the note."


def test_a_note_longer_than_the_cap_is_refused(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    response = add_note(reviewer_client, awaiting_review, "x" * 2001)

    assert response.status_code == 422
    assert "2,000 characters" in error_of(response)["message"]


def test_a_note_may_be_added_to_a_closed_case(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    """The time to write an observation down is when it is known, not when the
    workflow permits it. It shows on the timeline, so it is not quiet."""
    confirm(reviewer_client, awaiting_review)
    close(reviewer_client, awaiting_review)

    response = add_note(reviewer_client, awaiting_review, "Seen by the veterinarian.")

    assert response.status_code == 200


def test_adding_a_note_writes_an_audit_entry_without_its_text(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """FR-43: the log cannot be corrected, so clinical content stays out of it."""
    text = "Bladder tense on palpation."
    add_note(reviewer_client, awaiting_review, text)

    from app.models import AuditEntry

    entry = db_session.scalars(
        select(AuditEntry)
        .where(AuditEntry.action == AuditAction.NOTE_ADDED.value)
        .order_by(AuditEntry.id.desc())
    ).first()
    assert entry is not None
    assert entry.after["char_count"] == len(text)
    assert text not in str(entry.after)


@pytest.mark.parametrize("role", [UserRole.INTAKE_STAFF, UserRole.ADMINISTRATOR])
def test_only_a_reviewer_can_add_a_note(
    api_client: TestClient, db_session: Session, awaiting_review: Case, role: UserRole
) -> None:
    """FR-37, BR-02: a clinical note is a clinician's record."""
    signed_in(api_client, db_session, role)

    response = add_note(api_client, awaiting_review, "Not allowed.")

    assert response.status_code == 403
    assert notes_of(db_session, awaiting_review) == []


def test_a_note_on_a_case_that_does_not_exist_is_404(
    reviewer_client: TestClient,
) -> None:
    response = reviewer_client.post(
        f"{CASES_URL}/00000000-0000-0000-0000-000000000000/notes",
        json={"text": "No such case."},
        headers=csrf_headers(reviewer_client),
    )

    assert response.status_code == 404


# --- Close (FR-38) --------------------------------------------------------


def test_closing_before_a_decision_is_409(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    """A patient must not leave the working list with no recorded urgency."""
    response = close(reviewer_client, awaiting_review)

    assert response.status_code == 409
    assert error_of(response)["code"] == "INVALID_TRANSITION"
    assert "before closing" in error_of(response)["message"]

    db_session.expire_all()
    stored = db_session.scalars(select(Case).where(Case.id == awaiting_review.id)).one()
    assert stored.status is CaseStatus.AWAITING_REVIEW
    assert stored.closed_at is None


def test_closing_a_decided_case_stamps_closed_at(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    confirm(reviewer_client, awaiting_review)

    response = close(reviewer_client, awaiting_review)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == CaseStatus.CLOSED.value
    assert body["closed_at"]
    assert body["case_no"] == awaiting_review.case_no

    db_session.expire_all()
    stored = db_session.scalars(select(Case).where(Case.id == awaiting_review.id)).one()
    assert stored.status is CaseStatus.CLOSED
    assert stored.closed_at is not None


def test_a_closed_case_leaves_the_queue(reviewer_client: TestClient, awaiting_review: Case) -> None:
    """FR-29, FR-38: the queue is a working list of open cases."""
    confirm(reviewer_client, awaiting_review)
    before = reviewer_client.get(CASES_URL).json()
    assert any(item["case_no"] == awaiting_review.case_no for item in before["items"])

    close(reviewer_client, awaiting_review)

    after = reviewer_client.get(CASES_URL).json()
    assert all(item["case_no"] != awaiting_review.case_no for item in after["items"])
    assert after["counts"]["total"] == before["counts"]["total"] - 1


def test_closing_a_closed_case_is_409(reviewer_client: TestClient, awaiting_review: Case) -> None:
    confirm(reviewer_client, awaiting_review)
    close(reviewer_client, awaiting_review)

    response = close(reviewer_client, awaiting_review)

    assert response.status_code == 409
    assert "already closed" in error_of(response)["message"]


def test_closing_writes_an_audit_entry(
    reviewer_client: TestClient, db_session: Session, awaiting_review: Case
) -> None:
    confirm(reviewer_client, awaiting_review)
    close(reviewer_client, awaiting_review)

    assert AuditAction.CASE_CLOSED.value in audit_actions(db_session)


def test_a_closed_case_is_still_readable(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    """The record outlives the queue entry: the audit trail has to be readable
    afterwards, and `can_decide` goes false because closing is final."""
    confirm(reviewer_client, awaiting_review)
    close(reviewer_client, awaiting_review)

    body = reviewer_client.get(f"{CASES_URL}/{awaiting_review.id}").json()

    assert body["status"] == CaseStatus.CLOSED.value
    assert body["header"]["closed_at"] is not None
    assert body["permissions"] == {
        "can_decide": False,
        "can_regenerate": False,
        "can_regenerate_actions": False,
        "can_retry": False,
        "can_close": False,
    }


@pytest.mark.parametrize("role", [UserRole.INTAKE_STAFF, UserRole.ADMINISTRATOR])
def test_only_a_reviewer_can_close_a_case(
    api_client: TestClient, db_session: Session, awaiting_review: Case, role: UserRole
) -> None:
    """FR-35, BR-02."""
    signed_in(api_client, db_session, role)

    response = close(api_client, awaiting_review)

    assert response.status_code == 403
    assert error_of(response)["code"] == "FORBIDDEN"


def test_closing_without_the_csrf_header_is_refused(
    reviewer_client: TestClient, awaiting_review: Case
) -> None:
    confirm(reviewer_client, awaiting_review)

    response = reviewer_client.post(f"{CASES_URL}/{awaiting_review.id}/close")

    assert response.status_code == 403
    assert error_of(response)["code"] == "CSRF_FAILED"


def test_closing_a_case_that_does_not_exist_is_404(
    reviewer_client: TestClient,
) -> None:
    response = reviewer_client.post(
        f"{CASES_URL}/00000000-0000-0000-0000-000000000000/close",
        headers=csrf_headers(reviewer_client),
    )

    assert response.status_code == 404
