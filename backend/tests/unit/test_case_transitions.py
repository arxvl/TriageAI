"""The allowed-status table for decisions and closing (FR-32..FR-38, FR-48).

These are the non-negotiable safety tests (CLAUDE.md §10). The table is small
enough to assert exhaustively, so it is: every (status, decision type) pair is
checked, which is what stops a later edit from quietly widening one row.
"""

import pytest

from app.core.errors import AmendmentRequired, InvalidCaseTransition
from app.models import CaseStatus, DecisionDirection, DecisionType, VTLCategory
from app.services.case_transitions import (
    DECIDED_STATUSES,
    DECISION_FROM,
    DECISION_TO,
    direction,
    require_closable,
    require_decision_allowed,
)

ALL_STATUSES = tuple(CaseStatus)
ALL_TYPES = tuple(DecisionType)


# --- The table itself -----------------------------------------------------


def test_every_decision_type_has_a_source_set_and_a_destination() -> None:
    """A type missing from either map would raise KeyError at decision time."""
    assert set(DECISION_FROM) == set(ALL_TYPES)
    assert set(DECISION_TO) == set(ALL_TYPES)


def test_every_decision_lands_on_a_decided_status() -> None:
    """A decision that left the case undecided would break NFR-07's guarantee."""
    assert set(DECISION_TO.values()) == DECIDED_STATUSES


def test_no_decision_may_be_made_from_a_decided_or_closed_status() -> None:
    """A first decision is only ever made on an undecided, open case (FR-48)."""
    forbidden = DECIDED_STATUSES | {CaseStatus.CLOSED}
    for allowed in DECISION_FROM.values():
        assert not allowed & forbidden


# --- First decisions ------------------------------------------------------


@pytest.mark.parametrize(
    ("decision_type", "status", "expected"),
    [
        (DecisionType.CONFIRM, CaseStatus.AWAITING_REVIEW, CaseStatus.CONFIRMED),
        (DecisionType.ADJUST, CaseStatus.AWAITING_REVIEW, CaseStatus.ADJUSTED),
        (DecisionType.MANUAL, CaseStatus.AWAITING_REVIEW, CaseStatus.MANUALLY_TRIAGED),
        (
            DecisionType.MANUAL,
            CaseStatus.MANUAL_TRIAGE_REQUIRED,
            CaseStatus.MANUALLY_TRIAGED,
        ),
    ],
)
def test_an_allowed_decision_returns_the_status_it_moves_to(
    decision_type: DecisionType, status: CaseStatus, expected: CaseStatus
) -> None:
    assert require_decision_allowed(status, decision_type, is_amendment=False) is expected


def test_manual_triage_is_available_before_a_failure_too() -> None:
    """FR-34 and ADR-15 §4: at any time, not only when the AI failed."""
    assert CaseStatus.AWAITING_REVIEW in DECISION_FROM[DecisionType.MANUAL]


@pytest.mark.parametrize("decision_type", ALL_TYPES)
@pytest.mark.parametrize(
    "status",
    [CaseStatus.SUBMITTED, CaseStatus.PROCESSING],
)
def test_no_decision_is_allowed_while_the_case_is_still_being_processed(
    status: CaseStatus, decision_type: DecisionType
) -> None:
    """There is nothing to confirm, adjust or override yet."""
    with pytest.raises(InvalidCaseTransition):
        require_decision_allowed(status, decision_type, is_amendment=False)


@pytest.mark.parametrize("decision_type", [DecisionType.CONFIRM, DecisionType.ADJUST])
def test_confirm_and_adjust_need_a_recommendation_to_speak_about(
    decision_type: DecisionType,
) -> None:
    """From MANUAL_TRIAGE_REQUIRED there is no AI category to accept or depart
    from, and the message says to use manual triage instead."""
    with pytest.raises(InvalidCaseTransition) as raised:
        require_decision_allowed(
            CaseStatus.MANUAL_TRIAGE_REQUIRED, decision_type, is_amendment=False
        )
    assert "manual triage" in raised.value.message


@pytest.mark.parametrize("decision_type", ALL_TYPES)
@pytest.mark.parametrize("status", sorted(DECIDED_STATUSES))
def test_a_second_plain_decision_asks_for_an_amendment(
    status: CaseStatus, decision_type: DecisionType
) -> None:
    """FR-48: a decided case is changed by amendment, never by a second
    decision that would silently replace the first."""
    with pytest.raises(AmendmentRequired) as raised:
        require_decision_allowed(status, decision_type, is_amendment=False)
    assert raised.value.status_code == 409
    assert raised.value.code == "AMENDMENT_REQUIRED"


