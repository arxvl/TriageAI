"""Request and response bodies for the Case Review screen (P06 §6.1).

Everything P06 adds to `/cases` lives here rather than in `schemas/case.py`,
which stays about intake and the Triage Queue. `CaseDetail` composes these.

Three things here are deliberate.

**No owner identifiers, as everywhere else.** No model in this module has an
owner name or contact field, and `AlertOut` deliberately omits the alert's
`matched_text`: it is a substring of the owner's description, and the review
screen already shows that description in full to the one role that may read it
(FR-07, DR-04, and the same reasoning as `QueueRedFlagAlert`).

**Cross-field decision rules are not here.** Whether a decision needs a
category, a reason code or a note depends on its `type`, and a rule like that has
no Pydantic error type to key plain wording on. `DecisionCreate` checks shapes
and lengths; `ReviewService` checks agreement and raises `InvalidDecision` with
the field the form should point at (IR-05).

**The timeline carries composed English.** `AuditTimelineItem` has both a stable
`action` code and a `label`/`details` pair rendered server-side. The code is
there so the frontend can substitute its own wording from a resource file
(NFR-27); the details are composed here because they are data-derived sentences
over versions, counts and a reviewer's reason text — and that reason text has to
come from `staff_decisions`, never from `audit_log`, which records categories and
statuses only (ADR-12).
"""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models.enums import (
    ActionSource,
    ActionsStatus,
    ActionStatus,
    AdjustReason,
    AgeUnit,
    CaseStatus,
    ConfidenceLevel,
    DecisionDirection,
    DecisionType,
    IntakeChannel,
    Sex,
    Species,
    UserRole,
    VTLCategory,
)

# W-04's reason box and the clinical note are both paragraph fields, not essays.
TEXT_MAX_LENGTH = 2_000

# One suggested action is at most 25 words (ADR-18 §4). A reviewer writing their
# own gets room for a long sentence without the field becoming a note field.
ACTION_MAX_LENGTH = 300

# A triage action list is a short checklist. The cap exists so one request
# cannot write an unbounded number of append-only rows, not to shape the UI.
ACTION_LIST_MAX_ITEMS = 50


# --- Requests -------------------------------------------------------------


class FinalActionInput(BaseModel):
    """One row of the action list a reviewer finalized (FR-76).

    `status` is what the reviewer did with the row — `KEPT`, `EDITED`, `REMOVED`
    or `ADDED` — which is what makes keep/edit/remove rates measurable later.
    A removed row is still sent and still stored: the record is of the decision
    about the list, not only of its outcome (DR-09).

    `suggestion_id` points at the `action_suggestions` row this came from, and is
    null for an action the reviewer wrote themselves.

    The text is length-capped and nothing more. The FR-74 block list screens
    *model* output (ADR-18 §4); a Veterinary Reviewer is the clinician whose
    judgement the whole system defers to, and silently rejecting their wording
    mid-decision would be the wrong trade.
    """

    text: str = Field(min_length=1, max_length=ACTION_MAX_LENGTH)
    source: ActionSource
    status: ActionStatus
    suggestion_id: uuid.UUID | None = None

    @field_validator("text", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class DecisionCreate(BaseModel):
    """A reviewer's decision on one case (FR-32, FR-33, FR-34).

    `final_category` is omitted for a CONFIRM — the point of confirming is that
    the recommendation's category stands, and letting the client restate it would
    allow a confirmation that silently disagrees with what it confirmed.

    `final_actions` absent is not the same as empty. Absent means the reviewer
    did not touch the checklist, and the service records what they therefore
    accepted; an empty list means they removed everything.

    `amends_id` makes this a correction of an earlier decision. The earlier row
    is never modified (FR-48, ADR-12).
    """

    type: DecisionType
    final_category: VTLCategory | None = None
    reason_code: AdjustReason | None = None
    reason_text: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    note: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    amends_id: uuid.UUID | None = None
    final_actions: list[FinalActionInput] | None = Field(
        default=None, max_length=ACTION_LIST_MAX_ITEMS
    )

    @field_validator("reason_text", "note", mode="before")
    @classmethod
    def _blank_is_absent(cls, value: object) -> object:
        """An untouched optional textarea arrives as "" and means "not given"."""
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value


# One free-text value on the extraction panel. Short on purpose: these are the
# reviewer's corrections to a structured record, not clinical notes (FR-27).
EXTRACTION_VALUE_MAX_LENGTH = 300
EXTRACTION_ITEM_MAX_LENGTH = 200
EXTRACTION_LIST_MAX_ITEMS = 20
COMPLAINTS_MAX_ITEMS = 10

_Value = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=EXTRACTION_VALUE_MAX_LENGTH)
]
_Item = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=EXTRACTION_ITEM_MAX_LENGTH),
]
_Items = Annotated[list[_Item], Field(max_length=EXTRACTION_LIST_MAX_ITEMS)]


