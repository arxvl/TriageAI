"""The single write path into the append-only audit log (FR-43, SR-12, ADR-12)."""

import uuid

from sqlalchemy.orm import Session

from app.models import AuditEntry, UserRole
from app.services.audit_service import USER_ENTITY, AuditAction, AuditService
from tests.conftest import make_user


def test_record_writes_every_field_it_is_given(db_session: Session) -> None:
    user = make_user(db_session, role=UserRole.VETERINARY_REVIEWER)

    entry = AuditService(db_session).record(
        action=AuditAction.LOGIN_SUCCESS,
        entity_type=USER_ENTITY,
        entity_id=str(user.id),
        user_id=user.id,
        role=user.role,
        before={"failed_login_count": 2},
        after={"failed_login_count": 0},
    )

    stored = db_session.get(AuditEntry, entry.id)
    assert stored is not None
    assert stored.action == "LOGIN_SUCCESS"
    assert stored.entity_type == USER_ENTITY
    assert stored.entity_id == str(user.id)
    assert stored.user_id == user.id
    assert stored.role is UserRole.VETERINARY_REVIEWER
    assert stored.before == {"failed_login_count": 2}
    assert stored.after == {"failed_login_count": 0}


def test_record_stamps_the_time_itself(db_session: Session) -> None:
    """`ts` comes from the database default, so a caller cannot backdate an entry."""
    entry = AuditService(db_session).record(
        action=AuditAction.LOGOUT, entity_type=USER_ENTITY, entity_id=str(uuid.uuid4())
    )

    assert entry.ts is not None


def test_record_allows_an_entry_with_no_user(db_session: Session) -> None:
    """A login attempt for an address with no account still has to be recorded."""
    entry = AuditService(db_session).record(
        action=AuditAction.LOGIN_FAILURE,
        entity_type=USER_ENTITY,
        entity_id="unknown",
        after={"email": "nobody@triageai.invalid"},
    )

    assert entry.user_id is None
    assert entry.role is None


def test_every_security_event_in_adr_11_has_an_action(db_session: Session) -> None:
    """ADR-11 names the five events the audit log must carry (SR-12)."""
    assert {action.value for action in AuditAction} >= {
        "LOGIN_SUCCESS",
        "LOGIN_FAILURE",
        "ACCOUNT_LOCKED",
        "LOGOUT",
        "PASSWORD_CHANGED",
    }
