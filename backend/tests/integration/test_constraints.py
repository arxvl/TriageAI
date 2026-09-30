"""The schema's integrity rules hold in the database, not just in the models.

Covers the check constraints and uniqueness the SRS relies on (P02 §2.1,
DR-01, DR-02, FR-03).
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    DecisionDirection,
    DecisionType,
    ExtractionResult,
    StaffDecision,
    User,
    UserRole,
    VTLCategory,
)
from tests.conftest import make_case, make_user


def test_can_approve_kb_is_allowed_for_a_veterinary_reviewer(db_session: Session) -> None:
    user = make_user(db_session, role=UserRole.VETERINARY_REVIEWER, can_approve_kb=True)

    assert user.can_approve_kb is True


@pytest.mark.parametrize("role", [UserRole.INTAKE_STAFF, UserRole.ADMINISTRATOR])
def test_can_approve_kb_is_rejected_for_other_roles(db_session: Session, role: UserRole) -> None:
    """KB approval is a veterinary judgement (BR-03, CLAUDE.md §6)."""
    db_session.add(
        User(
            full_name="Test Staff",
            email=f"staff-{uuid.uuid4().hex[:8]}@triageai.invalid",
            password_hash="not-a-real-hash",
            role=role,
            can_approve_kb=True,
            is_active=True,
            must_change_password=False,
            failed_login_count=0,
        )
    )

    with pytest.raises(IntegrityError, match="ck_users_can_approve_kb_requires_reviewer"):
        db_session.flush()


def test_user_email_is_unique(db_session: Session) -> None:
    make_user(db_session, email="duplicate@triageai.invalid")

    with pytest.raises(IntegrityError):
        make_user(db_session, email="duplicate@triageai.invalid")


def extraction(**overrides: object) -> ExtractionResult:
    values: dict[str, object] = {
        "version": 1,
        "entities": {},
        "red_flags": [],
        "missing_information": [],
        "is_corrected": False,
        "model_id": "mock",
        "prompt_version": "mock-0",
    }
    values.update(overrides)
    return ExtractionResult(**values)


def test_extraction_result_accepts_a_case(db_session: Session) -> None:
    case = make_case(db_session)

    db_session.add(extraction(case_id=case.id))
    db_session.flush()


def test_extraction_result_rejects_both_case_and_vignette(db_session: Session) -> None:
    """An extraction belongs to a case or to an evaluation vignette, never both."""
    case = make_case(db_session)
    vignette_id = seed_vignette(db_session)

    db_session.add(extraction(case_id=case.id, vignette_id=vignette_id))

    with pytest.raises(IntegrityError, match="ck_extraction_results_case_xor_vignette"):
        db_session.flush()


def test_extraction_result_rejects_neither_case_nor_vignette(db_session: Session) -> None:
    db_session.add(extraction())

    with pytest.raises(IntegrityError, match="ck_extraction_results_case_xor_vignette"):
        db_session.flush()


def test_adjust_decision_requires_a_reason_code(db_session: Session) -> None:
    """FR-33: an adjustment must record why the reviewer disagreed."""
    case = make_case(db_session)
    reviewer = make_user(db_session, role=UserRole.VETERINARY_REVIEWER)

    db_session.add(
        StaffDecision(
            case_id=case.id,
            type=DecisionType.ADJUST,
            final_category=VTLCategory.RED,
            reason_code=None,
            direction=DecisionDirection.UP,
            decided_by=reviewer.id,
            decided_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError, match="ck_staff_decisions_reason_code_required_for_adjust"):
        db_session.flush()


def test_confirm_decision_needs_no_reason_code(db_session: Session) -> None:
    case = make_case(db_session)
    reviewer = make_user(db_session, role=UserRole.VETERINARY_REVIEWER)

    db_session.add(
        StaffDecision(
            case_id=case.id,
            type=DecisionType.CONFIRM,
            final_category=VTLCategory.GREEN,
            direction=DecisionDirection.SAME,
            decided_by=reviewer.id,
            decided_at=datetime.now(UTC),
        )
    )
    db_session.flush()


def seed_vignette(session: Session) -> uuid.UUID:
    """A fictitious evaluation vignette, inserted with raw SQL to keep the
    constraint tests focused."""
    importer = make_user(session, role=UserRole.ADMINISTRATOR)
    set_id = session.execute(
        text(
            "INSERT INTO evaluation_sets (id, name, imported_at, imported_by) "
            "VALUES (:id, 'Test set', now(), :importer) RETURNING id"
        ),
        {"id": uuid.uuid4(), "importer": importer.id},
    ).scalar_one()
    return session.execute(
        text(
            "INSERT INTO vignettes (id, set_id, external_id, species, description, "
            "reference_category) VALUES (:id, :set_id, 'V-001', 'DOG', "
            "'Dog is limping.', 'GREEN') RETURNING id"
        ),
        {"id": uuid.uuid4(), "set_id": set_id},
    ).scalar_one()