class ComplaintCorrection(BaseModel):
    """One presenting complaint in a correction: a code and whether it is primary."""

    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    is_primary: bool


class ExtractionCorrection(BaseModel):
    """A reviewer's corrections to the extracted information (UC-09, FR-27).

    Partial: only the fields present in the request are changed, and the rest
    are carried over from the latest extraction (`model_fields_set`). A field
    sent as null or an empty list is a deliberate clearing, which is different
    from leaving it out.

    **Not editable here:** species and signalment (they come from the case
    record) and the evidence spans (they index the de-identified text, which a
    correction does not change). `extra="forbid"` turns an attempt to send them
    into a 422 instead of a silent drop.
    """

    model_config = ConfigDict(extra="forbid")

    presenting_complaints: (
        Annotated[list[ComplaintCorrection], Field(max_length=COMPLAINTS_MAX_ITEMS)] | None
    ) = None
    onset_duration: _Value | None = None
    frequency_severity: _Value | None = None
    associated_signs: _Items | None = None
    negated_findings: _Items | None = None
    exposure_history: _Value | None = None
    relevant_history: _Value | None = None
    red_flags: _Items | None = None
    missing_information: _Items | None = None

    @field_validator(
        "onset_duration",
        "frequency_severity",
        "exposure_history",
        "relevant_history",
        mode="after",
    )
    @classmethod
    def _blank_is_absent(cls, value: str | None) -> str | None:
        """A cleared input arrives as "" and means "nothing stated"."""
        return value or None


