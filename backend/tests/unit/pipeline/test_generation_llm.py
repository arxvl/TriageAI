"""Unit tests for LLMRecommendationGenerator (M6 Step B3). No real LLM: FakeLLM only."""

import pytest

from app.models.enums import ConfidenceLevel, Species, VTLCategory
from app.pipeline.config import PipelineConfig
from app.pipeline.errors import GenerationFailed, LLMInvalidOutput, LLMTimeout
from app.pipeline.generation_llm import LLMRecommendationGenerator
from app.pipeline.mock_fixtures import load_fixtures
from app.pipeline.prompts import load_prompt
from app.pipeline.safety import SafetyValidator
from app.pipeline.types import DraftRecommendation, ExtractedComplaint, ExtractionOutput, Passage


class FakeLLM:
    """Queues dicts to return, or an exception to raise, one per call."""

    model_id = "fake-model"

    def __init__(self, *to_return):
        self._queue = list(to_return)
        self.calls = []

    def complete_json(self, *, system, user, json_schema, timeout_s):
        self.calls.append(
            {"system": system, "user": user, "json_schema": json_schema, "timeout_s": timeout_s}
        )
        if not self._queue:
            raise AssertionError("FakeLLM called more times than it has queued responses")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def answer(**overrides) -> dict:
    base = {
        "category": "ORANGE",
        "rationale": "The owner reports the cat straining without passing urine.",
        "cited": [1],
        "confidence": "HIGH",
    }
    base.update(overrides)
    return base


def make_extraction() -> ExtractionOutput:
    return ExtractionOutput(
        species=Species.CAT,
        signalment={},
        presenting_complaints=[ExtractedComplaint(code="VOMITING", is_primary=True)],
        onset_duration="since this morning",
        frequency_severity=None,
        associated_signs=[],
        negated_findings=[],
        exposure_history=None,
        relevant_history=None,
        red_flags=[],
        missing_information=[],
        evidence_spans=[],
    )


def make_passages() -> list[Passage]:
    import uuid

    return [
        Passage(
            rank=1,
            chunk_id=uuid.uuid4(),
            entry_id=uuid.uuid4(),
            entry_title="Entry one",
            source_title="Source one",
            source_url=None,
            text="First passage text.",
            score=0.8,
        ),
        Passage(
            rank=2,
            chunk_id=uuid.uuid4(),
            entry_id=uuid.uuid4(),
            entry_title="Entry two",
            source_title="Source two",
            source_url=None,
            text="Second passage text.",
            score=0.7,
        ),
    ]


def make_generator(llm, *, max_retries=1) -> LLMRecommendationGenerator:
    return LLMRecommendationGenerator(
        llm, load_prompt("generation", "v1.0"), timeout_s=30, max_retries=max_retries
    )


def test_valid_answer_becomes_a_draft() -> None:
    llm = FakeLLM(answer())

    draft = make_generator(llm).generate(make_extraction(), make_passages())

    assert isinstance(draft, DraftRecommendation)
    assert draft.category is VTLCategory.ORANGE
    assert draft.cited_ranks == [1]
    assert draft.confidence is ConfidenceLevel.HIGH
    assert len(llm.calls) == 1
    assert llm.calls[0]["timeout_s"] == 30


def test_prompt_carries_species_findings_and_numbered_passages() -> None:
    llm = FakeLLM(answer())

    make_generator(llm).generate(make_extraction(), make_passages())

    user = llm.calls[0]["user"]
    assert "Species: CAT" in user
    assert "since this morning" in user
    assert "[1] Entry one — Source one\nFirst passage text." in user
    assert "[2] Entry two — Source two\nSecond passage text." in user


def test_invalid_then_valid_retries_once_with_feedback() -> None:
    llm = FakeLLM({}, answer())

    draft = make_generator(llm, max_retries=1).generate(make_extraction(), make_passages())

    assert draft.category is VTLCategory.ORANGE
    assert len(llm.calls) == 2
    assert "previous answer was invalid" not in llm.calls[0]["user"]
    assert "previous answer was invalid" in llm.calls[1]["user"]


def test_malformed_provider_output_is_retried_too() -> None:
    llm = FakeLLM(LLMInvalidOutput("not json"), answer())

    draft = make_generator(llm).generate(make_extraction(), make_passages())

    assert draft.category is VTLCategory.ORANGE
    assert len(llm.calls) == 2


def test_invalid_twice_raises_generation_failed() -> None:
    llm = FakeLLM({}, {})

    with pytest.raises(GenerationFailed):
        make_generator(llm, max_retries=1).generate(make_extraction(), make_passages())

    assert len(llm.calls) == 2


