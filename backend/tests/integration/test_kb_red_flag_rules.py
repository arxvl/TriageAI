"""The `/kb/red-flag-rules` endpoints (FR-12, FR-23, NFR-08, BR-04).

The safety floor cannot be switched off, so the only thing that changes it is
approving or retiring a rule — and both are the KB approver's, both publish a
knowledge-base version, and neither is open to an administrator.

All data here is fictitious (CLAUDE.md §9).
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import UserRole
from tests.conftest import csrf_headers, make_red_flag_rule, make_user, sign_in

PASSWORD = "Sampaguita2026"
RULES_URL = "/api/v1/kb/red-flag-rules"
VERSIONS_URL = "/api/v1/kb/versions"


def rule_body(**overrides: object) -> dict:
    body: dict = {
        "code": "FIXTURE_API_RULE",
        "label": "Fixture rule created through the API",
        "min_category": "ORANGE",
        "species": ["CAT"],
        "phrases_ref": "FIXTURE_API_RULE",
    }
    body.update(overrides)
    return body


def signed_in(
    client: TestClient, session: Session, role: UserRole, *, can_approve_kb: bool = False
):
    user = make_user(session, password=PASSWORD, role=role, can_approve_kb=can_approve_kb)
    sign_in(client, user.email, PASSWORD)
    return user


def as_admin(client: TestClient, session: Session):
    return signed_in(client, session, UserRole.ADMINISTRATOR)


def as_approver(client: TestClient, session: Session):
    return signed_in(client, session, UserRole.VETERINARY_REVIEWER, can_approve_kb=True)


# --- Listing and creating -------------------------------------------------


def test_the_rules_table_says_which_rules_are_screening(
    api_client: TestClient, db_session: Session
) -> None:
    """Dev includes the seeded placeholders; production would not (NFR-08)."""
    make_red_flag_rule(db_session, code="FIXTURE_TABLE_PLACEHOLDER", is_placeholder=True)
    as_admin(api_client, db_session)

    rows = {row["code"]: row for row in api_client.get(RULES_URL).json()}

    row = rows["FIXTURE_TABLE_PLACEHOLDER"]
    assert row["is_placeholder"] is True
    assert row["approved_at"] is None
    assert row["is_active"] is True


def test_an_administrator_creates_an_unapproved_rule(
    api_client: TestClient, db_session: Session
) -> None:
    as_admin(api_client, db_session)

    response = api_client.post(RULES_URL, json=rule_body(), headers=csrf_headers(api_client))

    assert response.status_code == 201
    body = response.json()
    assert body["approved_at"] is None
    assert body["is_active"] is False
    assert body["min_category"] == "ORANGE"


def test_a_rule_code_with_spaces_is_refused(api_client: TestClient, db_session: Session) -> None:
    as_admin(api_client, db_session)

    response = api_client.post(
        RULES_URL, json=rule_body(code="not a code"), headers=csrf_headers(api_client)
    )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "code"


def test_a_duplicate_code_is_refused(api_client: TestClient, db_session: Session) -> None:
    make_red_flag_rule(db_session, code="FIXTURE_API_RULE")
    as_admin(api_client, db_session)

    response = api_client.post(RULES_URL, json=rule_body(), headers=csrf_headers(api_client))

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "code"


def test_a_reviewer_cannot_create_a_rule(api_client: TestClient, db_session: Session) -> None:
    as_approver(api_client, db_session)

    response = api_client.post(RULES_URL, json=rule_body(), headers=csrf_headers(api_client))

    assert response.status_code == 403


def test_intake_staff_cannot_read_the_rules(api_client: TestClient, db_session: Session) -> None:
    signed_in(api_client, db_session, UserRole.INTAKE_STAFF)

    assert api_client.get(RULES_URL).status_code == 403


# --- Editing while unapproved --------------------------------------------


def test_an_unapproved_rule_can_be_edited(api_client: TestClient, db_session: Session) -> None:
    rule = make_red_flag_rule(db_session, code="FIXTURE_EDIT_RULE")
    as_admin(api_client, db_session)

    response = api_client.patch(
        f"{RULES_URL}/{rule.id}",
        json={"label": "A clearer label", "min_category": "RED"},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 200
    assert response.json()["label"] == "A clearer label"
    assert response.json()["min_category"] == "RED"


def test_an_approved_rule_cannot_be_edited(api_client: TestClient, db_session: Session) -> None:
    """Editing it would change what a stored safety floor meant (ADR-14)."""
    approver = make_user(db_session, role=UserRole.VETERINARY_REVIEWER, can_approve_kb=True)
    rule = make_red_flag_rule(db_session, code="FIXTURE_LOCKED_RULE", approved_by=approver)
    as_admin(api_client, db_session)

    response = api_client.patch(
        f"{RULES_URL}/{rule.id}",
        json={"label": "Not allowed"},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_the_phrase_key_can_be_cleared(api_client: TestClient, db_session: Session) -> None:
    """The one field a rule may be left without: the phrases are manual (M1)."""
    rule = make_red_flag_rule(db_session, code="FIXTURE_CLEAR_REF", phrases_ref="FIXTURE_CLEAR_REF")
    as_admin(api_client, db_session)

    response = api_client.patch(
        f"{RULES_URL}/{rule.id}",
        json={"phrases_ref": None},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 200
    assert response.json()["phrases_ref"] is None


def test_clearing_the_label_is_a_422_naming_it(api_client: TestClient, db_session: Session) -> None:
    rule = make_red_flag_rule(db_session, code="FIXTURE_NULL_LABEL")
    as_admin(api_client, db_session)

    response = api_client.patch(
        f"{RULES_URL}/{rule.id}",
        json={"label": None},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "label"


def test_the_code_cannot_be_edited(api_client: TestClient, db_session: Session) -> None:
    """Stored alerts and the phrase file both reference it (FR-23)."""
    rule = make_red_flag_rule(db_session, code="FIXTURE_FIXED_CODE")
    as_admin(api_client, db_session)

    response = api_client.patch(
        f"{RULES_URL}/{rule.id}",
        json={"code": "FIXTURE_OTHER_CODE"},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 422


# --- Approval and retirement publish a version (FR-54, NFR-08) -----------


def test_approving_a_rule_publishes_a_version(api_client: TestClient, db_session: Session) -> None:
    rule = make_red_flag_rule(db_session, code="FIXTURE_APPROVE_RULE", is_placeholder=True)
    as_approver(api_client, db_session)

    response = api_client.post(f"{RULES_URL}/{rule.id}/approve", headers=csrf_headers(api_client))

    assert response.status_code == 200
    assert response.json()["version_no"] == 1
    versions = api_client.get(VERSIONS_URL).json()
    assert versions[0]["note"] == "Approved red-flag rule FIXTURE_APPROVE_RULE"
    row = next(
        row for row in api_client.get(RULES_URL).json() if row["code"] == "FIXTURE_APPROVE_RULE"
    )
    assert row["approved_at"] is not None
    assert row["is_placeholder"] is False
    assert row["is_active"] is True


def test_an_administrator_cannot_approve_a_rule(
    api_client: TestClient, db_session: Session
) -> None:
    rule = make_red_flag_rule(db_session, code="FIXTURE_ADMIN_APPROVE")
    as_admin(api_client, db_session)

    response = api_client.post(f"{RULES_URL}/{rule.id}/approve", headers=csrf_headers(api_client))

    assert response.status_code == 403


def test_a_reviewer_without_the_permission_cannot_approve_a_rule(
    api_client: TestClient, db_session: Session
) -> None:
    rule = make_red_flag_rule(db_session, code="FIXTURE_NO_PERMISSION_RULE")
    signed_in(api_client, db_session, UserRole.VETERINARY_REVIEWER, can_approve_kb=False)

    response = api_client.post(f"{RULES_URL}/{rule.id}/approve", headers=csrf_headers(api_client))

    assert response.status_code == 403


def test_retiring_a_rule_publishes_a_version_and_stops_it_screening(
    api_client: TestClient, db_session: Session
) -> None:
    approver = make_user(db_session, role=UserRole.VETERINARY_REVIEWER, can_approve_kb=True)
    rule = make_red_flag_rule(db_session, code="FIXTURE_RETIRE_RULE", approved_by=approver)
    as_approver(api_client, db_session)

    response = api_client.post(f"{RULES_URL}/{rule.id}/retire", headers=csrf_headers(api_client))

    assert response.status_code == 200
    assert response.json()["version_no"] == 1
    row = next(
        row for row in api_client.get(RULES_URL).json() if row["code"] == "FIXTURE_RETIRE_RULE"
    )
    assert row["retired_at"] is not None
    assert row["is_active"] is False


def test_an_administrator_cannot_retire_a_rule(api_client: TestClient, db_session: Session) -> None:
    """Retiring a rule lowers the safety floor, so NFR-08 applies."""
    rule = make_red_flag_rule(db_session, code="FIXTURE_ADMIN_RETIRE")
    as_admin(api_client, db_session)

    response = api_client.post(f"{RULES_URL}/{rule.id}/retire", headers=csrf_headers(api_client))

    assert response.status_code == 403


def test_a_rule_cannot_be_retired_twice(api_client: TestClient, db_session: Session) -> None:
    rule = make_red_flag_rule(db_session, code="FIXTURE_RETIRE_TWICE")
    as_approver(api_client, db_session)
    api_client.post(f"{RULES_URL}/{rule.id}/retire", headers=csrf_headers(api_client))

    response = api_client.post(f"{RULES_URL}/{rule.id}/retire", headers=csrf_headers(api_client))

    assert response.status_code == 409


def test_an_unknown_rule_is_404(api_client: TestClient, db_session: Session) -> None:
    as_approver(api_client, db_session)

    response = api_client.post(
        f"{RULES_URL}/00000000-0000-0000-0000-000000000000/approve",
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 404
