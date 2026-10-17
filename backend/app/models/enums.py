from enum import StrEnum

from sqlalchemy import Enum


class VTLCategory(StrEnum):
    RED = "RED"
    ORANGE = "ORANGE"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    BLUE = "BLUE"


class CaseStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    MANUAL_TRIAGE_REQUIRED = "MANUAL_TRIAGE_REQUIRED"
    CONFIRMED = "CONFIRMED"
    ADJUSTED = "ADJUSTED"
    MANUALLY_TRIAGED = "MANUALLY_TRIAGED"
    CLOSED = "CLOSED"


class UserRole(StrEnum):
    INTAKE_STAFF = "INTAKE_STAFF"
    VETERINARY_REVIEWER = "VETERINARY_REVIEWER"
    ADMINISTRATOR = "ADMINISTRATOR"


class KBEntryStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class KBEntryKind(StrEnum):
    """What a knowledge-base entry is for (CLAUDE.md §6, ADR-18).

    `COMPLAINT` entries are the retrievable clinical content. `URGENCY_ACTIONS`
    entries hold the baseline action set for one VTL category: there is at most
    one ACTIVE entry per category, it is looked up by category, and it is never
    similarity-searched, so it cannot displace a clinical passage in retrieval.
    """

    COMPLAINT = "COMPLAINT"
    URGENCY_ACTIONS = "URGENCY_ACTIONS"


class DecisionType(StrEnum):
    CONFIRM = "CONFIRM"
    ADJUST = "ADJUST"
    MANUAL = "MANUAL"


class AdjustReason(StrEnum):
    """Why a reviewer moved the category away from the recommendation (FR-33).

    A reason is mandatory for an ADJUST (BR-03) and comes from this fixed list
    rather than free text, because these codes are the data behind the
    disagreement analysis: "the model under-triaged" and "the patient looked
    different on arrival" are different findings about the system, and prose
    cannot be counted. `reason_text` carries the detail, and is itself required
    when the code is `OTHER`.
    """

    CONDITION_DIFFERS_ON_ARRIVAL = "CONDITION_DIFFERS_ON_ARRIVAL"
    SIGN_NOT_CAPTURED = "SIGN_NOT_CAPTURED"
    RECOMMENDATION_TOO_LOW = "RECOMMENDATION_TOO_LOW"
    RECOMMENDATION_TOO_HIGH = "RECOMMENDATION_TOO_HIGH"
    OTHER = "OTHER"


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Species(StrEnum):
    DOG = "DOG"
    CAT = "CAT"


class ActionSource(StrEnum):
    """Where one suggested action came from (CLAUDE.md §6, IR-23).

    Shown as a tag on every row of the W-04 checklist, so a reviewer can always
    tell curated content from model output.
    """

    BASELINE = "BASELINE"
    AI = "AI"
    REVIEWER = "REVIEWER"


class ActionStatus(StrEnum):
    """What the reviewer did with one action when finalizing the list (FR-76).

    `SUGGESTED` is the state of a suggestion that has not been finalized; the
    other four are the outcomes recorded on the append-only `final_actions`
    rows, which is what makes keep/edit/remove rates measurable (ADR-18).
    """

    SUGGESTED = "SUGGESTED"
    KEPT = "KEPT"
    EDITED = "EDITED"
    REMOVED = "REMOVED"
    ADDED = "ADDED"


class ActionsStatus(StrEnum):
    """Progress of the `SUGGEST_ACTIONS` job for one recommendation (FR-77).

    Not in the CLAUDE.md §6 enum list: P05b §5b.1 requires the field but names
    no enum for it, so it follows the same UPPERCASE native-enum convention as
    every other status column here.

    `FAILED` never changes the case status — the case stays in
    `AWAITING_REVIEW` and the baseline actions are shown on their own
    (ADR-18 §3).
    """

    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# Enums required by the P02 §2.1 model field lists but not listed in
# CLAUDE.md §6.
class IntakeChannel(StrEnum):
    WALK_IN = "WALK_IN"
    PHONE = "PHONE"
    MESSAGE = "MESSAGE"


class AgeUnit(StrEnum):
    MONTHS = "MONTHS"
    YEARS = "YEARS"


class Sex(StrEnum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    UNKNOWN = "UNKNOWN"


class DecisionDirection(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    SAME = "SAME"
    NONE = "NONE"


class JobType(StrEnum):
    PIPELINE_RUN = "PIPELINE_RUN"
    REGENERATE = "REGENERATE"
    SUGGEST_ACTIONS = "SUGGEST_ACTIONS"
    EVAL_RUN = "EVAL_RUN"
    KB_INDEX = "KB_INDEX"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


def pg_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Build a native PostgreSQL enum column type for a StrEnum.

    Centralizes the args every enum column needs so PG type names stay
    consistent and Alembic (in a later subphase) sees stable, named types.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=True,
        values_callable=lambda e: [m.value for m in e],
    )
