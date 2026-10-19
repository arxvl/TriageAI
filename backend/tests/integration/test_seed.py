"""The seed script inserts the expected rows, and only once.

These run against `triageai_test` as the application role, through the
rolled-back `db_session` fixture, so `seed()` is exercised exactly as the
application's role would exercise it.
"""

from argon2 import PasswordHasher
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    KBEntry,
    KBEntryKind,
    KBEntryStatus,
    KBVersion,
    PresentingComplaint,
    RedFlagRule,
    Species,
    User,
    UserRole,
    VTLCategory,
    kb_version_entries,
)
from app.schemas.kb import content_problem
from scripts.seed import (
    COMPLAINTS,
    RED_FLAG_RULES,
    SAMPLE_MARKER,
    SEED_KB_VERSION_NO,
    SEED_KB_VERSION_NOTE,
    SEED_PASSWORD,
    URGENCY_ACTIONS,
    USERS,
    seed,
)

EXPECTED_COMPLAINT_COUNT = len(COMPLAINTS) + 1  # the 20 SRS complaints plus OTHER
EXPECTED_BASELINE_COUNT = len(URGENCY_ACTIONS)  # one URGENCY_ACTIONS entry per VTL category


def count(session: Session, model: type) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def test_seed_creates_the_expected_rows(db_session: Session) -> None:
    report = seed(db_session)

    assert count(db_session, User) == len(USERS)
    assert count(db_session, PresentingComplaint) == EXPECTED_COMPLAINT_COUNT
    assert count(db_session, RedFlagRule) == len(RED_FLAG_RULES)
    assert count(db_session, KBVersion) == 1
    assert count(db_session, KBEntry) == EXPECTED_BASELINE_COUNT

    assert report.created == {
        "users": len(USERS),
        "presenting_complaints": EXPECTED_COMPLAINT_COUNT,
        "red_flag_rules": len(RED_FLAG_RULES),
        "kb_versions": 1,
        "kb_entries": EXPECTED_BASELINE_COUNT,
        "kb_version_entries": EXPECTED_BASELINE_COUNT,
    }
    assert all(skipped == 0 for skipped in report.skipped.values())


def test_seed_is_idempotent(db_session: Session) -> None:
    seed(db_session)
    second = seed(db_session)

    assert count(db_session, User) == len(USERS)
    assert count(db_session, PresentingComplaint) == EXPECTED_COMPLAINT_COUNT
    assert count(db_session, RedFlagRule) == len(RED_FLAG_RULES)
    assert count(db_session, KBVersion) == 1
    assert count(db_session, KBEntry) == EXPECTED_BASELINE_COUNT

    assert second.total_created == 0
    assert second.skipped == {
        "users": len(USERS),
        "presenting_complaints": EXPECTED_COMPLAINT_COUNT,
        "red_flag_rules": len(RED_FLAG_RULES),
        "kb_versions": 1,
        "kb_entries": EXPECTED_BASELINE_COUNT,
        "kb_version_entries": EXPECTED_BASELINE_COUNT,
    }


def test_seeded_users_must_change_their_password(db_session: Session) -> None:
    seed(db_session)

    hasher = PasswordHasher()
    for user in db_session.execute(select(User)).scalars():
        assert user.must_change_password is True
        assert user.is_active is True
        # Verified here rather than through a helper: verify_password is P03's.
        assert hasher.verify(user.password_hash, SEED_PASSWORD)


def test_only_the_approver_can_approve_kb(db_session: Session) -> None:
    seed(db_session)

    approvers = db_session.execute(select(User).where(User.can_approve_kb)).scalars().all()

    assert [user.email for user in approvers] == ["approver@triageai.local"]
    # KB approval is only ever held by a Veterinary Reviewer (CLAUDE.md §6).
    assert approvers[0].role is UserRole.VETERINARY_REVIEWER


