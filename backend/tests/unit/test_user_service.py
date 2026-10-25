"""Account administration rules (FR-60, FR-63, SR-03, BR-04).

The last-administrator guard and the knowledge-base approval rule are the safety
logic here, so they have explicit tests (CLAUDE.md §10).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    EmailAlreadyInUse,
    InvalidUserUpdate,
    LastAdministrator,
    UserNotFound,
)
from app.core.security import verify_password
from app.models import AuditEntry, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserFilters, UserUpdate
from app.services.audit_service import AuditAction
from app.services.user_service import UserService
from tests.conftest import audit_actions, make_user


def new_user(**overrides: object) -> UserCreate:
    fields: dict[str, object] = {
        "full_name": "Maria Santos",
        "email": "maria.santos@triageai.invalid",
        "role": UserRole.INTAKE_STAFF,
        "can_approve_kb": False,
    }
    fields.update(overrides)
    return UserCreate.model_validate(fields)


def audit_rows(session: Session) -> list[AuditEntry]:
    return list(session.execute(select(AuditEntry).order_by(AuditEntry.id)).scalars())


# --- Creating -------------------------------------------------------------


def test_create_returns_the_password_once_and_stores_only_its_hash(db_session: Session) -> None:
    admin = make_user(db_session, role=UserRole.ADMINISTRATOR)

    result = UserService(db_session).create_user(new_user(), admin)

    stored = result.user
    assert len(result.temporary_password) == 16
    assert not hasattr(stored, "temporary_password")
    row = UserRepository(db_session).get_by_id(stored.id)
    assert row is not None
    assert row.password_hash != result.temporary_password
    assert verify_password(result.temporary_password, row.password_hash)
    assert row.must_change_password is True
    assert row.is_active is True


def test_create_normalises_the_email_and_rejects_a_duplicate_ignoring_case(
    db_session: Session,
) -> None:
    admin = make_user(db_session, role=UserRole.ADMINISTRATOR)
    service = UserService(db_session)
    created = service.create_user(new_user(email="  Maria.Santos@TriageAI.invalid "), admin)

    assert created.user.email == "maria.santos@triageai.invalid"
    with pytest.raises(EmailAlreadyInUse):
        service.create_user(new_user(email="MARIA.SANTOS@triageai.invalid"), admin)


@pytest.mark.parametrize("role", [UserRole.INTAKE_STAFF, UserRole.ADMINISTRATOR])
def test_create_refuses_kb_approval_for_anyone_but_a_reviewer(
    db_session: Session, role: UserRole
) -> None:
    admin = make_user(db_session, role=UserRole.ADMINISTRATOR)

    with pytest.raises(InvalidUserUpdate) as raised:
        UserService(db_session).create_user(new_user(role=role, can_approve_kb=True), admin)

    assert raised.value.field == "can_approve_kb"


def test_create_grants_kb_approval_to_a_reviewer(db_session: Session) -> None:
    admin = make_user(db_session, role=UserRole.ADMINISTRATOR)

    result = UserService(db_session).create_user(
        new_user(role=UserRole.VETERINARY_REVIEWER, can_approve_kb=True), admin
    )

    assert result.user.can_approve_kb is True


# --- Updating: approval permission ---------------------------------------


def test_update_cannot_move_an_approver_off_reviewer_without_clearing_the_flag(
    db_session: Session,
) -> None:
    admin = make_user(db_session, role=UserRole.ADMINISTRATOR)
    approver = make_user(db_session, role=UserRole.VETERINARY_REVIEWER, can_approve_kb=True)

    with pytest.raises(InvalidUserUpdate):
        UserService(db_session).update_user(
            approver.id, UserUpdate(role=UserRole.INTAKE_STAFF), admin
        )

    result = UserService(db_session).update_user(
        approver.id, UserUpdate(role=UserRole.INTAKE_STAFF, can_approve_kb=False), admin
    )
    assert result.role is UserRole.INTAKE_STAFF
    assert result.can_approve_kb is False


def test_update_cannot_grant_kb_approval_to_intake_staff(db_session: Session) -> None:
    admin = make_user(db_session, role=UserRole.ADMINISTRATOR)
    staff = make_user(db_session)

    with pytest.raises(InvalidUserUpdate):
        UserService(db_session).update_user(staff.id, UserUpdate(can_approve_kb=True), admin)


# --- Updating: the last administrator ------------------------------------


def test_the_last_active_administrator_cannot_be_deactivated(db_session: Session) -> None:
    only_admin = make_user(db_session, role=UserRole.ADMINISTRATOR)

    with pytest.raises(LastAdministrator):
        UserService(db_session).update_user(only_admin.id, UserUpdate(is_active=False), only_admin)

    assert only_admin.is_active is True


def test_the_last_active_administrator_cannot_be_demoted(db_session: Session) -> None:
    only_admin = make_user(db_session, role=UserRole.ADMINISTRATOR)

    with pytest.raises(LastAdministrator):
        UserService(db_session).update_user(
            only_admin.id, UserUpdate(role=UserRole.INTAKE_STAFF), only_admin
        )

    assert only_admin.role is UserRole.ADMINISTRATOR


def test_an_inactive_administrator_does_not_count_as_a_second_one(db_session: Session) -> None:
    only_active = make_user(db_session, role=UserRole.ADMINISTRATOR)
    make_user(db_session, role=UserRole.ADMINISTRATOR, is_active=False)

    with pytest.raises(LastAdministrator):
        UserService(db_session).update_user(
            only_active.id, UserUpdate(is_active=False), only_active
        )


def test_an_administrator_can_be_deactivated_or_demoted_when_another_is_active(
    db_session: Session,
) -> None:
    first = make_user(db_session, role=UserRole.ADMINISTRATOR)
    second = make_user(db_session, role=UserRole.ADMINISTRATOR)
    service = UserService(db_session)

    deactivated = service.update_user(first.id, UserUpdate(is_active=False), second)
    assert deactivated.is_active is False

    # `second` is now the last one again.
    with pytest.raises(LastAdministrator):
        service.update_user(second.id, UserUpdate(role=UserRole.INTAKE_STAFF), second)


def test_reactivating_and_renaming_an_administrator_is_never_blocked(
    db_session: Session,
) -> None:
    only_admin = make_user(db_session, role=UserRole.ADMINISTRATOR)

    result = UserService(db_session).update_user(
        only_admin.id, UserUpdate(full_name="Ana Reyes", is_active=True), only_admin
    )

    assert result.full_name == "Ana Reyes"


def test_update_of_an_unknown_user_is_not_found(db_session: Session) -> None:
    admin = make_user(db_session, role=UserRole.ADMINISTRATOR)

    with pytest.raises(UserNotFound):
        UserService(db_session).update_user(uuid.uuid4(), UserUpdate(is_active=False), admin)


# --- Unlock and reset ------------------------------------------------------


def test_unlock_clears_the_counter_and_the_lock(db_session: Session) -> None:
    admin = make_user(db_session, role=UserRole.ADMINISTRATOR)
    locked = make_user(
        db_session,
        failed_login_count=5,
        locked_until=datetime.now(UTC) + timedelta(minutes=10),
    )

    result = UserService(db_session).unlock_user(locked.id, admin)

    assert result.locked_until is None
    assert locked.failed_login_count == 0


def test_reset_issues_a_new_password_forces_a_change_and_unlocks(db_session: Session) -> None:
    admin = make_user(db_session, role=UserRole.ADMINISTRATOR)
    target = make_user(
        db_session,
        password="Sampaguita2026",
        failed_login_count=5,
        locked_until=datetime.now(UTC) + timedelta(minutes=10),
    )
    old_hash = target.password_hash

    result = UserService(db_session).reset_password(target.id, admin)

    assert len(result.temporary_password) == 16
    assert target.password_hash != old_hash
    assert verify_password(result.temporary_password, target.password_hash)
    assert not verify_password("Sampaguita2026", target.password_hash)
    assert target.must_change_password is True
    assert target.locked_until is None
    assert target.failed_login_count == 0


# --- Search ----------------------------------------------------------------


def test_list_searches_name_and_email_and_treats_wildcards_literally(
    db_session: Session,
) -> None:
    make_user(db_session, full_name="Maria Santos", email="m.santos@triageai.invalid")
    make_user(db_session, full_name="Jun Cruz", email="jun_cruz@triageai.invalid")
    service = UserService(db_session)

    by_name = service.list_users(UserFilters(q="santos"))
    by_email = service.list_users(UserFilters(q="JUN_CRUZ"))
    wildcard = service.list_users(UserFilters(q="%"))

    assert [u.full_name for u in by_name.items] == ["Maria Santos"]
    assert [u.full_name for u in by_email.items] == ["Jun Cruz"]
    assert wildcard.items == []


# --- Audit ------------------------------------------------------------------


def test_every_change_is_audited_without_any_password_material(db_session: Session) -> None:
    admin = make_user(db_session, role=UserRole.ADMINISTRATOR)
    other_admin = make_user(db_session, role=UserRole.ADMINISTRATOR)
    service = UserService(db_session)

    created = service.create_user(new_user(), admin)
    service.update_user(created.user.id, UserUpdate(role=UserRole.VETERINARY_REVIEWER), admin)
    service.unlock_user(created.user.id, other_admin)
    reset = service.reset_password(created.user.id, admin)

    assert audit_actions(db_session) == [
        AuditAction.USER_CREATED,
        AuditAction.USER_UPDATED,
        AuditAction.USER_UNLOCKED,
        AuditAction.USER_PASSWORD_RESET,
    ]
    rows = audit_rows(db_session)
    assert [row.user_id for row in rows] == [admin.id, admin.id, other_admin.id, admin.id]
    assert all(row.entity_id == str(created.user.id) for row in rows)
    assert rows[1].before == {"role": "INTAKE_STAFF"}
    assert rows[1].after["role"] == "VETERINARY_REVIEWER"

    dump = json.dumps([(row.before, row.after) for row in rows])
    assert created.temporary_password not in dump
    assert reset.temporary_password not in dump
    assert "argon2" not in dump
    assert "password_hash" not in dump
