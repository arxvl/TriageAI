"""Shared endpoint dependencies: the session, the current user, and RBAC.

`require_role` is the single authorisation control (SR-05). Every endpoint
except `/health` and `/auth/login` declares it; a route-scanning test in
`tests/integration/test_rbac.py` proves it, which is why the dependency carries
the `ROLE_GUARD_ATTR` marker.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.api.cookies import SESSION_COOKIE_NAME
from app.api.middleware import SESSION_STATE_ATTR
from app.core.config import Settings, get_settings
from app.core.errors import Forbidden, NotAuthenticated, PasswordChangeRequired
from app.core.security import InvalidSessionToken, decode_session_token
from app.db.session import get_db
from app.models import User, UserRole
from app.repositories.user_repository import UserRepository

# Marks a dependency produced by `require_role`.
ROLE_GUARD_ATTR = "_triageai_role_guard"

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True)
class SessionContext:
    """What the sliding-expiry middleware needs to re-issue the cookie."""

    user_id: uuid.UUID
    role: UserRole
    jti: str


def get_current_user(request: Request, db: DbSession) -> User:
    """Resolve the signed-in user, or raise 401 (FR-57, SR-01).

    A missing, malformed, or expired cookie, a user who has been deleted, and a
    deactivated account all fail the same way.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise NotAuthenticated()

    try:
        claims = decode_session_token(token)
        user_id = uuid.UUID(claims["sub"])
    except (InvalidSessionToken, ValueError) as error:
        raise NotAuthenticated() from error

    user = UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active:
        raise NotAuthenticated()

    # Tells `SessionCookieMiddleware` to refresh the cookie (SR-04).
    setattr(
        request.state,
        SESSION_STATE_ATTR,
        SessionContext(user_id=user.id, role=user.role, jti=claims["jti"]),
    )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(
    *roles: UserRole,
    kb_approver: bool = False,
    allow_password_change_pending: bool = False,
) -> Callable[[User], User]:
    """Build a dependency that admits only `roles`, and 403s otherwise (FR-59).

    `kb_approver=True` additionally requires the `can_approve_kb` permission,
    which only a Veterinary Reviewer can hold (BR-04, FR-58).

    `allow_password_change_pending=True` is set only by the `/auth/*` routes.
    Everywhere else a user who still has a temporary password is turned away
    with `PASSWORD_CHANGE_REQUIRED` (FR-61).
    """
    permitted = frozenset(roles)

    def dependency(user: CurrentUser) -> User:
        if user.must_change_password and not allow_password_change_pending:
            raise PasswordChangeRequired()
        if permitted and user.role not in permitted:
            raise Forbidden()
        if kb_approver and not user.can_approve_kb:
            raise Forbidden("Only an approved veterinary reviewer can do that.")
        return user

    setattr(dependency, ROLE_GUARD_ATTR, True)
    return dependency


# Any signed-in account, used by the `/auth` routes themselves.
ANY_ROLE: tuple[UserRole, ...] = (
    UserRole.INTAKE_STAFF,
    UserRole.VETERINARY_REVIEWER,
    UserRole.ADMINISTRATOR,
)
