"""The data contracts every pipeline stage speaks (CLAUDE.md §8.1).

These models are the seam between the application and the AI components. A mock
stage and the real stage the team writes later (M1–M6) return the *same* shapes,
so the orchestrator, the safety validator and the storage code are written once
and never branch on which implementation is configured (ADR-17).

They are also the provenance record. What is stored on `extraction_results` and
`recommendations` is derived from these objects, which is what lets a reviewer
reopen an old case and see the same category, rationale and passages that were
produced at the time (FR-26, NFR-23, ADR-14).

Nothing here is tuned, scored or inferred: these are declarations of shape. The
logic that fills them is either deterministic (the safety validator, FR-22/FR-23)
or manual (M1–M6).

Field names, order and types follow CLAUDE.md §8.1 exactly. Changing one is a
change to the contract and to the stored rows — do it in the ADR first.
"""

import uuid

from pydantic import BaseModel

from app.models.enums import ActionSource, ConfidenceLevel, Species, VTLCategory

# The complaint code for anything outside the supported set in
# `presenting_complaints`. Defined here, with the contract that uses it, because
# both the mock stages and the safety validator have to mean the same thing by
# it (P05 §5.3 rule 4).
OTHER_COMPLAINT = "OTHER"


class RedFlagHit(BaseModel):
    """One red-flag rule that fired during the pre-screen (FR-12).

    `min_category` is the floor the rule imposes: the safety validator may raise
    the recommendation to it, never below it (FR-23).
    """

    rule_code: str
    matched_text: str
    min_category: VTLCategory


class ExtractedComplaint(BaseModel):
    """A presenting complaint, by `presenting_complaints.code` or `"OTHER"`.

    A primary complaint of `OTHER` means the case falls outside the supported
    complaint set, which the safety validator treats as a reason to recommend
    manual triage.
    """

    code: str
    is_primary: bool


class EvidenceSpan(BaseModel):
    """Where in the de-identified text a field came from.

    `text` is an exact substring of the de-identified description, so the review
    screen can highlight it without re-deriving anything. It is never a substring
    of the raw text: raw text does not leave the de-identifier (ADR-10).
    """

    field: str
    text: str


class ExtractionOutput(BaseModel):
    """Everything the extraction stage reports about one description (FR-11)."""

    species: Species
    signalment: dict[str, str | None]
    presenting_complaints: list[ExtractedComplaint]
    onset_duration: str | None
    frequency_severity: str | None
    associated_signs: list[str]
    negated_findings: list[str]
    exposure_history: str | None
    relevant_history: str | None
    red_flags: list[str]
    missing_information: list[str]
    evidence_spans: list[EvidenceSpan]


class Passage(BaseModel):
    """One retrieved knowledge-base chunk, with its source for citation.

    The source fields are copied onto `retrieved_references` rather than joined
    at display time, so a recommendation keeps the passage as it read when it was
    made even if the entry is later edited or retired (ADR-14).

    `rank` is 1-based and is what a generated recommendation cites.
    """

    rank: int
    chunk_id: uuid.UUID
    entry_id: uuid.UUID
    entry_title: str
    source_title: str
    source_url: str | None
    text: str
    score: float


class DraftRecommendation(BaseModel):
    """What the generation stage proposed, before any safety rule is applied.

    This is never stored as the recommendation and never shown as one. The
    category a reviewer sees comes from `FinalRecommendation` (ADR-09).
    """

    category: VTLCategory
    rationale: str
    cited_ranks: list[int]
    confidence: ConfidenceLevel


class FinalRecommendation(BaseModel):
    """The draft after the deterministic safety and citation validator (FR-22,
    FR-23, FR-25).

    `safety_floor_applied` and `safety_floor_rule_codes` record that a red flag
    raised the category and which rules did it, so the review screen can say why
    (IR-04) and the audit trail can be read back. `low_confidence_reasons` holds
    machine-readable codes, not prose.

    Produced only by `app.pipeline.safety` (subphase 5.3).
    """

    category: VTLCategory
    rationale: str
    cited_ranks: list[int]
    confidence: ConfidenceLevel
    safety_floor_applied: bool
    safety_floor_rule_codes: list[str]
    low_confidence_reasons: list[str]


class SuggestedAction(BaseModel):
    """One suggested staff action, before the reviewer decides on it (FR-73).

    Triage-level handling only: escalate, prepare, monitor, what to ask the
    owner, transport precautions. Never a diagnosis, a medication, a dose or a
    treatment protocol (FR-28, ADR-18 §1) — and that boundary is enforced by the
    deterministic action validator, not by the shape of this model and not by
    prompt wording alone (FR-74).

    `cited_ranks` are `Passage.rank` values, as in `DraftRecommendation`. An
    action left with no valid citation is dropped rather than shown with lowered
    confidence, which is where FR-74 is stricter than FR-22: a recommendation
    with no citation is still a recommendation, an uncited action is just noise.

    `text` is at most 25 words and is untrusted model output throughout: plain
    text, never markup, and never written to a log (SR-17).
    """

    text: str
    cited_ranks: list[int]
    source: ActionSource


class ActionPlan(BaseModel):
    """Everything the actions stage produced for one recommendation (ADR-18 §2).

    Two layers, because `baseline` must always be there and `tailored` is best
    effort. `baseline` comes verbatim from the ACTIVE `URGENCY_ACTIONS` entry for
    `category`, so every one of the five categories shows something useful even
    with the language model switched off entirely (FR-71, FR-72).

    `category` is the category the actions were generated for, recorded so that
    a later change of category marks the tailored list outdated instead of
    silently re-labelling it (FR-78).

    `rejected_count` and `rejection_reasons` are the validator's tally. They are
    surfaced so a high rejection rate is visible as a prompt problem (M6b) —
    never as a reason to loosen the validator.
    """

    category: VTLCategory
    baseline: list[str]
    tailored: list[SuggestedAction]
    rejected_count: int
    rejection_reasons: list[str]
