"""Unit tests for LLMEntityExtractor (M3 Step 4). No real LLM: FakeLLM only."""

import pytest

from app.models.enums import Species
from app.pipeline.errors import ExtractionFailed, LLMTimeout
from app.pipeline.extraction_llm import LLMEntityExtractor
from app.pipeline.prompts import load_prompt
from app.pipeline.types import EvidenceSpan, ExtractionOutput


class FakeLLM:
    """Queues dicts to return, or an exception to raise, one per call."""

    model_id = "fake-model"

    def __init__(self, *to_return):
        self._queue = list(to_return)
        self.calls = []

    def complete_json(self, *, system, user, json_schema, timeout_s):
        self.calls.append({"system": system, "user": user, "timeout_s": timeout_s})
        if not self._queue:
            raise AssertionError("FakeLLM called more times than it has queued responses")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


CODES = {"VOMITING": "Vomiting", "LETHARGY": "Lethargy"}


def valid_payload(**overrides) -> dict:
    """A minimal ExtractionOutput dict that validates against the schema."""
    base = {
        "species": "CAT",
        "signalment": {},
        "presenting_complaints": [{"code": "VOMITING", "is_primary": True}],
        "onset_duration": "since this morning",
        "frequency_severity": None,
        "associated_signs": [],
        "negated_findings": [],
        "exposure_history": None,
        "relevant_history": None,
        "red_flags": [],
        "missing_information": [],
        "evidence_spans": [],
    }
    base.update(overrides)
    return base


def make_extractor(llm, codes=CODES, timeout_s=30, max_retries=1) -> LLMEntityExtractor:
    prompt = load_prompt("extraction", "v1.0")
    return LLMEntityExtractor(llm, prompt, codes, timeout_s, max_retries)


# valid | full valid dict -> ExtractionOutput; the species forced from the form
def test_valid_output_species_forced_from_form():
    llm = FakeLLM(valid_payload(species="DOG"))  # model says DOG...
    extractor = make_extractor(llm)

    out = extractor.extract("The cat vomited this morning.", Species.CAT)  # ...form says CAT

    assert isinstance(out, ExtractionOutput)
    assert out.species == Species.CAT  # the form wins, not the model
    assert len(llm.calls) == 1


# invalid then valid | {} then a valid dict -> success after 1 retry; called twice
def test_invalid_then_valid_retries_once():
    llm = FakeLLM({}, valid_payload())  # {} fails ExtractionOutput validation
    extractor = make_extractor(llm, max_retries=1)

    out = extractor.extract("text", Species.CAT)

    assert isinstance(out, ExtractionOutput)
    assert len(llm.calls) == 2
    # the retry carries corrective feedback
    assert "not valid for the schema" in llm.calls[1]["user"]


# invalid twice | {}, {} -> ExtractionFailed
def test_invalid_twice_raises_extraction_failed():
    llm = FakeLLM({}, {})
    extractor = make_extractor(llm, max_retries=1)

    with pytest.raises(ExtractionFailed):
        extractor.extract("text", Species.CAT)

    assert len(llm.calls) == 2  # 1 original attempt + 1 retry, no more


# unknown code | complaint "KIDNEY_STONES" -> mapped to OTHER
def test_unknown_complaint_code_mapped_to_other():
    llm = FakeLLM(
        valid_payload(
            presenting_complaints=[
                {"code": "KIDNEY_STONES", "is_primary": True},
            ]
        )
    )
    extractor = make_extractor(llm)

    out = extractor.extract("text", Species.CAT)

    assert len(out.presenting_complaints) == 1
    assert out.presenting_complaints[0].code == "OTHER"
    assert out.presenting_complaints[0].is_primary is True


# two primaries | 2 x is_primary=True -> exactly one primary
def test_two_primaries_collapsed_to_one():
    llm = FakeLLM(
        valid_payload(
            presenting_complaints=[
                {"code": "VOMITING", "is_primary": True},
                {"code": "LETHARGY", "is_primary": True},
            ]
        )
    )
    extractor = make_extractor(llm)

    out = extractor.extract("text", Species.CAT)

    primaries = [c for c in out.presenting_complaints if c.is_primary]
    assert len(primaries) == 1
    assert primaries[0].code == "VOMITING"  # the first one wins
    assert out.presenting_complaints[1].is_primary is False


# no complaint | empty list -> OTHER, primary
def test_empty_complaint_list_becomes_other_primary():
    llm = FakeLLM(valid_payload(presenting_complaints=[]))
    extractor = make_extractor(llm)

    out = extractor.extract("text", Species.CAT)

    assert len(out.presenting_complaints) == 1
    assert out.presenting_complaints[0].code == "OTHER"
    assert out.presenting_complaints[0].is_primary is True


# invented span | span text not in the input -> span removed
def test_invented_evidence_span_is_removed():
    text = "The cat vomited this morning."
    llm = FakeLLM(
        valid_payload(
            evidence_spans=[
                {"field": "onset_duration", "text": "this morning"},  # really in the text: kept
                {"field": "red_flags", "text": "collapsed and seized"},  # NOT in the text: invented
            ]
        )
    )
    extractor = make_extractor(llm)

    out = extractor.extract(text, Species.CAT)

    assert out.evidence_spans == [EvidenceSpan(field="onset_duration", text="this morning")]


# LLMTimeout raised | propagates, so the orchestrator takes the failure path
def test_llm_timeout_propagates_uncaught():
    llm = FakeLLM(LLMTimeout("provider timed out"))
    extractor = make_extractor(llm, max_retries=1)

    with pytest.raises(LLMTimeout):
        extractor.extract("text", Species.CAT)

    # not retried: only LLMInvalidOutput/ValidationError trigger a retry
    assert len(llm.calls) == 1
