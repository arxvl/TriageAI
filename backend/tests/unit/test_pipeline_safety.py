"""The deterministic safety and citation validator (P05 §5.3, FR-22, FR-23, ADR-09).

These are the tests CLAUDE.md §10 calls non-negotiable. The validator is the
only thing standing between a fluent model answer and a stored triage category,
so the two properties it exists for are asserted directly and from several
directions:

- a red flag can **raise** the category and nothing here can lower it (FR-23);
- a citation the model invented is dropped, and a recommendation left with none
  is labelled low confidence (FR-22).

The `DEMO_1` case at the end is the one a reader should check first: it runs the
recorded walkthrough fixture — a YELLOW draft with a `MALE_CAT_NO_URINE` hit at
ORANGE — through `finalize` and asserts the ORANGE a reviewer will see on
screen. If that test fails, the PD8 demonstration of FR-23 fails with it.

All data here is fictitious (CLAUDE.md §9).
"""

import uuid

import pytest

from app.models.enums import ConfidenceLevel, Species, VTLCategory
from app.pipeline.config import PipelineConfig
from app.pipeline.mock_fixtures import load_fixtures
from app.pipeline.safety import (
    LOW_RETRIEVAL_SCORE,
    NO_VALID_CITATION,
    UNSUPPORTED_COMPLAINT,
    SafetyValidator,
    citation_flags,
)
from app.pipeline.types import (
    OTHER_COMPLAINT,
    DraftRecommendation,
    ExtractedComplaint,
    ExtractionOutput,
    FinalRecommendation,
    Passage,
    RedFlagHit,
)

CONFIG = PipelineConfig()

# A score comfortably above `retrieval_min_score` (0.30), used wherever the test
# is about something other than retrieval quality.
GOOD_SCORE = 0.80


def make_passage(rank: int, score: float = GOOD_SCORE) -> Passage:
    return Passage(
        rank=rank,
        chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, f"test-chunk-{rank}"),
        entry_id=uuid.uuid5(uuid.NAMESPACE_URL, "test-entry"),
        entry_title="Straining to urinate in cats",
        source_title="Placeholder triage reference (invented for tests)",
        source_url=None,
        text="Placeholder passage text for the validator tests.",
        score=score,
    )


def make_passages(count: int = 3, score: float = GOOD_SCORE) -> list[Passage]:
    return [make_passage(rank, score) for rank in range(1, count + 1)]


def make_draft(
    category: VTLCategory = VTLCategory.YELLOW,
    cited_ranks: list[int] | None = None,
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH,
) -> DraftRecommendation:
    return DraftRecommendation(
        category=category,
        rationale="Placeholder rationale from the mock generator.",
        cited_ranks=[1] if cited_ranks is None else cited_ranks,
        confidence=confidence,
    )


def make_hit(rule_code: str, min_category: VTLCategory) -> RedFlagHit:
    return RedFlagHit(
        rule_code=rule_code,
        matched_text="nothing comes out",
        min_category=min_category,
    )


def make_extraction(
    complaints: list[ExtractedComplaint] | None = None,
) -> ExtractionOutput:
    if complaints is None:
        complaints = [ExtractedComplaint(code="URINARY_OBSTRUCTION", is_primary=True)]
    return ExtractionOutput(
        species=Species.CAT,
        signalment={"sex": "MALE"},
        presenting_complaints=complaints,
        onset_duration="since last night",
        frequency_severity=None,
        associated_signs=[],
        negated_findings=[],
        exposure_history=None,
        relevant_history=None,
        red_flags=[],
        missing_information=[],
        evidence_spans=[],
    )


def finalize(
    draft: DraftRecommendation | None = None,
    passages: list[Passage] | None = None,
    hits: list[RedFlagHit] | None = None,
    extraction: ExtractionOutput | None = None,
    config: PipelineConfig = CONFIG,
) -> FinalRecommendation:
    """Call the validator with sensible, uninteresting defaults.

    Every default is the *benign* value — a supported complaint, well-scored
    passages, a valid citation, no red flag — so each test below varies exactly
    the one input it is about.
    """
    return SafetyValidator.finalize(
        make_draft() if draft is None else draft,
        make_passages() if passages is None else passages,
        [] if hits is None else hits,
        make_extraction() if extraction is None else extraction,
        config,
    )


