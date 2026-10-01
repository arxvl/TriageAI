"""Double-submit CSRF protection on state-changing requests (SR-09, ADR-11)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.cookies import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from tests.conftest import csrf_headers, make_user, sign_in

PASSWORD = "Sampaguita2026"

LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/auth/me"


def test_login_is_the_one_exempt_route(api_client: TestClient, db_session: Session) -> None:
    """The browser has no CSRF cookie yet when it signs in."""
    user = make_user(db_session, password=PASSWORD)

    response = sign_in(api_client, user.email, PASSWORD)

    assert response.status_code == 200


def test_a_post_without_the_header_is_refused(api_client: TestClient, db_session: Session) -> None:
    user = make_user(db_session, password=PASSWORD)
    sign_in(api_client, user.email, PASSWORD)

    response = api_client.post(LOGOUT_URL)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


def test_a_post_with_a_mismatched_header_is_refused(
    api_client: TestClient, db_session: Session
) -> None:
    """A page that cannot read the cookie cannot guess the value either."""
    user = make_user(db_session, password=PASSWORD)
    sign_in(api_client, user.email, PASSWORD)

    response = api_client.post(LOGOUT_URL, headers={CSRF_HEADER_NAME: "not-the-token"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


def test_a_post_with_the_matching_header_is_allowed(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(db_session, password=PASSWORD)
    sign_in(api_client, user.email, PASSWORD)

    response = api_client.post(LOGOUT_URL, headers=csrf_headers(api_client))

    assert response.status_code == 200


def test_the_header_alone_is_not_enough(api_client: TestClient) -> None:
    """Both halves of the double submit must be present."""
    response = api_client.post(LOGOUT_URL, headers={CSRF_HEADER_NAME: "a-token"})

    assert response.status_code == 403


def test_the_cookie_alone_is_not_enough(api_client: TestClient) -> None:
    api_client.cookies.set(CSRF_COOKIE_NAME, "a-token")

    response = api_client.post(LOGOUT_URL)

    assert response.status_code == 403


def test_the_check_runs_before_authentication(api_client: TestClient) -> None:
    """A forged request is rejected without the server even reading the session."""
    response = api_client.post("/api/v1/auth/change-password", json={})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.parametrize("url", [ME_URL, "/api/v1/health"])
def test_safe_methods_are_never_blocked(api_client: TestClient, url: str) -> None:
    assert api_client.get(url).status_code in {200, 401}
