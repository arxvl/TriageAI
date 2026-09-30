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


class DecisionType(StrEnum):
    CONFIRM = "CONFIRM"
    ADJUST = "ADJUST"
    MANUAL = "MANUAL"


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Species(StrEnum):
    DOG = "DOG"
    CAT = "CAT"


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
