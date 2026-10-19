"""Request and response bodies for the knowledge-base workflow (P08 §8.1).

Three things here are deliberate.

**The citation is required by the schema, not by politeness.** FR-50 allows no
entry without the title, publisher, URL and access date of its source, and BR-04
puts approval behind an account that can check them. So `KBEntryCreate` makes
all four mandatory, and `KBService.submit_entry` checks the *stored* row again —
an entry imported from a YAML file (8.2) never passed through this schema.

**The content bound is in words, not characters.** The 50–1,500 word rule comes
from the P08 prompt and is what keeps an entry long enough to be a passage and
short enough to chunk sensibly (M5). A word count has no Pydantic error type of
its own, so the message for it is registered under `value_error`.

**No model here carries owner data.** The knowledge base holds curated clinical
content and never a case, so nothing in this module touches a description, an
owner reference or a recommendation (DR-04).
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    JobStatus,
    KBEntryKind,
    KBEntryStatus,
    Species,
    VTLCategory,
)

# The P08 §8.1 content bound, in words.
CONTENT_MIN_WORDS = 50
CONTENT_MAX_WORDS = 1_500

# Generous caps that match the columns; the real limit on content is the word
# count above.
CONTENT_MAX_LENGTH = 20_000
COMMENTS_MAX_LENGTH = 2_000

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
RULE_CODE_PATTERN = r"^[A-Z][A-Z0-9_]*$"


def word_count(text: str) -> int:
    """How many words an entry's content holds (FR-50, M5 chunking)."""
    return len(text.split())


def _require_word_count(value: str) -> str:
    if not CONTENT_MIN_WORDS <= word_count(value) <= CONTENT_MAX_WORDS:
        raise ValueError(
            f"content must be between {CONTENT_MIN_WORDS} and {CONTENT_MAX_WORDS} words"
        )
    return value


# --- Requests -------------------------------------------------------------


class KBEntryCreate(BaseModel):
    """A new draft entry (FR-49, FR-50).

    `kind` is not a field: this subphase authors `COMPLAINT` entries only. The
    five `URGENCY_ACTIONS` sets are seeded, and authoring them through the API
    arrives with the importer's urgency-action support (8.2b, ADR-18).
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    complaint_code: str = Field(min_length=1, max_length=64)
    species: list[Species] = Field(min_length=1)
    content: str = Field(min_length=1, max_length=CONTENT_MAX_LENGTH)
    source_title: str = Field(min_length=1, max_length=300)
    source_publisher: str = Field(min_length=1, max_length=300)
    source_url: str = Field(min_length=1, max_length=1_000)
    access_date: date
    slug: str | None = Field(default=None, max_length=120, pattern=SLUG_PATTERN)
    red_flag_codes: list[str] = Field(default_factory=list, max_length=50)

    @field_validator(
        "title", "content", "source_title", "source_publisher", "source_url", mode="before"
    )
    @classmethod
    def _trim(cls, value: object) -> object:
        """Trimmed before the length check, so blanks fail rather than pass."""
        return value.strip() if isinstance(value, str) else value

    @field_validator("content")
    @classmethod
    def _bounded_words(cls, value: str) -> str:
        return _require_word_count(value)

    @field_validator("species")
    @classmethod
    def _unique_species(cls, value: list[Species]) -> list[Species]:
        return list(dict.fromkeys(value))


class KBEntryUpdate(BaseModel):
    """An edit to a draft. Every field is optional; only what is sent changes.

    Allowed while the entry is `DRAFT` and at no other time — an ACTIVE entry is
    never edited in place (ADR-14), and the state machine, not this schema, is
    what refuses.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=300)
    complaint_code: str | None = Field(default=None, min_length=1, max_length=64)
    species: list[Species] | None = Field(default=None, min_length=1)
    content: str | None = Field(default=None, min_length=1, max_length=CONTENT_MAX_LENGTH)
    source_title: str | None = Field(default=None, min_length=1, max_length=300)
    source_publisher: str | None = Field(default=None, min_length=1, max_length=300)
    source_url: str | None = Field(default=None, min_length=1, max_length=1_000)
    access_date: date | None = None
    red_flag_codes: list[str] | None = Field(default=None, max_length=50)

    @field_validator(
        "title", "content", "source_title", "source_publisher", "source_url", mode="before"
    )
    @classmethod
    def _trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("content")
    @classmethod
    def _bounded_words(cls, value: str | None) -> str | None:
        return None if value is None else _require_word_count(value)

    @field_validator("species")
    @classmethod
    def _unique_species(cls, value: list[Species] | None) -> list[Species] | None:
        return None if value is None else list(dict.fromkeys(value))


