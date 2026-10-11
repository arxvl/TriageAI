"""A finalized action list is append-only (DR-09, ADR-12).

The same two layers as `test_db_protections.py`: the REVOKE stops the
application role, the `prevent_modify()` trigger stops the database owner too.
A reviewer who changes their mind records a new decision with new rows; the
original list stays readable exactly as it was acted on (FR-76).
"""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import ActionSource, ActionStatus, DecisionType, UserRole, VTLCategory
from tests.conftest import make_case, make_staff_decision, make_user
from tests.integration.test_db_protections import (
    APPEND_ONLY,
    PERMISSION_DENIED,
    assert_rejected,
)

INSERT_FINAL_ACTION = (
    "INSERT INTO final_actions (id, case_id, decision_id, rank, text, source, status, "
    "suggestion_id, finalized_by, finalized_at) VALUES (gen_random_uuid(), :case_id, "
    ":decision_id, 1, :text, :source, :status, NULL, :user_id, :finalized_at) RETURNING id"
)


def insert_final_action(session: Session) -> None:
    """Write one finalized action through the same path the reviewer flow will.

    Raw SQL, not the model: the point here is what the database permits, and the
    service that will own this write is P06's.
    """
    reviewer = make_user(session, role=UserRole.VETERINARY_REVIEWER)
    case = make_case(session)
    decision = make_staff_decision(
        session,
        case=case,
        final_category=VTLCategory.GREEN,
        decision_type=DecisionType.CONFIRM,
        decided_by=reviewer,
    )
    session.execute(
        text(INSERT_FINAL_ACTION),
        {
            "case_id": case.id,
            "decision_id": decision.id,
            "text": "Seat the owner in the waiting area.",
            "source": ActionSource.BASELINE.value,
            "status": ActionStatus.KEPT.value,
            "user_id": reviewer.id,
            "finalized_at": datetime.now(UTC),
        },
    )


# --- Layer 1: the restricted application role ----------------------------


def test_app_role_can_append_a_final_action(db_session: Session) -> None:
    """The revokes must not have taken away what the finalize flow needs."""
    insert_final_action(db_session)

    count = db_session.execute(text("SELECT count(*) FROM final_actions")).scalar_one()
    assert count == 1


def test_app_role_cannot_update_final_actions(db_session: Session) -> None:
    insert_final_action(db_session)

    assert_rejected(db_session, "UPDATE final_actions SET rank = 2", PERMISSION_DENIED)


def test_app_role_cannot_delete_from_final_actions(db_session: Session) -> None:
    insert_final_action(db_session)

    assert_rejected(db_session, "DELETE FROM final_actions", PERMISSION_DENIED)


# --- Layer 2: the trigger, which binds the owner too ---------------------


def test_trigger_rejects_final_action_update_even_for_owner(owner_session: Session) -> None:
    insert_final_action(owner_session)

    assert_rejected(owner_session, "UPDATE final_actions SET rank = 2", APPEND_ONLY)


def test_trigger_rejects_final_action_delete_even_for_owner(owner_session: Session) -> None:
    insert_final_action(owner_session)

    assert_rejected(owner_session, "DELETE FROM final_actions", APPEND_ONLY)


def test_trigger_rejects_an_update_matching_no_rows(owner_session: Session) -> None:
    """Statement-level, so the guarantee does not depend on table contents."""
    assert_rejected(
        owner_session,
        "UPDATE final_actions SET rank = 2 WHERE false",
        APPEND_ONLY,
    )


# --- action_suggestions is not append-only -------------------------------


def test_action_suggestions_stays_writable(db_session: Session) -> None:
    """A retried actions job replaces its previous rows (P05b §5b.3), so this
    table deliberately has no REVOKE and no trigger."""
    update = db_session.execute(
        text("SELECT has_table_privilege('triageai_app', 'action_suggestions', 'UPDATE')")
    ).scalar_one()
    delete = db_session.execute(
        text("SELECT has_table_privilege('triageai_app', 'action_suggestions', 'DELETE')")
    ).scalar_one()

    assert update is True
    assert delete is True
