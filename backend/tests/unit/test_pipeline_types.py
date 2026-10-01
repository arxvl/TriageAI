"""The §8.1 contracts are what gets stored, so their shape is pinned here.

These tests look pedantic on purpose. `ExtractionOutput` and `FinalRecommendation`
are written to `extraction_results` and `recommendations`, and the review screen,
the audit trail and the evaluation harness all read those rows back. A field
quietly renamed or widened would be a silent change to stored clinical
provenance (FR-26, NFR-23, ADR-14), so the field names and annotations are
asserted against CLAUDE.md §8.1 directly.

All data here is fictitious (CLAUDE.md §9).
"""

import uuid

import pytest
from pydantic import ValidationError

from app.models.enums import ConfidenceLevel, Species, VTLCategory
from app.pipeline.types import (
    DraftRecommendation,
    EvidenceSpan,
    ExtractedComplaint,
    ExtractionOutput,
    FinalRecommendation,
    Passage,
    RedFlagHit,
)

# CLAUDE.md §8.1, transcribed. Keys are field names in declaration order; values
# are the annotation as it appears in the document.
CONTRACTS: dict[type, dict[str, str]] = {
    RedFlagHit: {
        "rule_code": "str",
        "matched_text": "str",
        "min_category": "VTLCategory",
    },
    ExtractedComplaint: {
        "code": "str",
        "is_primary": "bool",
    },
    EvidenceSpan: {
        "field": "str",
        "text": "str",
    },
    ExtractionOutput: {
        "species": "Species",
        "signalment": "dict[str, str | None]",
        "presenting_complaints": "list[ExtractedComplaint]",
        "onset_duration": "str | None",
        "frequency_severity": "str | None",
        "associated_signs": "list[str]",
        "negated_findings": "list[str]",
        "exposure_history": "str | None",
        "relevant_history": "str | None",
        "red_flags": "list[str]",
        "missing_information": "list[str]",
        "evidence_spans": "list[EvidenceSpan]",
    },
    Passage: {
        "rank": "int",
        "chunk_id": "UUID",
        "entry_id": "UUID",
        "entry_title": "str",
        "source_title": "str",
        "source_url": "str | None",
        "text": "str",
        "score": "float",
    },
    DraftRecommendation: {
        "category": "VTLCategory",
        "rationale": "str",
        "cited_ranks": "list[int]",
        "confidence": "ConfidenceLevel",
    },
    FinalRecommendation: {
        "category": "VTLCategory",
        "rationale": "str",
        "cited_ranks": "list[int]",
        "confidence": "ConfidenceLevel",
        "safety_floor_applied": "bool",
        "safety_floor_rule_codes": "list[str]",
        "low_confidence_reasons": "list[str]",
    },
}


def annotation_name(annotation: object) -> str:
    """Render an annotation the way CLAUDE.md §8.1 writes it."""
    text = str(annotation)
    # Pydantic resolves enum and model annotations to the class itself, which
    # renders as "<class 'app.pipeline.types.EvidenceSpan'>" bare or as
    # "list[app.pipeline.types.EvidenceSpan]" nested. Both become the bare name.
    for prefix in ("<enum '", "<class '"):
        if text.startswith(prefix):
            text = text.split("'")[1]
    for module in ("app.pipeline.types.", "app.models.enums.", "typing.", "uuid."):
        text = text.replace(module, "")
    return text


@pytest.mark.parametrize("model", list(CONTRACTS), ids=lambda m: m.__name__)
def test_field_names_and_order_match_the_contract(model: type) -> None:
    assert list(model.model_fields) == list(CONTRACTS[model])


@pytest.mark.parametrize("model", list(CONTRACTS), ids=lambda m: m.__name__)
def test_field_types_match_the_contract(model: type) -> None:
    rendered = {
        name: annotation_name(field.annotation) for name, field in model.model_fields.items()
    }
    assert rendered == CONTRACTS[model]