def test_no_retries_means_one_call() -> None:
    llm = FakeLLM({})

    with pytest.raises(GenerationFailed):
        make_generator(llm, max_retries=0).generate(make_extraction(), make_passages())

    assert len(llm.calls) == 1


def test_unknown_category_is_invalid() -> None:
    llm = FakeLLM(answer(category="PURPLE"), answer(category="PURPLE"))

    with pytest.raises(GenerationFailed):
        make_generator(llm).generate(make_extraction(), make_passages())


def test_unknown_confidence_is_invalid() -> None:
    llm = FakeLLM(answer(confidence="CERTAIN"), answer())

    draft = make_generator(llm).generate(make_extraction(), make_passages())

    assert draft.confidence is ConfidenceLevel.HIGH
    assert len(llm.calls) == 2


def test_overlong_rationale_is_invalid() -> None:
    llm = FakeLLM(answer(rationale="word " * 200), answer())

    draft = make_generator(llm).generate(make_extraction(), make_passages())

    assert len(draft.rationale) <= 900
    assert len(llm.calls) == 2


def test_duplicate_citations_are_removed_and_sorted() -> None:
    llm = FakeLLM(answer(cited=[2, 1, 2, 1]))

    draft = make_generator(llm).generate(make_extraction(), make_passages())

    assert draft.cited_ranks == [1, 2]


def test_invented_citation_numbers_are_kept_for_the_safety_validator() -> None:
    """The generator does not police citations; SafetyValidator does (FR-22)."""
    llm = FakeLLM(answer(cited=[1, 99]))

    draft = make_generator(llm).generate(make_extraction(), make_passages())

    assert draft.cited_ranks == [1, 99]


def test_rationale_is_stripped() -> None:
    llm = FakeLLM(answer(rationale="  Straining to urinate.  \n"))

    draft = make_generator(llm).generate(make_extraction(), make_passages())

    assert draft.rationale == "Straining to urinate."


def test_no_passages_says_so_in_the_prompt() -> None:
    llm = FakeLLM(answer(cited=[]))

    make_generator(llm).generate(make_extraction(), [])

    assert "(no passages found)" in llm.calls[0]["user"]


def test_evidence_spans_are_left_out_of_the_prompt() -> None:
    extraction = make_extraction().model_copy(
        update={"evidence_spans": [{"field": "onset_duration", "text": "UNIQUE-SPAN-TEXT"}]}
    )
    llm = FakeLLM(answer())

    make_generator(llm).generate(extraction, make_passages())

    assert "UNIQUE-SPAN-TEXT" not in llm.calls[0]["user"]


def test_provider_errors_other_than_invalid_output_propagate() -> None:
    """Timeouts and outages are the orchestrator's to handle, not retried here."""
    llm = FakeLLM(LLMTimeout("slow"))

    with pytest.raises(LLMTimeout):
        make_generator(llm).generate(make_extraction(), make_passages())

    assert len(llm.calls) == 1


def test_stage_attributes_follow_the_stage_contract() -> None:
    llm = FakeLLM(answer())
    generator = make_generator(llm)

    assert generator.model_id == "fake-model"
    assert generator.prompt_version == "generation/v1.0"
    assert generator.last_latency_ms == 0

    generator.generate(make_extraction(), make_passages())

    assert generator.last_latency_ms >= 0


def test_schema_sent_to_the_provider_is_the_answer_schema() -> None:
    llm = FakeLLM(answer())

    make_generator(llm).generate(make_extraction(), make_passages())

    properties = llm.calls[0]["json_schema"]["properties"]
    assert set(properties) == {"category", "rationale", "cited", "confidence"}


def test_prompt_template_keeps_actions_out_of_this_stage() -> None:
    """ADR-18: suggested actions are a separate stage, not part of this prompt."""
    prompt = load_prompt("generation", "v1.0")

    assert "handled by a separate component" in prompt.system


def test_safety_floor_raises_a_green_draft_to_orange_for_demo_1() -> None:
    """The generator says GREEN; the real SafetyValidator still delivers ORANGE (FR-23)."""
    fixture = load_fixtures()["DEMO_1"]
    llm = FakeLLM(answer(category="GREEN", cited=[1], confidence="HIGH"))

    draft = make_generator(llm).generate(fixture.extraction, fixture.passages)
    final = SafetyValidator.finalize(
        draft, fixture.passages, fixture.red_flags, fixture.extraction, PipelineConfig()
    )

    assert [hit.rule_code for hit in fixture.red_flags] == ["MALE_CAT_NO_URINE"]
    assert draft.category is VTLCategory.GREEN
    assert final.category is VTLCategory.ORANGE
    assert final.safety_floor_applied is True
    assert final.safety_floor_rule_codes == ["MALE_CAT_NO_URINE"]
