"""Unit tests for LLMActionSuggester. No real LLM, no real database."""

from __future__ import annotations

import uuid
from string import Template

import pytest

from app.models.enums import ActionSource, Species, VTLCategory
from app.pipeline.actions_llm import LLMActionSuggester
from app.pipeline.errors import ActionsFailed, LLMInvalidOutput, LLMTimeout
from app.pipeline.prompts import PromptTemplate
from app.pipeline.types import EvidenceSpan, ExtractedComplaint, ExtractionOutput, Passage


class FakeLLM:
    """Replays a queue of dict/Exception results; records every call it receives."""

    model_id = "fake-model-for-tests"

    def __init__(self, *to_return):
        self._queue = list(to_return)
        self.calls: list[dict] = []

    def complete_json(self, *, system, user, json_schema, timeout_s):
        self.calls.append(
            {"system": system, "user": user, "schema": json_schema, "timeout_s": timeout_s}
        )
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def no_baseline_session_factory():
    raise AssertionError(
        "session_factory should not be called in these tests; the autouse "
        "stub_baseline fixture below replaces _fetch_current_baseline instead"
    )


@pytest.fixture(autouse=True)
def stub_baseline(monkeypatch):
    """Keeps every test in this file independent of the database. The one test
    that needs to check the baseline text overrides this with its own stub."""
    monkeypatch.setattr(
        "app.pipeline.actions_llm._fetch_current_baseline",
        lambda session_factory, category: ["Alert the veterinarian now."],
    )


def make_extraction() -> ExtractionOutput:
    return ExtractionOutput(
        species=Species.CAT,
        signalment={"age": "3 years", "sex": "MALE"},
        presenting_complaints=[ExtractedComplaint(code="URINARY_OBSTRUCTION", is_primary=True)],
        onset_duration="since this morning",
        frequency_severity=None,
        associated_signs=["vomiting"],
        negated_findings=["no blood in urine"],
        exposure_history=None,
        relevant_history=None,
        red_flags=["nothing comes out"],
        missing_information=["appetite"],
        evidence_spans=[EvidenceSpan(field="onset_duration", text="since this morning")],
    )


def make_passages() -> list[Passage]:
    return [
        Passage(
            rank=1,
            chunk_id=uuid.uuid4(),
            entry_id=uuid.uuid4(),
            entry_title="Urethral obstruction",
            source_title="Merck Veterinary Manual",
            source_url="https://example.test/a",
            text="Male cats with a blocked urethra need prompt veterinary attention.",
            score=0.81,
        ),
        Passage(
            rank=2,
            chunk_id=uuid.uuid4(),
            entry_id=uuid.uuid4(),
            entry_title="Vomiting in cats",
            source_title="WSAVA guidelines",
            source_url="https://example.test/b",
            text="Occasional vomiting alone is not usually an emergency.",
            score=0.40,
        ),
    ]


def make_suggester(llm) -> LLMActionSuggester:
    prompt = PromptTemplate(
        name="actions",
        version="v1.0-test",
        system="Suggest actions. Say nothing about drugs. Return at most $max_items.",
        user=Template(
            "Category: $category ($category_meaning)\nBaseline:\n$baseline\n\n"
            "Extraction: $extraction_json\n\nPassages:\n$passages"
        ),
    )
    return LLMActionSuggester(
        llm=llm,
        prompt=prompt,
        session_factory=no_baseline_session_factory,
        timeout_s=30,
        max_retries=1,
    )


# ---------------------------------------------------------------- happy path
def test_valid_answer_maps_to_suggested_actions_with_source_ai():
    llm = FakeLLM(
        {"actions": [{"text": "Ask the owner when the cat last urinated.", "cited": [1]}]}
    )
    s = make_suggester(llm)
    out = s.suggest(make_extraction(), VTLCategory.ORANGE, make_passages(), max_items=5)
    assert len(out) == 1
    assert out[0].source == ActionSource.AI
    assert out[0].cited_ranks == [1]
    assert out[0].text == "Ask the owner when the cat last urinated."
    assert s.last_latency_ms is not None and s.last_latency_ms >= 0


def test_empty_actions_list_is_not_an_error():
    llm = FakeLLM({"actions": []})
    s = make_suggester(llm)
    out = s.suggest(make_extraction(), VTLCategory.BLUE, make_passages(), max_items=5)
    assert out == []


def test_duplicate_citation_ranks_are_deduplicated_and_sorted():
    llm = FakeLLM({"actions": [{"text": "Keep the cat calm and warm.", "cited": [2, 1, 2, 1]}]})
    s = make_suggester(llm)
    out = s.suggest(make_extraction(), VTLCategory.ORANGE, make_passages(), max_items=5)
    assert out[0].cited_ranks == [1, 2]


# ---------------------------------------------------------------- retry behaviour
def test_invalid_shape_then_valid_succeeds_after_one_retry():
    llm = FakeLLM({"not": "the right shape"}, {"actions": []})
    s = make_suggester(llm)
    out = s.suggest(make_extraction(), VTLCategory.ORANGE, make_passages(), max_items=5)
    assert out == []
    assert len(llm.calls) == 2


def test_llm_invalid_output_exception_is_also_retried():
    llm = FakeLLM(LLMInvalidOutput("provider did not return JSON"), {"actions": []})
    s = make_suggester(llm)
    out = s.suggest(make_extraction(), VTLCategory.ORANGE, make_passages(), max_items=5)
    assert out == []
    assert len(llm.calls) == 2


def test_invalid_twice_raises_actions_failed():
    llm = FakeLLM({"nope": True}, {"still": "wrong"})
    s = make_suggester(llm)
    with pytest.raises(ActionsFailed):
        s.suggest(make_extraction(), VTLCategory.ORANGE, make_passages(), max_items=5)
    assert len(llm.calls) == 2


def test_llm_timeout_propagates_unchanged_not_wrapped():
    """Transport failures (timeout, provider unavailable) are handled by the
    orchestrator's run_actions (P05b), not by this class -- so they must come
    out exactly as the adapter raised them, not re-wrapped as ActionsFailed."""
    llm = FakeLLM(LLMTimeout("provider too slow"))
    s = make_suggester(llm)
    with pytest.raises(LLMTimeout):
        s.suggest(make_extraction(), VTLCategory.RED, make_passages(), max_items=5)


# ---------------------------------------------------------------- prompt content
def test_prompt_contains_baseline_text_and_category_meaning(monkeypatch):
    monkeypatch.setattr(
        "app.pipeline.actions_llm._fetch_current_baseline",
        lambda session_factory, category: [
            "Alert the veterinarian now.",
            "Prepare a quiet kennel.",
        ],
    )
    llm = FakeLLM({"actions": []})
    s = make_suggester(llm)
    s.suggest(make_extraction(), VTLCategory.RED, make_passages(), max_items=5)
    sent_user = llm.calls[0]["user"]
    assert "Alert the veterinarian now." in sent_user
    assert "Prepare a quiet kennel." in sent_user
    assert "Immediate" in sent_user  # CATEGORY_MEANING["RED"]


def test_max_items_is_sent_into_the_system_message():
    llm = FakeLLM({"actions": []})
    s = make_suggester(llm)
    s.suggest(make_extraction(), VTLCategory.YELLOW, make_passages(), max_items=3)
    assert "Return at most 3." in llm.calls[0]["system"]


def test_model_id_and_prompt_version_properties():
    llm = FakeLLM({"actions": []})
    s = make_suggester(llm)
    assert s.model_id == "fake-model-for-tests"
    assert s.prompt_version == "actions/v1.0-test"