class KBRejection(BaseModel):
    """Why an entry is being sent back (FR-51).

    The comments are required. A rejection with no reason gives the author
    nothing to act on, and the whole point of the Pending Review state is the
    exchange between the author and the approver.
    """

    model_config = ConfigDict(extra="forbid")

    comments: str = Field(min_length=1, max_length=COMMENTS_MAX_LENGTH)

    @field_validator("comments", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        """Trimmed first: whitespace is not a reason (IR-05)."""
        return value.strip() if isinstance(value, str) else value


class RedFlagRuleCreate(BaseModel):
    """A new, unapproved red-flag rule (FR-12, FR-23, NFR-08).

    Created unapproved whoever asks for it: the safety floor is the one thing in
    the system a single person must not be able to change alone (BR-04).
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100, pattern=RULE_CODE_PATTERN)
    label: str = Field(min_length=1, max_length=300)
    min_category: VTLCategory
    species: list[Species] = Field(min_length=1)
    phrases_ref: str | None = Field(default=None, max_length=100)
    is_placeholder: bool = False

    @field_validator("label", "phrases_ref", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("species")
    @classmethod
    def _unique_species(cls, value: list[Species]) -> list[Species]:
        return list(dict.fromkeys(value))


class RedFlagRuleUpdate(BaseModel):
    """An edit to a rule that has not been approved yet.

    `code` is not editable: it is the key the phrase file and every stored alert
    reference, so changing it would orphan both (FR-23).
    """

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=300)
    min_category: VTLCategory | None = None
    species: list[Species] | None = Field(default=None, min_length=1)
    phrases_ref: str | None = Field(default=None, max_length=100)
    is_placeholder: bool | None = None

    @field_validator("label", "phrases_ref", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("species")
    @classmethod
    def _unique_species(cls, value: list[Species] | None) -> list[Species] | None:
        return None if value is None else list(dict.fromkeys(value))


class KBEntryFilters(BaseModel):
    """The W-08 tab and kind filter, as query parameters."""

    model_config = ConfigDict(extra="forbid")

    status: KBEntryStatus | None = None
    kind: KBEntryKind | None = None


# --- Responses ------------------------------------------------------------


class SourceCitation(BaseModel):
    """The source an entry was written from (FR-49, FR-50)."""

    title: str | None
    publisher: str | None
    url: str | None
    access_date: date | None


class IndexingState(BaseModel):
    """What happened the last time this entry was indexed (FR-53).

    Read from the entry's newest `KB_INDEX` job rather than from a column on the
    entry: the job row already holds the outcome and the reason code, and a
    second copy of it could disagree with the first. `error` is that reason code,
    never a model response or a traceback (CLAUDE.md §9).

    `None` for an entry that has never been approved.
    """

    status: JobStatus
    error: str | None
    queued_at: datetime


class KBEntrySummary(BaseModel):
    """One row of the W-08 entry list."""

    id: uuid.UUID
    slug: str | None
    kind: KBEntryKind
    title: str
    complaint_code: str | None
    urgency_category: VTLCategory | None
    species: list[Species]
    status: KBEntryStatus
    word_count: int


class KBEntryDetail(BaseModel):
    """One entry, everything the W-08 detail panel and the editor show.

    `review_comments` is the approver's rejection text. It is returned here,
    where the author can act on it, and is deliberately absent from the audit
    log, which cannot be corrected (FR-43).
    """

    id: uuid.UUID
    slug: str | None
    kind: KBEntryKind
    title: str
    complaint_code: str | None
    urgency_category: VTLCategory | None
    species: list[Species]
    content: str
    word_count: int
    status: KBEntryStatus
    source: SourceCitation
    red_flag_codes: list[str]
    created_by_name: str | None
    approved_by_name: str | None
    approved_at: datetime | None
    review_comments: str | None
    revises_entry_id: uuid.UUID | None
    indexing: IndexingState | None


class KBEntryListResponse(BaseModel):
    """The entry list plus the tab counters.

    The counts always describe the whole knowledge base, so filtering the rows
    does not move the numbers — the same contract as the Triage Queue's
    counters (FR-39).
    """

    items: list[KBEntrySummary]
    counts: dict[KBEntryStatus, int]
    published_version_no: int | None
    active_entry_count: int


class KBEntryActionResult(BaseModel):
    """What one workflow action did.

    `version_no` is set when the action published a version, and `job_id` when it
    enqueued indexing instead — approval answers with a job, because the entry
    does not go live until the job succeeds (FR-53).
    """

    id: uuid.UUID
    status: KBEntryStatus
    version_no: int | None = None
    job_id: uuid.UUID | None = None


class KBVersionSummary(BaseModel):
    """One published knowledge-base version (FR-54, DR-05)."""

    id: uuid.UUID
    version_no: int
    published_at: datetime | None
    published_by_name: str | None
    note: str | None
    entry_count: int


class KBVersionDetail(KBVersionSummary):
    entries: list[KBEntrySummary]


class RedFlagRuleOut(BaseModel):
    """One red-flag rule, as the W-08 rules table shows it.

    `is_active` is the answer `get_active_rules` would give for this rule in the
    *running* environment, so the table cannot imply that an unapproved
    placeholder is screening cases in production (NFR-08).
    """

    id: uuid.UUID
    code: str
    label: str
    min_category: VTLCategory
    species: list[Species]
    phrases_ref: str | None
    is_placeholder: bool
    approved_by_name: str | None
    approved_at: datetime | None
    retired_at: datetime | None
    is_active: bool


class RedFlagRuleActionResult(BaseModel):
    id: uuid.UUID
    code: str
    version_no: int | None = None
