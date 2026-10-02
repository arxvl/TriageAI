"""The deterministic safety and citation validator (P05 §5.3, FR-22, FR-23, ADR-09).

The model never writes the stored category. Generation produces a
`DraftRecommendation`; this module turns it into the `FinalRecommendation` a
reviewer sees, and it is the last word on urgency.

That split exists because the worst failure of this system is **under-triage**.
A prompt can ask for caution and usually get it; only code gets it every time,
and only code can be tested without calling a model (ADR-09). So everything here
is pure: no session, no settings lookup, no clock, no I/O. Same inputs, same
output, on a laptop and in the evaluation harness (NFR-23).

Two properties hold unconditionally and the tests exist to keep them holding:

- **The category is never lowered.** A red flag can raise it; nothing here can
  move it the other way (FR-23, NFR-08).
- **Confidence never rises.** Each rule may cap it; none may lift it above what
  the model reported (FR-24).

FR-25 — on a genuine tie between two adjacent categories, prefer the more urgent
— is **not** implemented here. A tie is only visible to the model that weighed
the evidence, so it is instructed in the generation prompt (M6). The validator
cannot see a tie; it can only raise.

What this module does *not* do: rewrite the rationale. A raised category leaves
the model's prose in place, because deterministic code has no business writing
clinical text. The review screen names the rule that raised it instead (IR-04).
"""

from collections.abc import Hashable, Iterable
from typing import TypeVar

from app.core.vtl import URGENCY_ORDER, more_urgent
from app.models.enums import ConfidenceLevel, VTLCategory
from app.pipeline.config import PipelineConfig
from app.pipeline.types import (
    OTHER_COMPLAINT,
    DraftRecommendation,
    ExtractionOutput,
    FinalRecommendation,
    Passage,
    RedFlagHit,
)

__all__ = [
    "LOW_CONFIDENCE_REASONS",
    "LOW_RETRIEVAL_SCORE",
    "NO_VALID_CITATION",
    "UNSUPPORTED_COMPLAINT",
    "SafetyValidator",
    "citation_flags",
]

# The machine-readable reasons stored in `recommendations.low_confidence_reasons`
# (JSONB). Codes, not prose: the UI maps them to wording a reviewer reads
# (IR-04), and the evaluation harness counts them (M7).
NO_VALID_CITATION = "NO_VALID_CITATION"
LOW_RETRIEVAL_SCORE = "LOW_RETRIEVAL_SCORE"
UNSUPPORTED_COMPLAINT = "UNSUPPORTED_COMPLAINT_MANUAL_TRIAGE_RECOMMENDED"

# In the order the rules run, which is the order they appear on a stored row.
LOW_CONFIDENCE_REASONS: tuple[str, ...] = (
    NO_VALID_CITATION,
    LOW_RETRIEVAL_SCORE,
    UNSUPPORTED_COMPLAINT,
)

# Most confident first, mirroring `URGENCY_ORDER`. Used only to take the lower of
# two levels; confidence is never computed any other way here.
_CONFIDENCE_ORDER: tuple[ConfidenceLevel, ...] = (
    ConfidenceLevel.HIGH,
    ConfidenceLevel.MEDIUM,
    ConfidenceLevel.LOW,
)


def _least_confident(left: ConfidenceLevel, right: ConfidenceLevel) -> ConfidenceLevel:
    """The lower of two confidence levels.

    Every rule caps through this, which is what makes "confidence never rises"
    (P05 §5.3 rule 5) a property of the code rather than of the rule order.
    """
    return max(left, right, key=_CONFIDENCE_ORDER.index)


def _most_urgent(categories: list[VTLCategory]) -> VTLCategory:
    """The most urgent of a non-empty list of categories."""
    return min(categories, key=URGENCY_ORDER.index)


def _primary_complaint_code(extraction: ExtractionOutput) -> str:
    """The code of the primary presenting complaint, or `OTHER` if there is none.

    An extraction that named no primary complaint is treated exactly like one
    that named `OTHER`: in both cases nothing in the supported complaint set
    anchors the recommendation, so the case is pushed toward manual triage
    rather than presented as a supported result (P05 §5.3 rule 4).
    """
    for complaint in extraction.presenting_complaints:
        if complaint.is_primary:
            return complaint.code
    return OTHER_COMPLAINT


