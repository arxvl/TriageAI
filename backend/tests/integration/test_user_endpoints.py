"""`/users`: the Administrator's account management (FR-60, FR-63, SR-03, SR-05, BR-04)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import MAX_FAILED_ATTEMPTS
from app.models import AuditEntry, User, UserRole
from tests.conftest import audit_actions, csrf_headers, make_user, sign_in

PASSWORD = "Sampaguita2026"
USERS = "/api/v1/users"


def signed_in(client: TestClient, session: Session, role: UserRole) -> User:
    user = make_user(session, password=PASSWORD, role=role)
    sign_in(client, user.email, PASSWORD)
    return user


def as_admin(client: TestClient, session: Session) -> User:
    return signed_in(client, session, UserRole.ADMINISTRATOR)


def new_user_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "full_name": "Maria Santos",
        "email": "maria.santos@triageai.invalid",
        "role": "INTAKE_STAFF",
        "can_approve_kb": False,
    }
    body.update(overrides)
    return body


# --- Create -----------------------------------------------------------------


def test_create_returns_the_temporary_password_and_the_new_user_must_change_it(
    api_client: TestClient, db_session: Session
) -> None:
    as_admin(api_client, db_session)

    response = api_client.post(USERS, json=new_user_body(), headers=csrf_headers(api_client))

    assert response.status_code == 201
    body = response.json()
    temporary_password = body["temporary_password"]
    assert len(temporary_password) == 16
    assert body["user"]["email"] == "maria.santos@triageai.invalid"
    assert body["user"]["must_change_password"] is True
    assert "password_hash" not in response.text

    # The new person can sign in with it, and is held at the password change.
    other = TestClient(api_client.app)
    login = sign_in(other, "maria.santos@triageai.invalid", temporary_password)
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True
    blocked = other.get(USERS)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"


def test_create_is_audited_without_the_password(
    api_client: TestClient, db_session: Session
) -> None:
    admin = as_admin(api_client, db_session)

    response = api_client.post(USERS, json=new_user_body(), headers=csrf_headers(api_client))

    assert "USER_CREATED" in audit_actions(db_session, admin.id)
    entries = db_session.execute(select(AuditEntry)).scalars()
    assert response.json()["temporary_password"] not in str(
        [(entry.before, entry.after) for entry in entries]
    )


def test_create_validation_failures_name_the_field(
    api_client: TestClient, db_session: Session
) -> None:
    as_admin(api_client, db_session)
    headers = csrf_headers(api_client)

    bad_email = api_client.post(USERS, json=new_user_body(email="not-an-address"), headers=headers)
    blank_name = api_client.post(USERS, json=new_user_body(full_name="  "), headers=headers)
    bad_role = api_client.post(USERS, json=new_user_body(role="OWNER"), headers=headers)

    assert bad_email.status_code == 422
    assert bad_email.json()["error"]["field"] == "email"
    assert blank_name.status_code == 422
    assert blank_name.json()["error"]["field"] == "full_name"
    assert bad_role.status_code == 422
    assert bad_role.json()["error"]["field"] == "role"


@pytest.mark.parametrize("role", ["INTAKE_STAFF", "ADMINISTRATOR"])
def test_create_rejects_kb_approval_for_a_role_that_cannot_hold_it(
    api_client: TestClient, db_session: Session, role: str
) -> None:
    as_admin(api_client, db_session)

    response = api_client.post(
        USERS,
        json=new_user_body(role=role, can_approve_kb=True),
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "can_approve_kb"


def test_create_rejects_a_duplicate_email(api_client: TestClient, db_session: Session) -> None:
    as_admin(api_client, db_session)
    headers = csrf_headers(api_client)
    api_client.post(USERS, json=new_user_body(), headers=headers)

    response = api_client.post(
        USERS, json=new_user_body(email="MARIA.SANTOS@triageai.invalid"), headers=headers
    )

    assert response.status_code == 409
    assert response.json()["error"]["field"] == "email"


# --- List -------------------------------------------------------------------


def test_list_searches_by_name_and_email_and_never_leaks_a_password(
    api_client: TestClient, db_session: Session
) -> None:
    as_admin(api_client, db_session)
    make_user(db_session, full_name="Jun Cruz", email="jun.cruz@triageai.invalid")
    make_user(db_session, full_name="Ana Reyes", email="a.reyes@triageai.invalid")

    everyone = api_client.get(USERS)
    by_name = api_client.get(USERS, params={"q": "cruz"})
    by_email = api_client.get(USERS, params={"q": "a.reyes"})
    too_long = api_client.get(USERS, params={"q": "x" * 101})

    assert everyone.status_code == 200
    assert everyone.json()["total"] == 3
    assert [u["full_name"] for u in by_name.json()["items"]] == ["Jun Cruz"]
    assert [u["full_name"] for u in by_email.json()["items"]] == ["Ana Reyes"]
    assert too_long.status_code == 422
    assert "password_hash" not in everyone.text
    assert "temporary_password" not in everyone.text


# --- Update -----------------------------------------------------------------


def test_patch_edits_name_role_approval_and_active(
    api_client: TestClient, db_session: Session
) -> None:
    admin = as_admin(api_client, db_session)
    other_admin = make_user(db_session, role=UserRole.ADMINISTRATOR)
    target = make_user(db_session)
    headers = csrf_headers(api_client)

    promoted = api_client.patch(
        f"{USERS}/{target.id}",
        json={"full_name": "Ana Reyes", "role": "VETERINARY_REVIEWER", "can_approve_kb": True},
        headers=headers,
    )
    deactivated = api_client.patch(
        f"{USERS}/{other_admin.id}", json={"is_active": False}, headers=headers
    )

    assert promoted.status_code == 200
    assert promoted.json()["role"] == "VETERINARY_REVIEWER"
    assert promoted.json()["can_approve_kb"] is True
    assert promoted.json()["full_name"] == "Ana Reyes"
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert "temporary_password" not in promoted.text
    assert audit_actions(db_session, admin.id).count("USER_UPDATED") == 2


def test_patch_rejects_the_approval_flag_on_a_non_reviewer_and_unknown_fields(
    api_client: TestClient, db_session: Session
) -> None:
    as_admin(api_client, db_session)
    target = make_user(db_session)
    headers = csrf_headers(api_client)

    approval = api_client.patch(
        f"{USERS}/{target.id}", json={"can_approve_kb": True}, headers=headers
    )
    email = api_client.patch(f"{USERS}/{target.id}", json={"email": "x@y.invalid"}, headers=headers)

    assert approval.status_code == 422
    assert approval.json()["error"]["field"] == "can_approve_kb"
    assert email.status_code == 422


def test_the_only_administrator_cannot_deactivate_or_demote_themselves(
    api_client: TestClient, db_session: Session
) -> None:
    admin = as_admin(api_client, db_session)
    headers = csrf_headers(api_client)

    deactivate = api_client.patch(f"{USERS}/{admin.id}", json={"is_active": False}, headers=headers)
    demote = api_client.patch(f"{USERS}/{admin.id}", json={"role": "INTAKE_STAFF"}, headers=headers)

    assert deactivate.status_code == 409
    assert deactivate.json()["error"]["code"] == "LAST_ADMINISTRATOR"
    assert demote.status_code == 409
    assert "USER_UPDATED" not in audit_actions(db_session, admin.id)


def test_patch_of_an_unknown_user_is_404(api_client: TestClient, db_session: Session) -> None:
    as_admin(api_client, db_session)

    response = api_client.patch(
        f"{USERS}/{uuid.uuid4()}", json={"is_active": False}, headers=csrf_headers(api_client)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# --- Unlock -----------------------------------------------------------------


def test_five_wrong_passwords_lock_an_account_and_unlock_lets_it_in(
    api_client: TestClient, db_session: Session
) -> None:
    admin = as_admin(api_client, db_session)
    target = make_user(db_session, password=PASSWORD)
    other = TestClient(api_client.app)
    for _ in range(MAX_FAILED_ATTEMPTS):
        sign_in(other, target.email, "Wrong-password-1")
    assert sign_in(other, target.email, PASSWORD).status_code == 423

    response = api_client.post(f"{USERS}/{target.id}/unlock", headers=csrf_headers(api_client))

    assert response.status_code == 200
    assert response.json()["locked_until"] is None
    assert sign_in(other, target.email, PASSWORD).status_code == 200
    assert "USER_UNLOCKED" in audit_actions(db_session, admin.id)


def test_unlock_of_an_unknown_user_is_404(api_client: TestClient, db_session: Session) -> None:
    as_admin(api_client, db_session)

    response = api_client.post(f"{USERS}/{uuid.uuid4()}/unlock", headers=csrf_headers(api_client))

    assert response.status_code == 404


# --- Reset password -----------------------------------------------------------


def test_reset_returns_a_new_temporary_password_once(
    api_client: TestClient, db_session: Session
) -> None:
    admin = as_admin(api_client, db_session)
    target = make_user(
        db_session,
        password=PASSWORD,
        failed_login_count=5,
        locked_until=datetime.now(UTC) + timedelta(minutes=10),
    )

    response = api_client.post(
        f"{USERS}/{target.id}/reset-password", headers=csrf_headers(api_client)
    )

    assert response.status_code == 200
    temporary_password = response.json()["temporary_password"]
    assert len(temporary_password) == 16
    assert response.json()["user"]["must_change_password"] is True
    other = TestClient(api_client.app)
    assert sign_in(other, target.email, PASSWORD).status_code == 401
    assert sign_in(other, target.email, temporary_password).status_code == 200
    assert "USER_PASSWORD_RESET" in audit_actions(db_session, admin.id)

    # The password is not retrievable afterwards.
    assert temporary_password not in api_client.get(USERS).text


# --- Who may call -----------------------------------------------------------


@pytest.mark.parametrize("role", [UserRole.INTAKE_STAFF, UserRole.VETERINARY_REVIEWER])
def test_non_administrators_get_403_on_every_user_endpoint(
    api_client: TestClient, db_session: Session, role: UserRole
) -> None:
    signed_in(api_client, db_session, role)
    target = make_user(db_session)
    headers = csrf_headers(api_client)

    responses = [
        api_client.get(USERS),
        api_client.post(USERS, json=new_user_body(), headers=headers),
        api_client.patch(f"{USERS}/{target.id}", json={"is_active": False}, headers=headers),
        api_client.post(f"{USERS}/{target.id}/unlock", headers=headers),
        api_client.post(f"{USERS}/{target.id}/reset-password", headers=headers),
    ]

    for response in responses:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"


def test_an_unauthenticated_caller_gets_401(api_client: TestClient) -> None:
    assert api_client.get(USERS).status_code == 401
