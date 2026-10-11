from app.models.enums import (
    ActionSource,
    ActionsStatus,
    ActionStatus,
    CaseStatus,
    ConfidenceLevel,
    DecisionType,
    JobType,
    KBEntryKind,
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


def test_kb_entry_kind_matches_claude_md() -> None:
    assert {member.value for member in KBEntryKind} == {"COMPLAINT", "URGENCY_ACTIONS"}


def test_action_source_matches_claude_md() -> None:
    assert {member.value for member in ActionSource} == {"BASELINE", "AI", "REVIEWER"}


def test_action_status_matches_claude_md() -> None:
    assert {member.value for member in ActionStatus} == {
        "SUGGESTED",
        "KEPT",
        "EDITED",
        "REMOVED",
        "ADDED",
    }


def test_actions_status_covers_the_four_job_outcomes() -> None:
    """Not in CLAUDE.md §6; P05b §5b.1 names the field, not an enum.

    UPPERCASE, as every other status enum here is.
    """
    assert {member.value for member in ActionsStatus} == {
        "PENDING",
        "READY",
        "FAILED",
        "NOT_APPLICABLE",
    }


def test_job_type_matches_claude_md() -> None:
    assert {member.value for member in JobType} == {
        "PIPELINE_RUN",
        "REGENERATE",
        "SUGGEST_ACTIONS",
        "EVAL_RUN",
        "KB_INDEX",
    }
