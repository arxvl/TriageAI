"""`POST /cases/{id}/retry` (P07 §7.1 task 3, UC-08, NFR-09, W-06).

Reviewer-only, allowed in one state, and safe against a second press. Driven
through a real mocked failure so the audit entry the W-06 banner reads is the one
the orchestrator wrote.

All data is fictitious (CLAUDE.md §9).
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import MockLLMBehavior
from app.jobs.worker import run_pending_jobs_once
from app.models import (
    AuditEntry,
    Case,
    CaseStatus,
    Job,
    JobStatus,
    JobType,
    UserRole,
    VTLCategory,
)
from app.services.audit_service import AuditAction
from scripts.seed import seed
from tests.conftest import csrf_headers, make_demo_case, make_staff_decision, make_user, sign_in

CASES_URL = "/api/v1/cases"
PASSWORD = "Sampaguita2026"


def signed_in(client: TestClient, session: Session, role: UserRole):
    user = make_user(session, password=PASSWORD, role=role)
    sign_in(client, user.email, PASSWORD)
    return user


@pytest.fixture
def reviewer(api_client: TestClient, db_session: Session):
    return signed_in(api_client, db_session, UserRole.VETERINARY_REVIEWER)


@pytest.fixture
def failed_case(db_session: Session, pipeline_factory, app_session_factory: sessionmaker) -> Case:
    """`DEMO_1` after the model timed out: `MANUAL_TRIAGE_REQUIRED`."""
    seed(db_session)
    db_session.flush()
    case = make_demo_case(db_session, "DEMO_1")
    pipeline_factory(mock_llm_behavior=MockLLMBehavior.TIMEOUT).run(case.id)
    return case


def retry(client: TestClient, case: Case) -> Any:
    return client.post(f"{CASES_URL}/{case.id}/retry", headers=csrf_headers(client))


def jobs_of(session: Session, case: Case) -> list[Job]:
    return list(session.scalars(select(Job).where(Job.case_id == case.id).order_by(Job.created_at)))


def status_of(session: Session, case: Case) -> CaseStatus:
    session.expire(case)
    return case.status


# --- Success --------------------------------------------------------------


def test_retry_queues_a_pipeline_job_and_moves_the_case_to_submitted(
    api_client: TestClient, db_session: Session, reviewer, failed_case: Case
) -> None:
    response = retry(api_client, failed_case)

    assert response.status_code == 202
    assert response.json() == {
        "id": str(failed_case.id),
        "case_no": failed_case.case_no,
        "status": "SUBMITTED",
    }
    assert status_of(db_session, failed_case) is CaseStatus.SUBMITTED
    (job,) = jobs_of(db_session, failed_case)
    assert job.type is JobType.PIPELINE_RUN
    assert job.status is JobStatus.QUEUED


def test_retry_is_audited_with_the_person_and_the_earlier_reason(
    api_client: TestClient, db_session: Session, reviewer, failed_case: Case
) -> None:
    retry(api_client, failed_case)

    entry = db_session.scalars(
        select(AuditEntry).where(
            AuditEntry.entity_id == str(failed_case.id),
            AuditEntry.action == AuditAction.PIPELINE_RETRY.value,
        )
    ).one()
    assert entry.user_id == reviewer.id
    assert entry.role is UserRole.VETERINARY_REVIEWER
    assert entry.before == {"status": "MANUAL_TRIAGE_REQUIRED", "reason": "LLM_TIMEOUT"}
    assert entry.after == {"status": "SUBMITTED"}


def test_the_retried_run_succeeds_and_the_failure_stays_in_the_log(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
    reviewer,
    failed_case: Case,
) -> None:
    retry(api_client, failed_case)

    assert run_pending_jobs_once(app_session_factory, pipeline, max_jobs=1) == 1

    assert status_of(db_session, failed_case) is CaseStatus.AWAITING_REVIEW
    actions = list(
        db_session.scalars(
            select(AuditEntry.action)
            .where(AuditEntry.entity_id == str(failed_case.id))
            .order_by(AuditEntry.id)
        )
    )
    assert AuditAction.PIPELINE_FAILED.value in actions
    assert actions.index(AuditAction.PIPELINE_RETRY.value) < actions.index(
        AuditAction.RECOMMENDATION_CREATED.value
    )
    # The earlier failure no longer shows as the case's banner (P06 §6.3).
    body = api_client.get(f"{CASES_URL}/{failed_case.id}").json()
    assert body["failure"] is None
    assert body["permissions"]["can_retry"] is False


def test_a_retry_that_fails_again_returns_the_case_to_manual_triage(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline_factory,
    reviewer,
    failed_case: Case,
) -> None:
    retry(api_client, failed_case)

    run_pending_jobs_once(
        app_session_factory,
        pipeline_factory(mock_llm_behavior=MockLLMBehavior.TIMEOUT),
        max_jobs=1,
    )

    assert status_of(db_session, failed_case) is CaseStatus.MANUAL_TRIAGE_REQUIRED
    assert api_client.get(f"{CASES_URL}/{failed_case.id}").json()["permissions"]["can_retry"]


# --- Who and when ---------------------------------------------------------


@pytest.mark.parametrize("role", [UserRole.INTAKE_STAFF, UserRole.ADMINISTRATOR])
def test_only_a_reviewer_may_retry(
    api_client: TestClient, db_session: Session, failed_case: Case, role: UserRole
) -> None:
    signed_in(api_client, db_session, role)

    response = retry(api_client, failed_case)

    assert response.status_code == 403
    assert status_of(db_session, failed_case) is CaseStatus.MANUAL_TRIAGE_REQUIRED
    assert jobs_of(db_session, failed_case) == []


def test_retry_needs_a_signed_in_user(api_client: TestClient, failed_case: Case) -> None:
    response = api_client.post(f"{CASES_URL}/{failed_case.id}/retry")

    assert response.status_code in (401, 403)


@pytest.mark.parametrize(
    "status",
    [
        CaseStatus.SUBMITTED,
        CaseStatus.PROCESSING,
        CaseStatus.AWAITING_REVIEW,
        CaseStatus.CONFIRMED,
        CaseStatus.ADJUSTED,
        CaseStatus.MANUALLY_TRIAGED,
        CaseStatus.CLOSED,
    ],
)
def test_retry_is_refused_in_every_other_state(
    api_client: TestClient, db_session: Session, reviewer, status: CaseStatus
) -> None:
    seed(db_session)
    case = make_demo_case(db_session, "DEMO_1")
    case.status = status
    db_session.flush()

    response = retry(api_client, case)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"
    assert jobs_of(db_session, case) == []


def test_retry_is_refused_when_a_decision_already_exists(
    api_client: TestClient, db_session: Session, reviewer, failed_case: Case
) -> None:
    make_staff_decision(db_session, case=failed_case, final_category=VTLCategory.RED)

    response = retry(api_client, failed_case)

    assert response.status_code == 409
    assert jobs_of(db_session, failed_case) == []


def test_a_second_press_does_not_queue_a_second_run(
    api_client: TestClient, db_session: Session, reviewer, failed_case: Case
) -> None:
    assert retry(api_client, failed_case).status_code == 202

    assert retry(api_client, failed_case).status_code == 409

    assert len(jobs_of(db_session, failed_case)) == 1


def test_an_unknown_case_is_404(api_client: TestClient, reviewer) -> None:
    response = api_client.post(
        f"{CASES_URL}/00000000-0000-0000-0000-000000000000/retry",
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 404


def test_retry_needs_the_csrf_header(
    api_client: TestClient, db_session: Session, reviewer, failed_case: Case
) -> None:
    response = api_client.post(f"{CASES_URL}/{failed_case.id}/retry")

    assert response.status_code == 403
    assert status_of(db_session, failed_case) is CaseStatus.MANUAL_TRIAGE_REQUIRED