@pytest.mark.parametrize("model", list(CONTRACTS), ids=lambda m: m.__name__)
def test_every_field_is_required(model: type) -> None:
    """No defaults. A stage that forgets a field must fail, not store a blank.

    A silently defaulted `species` or `safety_floor_applied` would be the kind of
    missing provenance ADR-14 exists to prevent.
    """
    assert all(field.is_required() for field in model.model_fields.values())


def red_flag_hit() -> RedFlagHit:
    return RedFlagHit(
        rule_code="MALE_CAT_NO_URINE",
        matched_text="nothing comes out",
        min_category=VTLCategory.ORANGE,
    )


def extraction_output() -> ExtractionOutput:
    return ExtractionOutput(
        species=Species.CAT,
        signalment={"sex": "MALE", "breed": None},
        presenting_complaints=[ExtractedComplaint(code="STRAINING_TO_URINATE", is_primary=True)],
        onset_duration="since last night",
        frequency_severity="repeatedly",
        associated_signs=["vocalising"],
        negated_findings=["no vomiting"],
        exposure_history=None,
        relevant_history=None,
        red_flags=["no urine produced"],
        missing_information=["water intake"],
        evidence_spans=[EvidenceSpan(field="onset_duration", text="since last night")],
    )


def passage(rank: int = 1) -> Passage:
    return Passage(
        rank=rank,
        chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, f"chunk{rank}"),
        entry_id=uuid.uuid5(uuid.NAMESPACE_URL, "entry"),
        entry_title="Feline urinary obstruction",
        source_title="Fictitious Veterinary Triage Reference",
        source_url=None,
        text="A male cat straining without producing urine is an emergency.",
        score=0.81,
    )


def final_recommendation() -> FinalRecommendation:
    return FinalRecommendation(
        category=VTLCategory.ORANGE,
        rationale="Raised by the safety floor.",
        cited_ranks=[1],
        confidence=ConfidenceLevel.MEDIUM,
        safety_floor_applied=True,
        safety_floor_rule_codes=["MALE_CAT_NO_URINE"],
        low_confidence_reasons=["LOW_RETRIEVAL_SCORE"],
    )


@pytest.mark.parametrize(
    "instance",
    [
        red_flag_hit(),
        ExtractedComplaint(code="OTHER", is_primary=True),
        EvidenceSpan(field="onset_duration", text="since last night"),
        extraction_output(),
        passage(),
        DraftRecommendation(
            category=VTLCategory.YELLOW,
            rationale="Draft.",
            cited_ranks=[1, 2],
            confidence=ConfidenceLevel.MEDIUM,
        ),
        final_recommendation(),
    ],
    ids=lambda i: type(i).__name__,
)
def test_round_trips_through_dump_and_validate(instance: object) -> None:
    """What is written to JSONB must come back equal.

    `model_dump(mode="json")` is how these reach a JSONB column and an API
    response, so that is the direction worth asserting.
    """
    restored = type(instance).model_validate(instance.model_dump(mode="json"))

    assert restored == instance


def test_final_recommendation_carries_the_safety_validator_fields() -> None:
    """FR-23's evidence is on the contract, not inferred from the category.

    Subphase 5.3 sets these, and the review screen shows them, so a raised
    category can always be explained by rule code (IR-04).
    """
    final = final_recommendation()

    assert final.safety_floor_applied is True
    assert final.safety_floor_rule_codes == ["MALE_CAT_NO_URINE"]
    assert final.low_confidence_reasons == ["LOW_RETRIEVAL_SCORE"]


def test_species_outside_scope_is_rejected() -> None:
    """Only dogs and cats reach the pipeline (FR-02, BR-06)."""
    with pytest.raises(ValidationError):
        ExtractionOutput.model_validate(
            {**extraction_output().model_dump(mode="json"), "species": "RABBIT"}
        )


def test_category_outside_the_vtl_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DraftRecommendation.model_validate(
            {
                "category": "PURPLE",
                "rationale": "Draft.",
                "cited_ranks": [1],
                "confidence": "MEDIUM",
            }
        )
