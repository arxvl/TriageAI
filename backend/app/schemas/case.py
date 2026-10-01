"""Request and response bodies for `/cases` (FR-01, FR-02, FR-29, FR-39, IR-05).

Two things here are deliberate and worth reading before changing them.

**`SpeciesInput` is not `Species`.** The model enum has only DOG and CAT, which
is correct — no case row may ever carry another species. But the intake form has
a third button, and FR-02 says choosing it must produce the manual-triage
message, not a generic "unknown value" rejection. So the request accepts a wider
enum than the database does, and the service narrows it.

**No response model has an owner-reference field.** Owner name and contact
number are accepted on the way in and are never returned (FR-07, DR-04, IR-20).
That is a property of the types, not a filtering step someone has to remember.

Length and range limits match the client-side limits in W-03 exactly; the plain
wording for each is in `core/validation_messages.py`.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    AgeUnit,
    CaseStatus,
    DecisionType,
    IntakeChannel,
    Sex,
    Species,
    VTLCategory,
)

DESCRIPTION_MIN_LENGTH = 20
DESCRIPTION_MAX_LENGTH = 2_000

# The queue is a working list, not an archive, so a page is generous rather than
# small: a clinic takes around 200 cases a day (NFR-06) and closes them as they
# are seen, so one page is normally the whole queue.
QUEUE_DEFAULT_LIMIT = 200
QUEUE_MAX_LIMIT = 500

SEARCH_MAX_LENGTH = 100


class SpeciesInput(StrEnum):
    """What the species control on W-03 can submit. See the module docstring."""

    DOG = "DOG"
    CAT = "CAT"
    OTHER = "OTHER"


class QueueCategoryFilter(StrEnum):
    """The category filter on W-02: the five VTL categories plus manual triage.

    MANUAL is not a VTL category. It selects the cases the queue shows with a
    MANUAL badge — those that reached `MANUAL_TRIAGE_REQUIRED`.
    """

    RED = "RED"
    ORANGE = "ORANGE"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    BLUE = "BLUE"
    MANUAL = "MANUAL"


# --- Requests -------------------------------------------------------------


class CaseCreate(BaseModel):
    """The Case Intake Form (FR-01). Species and description are the only
    required fields; everything else is optional signalment or an owner
    reference."""

    species: SpeciesInput
    description: str = Field(min_length=DESCRIPTION_MIN_LENGTH, max_length=DESCRIPTION_MAX_LENGTH)

    intake_channel: IntakeChannel | None = None

    pet_name: str | None = Field(default=None, max_length=60)
    age_value: Decimal | None = Field(default=None, ge=0, le=40)
    age_unit: AgeUnit | None = None
    sex: Sex | None = None
    neutered: bool | None = None
    breed: str | None = Field(default=None, max_length=60)
    weight_kg: Decimal | None = Field(default=None, ge=Decimal("0.1"), le=Decimal("120"))

    # Stored in `owner_references` and never returned (FR-07, DR-04).
    owner_name: str | None = Field(default=None, max_length=80)
    contact_number: str | None = Field(default=None, max_length=30)

    @field_validator("description", mode="before")
    @classmethod
    def _trim_description(cls, value: object) -> object:
        """Trim before the length check, so 20 spaces is not a description.

        What is stored is this trimmed value, verbatim from there on (FR-05):
        surrounding whitespace is an artefact of typing, not of what the owner
        said.
        """
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("pet_name", "breed", "owner_name", "contact_number", mode="before")
    @classmethod
    def _blank_is_absent(cls, value: object) -> object:
        """An untouched optional input arrives as "" and means "not given"."""
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @property
    def has_owner_reference(self) -> bool:
        return self.owner_name is not None or self.contact_number is not None


class CaseQueueFilters(BaseModel):
    """The W-02 search and filter bar (FR-39, FR-44), as query parameters.

    `date_from` and `date_to` are inclusive calendar dates read in the clinic's
    timezone, not UTC: "today" has to mean the clinic's working day even though
    every timestamp is stored in UTC (DR-03).
    """

    model_config = ConfigDict(extra="forbid")

    species: Species | None = None
    category: QueueCategoryFilter | None = None
    status: CaseStatus | None = None
    date_from: date | None = None
    date_to: date | None = None
    q: str | None = Field(default=None, max_length=SEARCH_MAX_LENGTH)

    limit: int = Field(default=QUEUE_DEFAULT_LIMIT, ge=1, le=QUEUE_MAX_LIMIT)
    offset: int = Field(default=0, ge=0)

    @field_validator("q", mode="before")
    @classmethod
    def _blank_search_is_absent(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value


# --- Responses ------------------------------------------------------------


class CaseCreated(BaseModel):
    """What intake needs to show the "Case C-00xx submitted" toast."""

    id: uuid.UUID
    case_no: str
    status: CaseStatus


class CaseQueueItem(BaseModel):
    """One row of the Triage Queue (W-02).

    `category` is the one the row displays: the confirmed category if a reviewer
    has decided, otherwise the AI's recommendation (FR-29). The two sources are
    also returned separately, because the status chip has to say *which* it is —
    "AI recommendation, pending" against "Adjusted (Yellow -> Green)" — and that
    is the FR-36 / IR-04 guarantee that AI output is never shown as settled.

    Everything below `created_at` is derived at request time, not stored.
    """

    id: uuid.UUID
    case_no: str
    status: CaseStatus
    created_at: datetime

    species: Species
    pet_name: str | None
    age_value: float | None
    age_unit: AgeUnit | None
    breed: str | None

    primary_complaint_code: str | None
    primary_complaint_name: str | None

    category: VTLCategory | None
    recommended_category: VTLCategory | None
    confirmed_category: VTLCategory | None
    decision_type: DecisionType | None

    waiting_minutes: int
    target_minutes: int | None
    is_overdue: bool
    has_red_flag: bool


class CaseQueueCounts(BaseModel):
    """The counters above the W-02 table.

    They always cover the whole open queue, never the filtered rows, so the
    numbers do not move when a filter is applied and a counter can be used to
    apply one.
    """

    by_category: dict[VTLCategory, int]
    manual_count: int
    awaiting_review_count: int
    total: int


class CaseListResponse(BaseModel):
    items: list[CaseQueueItem]
    counts: CaseQueueCounts
    # Drives the "Updated N s ago, auto-refresh every 15 s" indicator (IR-22).
    generated_at: datetime


class CaseStatusOut(BaseModel):
    """The polling response while a case is being processed (IR-22, ADR-08).

    P05 adds `pipeline_stage` here once the orchestrator records progress.
    """

    status: CaseStatus
    category: VTLCategory | None
    has_red_flag: bool
    updated_at: datetime
