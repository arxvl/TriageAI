"""The VTL constants match CLAUDE.md §6, and the overdue rule (FR-30).

These numbers are restated in the SRS, the wireframes and the frontend tokens, so
a silent edit here would show up as a wrong target time on screen long before
anyone traced it back. The table is asserted literally, value by value, rather
than derived from the module under test.
"""

import pytest

from app.core.vtl import (
    QUEUE_RANK,
    TARGET_MINUTES,
    URGENCY_ORDER,
    is_overdue,
    more_urgent,
    target_minutes,
)
from app.models import VTLCategory

# Straight from CLAUDE.md §6.
EXPECTED_TARGETS = {
    VTLCategory.RED: 0,
    VTLCategory.ORANGE: 15,
    VTLCategory.YELLOW: 60,
    VTLCategory.GREEN: 120,
    VTLCategory.BLUE: 240,
}


def test_target_minutes_match_the_domain_constants() -> None:
    assert TARGET_MINUTES == EXPECTED_TARGETS


def test_every_category_has_a_target() -> None:
    assert set(TARGET_MINUTES) == set(VTLCategory)


def test_urgency_order_runs_red_to_blue() -> None:
    assert URGENCY_ORDER == (
        VTLCategory.RED,
        VTLCategory.ORANGE,
        VTLCategory.YELLOW,
        VTLCategory.GREEN,
        VTLCategory.BLUE,
    )


def test_more_urgent_compares_in_that_order() -> None:
    assert more_urgent(VTLCategory.RED, VTLCategory.BLUE)
    assert more_urgent(VTLCategory.ORANGE, VTLCategory.YELLOW)
    assert not more_urgent(VTLCategory.GREEN, VTLCategory.ORANGE)
    assert not more_urgent(VTLCategory.RED, VTLCategory.RED)


def test_queue_rank_puts_uncategorised_cases_directly_below_red() -> None:
    """The one surprising part of FR-29, so it gets its own assertion."""
    assert QUEUE_RANK[VTLCategory.RED] < QUEUE_RANK[None] < QUEUE_RANK[VTLCategory.ORANGE]


def test_queue_rank_is_otherwise_the_urgency_order() -> None:
    ranked = [category for category in QUEUE_RANK if category is not None]
    assert sorted(ranked, key=lambda c: QUEUE_RANK[c]) == list(URGENCY_ORDER)


def test_queue_rank_values_are_distinct() -> None:
    assert len(set(QUEUE_RANK.values())) == len(QUEUE_RANK)


def test_a_case_with_no_category_has_no_target() -> None:
    assert target_minutes(None) is None


@pytest.mark.parametrize(
    ("category", "waiting", "expected"),
    [
        # Exactly at the target is not yet overdue; one minute past it is.
        (VTLCategory.YELLOW, 59, False),
        (VTLCategory.YELLOW, 60, False),
        (VTLCategory.YELLOW, 61, True),
        (VTLCategory.BLUE, 240, False),
        (VTLCategory.BLUE, 241, True),
        # RED's target is 0, so it is overdue from the first whole minute.
        (VTLCategory.RED, 0, False),
        (VTLCategory.RED, 1, True),
    ],
)
def test_overdue_boundary(category: VTLCategory, waiting: int, expected: bool) -> None:
    assert is_overdue(category, waiting) is expected


def test_a_case_with_no_category_is_never_overdue() -> None:
    """It is waiting for manual triage, not against a target (FR-29, FR-30)."""
    assert is_overdue(None, 10_000) is False
