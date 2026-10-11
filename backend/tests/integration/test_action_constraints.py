"""The two kinds of knowledge-base entry stay exclusive, in the database.

`kind` alone would be a convention. These constraints are what stops an
`URGENCY_ACTIONS` entry being written as though it were retrievable clinical
content, or two ACTIVE baseline sets existing for one category so that the
lookup in FR-72 becomes ambiguous (ADR-18 §2, DR-09).
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ActionSource,
    ActionSuggestion,
    KBEntryKind,
    KBEntryStatus,
    VTLCategory,
)
from tests.conftest import make_case, make_kb_entry, make_kb_version, make_recommendation
from tests.integration.test_constraints import seed_vignette

URGENCY_CHECK = "ck_kb_entries_urgency_category_iff_urgency_actions"
COMPLAINT_CHECK = "ck_kb_entries_complaint_code_iff_complaint"
ACTIVE_INDEX = "uq_kb_entries_active_urgency_actions"
SUGGESTION_CHECK = "ck_action_suggestions_case_xor_vignette"


# --- kb_entries: COMPLAINT xor URGENCY_ACTIONS ---------------------------


def test_a_valid_urgency_actions_entry_inserts(db_session: Session) -> None:
    entry = make_kb_entry(
        db_session,
        kind=KBEntryKind.URGENCY_ACTIONS,
        complaint_code=None,
        urgency_category=VTLCategory.RED,
        status=KBEntryStatus.ACTIVE,
    )

    assert entry.urgency_category is VTLCategory.RED
    assert entry.complaint_code is None


def test_a_valid_complaint_entry_inserts(db_session: Session) -> None:
    entry = make_kb_entry(db_session)

    assert entry.kind is KBEntryKind.COMPLAINT
    assert entry.urgency_category is None


def test_urgency_actions_entry_requires_a_category(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match=URGENCY_CHECK):
        make_kb_entry(
            db_session,
            kind=KBEntryKind.URGENCY_ACTIONS,
            complaint_code=None,
            urgency_category=None,
        )


def test_complaint_entry_may_not_carry_a_category(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match=URGENCY_CHECK):
        make_kb_entry(db_session, urgency_category=VTLCategory.GREEN)


def test_complaint_entry_requires_a_complaint_code(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match=COMPLAINT_CHECK):
        make_kb_entry(db_session, complaint_code=None)


def test_urgency_actions_entry_may_not_carry_a_complaint_code(db_session: Session) -> None:
    """A baseline set must not be able to masquerade as a retrievable entry."""
    with pytest.raises(IntegrityError, match=COMPLAINT_CHECK):
        make_kb_entry(
            db_session,
            kind=KBEntryKind.URGENCY_ACTIONS,
            complaint_code="LETHARGY",
            urgency_category=VTLCategory.BLUE,
        )


# --- one ACTIVE baseline set per category (FR-72) ------------------------


def test_a_second_active_set_for_the_same_category_is_rejected(db_session: Session) -> None:
    make_kb_entry(
        db_session,
        kind=KBEntryKind.URGENCY_ACTIONS,
        complaint_code=None,
        urgency_category=VTLCategory.ORANGE,
        status=KBEntryStatus.ACTIVE,
    )

    with pytest.raises(IntegrityError, match=ACTIVE_INDEX):
        make_kb_entry(
            db_session,
            kind=KBEntryKind.URGENCY_ACTIONS,
            complaint_code=None,
            urgency_category=VTLCategory.ORANGE,
            status=KBEntryStatus.ACTIVE,
            title="Second ORANGE set",
        )


def test_active_sets_for_different_categories_coexist(db_session: Session) -> None:
    for category in VTLCategory:
        make_kb_entry(
            db_session,
            kind=KBEntryKind.URGENCY_ACTIONS,
            complaint_code=None,
            urgency_category=category,
            status=KBEntryStatus.ACTIVE,
            title=f"{category.value} set",
        )


def test_a_draft_revision_of_an_active_set_is_allowed(db_session: Session) -> None:
    """The index is partial on purpose: the next revision is drafted alongside
    the one in use, and the approval workflow retires the old one (ADR-14)."""
    make_kb_entry(
        db_session,
        kind=KBEntryKind.URGENCY_ACTIONS,
        complaint_code=None,
        urgency_category=VTLCategory.YELLOW,
        status=KBEntryStatus.ACTIVE,
    )
    make_kb_entry(
        db_session,
        kind=KBEntryKind.URGENCY_ACTIONS,
        complaint_code=None,
        urgency_category=VTLCategory.YELLOW,
        status=KBEntryStatus.DRAFT,
        title="Next YELLOW revision",
    )


# --- action_suggestions: case xor vignette ------------------------------


def suggestion(**overrides: object) -> ActionSuggestion:
    values: dict[str, object] = {
        "generated_for_category": VTLCategory.GREEN,
        "rank": 1,
        "text": "Seat the owner in the waiting area.",
        "source": ActionSource.BASELINE,
        "cited_chunk_ids": [],
        "model_id": "mock",
        "prompt_version": "mock-0",
    }
    values.update(overrides)
    return ActionSuggestion(**values)


def test_action_suggestion_accepts_a_case(db_session: Session) -> None:
    case = make_case(db_session)
    recommendation = make_recommendation(db_session, case=case, category=VTLCategory.GREEN)
    make_kb_version(db_session)

    db_session.add(suggestion(case_id=case.id, recommendation_id=recommendation.id))
    db_session.flush()


def test_action_suggestion_rejects_both_case_and_vignette(db_session: Session) -> None:
    case = make_case(db_session)
    recommendation = make_recommendation(db_session, case=case, category=VTLCategory.GREEN)
    vignette_id = seed_vignette(db_session)

    db_session.add(
        suggestion(
            case_id=case.id,
            vignette_id=vignette_id,
            recommendation_id=recommendation.id,
        )
    )

    with pytest.raises(IntegrityError, match=SUGGESTION_CHECK):
        db_session.flush()


def test_action_suggestion_rejects_neither_case_nor_vignette(db_session: Session) -> None:
    case = make_case(db_session)
    recommendation = make_recommendation(db_session, case=case, category=VTLCategory.GREEN)

    db_session.add(suggestion(recommendation_id=recommendation.id))

    with pytest.raises(IntegrityError, match=SUGGESTION_CHECK):
        db_session.flush()


# --- the new job type exists (ADR-08) -----------------------------------


def test_suggest_actions_is_a_job_type_in_the_database(db_session: Session) -> None:
    values = set(
        db_session.execute(text("SELECT unnest(enum_range(NULL::job_type))::text")).scalars()
    )

    assert "SUGGEST_ACTIONS" in values


def test_recommendation_actions_status_defaults_to_pending(db_session: Session) -> None:
    """The actions job has not run yet when the recommendation is stored."""
    case = make_case(db_session)
    recommendation = make_recommendation(db_session, case=case, category=VTLCategory.RED)

    stored = db_session.execute(
        text(
            "SELECT actions_status::text, actions_error, actions_rejected_count "
            "FROM recommendations WHERE id = :id"
        ),
        {"id": recommendation.id},
    ).one()

    assert stored == ("PENDING", None, 0)
    assert isinstance(recommendation.id, uuid.UUID)