@pytest.mark.parametrize("decision_type", ALL_TYPES)
def test_a_closed_case_cannot_be_decided_again(decision_type: DecisionType) -> None:
    with pytest.raises(InvalidCaseTransition) as raised:
        require_decision_allowed(CaseStatus.CLOSED, decision_type, is_amendment=False)
    assert "closed" in raised.value.message.lower()


@pytest.mark.parametrize("decision_type", ALL_TYPES)
@pytest.mark.parametrize("status", ALL_STATUSES)
def test_the_table_is_the_only_thing_that_allows_a_decision(
    status: CaseStatus, decision_type: DecisionType
) -> None:
    """Exhaustive: a pair in `DECISION_FROM` succeeds and every other pair
    raises. This is the test a future edit to the table has to get past."""
    allowed = status in DECISION_FROM[decision_type]
    if allowed:
        assert (
            require_decision_allowed(status, decision_type, is_amendment=False)
            is DECISION_TO[decision_type]
        )
        return
    with pytest.raises((InvalidCaseTransition, AmendmentRequired)):
        require_decision_allowed(status, decision_type, is_amendment=False)


# --- Amendments -----------------------------------------------------------


@pytest.mark.parametrize("decision_type", ALL_TYPES)
@pytest.mark.parametrize("status", sorted(DECIDED_STATUSES))
def test_an_amendment_is_allowed_from_any_decided_status(
    status: CaseStatus, decision_type: DecisionType
) -> None:
    assert (
        require_decision_allowed(status, decision_type, is_amendment=True)
        is DECISION_TO[decision_type]
    )


@pytest.mark.parametrize("decision_type", ALL_TYPES)
@pytest.mark.parametrize(
    "status",
    [
        CaseStatus.SUBMITTED,
        CaseStatus.PROCESSING,
        CaseStatus.AWAITING_REVIEW,
        CaseStatus.MANUAL_TRIAGE_REQUIRED,
    ],
)
def test_there_is_nothing_to_amend_before_a_decision(
    status: CaseStatus, decision_type: DecisionType
) -> None:
    with pytest.raises(InvalidCaseTransition) as raised:
        require_decision_allowed(status, decision_type, is_amendment=True)
    assert "nothing to amend" in raised.value.message


@pytest.mark.parametrize("decision_type", ALL_TYPES)
def test_a_closed_case_cannot_be_amended_either(decision_type: DecisionType) -> None:
    """The closed check comes first, so closing is final whichever way in."""
    with pytest.raises(InvalidCaseTransition):
        require_decision_allowed(CaseStatus.CLOSED, decision_type, is_amendment=True)


# --- Closing (FR-38) ------------------------------------------------------


@pytest.mark.parametrize("status", sorted(DECIDED_STATUSES))
def test_a_decided_case_may_be_closed(status: CaseStatus) -> None:
    require_closable(status)


@pytest.mark.parametrize(
    "status",
    [
        CaseStatus.SUBMITTED,
        CaseStatus.PROCESSING,
        CaseStatus.AWAITING_REVIEW,
        CaseStatus.MANUAL_TRIAGE_REQUIRED,
    ],
)
def test_an_undecided_case_cannot_be_closed(status: CaseStatus) -> None:
    """A patient must not leave the working list with no recorded urgency."""
    with pytest.raises(InvalidCaseTransition) as raised:
        require_closable(status)
    assert "before closing" in raised.value.message
    assert raised.value.status_code == 409


def test_closing_a_closed_case_says_so() -> None:
    with pytest.raises(InvalidCaseTransition) as raised:
        require_closable(CaseStatus.CLOSED)
    assert "already closed" in raised.value.message


# --- Direction (FR-42, BR-03) ---------------------------------------------


@pytest.mark.parametrize(
    ("recommended", "final", "expected"),
    [
        (VTLCategory.ORANGE, VTLCategory.RED, DecisionDirection.UP),
        (VTLCategory.BLUE, VTLCategory.GREEN, DecisionDirection.UP),
        (VTLCategory.YELLOW, VTLCategory.GREEN, DecisionDirection.DOWN),
        (VTLCategory.RED, VTLCategory.BLUE, DecisionDirection.DOWN),
        (VTLCategory.YELLOW, VTLCategory.YELLOW, DecisionDirection.SAME),
    ],
)
def test_direction_reports_which_way_the_reviewer_moved(
    recommended: VTLCategory, final: VTLCategory, expected: DecisionDirection
) -> None:
    assert direction(recommended, final) is expected


@pytest.mark.parametrize("final", list(VTLCategory))
def test_a_case_with_no_recommendation_has_no_direction(final: VTLCategory) -> None:
    """NONE, not SAME: counting a manual triage after an AI failure as agreement
    would overstate how often the model was right (FR-46)."""
    assert direction(None, final) is DecisionDirection.NONE