# --- 2. The safety floor (FR-23, NFR-08) ----------------------------------


def test_floor_raises_yellow_to_orange() -> None:
    """The headline rule: a red flag's minimum category wins over the draft."""
    final = finalize(
        draft=make_draft(category=VTLCategory.YELLOW),
        hits=[make_hit("MALE_CAT_NO_URINE", VTLCategory.ORANGE)],
    )

    assert final.category is VTLCategory.ORANGE
    assert final.safety_floor_applied is True
    assert final.safety_floor_rule_codes == ["MALE_CAT_NO_URINE"]


def test_floor_never_lowers_red() -> None:
    """A less urgent rule cannot pull a RED draft down (FR-23: never lowered)."""
    final = finalize(
        draft=make_draft(category=VTLCategory.RED),
        hits=[make_hit("MALE_CAT_NO_URINE", VTLCategory.ORANGE)],
    )

    assert final.category is VTLCategory.RED
    assert final.safety_floor_applied is False
    assert final.safety_floor_rule_codes == []


@pytest.mark.parametrize(
    "hits",
    [
        [
            make_hit("MALE_CAT_NO_URINE", VTLCategory.ORANGE),
            make_hit("RESPIRATORY_DISTRESS", VTLCategory.RED),
        ],
        [
            make_hit("RESPIRATORY_DISTRESS", VTLCategory.RED),
            make_hit("MALE_CAT_NO_URINE", VTLCategory.ORANGE),
        ],
    ],
    ids=["ascending", "descending"],
)
def test_multiple_hits_take_the_most_urgent_in_any_order(hits: list[RedFlagHit]) -> None:
    """Both orderings give RED and record both rules.

    The screener returns hits in whatever order it found them. If the recorded
    rule codes depended on that order, the review screen would explain the same
    case differently from one run to the next.
    """
    final = finalize(draft=make_draft(category=VTLCategory.YELLOW), hits=hits)

    assert final.category is VTLCategory.RED
    assert sorted(final.safety_floor_rule_codes) == ["MALE_CAT_NO_URINE", "RESPIRATORY_DISTRESS"]


def test_floor_equal_to_the_draft_category_is_not_an_application() -> None:
    """A rule that agrees with the model changed nothing, and should not claim to."""
    final = finalize(
        draft=make_draft(category=VTLCategory.ORANGE),
        hits=[make_hit("MALE_CAT_NO_URINE", VTLCategory.ORANGE)],
    )

    assert final.category is VTLCategory.ORANGE
    assert final.safety_floor_applied is False
    assert final.safety_floor_rule_codes == []


def test_no_hits_leaves_the_category_alone() -> None:
    final = finalize(draft=make_draft(category=VTLCategory.GREEN), hits=[])

    assert final.category is VTLCategory.GREEN
    assert final.safety_floor_applied is False
    assert final.safety_floor_rule_codes == []


def test_the_same_rule_firing_twice_is_recorded_once() -> None:
    """Two matched phrases, one rule: the reviewer should see one rule code."""
    final = finalize(
        draft=make_draft(category=VTLCategory.YELLOW),
        hits=[
            make_hit("MALE_CAT_NO_URINE", VTLCategory.ORANGE),
            make_hit("MALE_CAT_NO_URINE", VTLCategory.ORANGE),
        ],
    )

    assert final.safety_floor_rule_codes == ["MALE_CAT_NO_URINE"]


def test_floor_applies_even_when_every_citation_is_invalid() -> None:
    """The floor does not depend on the model getting anything else right.

    This is the combination that matters most in practice: a model that cited
    passages it never received is exactly the model whose category should not be
    trusted, and the red flag still has to raise it (NFR-08).
    """
    final = finalize(
        draft=make_draft(category=VTLCategory.BLUE, cited_ranks=[99]),
        hits=[make_hit("RESPIRATORY_DISTRESS", VTLCategory.RED)],
    )

    assert final.category is VTLCategory.RED
    assert final.safety_floor_applied is True
    assert final.confidence is ConfidenceLevel.LOW
    assert NO_VALID_CITATION in final.low_confidence_reasons


# --- 1. Citations (FR-22, NFR-12) -----------------------------------------


