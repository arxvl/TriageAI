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

from app.models.enums import ConfidenceLevel, Species, VTLCategory


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
