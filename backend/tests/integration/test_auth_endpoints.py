"""The `/auth` endpoints end to end (FR-57, FR-61, FR-62, SR-03, SR-04, SR-12).

Each test runs inside the transaction the `api_client` fixture shares with
`db_session`, so a row an endpoint commits can be asserted on and still rolls
back afterwards.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from app.core.errors import GENERIC_LOGIN_FAILURE_MESSAGE
from app.core.security import (
    MAX_FAILED_ATTEMPTS,
    create_session_token,
    decode_session_token,
    verify_password,
)
from app.models import UserRole
from app.services.audit_service import AuditAction
from tests.conftest import (
    audit_actions,
    csrf_headers,
    make_user,
    session_token_from,
    set_session_cookie_value,
    sign_in,
)

PASSWORD = "Sampaguita2026"
WRONG_PASSWORD = "Sampaguita2027"
NEW_PASSWORD = "Tarsier-2026-Clinic"

LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/auth/me"
CHANGE_PASSWORD_URL = "/api/v1/auth/change-password"


def session_cookie_header(response) -> str:
    """The raw `Set-Cookie` line for the session cookie, for attribute checks."""
    return next(
        value
        for key, value in response.headers.multi_items()
        if key.lower() == "set-cookie" and value.startswith(f"{SESSION_COOKIE_NAME}=")
    )


# --- Successful login -----------------------------------------------------


def test_login_sets_both_cookies(api_client: TestClient, db_session: Session) -> None:
    user = make_user(db_session, password=PASSWORD)

    response = sign_in(api_client, user.email, PASSWORD)

    assert response.status_code == 200
    assert api_client.cookies[SESSION_COOKIE_NAME]
    assert api_client.cookies[CSRF_COOKIE_NAME]


def test_the_session_cookie_is_httponly_and_samesite_lax(
    api_client: TestClient, db_session: Session
) -> None:
    """SR-04 and ADR-11: injected JavaScript must not be able to read the token."""
    user = make_user(db_session, password=PASSWORD)

    response = sign_in(api_client, user.email, PASSWORD)
    cookie = session_cookie_header(response)

    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie


def test_the_csrf_cookie_is_readable_by_the_browser(
    api_client: TestClient, db_session: Session
) -> None:
    """The SPA has to copy it into the header, so this one is deliberately not HttpOnly."""
    user = make_user(db_session, password=PASSWORD)

    response = sign_in(api_client, user.email, PASSWORD)
    csrf_cookie = next(
        value
        for key, value in response.headers.multi_items()
        if key.lower() == "set-cookie" and value.startswith(f"{CSRF_COOKIE_NAME}=")
    )

    assert "HttpOnly" not in csrf_cookie


def test_login_returns_the_account_without_the_password_hash(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(
        db_session,
        password=PASSWORD,
        full_name="Dr. M. Santos",
        role=UserRole.VETERINARY_REVIEWER,
        can_approve_kb=True,
    )

    body = sign_in(api_client, user.email, PASSWORD).json()

    assert body == {
        "user": {
            "id": str(user.id),
            "full_name": "Dr. M. Santos",
            "email": user.email,
            "role": "VETERINARY_REVIEWER",
            "can_approve_kb": True,
            "must_change_password": False,
        }
    }


def test_login_records_the_success_and_stamps_last_login_at(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(db_session, password=PASSWORD)

    sign_in(api_client, user.email, PASSWORD)

    assert audit_actions(db_session, user.id) == [AuditAction.LOGIN_SUCCESS]
    assert user.last_login_at is not None


# --- Failed login ---------------------------------------------------------


def test_wrong_password_returns_the_generic_401(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(db_session, password=PASSWORD)

    response = sign_in(api_client, user.email, WRONG_PASSWORD)

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "INVALID_CREDENTIALS", "message": GENERIC_LOGIN_FAILURE_MESSAGE}
    }
    assert SESSION_COOKIE_NAME not in api_client.cookies


def test_an_unknown_address_is_indistinguishable_from_a_wrong_password(
    api_client: TestClient, db_session: Session
) -> None:
    """ADR-11: the API must not let anyone enumerate accounts."""
    user = make_user(db_session, password=PASSWORD)

    wrong_password = sign_in(api_client, user.email, WRONG_PASSWORD)
    unknown_account = sign_in(api_client, "nobody@triageai.invalid", PASSWORD)

    assert wrong_password.status_code == unknown_account.status_code == 401
    assert wrong_password.json() == unknown_account.json()


def test_a_deactivated_account_gets_the_same_generic_401(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(db_session, password=PASSWORD, is_active=False)

    response = sign_in(api_client, user.email, PASSWORD)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_a_malformed_body_returns_the_same_error_envelope(api_client: TestClient) -> None:
    """IR-05: a 422 is rendered like every other error, with no stack trace."""
    response = api_client.post(LOGIN_URL, json={"email": "intake@triageai.invalid"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "password" in response.json()["error"]["message"]


# --- Lockout (SR-03) ------------------------------------------------------


def test_the_fifth_failure_locks_the_account_and_names_the_unlock_time(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(db_session, password=PASSWORD)

    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        assert sign_in(api_client, user.email, WRONG_PASSWORD).status_code == 401
    response = sign_in(api_client, user.email, WRONG_PASSWORD)

    assert response.status_code == 423
    assert response.json()["error"]["code"] == "ACCOUNT_LOCKED"
    assert user.locked_until is not None
    assert user.locked_until.isoformat() in response.json()["error"]["message"]


def test_a_locked_account_is_refused_the_correct_password(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(
        db_session,
        password=PASSWORD,
        failed_login_count=MAX_FAILED_ATTEMPTS,
        locked_until=datetime.now(UTC) + timedelta(minutes=15),
    )

    response = sign_in(api_client, user.email, PASSWORD)

    assert response.status_code == 423


def test_a_lock_that_has_expired_lets_the_user_back_in(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(
        db_session,
        password=PASSWORD,
        failed_login_count=MAX_FAILED_ATTEMPTS,
        locked_until=datetime.now(UTC) - timedelta(minutes=1),
    )

    response = sign_in(api_client, user.email, PASSWORD)

    assert response.status_code == 200
    assert user.locked_until is None


# --- Session handling (SR-01, SR-04) -------------------------------------


def test_me_without_a_cookie_is_unauthenticated(api_client: TestClient) -> None:
    response = api_client.get(ME_URL)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_me_returns_the_signed_in_account(api_client: TestClient, db_session: Session) -> None:
    user = make_user(db_session, password=PASSWORD, role=UserRole.ADMINISTRATOR)
    sign_in(api_client, user.email, PASSWORD)

    response = api_client.get(ME_URL)

    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(user.id)


def test_an_expired_token_is_rejected(api_client: TestClient, db_session: Session) -> None:
    user = make_user(db_session, password=PASSWORD)
    stale = create_session_token(
        user.id, user.role, issued_at=datetime.now(UTC) - timedelta(hours=2)
    )
    set_session_cookie_value(api_client, stale)

    response = api_client.get(ME_URL)

    assert response.status_code == 401


def test_a_token_for_a_deactivated_account_is_rejected(
    api_client: TestClient, db_session: Session
) -> None:
    """Deactivating an account must end the session already in flight (SR-01)."""
    user = make_user(db_session, password=PASSWORD)
    sign_in(api_client, user.email, PASSWORD)

    user.is_active = False
    db_session.flush()
    response = api_client.get(ME_URL)

    assert response.status_code == 401


def test_an_authenticated_request_reissues_the_cookie_with_a_later_expiry(
    api_client: TestClient, db_session: Session
) -> None:
    """SR-04: the 30-minute timeout is an idle one, so activity extends it."""
    user = make_user(db_session, password=PASSWORD)
    nearly_idle = create_session_token(
        user.id, user.role, issued_at=datetime.now(UTC) - timedelta(minutes=20)
    )
    set_session_cookie_value(api_client, nearly_idle)

    response = api_client.get(ME_URL)

    assert response.status_code == 200
    refreshed = session_token_from(response)
    assert refreshed is not None and refreshed != nearly_idle
    assert decode_session_token(refreshed)["exp"] > decode_session_token(nearly_idle)["exp"]


def test_an_unauthenticated_request_does_not_set_a_session_cookie(
    api_client: TestClient,
) -> None:
    response = api_client.get(ME_URL)

    assert SESSION_COOKIE_NAME not in response.cookies


# --- Logout (FR-62) -------------------------------------------------------


def test_logout_clears_both_cookies_once_each(api_client: TestClient, db_session: Session) -> None:
    user = make_user(db_session, password=PASSWORD)
    sign_in(api_client, user.email, PASSWORD)

    response = api_client.post(LOGOUT_URL, headers=csrf_headers(api_client))

    assert response.status_code == 200
    set_cookie_names = [
        value.split("=", 1)[0]
        for key, value in response.headers.multi_items()
        if key.lower() == "set-cookie"
    ]
    # Exactly one directive per cookie: the sliding refresh must not fight the clear.
    assert sorted(set_cookie_names) == [CSRF_COOKIE_NAME, SESSION_COOKIE_NAME]
    assert not api_client.cookies.get(SESSION_COOKIE_NAME)
    assert audit_actions(db_session, user.id)[-1] == AuditAction.LOGOUT


def test_after_logout_the_session_no_longer_works(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(db_session, password=PASSWORD)
    sign_in(api_client, user.email, PASSWORD)

    api_client.post(LOGOUT_URL, headers=csrf_headers(api_client))

    assert api_client.get(ME_URL).status_code == 401


def test_logout_requires_a_session(api_client: TestClient) -> None:
    response = api_client.post(LOGOUT_URL, headers={"X-CSRF-Token": "irrelevant"})

    assert response.status_code == 403  # the CSRF cookie is missing too


# --- Change password (FR-61, SR-02) --------------------------------------


def test_change_password_updates_the_hash_and_clears_the_flag(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(db_session, password=PASSWORD, must_change_password=True)
    sign_in(api_client, user.email, PASSWORD)

    response = api_client.post(
        CHANGE_PASSWORD_URL,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 200
    assert response.json()["user"]["must_change_password"] is False
    assert verify_password(NEW_PASSWORD, user.password_hash)
    assert audit_actions(db_session, user.id)[-1] == AuditAction.PASSWORD_CHANGED


def test_change_password_reports_the_policy_when_the_new_one_is_too_weak(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(db_session, password=PASSWORD, must_change_password=True)
    sign_in(api_client, user.email, PASSWORD)

    response = api_client.post(
        CHANGE_PASSWORD_URL,
        json={"current_password": PASSWORD, "new_password": "short1"},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WEAK_PASSWORD"
    assert "12 characters" in response.json()["error"]["message"]


def test_change_password_rejects_a_wrong_current_password(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(db_session, password=PASSWORD, must_change_password=True)
    sign_in(api_client, user.email, PASSWORD)

    response = api_client.post(
        CHANGE_PASSWORD_URL,
        json={"current_password": WRONG_PASSWORD, "new_password": NEW_PASSWORD},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CURRENT_PASSWORD_INCORRECT"
    assert user.must_change_password is True


def test_the_new_password_works_on_the_next_login(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(db_session, password=PASSWORD, must_change_password=True)
    sign_in(api_client, user.email, PASSWORD)
    api_client.post(
        CHANGE_PASSWORD_URL,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=csrf_headers(api_client),
    )
    api_client.post(LOGOUT_URL, headers=csrf_headers(api_client))

    assert sign_in(api_client, user.email, NEW_PASSWORD).status_code == 200
    assert sign_in(api_client, user.email, PASSWORD).status_code == 401


# --- Audit coverage (SR-12) ----------------------------------------------


@pytest.mark.parametrize(
    ("action", "scenario"),
    [
        (AuditAction.LOGIN_SUCCESS, "success"),
        (AuditAction.LOGIN_FAILURE, "failure"),
        (AuditAction.ACCOUNT_LOCKED, "lockout"),
        (AuditAction.LOGOUT, "logout"),
        (AuditAction.PASSWORD_CHANGED, "password_change"),
    ],
)
def test_every_security_event_reaches_the_audit_log(
    api_client: TestClient, db_session: Session, action: AuditAction, scenario: str
) -> None:
    user = make_user(db_session, password=PASSWORD)

    if scenario == "success":
        sign_in(api_client, user.email, PASSWORD)
    elif scenario == "failure":
        sign_in(api_client, user.email, WRONG_PASSWORD)
    elif scenario == "lockout":
        for _ in range(MAX_FAILED_ATTEMPTS):
            sign_in(api_client, user.email, WRONG_PASSWORD)
    elif scenario == "logout":
        sign_in(api_client, user.email, PASSWORD)
        api_client.post(LOGOUT_URL, headers=csrf_headers(api_client))
    else:
        sign_in(api_client, user.email, PASSWORD)
        api_client.post(
            CHANGE_PASSWORD_URL,
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            headers=csrf_headers(api_client),
        )

    assert action in audit_actions(db_session, user.id)
