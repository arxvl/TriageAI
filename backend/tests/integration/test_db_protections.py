"""The audit log and the owner's description are append-only (FR-05, FR-43, ADR-12).

Two layers are tested separately, because either one alone would be a weaker
guarantee:

* as `triageai_app` — the role the application connects as — the REVOKE denies
  the statement outright;
* as the database owner, whom no grant restricts, the `prevent_modify()`
  trigger rejects it.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from tests.conftest import insert_audit_entry, make_owner_description

PERMISSION_DENIED = "permission denied"
APPEND_ONLY = "append-only"


def assert_rejected(session: Session, statement: str, expected: str) -> None:
    """Run `statement` inside a savepoint and assert the database rejects it."""
    with pytest.raises(DBAPIError) as exc_info, session.begin_nested():
        session.execute(text(statement))

    assert expected in str(exc_info.value).lower()


# --- Layer 1: the restricted application role ----------------------------


def test_app_role_cannot_update_audit_log(db_session: Session) -> None:
    insert_audit_entry(db_session)

    assert_rejected(db_session, "UPDATE audit_log SET action = 'TAMPERED'", PERMISSION_DENIED)


def test_app_role_cannot_delete_from_audit_log(db_session: Session) -> None:
    insert_audit_entry(db_session)

    assert_rejected(db_session, "DELETE FROM audit_log", PERMISSION_DENIED)


def test_app_role_cannot_update_owner_descriptions(db_session: Session) -> None:
    make_owner_description(db_session)

    assert_rejected(
        db_session, "UPDATE owner_descriptions SET text = 'rewritten'", PERMISSION_DENIED
    )


def test_app_role_cannot_write_schema_history(db_session: Session) -> None:
    assert_rejected(db_session, "DELETE FROM alembic_version", PERMISSION_DENIED)


def test_app_role_can_append_to_audit_log(db_session: Session) -> None:
    """The revokes must not have taken away what AuditService needs."""
    entry_id = insert_audit_entry(db_session, action="CASE_CREATED")

    stored = db_session.execute(
        text("SELECT action FROM audit_log WHERE id = :id"), {"id": entry_id}
    ).scalar_one()
    assert stored == "CASE_CREATED"


def test_app_role_can_read_audit_log(db_session: Session) -> None:
    """The per-case audit timeline in W-07 needs SELECT (FR-45)."""
    insert_audit_entry(db_session)

    count = db_session.execute(text("SELECT count(*) FROM audit_log")).scalar_one()
    assert count >= 1


# --- Layer 2: the prevent_modify() trigger, which binds the owner too -----


def test_trigger_rejects_audit_log_update_even_for_owner(owner_session: Session) -> None:
    insert_audit_entry(owner_session)

    assert_rejected(owner_session, "UPDATE audit_log SET action = 'TAMPERED'", APPEND_ONLY)


def test_trigger_rejects_audit_log_delete_even_for_owner(owner_session: Session) -> None:
    insert_audit_entry(owner_session)

    assert_rejected(owner_session, "DELETE FROM audit_log", APPEND_ONLY)


def test_trigger_rejects_owner_description_update_even_for_owner(owner_session: Session) -> None:
    make_owner_description(owner_session)

    assert_rejected(owner_session, "UPDATE owner_descriptions SET text = 'rewritten'", APPEND_ONLY)


def test_trigger_rejects_kb_version_entries_update(db_session: Session) -> None:
    """`kb_version_entries` has no REVOKE, so the trigger is its only guard.

    A published KB version is immutable: changing an entry means a new version
    (ADR-14).
    """
    assert_rejected(
        db_session,
        "UPDATE kb_version_entries SET entry_id = entry_id",
        APPEND_ONLY,
    )


def test_trigger_rejects_update_matching_no_rows(owner_session: Session) -> None:
    """The trigger is statement-level, so the guarantee does not depend on
    whether the statement would have matched anything."""
    assert_rejected(
        owner_session,
        "UPDATE owner_descriptions SET text = 'rewritten' WHERE false",
        APPEND_ONLY,
    )


def test_owner_description_delete_is_not_blocked(owner_session: Session) -> None:
    """Only UPDATE is trapped on owner_descriptions (FR-05 is about rewriting).

    Deleting a case's description is not part of any workflow, but the
    protections must not accidentally cover more than the SRS asks for.
    """
    description = make_owner_description(owner_session)

    owner_session.execute(
        text("DELETE FROM owner_descriptions WHERE id = :id"), {"id": description.id}
    )


def test_prevent_modify_message_names_table_and_operation(owner_session: Session) -> None:
    insert_audit_entry(owner_session)

    with pytest.raises(ProgrammingError) as exc_info, owner_session.begin_nested():
        owner_session.execute(text("UPDATE audit_log SET action = 'TAMPERED'"))

    message = str(exc_info.value)
    assert "audit_log" in message
    assert "UPDATE" in message
    assert "ADR-12" in message
