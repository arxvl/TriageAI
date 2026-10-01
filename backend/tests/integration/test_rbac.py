"""Server-side role enforcement (FR-58, FR-59, FR-61, SR-05, BR-04).

The routes under `/_rbac-test` exist only for these tests (P03 task 7); using
them keeps the RBAC assertions independent of any feature endpoint added later.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import UserRole
from tests.conftest import csrf_headers, has_role_guard, iter_api_routes, make_user, sign_in

PASSWORD = "Sampaguita2026"
NEW_PASSWORD = "Tarsier-2026-Clinic"

REVIEWER_URL = "/api/v1/_rbac-test/reviewer"
KB_APPROVER_URL = "/api/v1/_rbac-test/kb-approver"
ME_URL = "/api/v1/auth/me"
CHANGE_PASSWORD_URL = "/api/v1/auth/change-password"

# The only two endpoints allowed to go without a role guard (CLAUDE.md §7, SR-05).
UNGUARDED_PATHS = frozenset({"/api/v1/health", "/api/v1/auth/login"})


# --- Role checks ----------------------------------------------------------


def test_an_unauthenticated_request_is_401_not_403(api_client: TestClient) -> None:
    response = api_client.get(REVIEWER_URL)

    assert response.status_code == 401


def test_intake_staff_cannot_reach_a_reviewer_route(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(db_session, password=PASSWORD, role=UserRole.INTAKE_STAFF)
    sign_in(api_client, user.email, PASSWORD)

    response = api_client.get(REVIEWER_URL)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_an_administrator_cannot_reach_a_reviewer_route(
    api_client: TestClient, db_session: Session
) -> None:
    """Only a Veterinary Reviewer may act on urgency decisions (BR-01)."""
    user = make_user(db_session, password=PASSWORD, role=UserRole.ADMINISTRATOR)
    sign_in(api_client, user.email, PASSWORD)

    assert api_client.get(REVIEWER_URL).status_code == 403


def test_a_reviewer_can_reach_a_reviewer_route(api_client: TestClient, db_session: Session) -> None:
    user = make_user(db_session, password=PASSWORD, role=UserRole.VETERINARY_REVIEWER)
    sign_in(api_client, user.email, PASSWORD)

    response = api_client.get(REVIEWER_URL)

    assert response.status_code == 200
    assert response.json() == {"role": "VETERINARY_REVIEWER"}


# --- The KB approval permission (FR-58, BR-04) ---------------------------


def test_a_reviewer_without_the_kb_permission_is_refused(
    api_client: TestClient, db_session: Session
) -> None:
    """`can_approve_kb` is a separate capability from the role."""
    user = make_user(
        db_session,
        password=PASSWORD,
        role=UserRole.VETERINARY_REVIEWER,
        can_approve_kb=False,
    )
    sign_in(api_client, user.email, PASSWORD)

    assert api_client.get(KB_APPROVER_URL).status_code == 403


def test_a_reviewer_with_the_kb_permission_is_admitted(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(
        db_session,
        password=PASSWORD,
        role=UserRole.VETERINARY_REVIEWER,
        can_approve_kb=True,
    )
    sign_in(api_client, user.email, PASSWORD)

    assert api_client.get(KB_APPROVER_URL).status_code == 200


# --- The forced password change (FR-61) ----------------------------------


def test_a_temporary_password_blocks_other_endpoints(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(
        db_session,
        password=PASSWORD,
        role=UserRole.VETERINARY_REVIEWER,
        must_change_password=True,
    )
    sign_in(api_client, user.email, PASSWORD)

    response = api_client.get(REVIEWER_URL)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"


def test_a_temporary_password_still_allows_the_auth_routes(
    api_client: TestClient, db_session: Session
) -> None:
    user = make_user(db_session, password=PASSWORD, must_change_password=True)
    sign_in(api_client, user.email, PASSWORD)

    assert api_client.get(ME_URL).status_code == 200


def test_changing_the_password_lifts_the_block(api_client: TestClient, db_session: Session) -> None:
    user = make_user(
        db_session,
        password=PASSWORD,
        role=UserRole.VETERINARY_REVIEWER,
        must_change_password=True,
    )
    sign_in(api_client, user.email, PASSWORD)
    assert api_client.get(REVIEWER_URL).status_code == 403

    api_client.post(
        CHANGE_PASSWORD_URL,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=csrf_headers(api_client),
    )

    assert api_client.get(REVIEWER_URL).status_code == 200


# --- Coverage of the control itself (SR-05, FR-59) -----------------------


def test_every_endpoint_declares_a_role_guard() -> None:
    """The acceptance criterion for FR-59: no endpoint may be left unprotected.

    This is the test that catches a new router added in a later phase without
    `require_role`, which is why it scans the app instead of a list.
    """
    unprotected = [
        path
        for path, route in iter_api_routes(create_app().router)
        if path not in UNGUARDED_PATHS and not has_role_guard(route.dependant)
    ]

    assert unprotected == [], (
        f"these endpoints do not declare require_role: {unprotected}. "
        "Every endpoint except /health and /auth/login must (SR-05)."
    )


def test_the_route_scan_sees_the_routes_it_is_meant_to_guard() -> None:
    """Guards the guard: a walk that found nothing would pass the test above."""
    paths = {path for path, _ in iter_api_routes(create_app().router)}

    assert UNGUARDED_PATHS <= paths
    assert REVIEWER_URL in paths
    assert len(paths) >= 7
