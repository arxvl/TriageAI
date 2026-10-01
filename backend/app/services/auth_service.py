"""Login, logout, and password changes (FR-57, FR-61, FR-62, SR-02, SR-03, SR-12).

The service owns every rule a caller must not be able to skip: the generic
failure message, the failure counter, the 15-minute lockout, and the audit
entry for each outcome. It raises `AppError` subclasses and knows nothing about
HTTP (CLAUDE.md §7).

`now` is injectable so the lockout tests can let time pass without sleeping.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import NoReturn

from sqlalchemy.orm import Session

from app.core.errors import (
    AccountLocked,
    CurrentPasswordIncorrect,
    InvalidCredentials,
    WeakPassword,
)
from app.core.security import (
    LOCKOUT_MINUTES,
    MAX_FAILED_ATTEMPTS,
    hash_password,
    validate_password_policy,
    verify_password,
)
from app.models import User
from app.repositories.user_repository import UserRepository
from app.services.audit_service import UNKNOWN_ENTITY_ID, USER_ENTITY, AuditAction, AuditService

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def locked_message(unlock_at: datetime) -> str:
    """The 423 message, carrying the unlock time the login screen displays.

    The timestamp is ISO-8601 in UTC so the frontend can parse it and show it
    in Asia/Manila (CLAUDE.md §7).
    """
    return (
        f"Too many failed sign-in attempts. This account is locked until "
        f"{unlock_at.astimezone(UTC).isoformat()} and will unlock automatically."
    )


class AuthService:
    def __init__(self, session: Session, *, now: Clock | None = None) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._audit = AuditService(session)
        self._now = now or _utc_now

    # --- Login ------------------------------------------------------------

    def authenticate(self, email: str, password: str) -> User:
        """Return the user, or raise `InvalidCredentials` / `AccountLocked`.

        Every rejection other than a lockout raises the same error with the
        same message, so the endpoint cannot be used to tell an unknown address
        from a wrong password or a deactivated account (ADR-11).
        """
        now = self._now()
        user = self._users.get_by_email(email)

        if user is None:
            self._audit.record(
                action=AuditAction.LOGIN_FAILURE,
                entity_type=USER_ENTITY,
                entity_id=UNKNOWN_ENTITY_ID,
                after={"email": email.strip().lower(), "reason": "no_such_account"},
            )
            self._session.commit()
            raise InvalidCredentials()

        if user.locked_until is not None:
            if user.locked_until > now:
                raise AccountLocked(locked_message(user.locked_until))
            # The lock has expired: clear it and judge this attempt on its merits.
            user.locked_until = None
            user.failed_login_count = 0

        if not user.is_active:
            # Not counted as a failed attempt — there is no password to guess.
            self._audit.record(
                action=AuditAction.LOGIN_FAILURE,
                entity_type=USER_ENTITY,
                entity_id=str(user.id),
                user_id=user.id,
                role=user.role,
                after={"reason": "inactive"},
            )
            self._session.commit()
            raise InvalidCredentials()

        if not verify_password(password, user.password_hash):
            self._register_failed_attempt(user, now)

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        self._audit.record(
            action=AuditAction.LOGIN_SUCCESS,
            entity_type=USER_ENTITY,
            entity_id=str(user.id),
            user_id=user.id,
            role=user.role,
        )
        self._session.commit()
        return user

    def _register_failed_attempt(self, user: User, now: datetime) -> NoReturn:
        """Count the failure, lock the account on the fifth, and raise (SR-03)."""
        user.failed_login_count += 1
        self._audit.record(
            action=AuditAction.LOGIN_FAILURE,
            entity_type=USER_ENTITY,
            entity_id=str(user.id),
            user_id=user.id,
            role=user.role,
            after={"reason": "wrong_password", "failed_login_count": user.failed_login_count},
        )

        if user.failed_login_count >= MAX_FAILED_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            self._audit.record(
                action=AuditAction.ACCOUNT_LOCKED,
                entity_type=USER_ENTITY,
                entity_id=str(user.id),
                user_id=user.id,
                role=user.role,
                after={
                    "locked_until": user.locked_until.isoformat(),
                    "failed_login_count": user.failed_login_count,
                },
            )
            self._session.commit()
            raise AccountLocked(locked_message(user.locked_until))

        self._session.commit()
        raise InvalidCredentials()

    # --- Logout -----------------------------------------------------------

    def logout(self, user: User) -> None:
        """Audit the end of a session (FR-62, SR-12).

        Clearing the cookies is the endpoint's job; the token is stateless, so
        there is nothing server-side to revoke.
        """
        self._audit.record(
            action=AuditAction.LOGOUT,
            entity_type=USER_ENTITY,
            entity_id=str(user.id),
            user_id=user.id,
            role=user.role,
        )
        self._session.commit()

    # --- Password change --------------------------------------------------

    def change_password(self, user: User, current_password: str, new_password: str) -> User:
        """Replace the password, enforcing SR-02, and clear the first-login flag."""
        if not verify_password(current_password, user.password_hash):
            raise CurrentPasswordIncorrect()

        validate_password_policy(new_password)

        if verify_password(new_password, user.password_hash):
            raise WeakPassword("Choose a password you have not used for this account before.")

        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        self._audit.record(
            action=AuditAction.PASSWORD_CHANGED,
            entity_type=USER_ENTITY,
            entity_id=str(user.id),
            user_id=user.id,
            role=user.role,
        )
        self._session.commit()
        return user
