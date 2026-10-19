"""The baseline action lookup (P05b §5b.2, FR-71, FR-72, ADR-18 §2).

`baseline_actions` is the half of the actions feature that must never fail. It
reads curated content, not model output, so it is what lets every one of the five
VTL categories show something useful with the language model switched off
entirely — or unavailable mid-demonstration.

Against a real database, because what is being asserted is the lookup: ACTIVE
only, pinned to one knowledge-base version, and the partial unique index behind
it (FR-54, ADR-14).

All data here is fictitious (CLAUDE.md §9).
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KBEntry, KBEntryKind, KBEntryStatus, KBVersion, UserRole, VTLCategory
from app.pipeline.action_validator import baseline_actions
from app.services.kb_indexing import run_kb_index
from app.services.kb_service import KBService
from scripts.seed import SEED_KB_VERSION_NO, URGENCY_ACTIONS, seed
from tests.conftest import baseline_actions_content, make_kb_entry, make_kb_version, make_user

VALIDATOR_LOGGER = "app.pipeline.action_validator"


def seed_kb_version_id(session: Session) -> uuid.UUID:
    return session.execute(
        select(KBVersion.id).where(KBVersion.version_no == SEED_KB_VERSION_NO)
    ).scalar_one()


def make_baseline_entry(
    session: Session,
    *,
    category: VTLCategory,
    content: str,
    status: KBEntryStatus = KBEntryStatus.ACTIVE,
    kb_version: KBVersion | None = None,
) -> KBEntry:
    return make_kb_entry(
        session,
        kind=KBEntryKind.URGENCY_ACTIONS,
        complaint_code=None,
        urgency_category=category,
        status=status,
        title="Fixture baseline actions",
        content=content,
        kb_version=kb_version,
    )


def test_every_category_has_baseline_actions(db_session: Session) -> None:
    """FR-71: all five categories, on mocks, with no model involved."""
    seed(db_session)
    kb_version_id = seed_kb_version_id(db_session)

    for category in VTLCategory:
        assert baseline_actions(db_session, category, kb_version_id)


def test_baseline_actions_match_the_seeded_content(db_session: Session) -> None:
    seed(db_session)
    kb_version_id = seed_kb_version_id(db_session)

    for category, _title, actions in URGENCY_ACTIONS:
        assert baseline_actions(db_session, category, kb_version_id) == list(actions)


def test_blank_lines_and_surrounding_space_are_dropped(db_session: Session) -> None:
    """One action per line, and nothing else (`scripts/seed.py` writes them)."""
    version = make_kb_version(db_session, version_no=7)
    make_baseline_entry(
        db_session,
        category=VTLCategory.RED,
        content="  Alert the veterinarian immediately.  \n\n\nPrepare oxygen.\n",
        kb_version=version,
    )

    assert baseline_actions(db_session, VTLCategory.RED, version.id) == [
        "Alert the veterinarian immediately.",
        "Prepare oxygen.",
    ]


def test_a_missing_entry_returns_empty_and_logs_a_warning(db_session: Session, caplog) -> None:
    """A knowledge-base gap is content to fill in M5, never a failed job (FR-77)."""
    version = make_kb_version(db_session, version_no=7)

    with caplog.at_level(logging.WARNING, logger=VALIDATOR_LOGGER):
        assert baseline_actions(db_session, VTLCategory.BLUE, version.id) == []

    records = [record for record in caplog.records if record.name == VALIDATOR_LOGGER]
    assert len(records) == 1
    message = records[0].getMessage()
    assert VTLCategory.BLUE.value in message
    assert str(version.id) in message


def test_a_draft_entry_is_not_returned(db_session: Session) -> None:
    """Only approved content is shown; DRAFT is what P08's workflow starts from."""
    version = make_kb_version(db_session, version_no=7)
    make_baseline_entry(
        db_session,
        category=VTLCategory.RED,
        content="Alert the veterinarian immediately.",
        status=KBEntryStatus.DRAFT,
        kb_version=version,
    )

    assert baseline_actions(db_session, VTLCategory.RED, version.id) == []