def test_invalid_citations_are_dropped_and_valid_ones_kept_in_order() -> None:
    final = finalize(
        draft=make_draft(cited_ranks=[3, 99, 1]),
        passages=make_passages(3),
    )

    assert final.cited_ranks == [3, 1]
    assert final.low_confidence_reasons == []


def test_all_citations_invalid_gives_no_valid_citation_and_low() -> None:
    final = finalize(draft=make_draft(cited_ranks=[7, 8]), passages=make_passages(3))

    assert final.cited_ranks == []
    assert final.low_confidence_reasons == [NO_VALID_CITATION]
    assert final.confidence is ConfidenceLevel.LOW


def test_an_uncited_recommendation_is_low_confidence() -> None:
    """NFR-18: nothing is displayed as supported when nothing was cited."""
    final = finalize(draft=make_draft(cited_ranks=[]))

    assert final.cited_ranks == []
    assert final.low_confidence_reasons == [NO_VALID_CITATION]
    assert final.confidence is ConfidenceLevel.LOW


def test_duplicate_cited_ranks_are_recorded_once() -> None:
    final = finalize(draft=make_draft(cited_ranks=[2, 2, 1, 2]), passages=make_passages(3))

    assert final.cited_ranks == [2, 1]


def test_valid_citations_pass_through_untouched() -> None:
    final = finalize(draft=make_draft(cited_ranks=[1, 2]), passages=make_passages(3))

    assert final.cited_ranks == [1, 2]
    assert final.low_confidence_reasons == []
    assert final.confidence is ConfidenceLevel.HIGH


def test_citation_flags_mark_only_the_validated_citations() -> None:
    """What subphase 5.4 stores on `retrieved_references.is_cited`."""
    passages = make_passages(3)
    final = finalize(draft=make_draft(cited_ranks=[2, 99]), passages=passages)

    assert citation_flags(passages, final.cited_ranks) == {1: False, 2: True, 3: False}


# --- 3. Retrieval quality (FR-24) -----------------------------------------


def test_low_retrieval_score_caps_confidence_at_medium() -> None:
    final = finalize(
        draft=make_draft(confidence=ConfidenceLevel.HIGH),
        passages=make_passages(2, score=0.20),
    )

    assert final.low_confidence_reasons == [LOW_RETRIEVAL_SCORE]
    assert final.confidence is ConfidenceLevel.MEDIUM


def test_a_score_exactly_at_the_floor_is_not_low() -> None:
    """The rule is "below `retrieval_min_score`", and 0.30 is not below 0.30."""
    final = finalize(passages=make_passages(2, score=CONFIG.retrieval_min_score))

    assert final.low_confidence_reasons == []
    assert final.confidence is ConfidenceLevel.HIGH


def test_the_best_passage_decides_retrieval_quality() -> None:
    """One strong passage among weak ones is still support for the answer."""
    passages = [make_passage(1, score=0.10), make_passage(2, score=0.55)]
    final = finalize(draft=make_draft(cited_ranks=[2]), passages=passages)

    assert final.low_confidence_reasons == []


def test_no_passages_at_all_is_both_uncited_and_low_scoring() -> None:
    """An empty retrieval is the weakest case, not a case the rules skip."""
    final = finalize(draft=make_draft(cited_ranks=[1]), passages=[])

    assert final.cited_ranks == []
    assert final.low_confidence_reasons == [NO_VALID_CITATION, LOW_RETRIEVAL_SCORE]
    assert final.confidence is ConfidenceLevel.LOW


def test_the_medium_cap_never_lifts_a_model_low() -> None:
    final = finalize(
        draft=make_draft(confidence=ConfidenceLevel.LOW),
        passages=make_passages(2, score=0.10),
    )

    assert final.confidence is ConfidenceLevel.LOW


# --- 4. Unsupported complaint ---------------------------------------------


def test_primary_other_recommends_manual_triage() -> None:
    final = finalize(
        extraction=make_extraction(
            [ExtractedComplaint(code=OTHER_COMPLAINT, is_primary=True)],
        ),
    )

    assert final.low_confidence_reasons == [UNSUPPORTED_COMPLAINT]
    assert final.confidence is ConfidenceLevel.LOW


