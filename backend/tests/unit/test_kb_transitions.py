"""Every allowed and forbidden knowledge-base transition (FR-51, ADR-14).

Exhaustive over `KBEntryStatus` x `KBEntryAction`, so a move added to the table
without being thought about fails here rather than in a demonstration. The two
properties that matter clinically:

* an ACTIVE entry can only be retired, never edited or resubmitted;
* nothing can be approved that was not submitted for review.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.core.errors import InvalidKBTransition
from app.models import KBEntryStatus, Species, UserRole, VTLCategory
from app.models.knowledge_base import RedFlagRule
from app.services.kb_transitions import (
    ENTRY_ACTION_FROM,
    ENTRY_ACTION_TO,
    KBEntryAction,
    require_entry_action_allowed,
    require_rule_editable,
    require_rule_retirable,
)
from tests.conftest import make_red_flag_rule, make_user

ALL_PAIRS = [(status, action) for status in KBEntryStatus for action in KBEntryAction]


@pytest.mark.parametrize(("status", "action"), ALL_PAIRS)
def test_every_pair_is_either_allowed_or_a_conflict(
    status: KBEntryStatus, action: KBEntryAction
) -> None:
    """One table decides, and it decides for every combination."""
    allowed = status in ENTRY_ACTION_FROM[action]

    if allowed:
        assert require_entry_action_allowed(status, action) == ENTRY_ACTION_TO.get(action)
        return

    with pytest.raises(InvalidKBTransition):
        require_entry_action_allowed(status, action)


@pytest.mark.parametrize(
    ("status", "action", "expected"),
    [
        (KBEntryStatus.DRAFT, KBEntryAction.SUBMIT, KBEntryStatus.PENDING_REVIEW),
        (KBEntryStatus.PENDING_REVIEW, KBEntryAction.REJECT, KBEntryStatus.DRAFT),
        (KBEntryStatus.ACTIVE, KBEntryAction.RETIRE, KBEntryStatus.RETIRED),
    ],
)
def test_the_lifecycle_moves(
    status: KBEntryStatus, action: KBEntryAction, expected: KBEntryStatus
) -> None:
    """Draft -> Pending review -> (Active) -> Retired, with rejection going back."""
    assert require_entry_action_allowed(status, action) is expected


@pytest.mark.parametrize("action", [KBEntryAction.EDIT, KBEntryAction.APPROVE])
def test_an_action_that_moves_nothing_returns_none(action: KBEntryAction) -> None:
    """An edit leaves the status alone; an approval only enqueues indexing (FR-53)."""
    status = next(iter(ENTRY_ACTION_FROM[action]))

    assert require_entry_action_allowed(status, action) is None


def test_an_active_entry_cannot_be_edited_and_the_message_says_why() -> None:
    """The one rule the whole versioning scheme rests on (ADR-14, DR-05)."""
    with pytest.raises(InvalidKBTransition) as error:
        require_entry_action_allowed(KBEntryStatus.ACTIVE, KBEntryAction.EDIT)

    assert "new draft revision" in error.value.message
    assert error.value.status_code == 409


def test_a_draft_cannot_be_approved() -> None:
    """Approval answers a submission; there is nothing here to answer (FR-52)."""
    with pytest.raises(InvalidKBTransition) as error:
        require_entry_action_allowed(KBEntryStatus.DRAFT, KBEntryAction.APPROVE)

    assert "not been submitted" in error.value.message


# --- Red-flag rules (NFR-08) ---------------------------------------------


def _rule(session: Session, code: str, **kwargs: object) -> RedFlagRule:
    return make_red_flag_rule(
        session,
        code=code,
        min_category=VTLCategory.ORANGE,
        species=(Species.CAT,),
        **kwargs,  # type: ignore[arg-type]
    )


def test_an_unapproved_rule_is_editable(db_session: Session) -> None:
    rule = _rule(db_session, "FIXTURE_EDITABLE")

    assert require_rule_editable(rule) is None


def test_an_approved_rule_cannot_be_edited(db_session: Session) -> None:
    """Editing an approved rule would change what a stored safety floor meant."""
    approver = make_user(db_session, role=UserRole.VETERINARY_REVIEWER, can_approve_kb=True)
    rule = _rule(db_session, "FIXTURE_APPROVED", approved_by=approver)

    with pytest.raises(InvalidKBTransition) as error:
        require_rule_editable(rule)

    assert "already been approved" in error.value.message


def test_a_retired_rule_cannot_be_edited_or_retired_again(db_session: Session) -> None:
    rule = _rule(db_session, "FIXTURE_RETIRED", retired_at=datetime.now(UTC))

    with pytest.raises(InvalidKBTransition):
        require_rule_editable(rule)
    with pytest.raises(InvalidKBTransition) as error:
        require_rule_retirable(rule)

    assert "already been retired" in error.value.message


def test_an_unretired_rule_can_be_retired(db_session: Session) -> None:
    rule = _rule(db_session, "FIXTURE_RETIRABLE")

    assert require_rule_retirable(rule) is None