class NoteCreate(BaseModel):
    """A clinical note added to a case (FR-37)."""

    text: str = Field(min_length=1, max_length=TEXT_MAX_LENGTH)

    @field_validator("text", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


# --- Responses: the review screen -----------------------------------------


class CaseHeaderOut(BaseModel):
    """The W-04 header line: who the patient is and how long they have waited.

    `waiting_minutes` and `target_minutes` are derived at request time against
    one instant, as in the queue. `target_minutes` is None for a case with no
    category, which has no target to be measured against (FR-30).
    """

    case_no: str
    species: Species
    pet_name: str | None
    age_value: float | None
    age_unit: AgeUnit | None
    sex: Sex
    neutered: bool | None
    breed: str | None
    weight_kg: float | None

    intake_channel: IntakeChannel
    created_at: datetime
    created_by_name: str | None
    closed_at: datetime | None

    waiting_minutes: int
    target_minutes: int | None
    is_overdue: bool


class DescriptionOut(BaseModel):
    """Panel 1: what the owner said, and what the pipeline actually read.

    Both are returned because they are not always the same string and the screen
    has to be honest about which one the highlights belong to. `text` is the
    verbatim submission, never updated after insert (FR-05). `deidentified_text`
    is what the de-identifier produced and what `EvidenceSpanOut` offsets index
    into (ADR-10); it is None for a case whose extraction predates migration
    0004, and for a case with no extraction yet.

    `differs` is computed here so the screen does not have to compare two
    possibly long strings to decide whether to show the
    "Highlights refer to the de-identified text" note (W-04 panel 1).
    """

    text: str
    deidentified_text: str | None
    differs: bool


class EvidenceSpanOut(BaseModel):
    """One highlight, as offsets into `DescriptionOut.deidentified_text` (FR-13).

    `found=false` with null offsets means the stored span no longer matches the
    text, or there is no stored text to match against. The span is still
    returned, so the screen can show the quoted evidence as text beside the
    value even when it cannot highlight it in place.
    """

    field: str
    text: str
    start: int | None
    end: int | None
    found: bool


class ExtractedComplaintOut(BaseModel):
    """One presenting complaint, with the display name W-04 and the queue share."""

    code: str
    name: str | None
    is_primary: bool


class ExtractionOut(BaseModel):
    """Panel 2: the extracted information, editable by a reviewer (P07 §7.2).

    A correction is a new version rather than an edit (ADR-14), so `version` and
    `is_corrected` say which one the screen is looking at, and
    `corrected_by_name` who made it.
    """

    id: uuid.UUID
    version: int
    is_corrected: bool
    corrected_by_name: str | None = None
    species: Species | None
    presenting_complaints: list[ExtractedComplaintOut]
    onset_duration: str | None
    frequency_severity: str | None
    associated_signs: list[str]
    negated_findings: list[str]
    exposure_history: str | None
    relevant_history: str | None
    red_flags: list[str]
    missing_information: list[str]
    evidence_spans: list[EvidenceSpanOut]
    created_at: datetime


class SafetyFloorRuleOut(BaseModel):
    """A red-flag rule that raised the category, with the clinic's own label.

    The label, not the code: W-04 says 'the red flag "male cat, no urine"
    requires at least Orange', and `MALE_CAT_NO_URINE` is not a sentence. The
    code stays so the rule is identifiable when the label is later edited.
    """

    code: str
    label: str | None


class RecommendationOut(BaseModel):
    """Panel 3: the AI's answer after the deterministic safety validator.

    This is `FinalRecommendation` as stored — never the generator's draft
    (ADR-09). `safety_floor_applied` and its rules are surfaced because a
    reviewer is entitled to know the category was raised by a rule rather than
    by the model's reading (FR-23, IR-04), and `low_confidence_reasons` are codes
    the screen renders as plain language (FR-24).
    """

    id: uuid.UUID
    version: int
    category: VTLCategory
    target_minutes: int
    rationale: str
    confidence: ConfidenceLevel
    safety_floor_applied: bool
    safety_floor_rules: list[SafetyFloorRuleOut]
    low_confidence_reasons: list[str]
    created_at: datetime


class ReferenceOut(BaseModel):
    """One retrieved passage, in rank order, with whether it was cited (FR-22).

    The source fields are the copies stored on the row rather than a live join,
    so an old case shows the passage as it read when the recommendation was made
    even if the entry has since been edited or retired (ADR-14).
    """

    rank: int
    entry_title: str
    source_title: str | None
    source_url: str | None
    passage_text: str
    score: float | None
    is_cited: bool


class ConfigurationOut(BaseModel):
    """The provenance footnote under panel 3 (FR-26, NFR-23, ADR-14).

    What produced this recommendation, recorded so the same configuration can be
    re-run and compared. `kb_version_no` is the human-readable version the
    footnote shows; `latency_ms` is the generation stage's own time.
    """

    model_id: str
    prompt_version: str
    kb_version_no: int | None
    generated_at: datetime
    latency_ms: int | None


class AlertOut(BaseModel):
    """One red-flag alert on this case (FR-12).

    Carries the rule's label rather than the text that matched it, as the queue
    banner does: `matched_text` is a substring of the owner's description, and a
    label is what the banner needs to say anyway (CLAUDE.md §9, DR-04).

    `acknowledged_at` is set the first time a Veterinary Reviewer opens the case,
    which is what clears the alert from the W-02 banner.
    """

    rule_code: str
    rule_label: str | None
    min_category: VTLCategory
    created_at: datetime
    acknowledged_at: datetime | None


class DecisionOut(BaseModel):
    """The latest decision on this case, or the one just recorded (FR-36).

    `direction` is the reviewer's movement away from the recommendation, and
    `amends_id` is set on a correction. Neither is derivable from the category
    alone once a case has been decided more than once.
    """

    id: uuid.UUID
    type: DecisionType
    final_category: VTLCategory
    target_minutes: int
    reason_code: AdjustReason | None
    reason_text: str | None
    direction: DecisionDirection
    decided_by_name: str | None
    decided_at: datetime
    amends_id: uuid.UUID | None
    status: CaseStatus


class NoteOut(BaseModel):
    """One clinical note, oldest first (FR-37)."""

    id: uuid.UUID
    text: str
    author_name: str | None
    created_at: datetime


class FailureOut(BaseModel):
    """Why the pipeline gave up on this case, and when (NFR-09 · W-06).

    Shown in the W-06 banner so a reviewer triaging by hand knows the case was
    not lost and why the system stepped aside. Present only while the case is
    actually sitting on that failure — see `CaseService._failure`.

    `reason_code` is a plain `str`, not the pipeline's `FailureReason` enum. The
    schema layer must not import `app.pipeline` (CLAUDE.md §7).

    `message` is the sentence the banner prints, built on the server from
    `app.pipeline.messages` so the client holds no list of codes and an
    unrecognised one still reads as a sentence, never as a code (IR-05, P07 §7.1).
    """

    reason_code: str
    message: str
    failed_at: datetime


class RetryAccepted(BaseModel):
    """202 for `POST /cases/{id}/retry`: the pipeline has been queued again.

    `status` is `SUBMITTED`, as for a new case; the client polls
    `GET /cases/{id}/status` from there (IR-22).
    """

    id: uuid.UUID
    case_no: str
    status: CaseStatus


class ActionsRegenerationAccepted(BaseModel):
    """202 for `POST /cases/{id}/actions/regenerate`: new suggestions are queued.

    `category` is the category the suggestions are being made for (FR-78) and
    `generation` the number of the set that will hold them. The case status is
    not part of the answer because it does not change; the client polls
    `GET /cases/{id}/status` for `actions_status`.
    """

    id: uuid.UUID
    case_no: str
    category: VTLCategory
    generation: int
    actions_status: ActionsStatus


class CorrectionAccepted(BaseModel):
    """202 for `PATCH /cases/{id}/extraction`: the regeneration has been queued.

    `status` is `PROCESSING` while the new recommendation is made; the client
    polls `GET /cases/{id}/status` from there (IR-22). `changed_fields` is the
    names of the fields that differ from the previous version, never their
    values; it is empty when the request re-queued a regeneration that had
    failed, for an extraction that already existed.
    """

    id: uuid.UUID
    case_no: str
    status: CaseStatus
    extraction_version: int
    changed_fields: list[str]


class RecommendationVersionOut(BaseModel):
    """One entry of the version switcher under panel 3 (FR-27).

    Every version is kept (ADR-14); only the current one can be decided on.
    """

    version: int
    category: VTLCategory
    created_at: datetime
    is_current: bool


class RecommendationVersionDetail(BaseModel):
    """One stored recommendation version, read-only (FR-27, ADR-14).

    What the switcher shows for an older version: the recommendation as it was,
    the passages it cited and the configuration that produced it, plus the
    extraction version it was made from. Nothing here can be decided on.
    """

    recommendation: RecommendationOut
    references: list[ReferenceOut]
    configuration: ConfigurationOut
    extraction_version: int
    is_current: bool


class PermissionsOut(BaseModel):
    """What this caller may do with this case, as the server sees it.

    Returned so the screen can hide controls instead of offering buttons that
    answer 403 or 409 — but it is a description of the server's rules, never the
    enforcement. `require_role` and `ReviewService` enforce them, and would
    refuse the request whatever these flags said (SR-05, BR-02).

    `can_regenerate` is true for a reviewer on a case that is awaiting review: a
    correction is refused once a decision exists (FR-48, NFR-11) and while a
    regeneration is already running.

    `can_retry` is true for a reviewer on a case sitting in
    `MANUAL_TRIAGE_REQUIRED`, which is when W-06's Retry button is live (P07 §7.1).

    `can_regenerate_actions` is true for a reviewer on a case that has a
    recommendation and is not closed or still being processed, while no actions
    job is already running — the "Regenerate suggestions" button (P07 §7.2b).
    """

    can_decide: bool
    can_regenerate: bool
    can_regenerate_actions: bool
    can_retry: bool
    can_close: bool


# --- Responses: the write endpoints ---------------------------------------


class CaseClosed(BaseModel):
    """What closing a case returns (FR-38)."""

    id: uuid.UUID
    case_no: str
    status: CaseStatus
    closed_at: datetime


# --- Responses: the audit timeline ----------------------------------------


class AuditTimelineItem(BaseModel):
    """One row of the per-case timeline (FR-42, FR-45, W-07).

    `action` is the stable code — an `AuditAction` member, or a derived marker
    such as `EXTRACTION_STORED` for an event that has a row but no audit entry.
    `label` and `details` are the sentence W-07 prints.

    `actor_name` and `actor_role` are null for the pipeline's own entries: the
    pipeline is not a person, and the human judgement about its output is
    recorded separately (ADR-12).
    """

    ts: datetime
    actor_name: str | None
    actor_role: UserRole | None
    action: str
    label: str
    details: str | None


class AuditTimeline(BaseModel):
    """The timeline for one case, with the FR-46 intervals.

    Both intervals are in seconds and either may be null — a case with no
    recommendation has no first interval, and an undecided case has no second.
    They are measured to the **first** recommendation and the **first** decision,
    so they report how long the system and the reviewer each took the first time,
    which is what the timing metric is about; a later regeneration or amendment
    does not reopen them.

    `append_only` is a constant the caption in W-07 states as fact. It is
    returned rather than hard-coded in the frontend because it is a property of
    the database, enforced by a REVOKE and a trigger (FR-43, ADR-12).
    """

    items: list[AuditTimelineItem]
    submission_to_recommendation_s: float | None
    recommendation_to_decision_s: float | None
    append_only: bool = True