def test_a_retired_entry_is_not_returned(db_session: Session) -> None:
    version = make_kb_version(db_session, version_no=7)
    make_baseline_entry(
        db_session,
        category=VTLCategory.RED,
        content="Alert the veterinarian immediately.",
        status=KBEntryStatus.RETIRED,
        kb_version=version,
    )

    assert baseline_actions(db_session, VTLCategory.RED, version.id) == []


def test_an_entry_in_another_kb_version_is_not_returned(db_session: Session) -> None:
    """A run pinned to version 7 must not read version 8's content (ADR-14)."""
    pinned = make_kb_version(db_session, version_no=7)
    other = make_kb_version(db_session, version_no=8)
    make_baseline_entry(
        db_session,
        category=VTLCategory.ORANGE,
        content="Tell the veterinarian the patient is waiting.",
        kb_version=other,
    )

    assert baseline_actions(db_session, VTLCategory.ORANGE, pinned.id) == []
    assert baseline_actions(db_session, VTLCategory.ORANGE, other.id) == [
        "Tell the veterinarian the patient is waiting."
    ]


def test_only_the_asked_for_category_is_returned(db_session: Session) -> None:
    version = make_kb_version(db_session, version_no=7)
    make_baseline_entry(
        db_session,
        category=VTLCategory.RED,
        content="Move the patient to the treatment area now.",
        kb_version=version,
    )
    make_baseline_entry(
        db_session,
        category=VTLCategory.GREEN,
        content="Seat the owner in the waiting area.",
        kb_version=version,
    )

    assert baseline_actions(db_session, VTLCategory.RED, version.id) == [
        "Move the patient to the treatment area now."
    ]
    assert baseline_actions(db_session, VTLCategory.GREEN, version.id) == [
        "Seat the owner in the waiting area."
    ]


# --- Through the approval workflow (P08 §8.2b) ----------------------------


def test_an_approved_baseline_set_replaces_the_one_it_revises(
    db_session: Session, pipeline
) -> None:
    """The replacement path M5 Part D walks, end to end (FR-72, ADR-18).

    Retire the live set, approve the replacement, and the lookup pinned to the
    new version reads the new actions. The warning on the retirement is the gap
    in between: between those two steps the category has no baseline actions at
    all, which is exactly what the warning says.
    """
    approver = make_user(db_session, role=UserRole.VETERINARY_REVIEWER, can_approve_kb=True)
    admin = make_user(db_session, role=UserRole.ADMINISTRATOR, email="curator@triageai.invalid")
    version_zero = make_kb_version(db_session)
    live = make_baseline_entry(
        db_session,
        category=VTLCategory.ORANGE,
        content="Tell the veterinarian the patient is waiting.",
        kb_version=version_zero,
    )
    replacement = make_kb_entry(
        db_session,
        kind=KBEntryKind.URGENCY_ACTIONS,
        complaint_code=None,
        urgency_category=VTLCategory.ORANGE,
        status=KBEntryStatus.PENDING_REVIEW,
        slug="actions-orange",
        title="Suggested staff actions - Orange",
        content=baseline_actions_content(3),
        with_source=True,
    )
    service = KBService(db_session, indexer=pipeline.kb_indexer)

    retirement = service.retire_entry(live.id, admin)
    assert retirement.warning is not None

    result = run_kb_index(
        db_session, pipeline.kb_indexer, entry_id=replacement.id, approver_id=approver.id
    )

    assert result.succeeded
    new_version_id = db_session.execute(
        select(KBVersion.id).where(KBVersion.version_no == result.version_no)
    ).scalar_one()
    assert baseline_actions(db_session, VTLCategory.ORANGE, new_version_id) == (
        baseline_actions_content(3).splitlines()
    )
