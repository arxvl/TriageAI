"""Authentication endpoints (FR-57, FR-61, FR-62, SR-03, SR-04, SR-12, ADR-11).

The router holds no business logic (CLAUDE.md §7): it translates a request into
an `AuthService` call and turns the result into cookies and a body.

Every route here declares `require_role` with `allow_password_change_pending`,
because a user with a temporary password must still be able to sign in, read
their own account, change the password, and sign out (FR-61).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.cookies import (
    clear_auth_cookies,
    new_csrf_token,
    set_csrf_cookie,
    set_session_cookie,
)
from app.api.deps import ANY_ROLE, AppSettings, DbSession, require_role
from app.api.middleware import SESSION_CLEARED_STATE_ATTR
from app.core.security import create_session_token
from app.models import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, UserEnvelope, UserOut
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

AuthenticatedUser = Annotated[
    User, Depends(require_role(*ANY_ROLE, allow_password_change_pending=True))
]


@router.post("/login")
def login(
    payload: LoginRequest,
    response: Response,
    db: DbSession,
    settings: AppSettings,
) -> UserEnvelope:
    """Sign in and start a session.

    Issues both cookies itself rather than leaving it to the sliding-expiry
    middleware, which only refreshes sessions that already exist.
    """
    user = AuthService(db).authenticate(payload.email, payload.password)
    set_session_cookie(response, create_session_token(user.id, user.role), settings)
    set_csrf_cookie(response, new_csrf_token(), settings)
    return UserEnvelope(user=UserOut.model_validate(user))


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: DbSession,
    settings: AppSettings,
    user: AuthenticatedUser,
) -> dict[str, str]:
    """End the session and clear both cookies (FR-62)."""
    AuthService(db).logout(user)
    # Stops the middleware from re-issuing the cookie this response clears.
    setattr(request.state, SESSION_CLEARED_STATE_ATTR, True)
    clear_auth_cookies(response, settings)
    return {"status": "signed_out"}


@router.get("/me")
def read_current_user(user: AuthenticatedUser) -> UserEnvelope:
    """The signed-in account, used by the SPA to restore its session."""
    return UserEnvelope(user=UserOut.model_validate(user))


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    db: DbSession,
    user: AuthenticatedUser,
) -> UserEnvelope:
    """Replace the password and clear the forced-change flag (FR-61, SR-02)."""
    updated = AuthService(db).change_password(user, payload.current_password, payload.new_password)
    return UserEnvelope(user=UserOut.model_validate(updated))