_T = TypeVar("_T", bound=Hashable)


def _unique(values: Iterable[_T]) -> list[_T]:
    """De-duplicate, preserving first-seen order.

    Order matters: a stored `cited_ranks` or rule-code list is read back on the
    review screen and asserted on in tests, so it has to be the same list every
    time the same inputs arrive.
    """
    seen: set[_T] = set()
    result: list[_T] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def citation_flags(passages: list[Passage], cited_ranks: list[int]) -> dict[int, bool]:
    """`is_cited` per passage rank, for the `retrieved_references` rows (FR-22).

    Rule 1 of P05 §5.3 asks the validator to record which retrieved passages the
    recommendation actually cited. The flag belongs on the stored reference, not
    on `FinalRecommendation`, so it is produced here and written by the
    orchestrator in subphase 5.4 — from the *validated* `cited_ranks`, so a rank
    the model invented can never be stored as a citation.
    """
    cited = set(cited_ranks)
    return {passage.rank: passage.rank in cited for passage in passages}


class SafetyValidator:
    """Turns a draft into the final recommendation (ADR-09).

    Stateless by design, so there is one way to produce a `FinalRecommendation`
    and the orchestrator, the regeneration path (P07) and the evaluation harness
    (M7) all go through it.
    """

    @staticmethod
    def finalize(
        draft: DraftRecommendation,
        passages: list[Passage],
        red_flag_hits: list[RedFlagHit],
        extraction: ExtractionOutput,
        config: PipelineConfig,
    ) -> FinalRecommendation:
        """Apply the four rules, in order, and return the stored recommendation.

        Nothing passed in is mutated: the draft and the passages are kept as the
        stage produced them, because they are also what the provenance record
        describes (FR-26, ADR-14).
        """
        category = draft.category
        confidence = draft.confidence
        reasons: list[str] = []

        # --- 1. Citations (FR-22, NFR-12) ---------------------------------
        # A rank the model cited that is not in the retrieved set is a citation
        # of something it never received. Drop it rather than store it.
        retrieved_ranks = {passage.rank for passage in passages}
        cited_ranks = _unique([rank for rank in draft.cited_ranks if rank in retrieved_ranks])
        if not cited_ranks:
            reasons.append(NO_VALID_CITATION)
            confidence = _least_confident(confidence, ConfidenceLevel.LOW)

        # --- 2. Safety floor (FR-23, NFR-08) ------------------------------
        # Every hit that would have raised the drafted category is recorded, not
        # only the one that raised it furthest: the reviewer's question is "which
        # rules fired on this case?", and answering it from the draft category
        # keeps the answer independent of the order the screener returned.
        floor_codes = _unique(
            [hit.rule_code for hit in red_flag_hits if more_urgent(hit.min_category, category)]
        )
        safety_floor_applied = bool(floor_codes)
        if safety_floor_applied:
            category = _most_urgent(
                [category] + [hit.min_category for hit in red_flag_hits],
            )

        # --- 3. Retrieval quality (FR-24) ---------------------------------
        # No passages at all is the weakest possible retrieval, not an exemption.
        best_score = max((passage.score for passage in passages), default=0.0)
        if best_score < config.retrieval_min_score:
            reasons.append(LOW_RETRIEVAL_SCORE)
            confidence = _least_confident(confidence, ConfidenceLevel.MEDIUM)

        # --- 4. Unsupported complaint -------------------------------------
        if _primary_complaint_code(extraction) == OTHER_COMPLAINT:
            reasons.append(UNSUPPORTED_COMPLAINT)
            confidence = _least_confident(confidence, ConfidenceLevel.LOW)

        # --- 5. Confidence never rises above the model's own value --------
        # Each cap above already took the lower of the two; this is the guard
        # that keeps that true if a rule is ever added out of order.
        confidence = _least_confident(confidence, draft.confidence)

        return FinalRecommendation(
            category=category,
            rationale=draft.rationale,
            cited_ranks=cited_ranks,
            confidence=confidence,
            safety_floor_applied=safety_floor_applied,
            safety_floor_rule_codes=floor_codes,
            low_confidence_reasons=reasons,
        )
