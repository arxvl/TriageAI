"""Login, lockout, and password changes (FR-57, FR-61, FR-62, SR-02, SR-03, SR-12).

These are the safety tests CLAUDE.md §10 calls non-negotiable, so the lockout is
driven by an injected clock rather than by sleeping.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.errors import GENERIC_LOGIN_FAILURE_MESSAGE as GENERIC
from app.core.errors import (
    AccountLocked,
    CurrentPasswordIncorrect,
    InvalidCredentials,
    WeakPassword,
)
from app.core.security import LOCKOUT_MINUTES, MAX_FAILED_ATTEMPTS, verify_password
from app.models import AuditEntry, UserRole
from app.services.audit_service import UNKNOWN_ENTITY_ID, AuditAction
from app.services.auth_service import AuthService
from tests.conftest import audit_actions, make_user

PASSWORD = "Sampaguita2026"
WRONG_PASSWORD = "Sampaguita2027"

START = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


class FrozenClock:
    """A clock the test moves on purpose."""

    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


# --- Successful login -----------------------------------------------------


def test_correct_password_returns_the_user_and_records_the_login(db_session: Session) -> None:
    clock = FrozenClock()
    user = make_user(db_session, password=PASSWORD, failed_login_count=3)

    signed_in = AuthService(db_session, now=clock).authenticate(user.email, PASSWORD)

    assert signed_in.id == user.id
    assert signed_in.failed_login_count == 0
    assert signed_in.last_login_at == START
    assert audit_actions(db_session, user.id) == [AuditAction.LOGIN_SUCCESS]


def test_email_is_matched_ignoring_case_and_spaces(db_session: Session) -> None:
    user = make_user(db_session, email="intake@triageai.invalid", password=PASSWORD)

    signed_in = AuthService(db_session).authenticate("  Intake@TriageAI.invalid  ", PASSWORD)

    assert signed_in.id == user.id


# --- Failed login ---------------------------------------------------------


def test_wrong_password_raises_the_generic_error_and_counts_the_attempt(
    db_session: Session,
) -> None:
    user = make_user(db_session, password=PASSWORD)

    with pytest.raises(InvalidCredentials) as raised:
        AuthService(db_session).authenticate(user.email, WRONG_PASSWORD)

    assert raised.value.message == GENERIC
    assert user.failed_login_count == 1
    assert audit_actions(db_session, user.id) == [AuditAction.LOGIN_FAILURE]


def test_unknown_email_raises_the_same_error_and_is_still_audited(db_session: Session) -> None:
    """SR-12 wants the attempt recorded; ADR-11 wants the response to say nothing."""
    with pytest.raises(InvalidCredentials) as raised:
        AuthService(db_session).authenticate("nobody@triageai.invalid", PASSWORD)

    assert raised.value.message == GENERIC
    assert audit_actions(db_session) == [AuditAction.LOGIN_FAILURE]


def test_unknown_email_audit_row_names_the_attempted_address(db_session: Session) -> None:
    with pytest.raises(InvalidCredentials):
        AuthService(db_session).authenticate("Probe@TriageAI.invalid", PASSWORD)

    entry = db_session.query(AuditEntry).one()
    assert entry.entity_id == UNKNOWN_ENTITY_ID
    assert entry.after == {"email": "probe@triageai.invalid", "reason": "no_such_account"}


def test_inactive_account_raises_the_same_error_without_counting_a_failure(
    db_session: Session,
) -> None:
    user = make_user(db_session, password=PASSWORD, is_active=False)

    with pytest.raises(InvalidCredentials) as raised:
        AuthService(db_session).authenticate(user.email, PASSWORD)

    assert raised.value.message == GENERIC
    assert user.failed_login_count == 0


# --- Lockout (SR-03) ------------------------------------------------------


def test_failures_below_the_threshold_do_not_lock_the_account(db_session: Session) -> None:
    clock = FrozenClock()
    user = make_user(db_session, password=PASSWORD)
    service = AuthService(db_session, now=clock)

    for attempt in range(1, MAX_FAILED_ATTEMPTS):
        with pytest.raises(InvalidCredentials):
            service.authenticate(user.email, WRONG_PASSWORD)
        assert user.failed_login_count == attempt
        assert user.locked_until is None


def test_the_fifth_consecutive_failure_locks_the_account_for_fifteen_minutes(
    db_session: Session,
) -> None:
    clock = FrozenClock()
    user = make_user(db_session, password=PASSWORD, failed_login_count=MAX_FAILED_ATTEMPTS - 1)
    service = AuthService(db_session, now=clock)

    with pytest.raises(AccountLocked) as raised:
        service.authenticate(user.email, WRONG_PASSWORD)

    assert user.locked_until == START + timedelta(minutes=LOCKOUT_MINUTES)
    assert raised.value.status_code == 423
    assert user.locked_until.isoformat() in raised.value.message
    assert audit_actions(db_session, user.id) == [
        AuditAction.LOGIN_FAILURE,
        AuditAction.ACCOUNT_LOCKED,
    ]


def test_a_locked_account_rejects_even_the_correct_password(db_session: Session) -> None:
    clock = FrozenClock()
    user = make_user(
        db_session,
        password=PASSWORD,
        failed_login_count=MAX_FAILED_ATTEMPTS,
        locked_until=START + timedelta(minutes=LOCKOUT_MINUTES),
    )

    with pytest.raises(AccountLocked):
        AuthService(db_session, now=clock).authenticate(user.email, PASSWORD)


def test_a_locked_account_unlocks_once_the_time_passes(db_session: Session) -> None:
    clock = FrozenClock()
    user = make_user(
        db_session,
        password=PASSWORD,
        failed_login_count=MAX_FAILED_ATTEMPTS,
        locked_until=START + timedelta(minutes=LOCKOUT_MINUTES),
    )
    service = AuthService(db_session, now=clock)

    clock.advance(minutes=LOCKOUT_MINUTES + 1)
    signed_in = service.authenticate(user.email, PASSWORD)

    assert signed_in.id == user.id
    assert signed_in.locked_until is None
    assert signed_in.failed_login_count == 0


def test_an_expired_lock_does_not_excuse_a_wrong_password(db_session: Session) -> None:
    """The lock is cleared, then the attempt is judged on its own — and counted once."""
    clock = FrozenClock()
    user = make_user(
        db_session,
        password=PASSWORD,
        failed_login_count=MAX_FAILED_ATTEMPTS,
        locked_until=START + timedelta(minutes=LOCKOUT_MINUTES),
    )
    service = AuthService(db_session, now=clock)

    clock.advance(minutes=LOCKOUT_MINUTES + 1)
    with pytest.raises(InvalidCredentials):
        service.authenticate(user.email, WRONG_PASSWORD)

    assert user.failed_login_count == 1
    assert user.locked_until is None


def test_a_successful_login_resets_the_failure_counter(db_session: Session) -> None:
    user = make_user(db_session, password=PASSWORD)
    service = AuthService(db_session)

    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(InvalidCredentials):
            service.authenticate(user.email, WRONG_PASSWORD)
    service.authenticate(user.email, PASSWORD)

    assert user.failed_login_count == 0


# --- Logout (FR-62) -------------------------------------------------------


def test_logout_writes_an_audit_entry(db_session: Session) -> None:
    user = make_user(db_session, password=PASSWORD, role=UserRole.ADMINISTRATOR)

    AuthService(db_session).logout(user)

    assert audit_actions(db_session, user.id) == [AuditAction.LOGOUT]


# --- Password change (FR-61, SR-02) --------------------------------------


def test_change_password_replaces_the_hash_and_clears_the_forced_flag(
    db_session: Session,
) -> None:
    user = make_user(db_session, password=PASSWORD, must_change_password=True)
    new_password = "Tarsier-2026-Clinic"

    AuthService(db_session).change_password(user, PASSWORD, new_password)

    assert user.must_change_password is False
    assert verify_password(new_password, user.password_hash)
    assert verify_password(PASSWORD, user.password_hash) is False
    assert audit_actions(db_session, user.id) == [AuditAction.PASSWORD_CHANGED]


def test_change_password_rejects_a_wrong_current_password(db_session: Session) -> None:
    user = make_user(db_session, password=PASSWORD, must_change_password=True)

    with pytest.raises(CurrentPasswordIncorrect):
        AuthService(db_session).change_password(user, WRONG_PASSWORD, "Tarsier-2026-Clinic")

    assert user.must_change_password is True
    assert verify_password(PASSWORD, user.password_hash)


def test_change_password_enforces_the_policy(db_session: Session) -> None:
    user = make_user(db_session, password=PASSWORD, must_change_password=True)

    with pytest.raises(WeakPassword):
        AuthService(db_session).change_password(user, PASSWORD, "short1")

    assert user.must_change_password is True
    assert audit_actions(db_session, user.id) == []


def test_change_password_refuses_to_reuse_the_current_password(db_session: Session) -> None:
    user = make_user(db_session, password=PASSWORD, must_change_password=True)

    with pytest.raises(WeakPassword):
        AuthService(db_session).change_password(user, PASSWORD, PASSWORD)

    assert user.must_change_password is True