def test_a_secondary_other_beside_a_supported_primary_is_fine() -> None:
    final = finalize(
        extraction=make_extraction(
            [
                ExtractedComplaint(code="URINARY_OBSTRUCTION", is_primary=True),
                ExtractedComplaint(code=OTHER_COMPLAINT, is_primary=False),
            ],
        ),
    )

    assert final.low_confidence_reasons == []
    assert final.confidence is ConfidenceLevel.HIGH


def test_an_extraction_with_no_primary_complaint_is_treated_as_unsupported() -> None:
    """Nothing anchors the recommendation, so it goes the same way as `OTHER`."""
    final = finalize(extraction=make_extraction([]))

    assert final.low_confidence_reasons == [UNSUPPORTED_COMPLAINT]
    assert final.confidence is ConfidenceLevel.LOW


# --- 5. Confidence, combinations and purity --------------------------------


def test_confidence_is_never_raised_above_the_model_value() -> None:
    """Everything is in order, the model still said LOW, so the answer is LOW."""
    final = finalize(
        draft=make_draft(cited_ranks=[1, 2], confidence=ConfidenceLevel.LOW),
        passages=make_passages(3),
    )

    assert final.low_confidence_reasons == []
    assert final.confidence is ConfidenceLevel.LOW


def test_all_four_conditions_at_once() -> None:
    """Reasons come out in rule order, once each, and the floor still applies."""
    final = finalize(
        draft=make_draft(
            category=VTLCategory.GREEN,
            cited_ranks=[42],
            confidence=ConfidenceLevel.HIGH,
        ),
        passages=make_passages(2, score=0.11),
        hits=[make_hit("MALE_CAT_NO_URINE", VTLCategory.ORANGE)],
        extraction=make_extraction([ExtractedComplaint(code=OTHER_COMPLAINT, is_primary=True)]),
    )

    assert final.category is VTLCategory.ORANGE
    assert final.safety_floor_applied is True
    assert final.cited_ranks == []
    assert final.low_confidence_reasons == [
        NO_VALID_CITATION,
        LOW_RETRIEVAL_SCORE,
        UNSUPPORTED_COMPLAINT,
    ]
    assert final.confidence is ConfidenceLevel.LOW


def test_the_rationale_is_carried_over_unchanged() -> None:
    """Deterministic code does not write clinical prose (ADR-09)."""
    draft = make_draft(category=VTLCategory.YELLOW)
    final = finalize(draft=draft, hits=[make_hit("MALE_CAT_NO_URINE", VTLCategory.ORANGE)])

    assert final.rationale == draft.rationale


def test_finalize_does_not_mutate_its_inputs_and_repeats_itself() -> None:
    """Pure: the draft and passages are also the provenance record (FR-26)."""
    draft = make_draft(cited_ranks=[1, 99])
    passages = make_passages(2)
    hits = [make_hit("MALE_CAT_NO_URINE", VTLCategory.ORANGE)]
    extraction = make_extraction()
    before = (draft.model_copy(deep=True), [p.model_copy(deep=True) for p in passages])

    first = SafetyValidator.finalize(draft, passages, hits, extraction, CONFIG)
    second = SafetyValidator.finalize(draft, passages, hits, extraction, CONFIG)

    assert (draft, passages) == before
    assert first == second


def test_demo_1_fixture_is_raised_to_orange() -> None:
    """The FR-23 demonstration the PD8 walkthrough shows on screen.

    The fixture records a YELLOW draft and a `MALE_CAT_NO_URINE` hit at ORANGE;
    the queue must show ORANGE with the rule named. Confidence stays HIGH — the
    floor says the category was too low, not that the evidence was weak.
    """
    fixture = load_fixtures()["DEMO_1"]
    assert fixture.extraction is not None and fixture.draft is not None

    final = SafetyValidator.finalize(
        fixture.draft,
        fixture.passages,
        fixture.red_flags,
        fixture.extraction,
        CONFIG,
    )

    assert fixture.draft.category is VTLCategory.YELLOW
    assert final.category is VTLCategory.ORANGE
    assert final.safety_floor_applied is True
    assert final.safety_floor_rule_codes == ["MALE_CAT_NO_URINE"]
    assert final.cited_ranks == [1, 2]
    assert final.low_confidence_reasons == []
    assert final.confidence is ConfidenceLevel.HIGH
