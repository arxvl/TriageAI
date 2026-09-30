from app.models.enums import (
    CaseStatus,
    ConfidenceLevel,
    DecisionType,
    KBEntryStatus,
    Species,
    UserRole,
    VTLCategory,
)


def test_vtl_category_matches_claude_md_and_urgency_order() -> None:
    assert list(VTLCategory) == [
        VTLCategory.RED,
        VTLCategory.ORANGE,
        VTLCategory.YELLOW,
        VTLCategory.GREEN,
        VTLCategory.BLUE,
    ]


def test_case_status_matches_claude_md() -> None:
    assert {member.value for member in CaseStatus} == {
        "SUBMITTED",
        "PROCESSING",
        "AWAITING_REVIEW",
        "MANUAL_TRIAGE_REQUIRED",
        "CONFIRMED",
        "ADJUSTED",
        "MANUALLY_TRIAGED",
        "CLOSED",
    }


def test_user_role_matches_claude_md() -> None:
    assert {member.value for member in UserRole} == {
        "INTAKE_STAFF",
        "VETERINARY_REVIEWER",
        "ADMINISTRATOR",
    }


def test_kb_entry_status_matches_claude_md() -> None:
    assert {member.value for member in KBEntryStatus} == {
        "DRAFT",
        "PENDING_REVIEW",
        "ACTIVE",
        "RETIRED",
    }


def test_decision_type_matches_claude_md() -> None:
    assert {member.value for member in DecisionType} == {"CONFIRM", "ADJUST", "MANUAL"}


def test_confidence_level_matches_claude_md() -> None:
    assert {member.value for member in ConfidenceLevel} == {"HIGH", "MEDIUM", "LOW"}


def test_species_matches_claude_md() -> None:
    assert {member.value for member in Species} == {"DOG", "CAT"}