def test_complaints_are_ordered_with_other_last(db_session: Session) -> None:
    seed(db_session)

    codes = (
        db_session.execute(
            select(PresentingComplaint.code).order_by(PresentingComplaint.sort_order)
        )
        .scalars()
        .all()
    )

    assert codes == [code for code, _ in COMPLAINTS] + ["OTHER"]


def test_red_flag_rules_are_unapproved_placeholders(db_session: Session) -> None:
    seed(db_session)

    rules = {rule.code: rule for rule in db_session.execute(select(RedFlagRule)).scalars()}

    assert set(rules) == {rule.code for rule in RED_FLAG_RULES}
    for rule in rules.values():
        # Nothing here has been reviewed by a veterinarian yet (P08/M5).
        assert rule.is_placeholder is True
        assert rule.approved_by is None
        assert rule.approved_at is None
        assert rule.entry_id is None

    assert rules["MALE_CAT_NO_URINE"].min_category is VTLCategory.ORANGE
    assert rules["MALE_CAT_NO_URINE"].species == [Species.CAT]
    assert rules["NOT_BREATHING"].min_category is VTLCategory.RED
    assert rules["NOT_BREATHING"].species == [Species.DOG, Species.CAT]


def test_seed_kb_version_holds_only_the_baseline_action_entries(db_session: Session) -> None:
    seed(db_session)

    version = db_session.execute(select(KBVersion)).scalar_one()

    assert version.version_no == SEED_KB_VERSION_NO
    assert version.note == SEED_KB_VERSION_NOTE
    # Nobody published it; the first real version comes from the P08 workflow.
    assert version.published_at is None
    assert version.published_by is None

    linked = (
        db_session.execute(
            select(kb_version_entries.c.entry_id).where(
                kb_version_entries.c.kb_version_id == version.id
            )
        )
        .scalars()
        .all()
    )
    assert len(linked) == EXPECTED_BASELINE_COUNT


def test_seed_creates_one_active_baseline_action_set_per_category(db_session: Session) -> None:
    """FR-71, FR-72: every VTL category has a baseline set, even on mocks."""
    seed(db_session)

    entries = db_session.execute(select(KBEntry)).scalars().all()

    assert {entry.urgency_category for entry in entries} == set(VTLCategory)
    for entry in entries:
        assert entry.kind is KBEntryKind.URGENCY_ACTIONS
        assert entry.status is KBEntryStatus.ACTIVE
        # A baseline set belongs to a category, not a presenting complaint.
        assert entry.complaint_code is None
        assert entry.species == [Species.DOG, Species.CAT]
        assert entry.content.splitlines()
        # Unreplaced placeholder content must be obvious (M5 Part D).
        assert SAMPLE_MARKER in entry.title


def test_every_seeded_baseline_set_would_pass_the_workflow(db_session: Session) -> None:
    """A seeded set has to be one a curator could submit (P08 §8.2b).

    The placeholders are replaced in M5 Part D, and until then they are what
    W-08 shows: a set the content rule would refuse would be an entry nobody
    could edit and resubmit.
    """
    seed(db_session)

    sets = db_session.scalars(
        select(KBEntry).where(KBEntry.kind == KBEntryKind.URGENCY_ACTIONS)
    ).all()

    assert len(sets) == EXPECTED_BASELINE_COUNT
    for entry in sets:
        problem = content_problem(entry.content, KBEntryKind.URGENCY_ACTIONS)
        assert problem is None, f"{entry.urgency_category}: {problem}"


def test_baseline_actions_name_no_drug_dose_or_diagnosis(db_session: Session) -> None:
    """The placeholder text already satisfies FR-28 (ADR-18 §1).

    Stricter than the 5b.2 validator will be, deliberately: the validator
    screens model output, while this text is curated and has no reason to come
    near a dose, a medication or the verbs that imply treating the animal.
    """
    seed(db_session)

    content = " ".join(
        entry.content.lower() for entry in db_session.execute(select(KBEntry)).scalars()
    )

    for blocked in ("mg", "ml", "dose", "give", "administer", "treat with", "diagnos"):
        assert blocked not in content
