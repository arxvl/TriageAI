"""The mock stages' generic answers (P05 §5.2's "no fixture match" case).

Subphase 5.1 ships the skeletons, so this file covers what they return today: the
generic answers, the provenance attributes, and `from_settings`. The fixture
lookup and the per-behaviour matrix (`invalid_json`, `timeout`, `flaky`, `slow`)
arrive with subphase 5.2 and are tested there.

Two assertions are load-bearing beyond the mocks themselves. The generic passage
score must stay *below* `retrieval_min_score`, and the generic primary complaint
must stay `OTHER` — subphase 5.3's validator turns both into
`low_confidence_reasons`, and the PD8 walkthrough depends on an unrecognised
description looking uncertain rather than confident.

All data here is fictitious (CLAUDE.md §9).
"""

import uuid

import pytest

from app.core.config import MockLLMBehavior, Settings
from app.models.enums import ConfidenceLevel, Species, VTLCategory
from app.pipeline.config import PipelineConfig
from app.pipeline.mocks import (
    GENERIC_MISSING_INFORMATION,
    GENERIC_PASSAGE_SCORE,
    MOCK_MODEL_ID,
    MOCK_PROMPT_VERSION,
    OTHER_COMPLAINT,
    MockDeidentifier,
    MockEntityExtractor,
    MockKBIndexer,
    MockRecommendationGenerator,
    MockRedFlagScreener,
    MockRetriever,
    generic_draft,
    generic_extraction,
    generic_passages,
    mock_chunk_id,
)
from app.pipeline.registry import PipelineDeps
from tests.test_config import BASE_ENV

ALL_MOCKS = [
    MockDeidentifier,
    MockRedFlagScreener,
    MockEntityExtractor,
    MockRetriever,
    MockRecommendationGenerator,
    MockKBIndexer,
]

DESCRIPTION = (
    "She has been sneezing since yesterday and her left eye is watery. She still eats normally."
)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    return Settings()


@pytest.fixture
def deps(settings: Settings) -> PipelineDeps:
    return PipelineDeps(
        config=PipelineConfig.from_settings(settings),
        session_factory=None,  # type: ignore[arg-type]
        llm=None,
        embedder=None,
        rules_provider=lambda: [],
    )


# --- Construction and provenance -----------------------------------------


@pytest.mark.parametrize("mock_class", ALL_MOCKS, ids=lambda c: c.__name__)
def test_from_settings_builds_every_mock(
    mock_class: type, settings: Settings, deps: PipelineDeps
) -> None:
    stage = mock_class.from_settings(settings, deps)

    assert isinstance(stage, mock_class)
    assert stage.config == deps.config
    assert stage.behavior == MockLLMBehavior.OK


@pytest.mark.parametrize("mock_class", ALL_MOCKS, ids=lambda c: c.__name__)
def test_every_mock_reports_mock_provenance(
    mock_class: type, settings: Settings, deps: PipelineDeps
) -> None:
    stage = mock_class.from_settings(settings, deps)

    assert stage.model_id == MOCK_MODEL_ID == "mock"
    assert stage.prompt_version == MOCK_PROMPT_VERSION == "mock-0"
    assert stage.last_latency_ms == 0


@pytest.mark.parametrize("behavior", list(MockLLMBehavior), ids=lambda b: b.value)
def test_the_behavior_switch_is_read_from_settings(
    monkeypatch: pytest.MonkeyPatch, deps: PipelineDeps, behavior: MockLLMBehavior
) -> None:
    """Every MOCK_LLM_BEHAVIOR value is accepted now; 5.2 gives each an effect."""
    for key, value in {**BASE_ENV, "MOCK_LLM_BEHAVIOR": behavior.value}.items():
        monkeypatch.setenv(key, value)

    stage = MockEntityExtractor.from_settings(Settings(), deps)

    assert stage.behavior == behavior


# --- MockDeidentifier ----------------------------------------------------


def test_the_mock_deidentifier_removes_nothing(settings: Settings, deps: PipelineDeps) -> None:
    """It is a placeholder, and the guard in the registry exists because of this.

    Asserted rather than assumed: if this ever started removing something, the
    reason `LLM_PROVIDER` is locked to `mock` would quietly stop being true
    (IR-20, ADR-10).
    """
    stage = MockDeidentifier.from_settings(settings, deps)

    text = f"{DESCRIPTION} Call Ramos at 0917-000-0000."

    assert stage.deidentify(text, owner_name="Ramos", owner_contact="0917-000-0000") == text


def test_latency_is_recorded_after_a_call(settings: Settings, deps: PipelineDeps) -> None:
    """The orchestrator reads this off the stage and stores it (FR-26)."""
    stage = MockDeidentifier.from_settings(settings, deps)
    stage.deidentify(DESCRIPTION, None, None)

    assert stage.last_latency_ms >= 0


# --- MockRedFlagScreener -------------------------------------------------


def test_no_fixture_match_means_no_red_flag(settings: Settings, deps: PipelineDeps) -> None:
    stage = MockRedFlagScreener.from_settings(settings, deps)

    assert stage.screen(DESCRIPTION, Species.CAT, "FEMALE") == []


# --- MockEntityExtractor -------------------------------------------------


def test_the_generic_extraction_claims_only_other(settings: Settings, deps: PipelineDeps) -> None:
    stage = MockEntityExtractor.from_settings(settings, deps)

    extraction = stage.extract(DESCRIPTION, Species.CAT)

    assert extraction.species == Species.CAT
    assert [(c.code, c.is_primary) for c in extraction.presenting_complaints] == [
        (OTHER_COMPLAINT, True)
    ]
    assert extraction.missing_information == GENERIC_MISSING_INFORMATION
    assert extraction.onset_duration is None
    assert extraction.associated_signs == []
    assert extraction.negated_findings == []
    assert extraction.red_flags == []
    assert extraction.evidence_spans == []


def test_the_generic_primary_complaint_stays_other() -> None:
    """Subphase 5.3 turns a primary `OTHER` into a manual-triage recommendation.

    If this ever became a real complaint code, an unrecognised description would
    start producing a confident category out of nothing (P05 §5.3 rule 4).
    """
    primary = [c for c in generic_extraction(Species.DOG).presenting_complaints if c.is_primary]

    assert [c.code for c in primary] == [OTHER_COMPLAINT]


def test_signalment_numbers_become_strings() -> None:
    """The contract stores signalment as text (CLAUDE.md §8.1)."""
    extraction = generic_extraction(
        Species.CAT, {"age_value": 3, "pet_name": "Miso", "breed": None}
    )

    assert extraction.signalment == {"age_value": "3", "pet_name": "Miso", "breed": None}


# --- MockRetriever -------------------------------------------------------


def test_the_generic_passages_are_two_and_ranked_from_one(
    settings: Settings, deps: PipelineDeps
) -> None:
    stage = MockRetriever.from_settings(settings, deps)

    passages = stage.retrieve(generic_extraction(Species.CAT), uuid.uuid4(), k=5)

    assert [p.rank for p in passages] == [1, 2]
    assert all(p.score == GENERIC_PASSAGE_SCORE for p in passages)


def test_the_generic_passage_score_is_below_the_retrieval_floor() -> None:
    """A description nothing matched must look unsupported, not supported.

    The validator records `LOW_RETRIEVAL_SCORE` and caps confidence on this
    (P05 §5.3 rule 3), so the two numbers have to stay on opposite sides.
    """
    assert GENERIC_PASSAGE_SCORE < PipelineConfig().retrieval_min_score


def test_retrieval_never_returns_more_than_k(settings: Settings, deps: PipelineDeps) -> None:
    stage = MockRetriever.from_settings(settings, deps)

    assert len(stage.retrieve(generic_extraction(Species.CAT), uuid.uuid4(), k=1)) == 1


def test_chunk_ids_are_stable_across_runs() -> None:
    """Derived from a seed, never random, so a stored reference is assertable."""
    assert mock_chunk_id("DEMO_1", 1) == mock_chunk_id("DEMO_1", 1)
    assert mock_chunk_id("DEMO_1", 1) != mock_chunk_id("DEMO_1", 2)
    assert mock_chunk_id("DEMO_1", 1) != mock_chunk_id("DEMO_2", 1)
    assert generic_passages(2)[0].chunk_id == generic_passages(2)[0].chunk_id


# --- MockRecommendationGenerator -----------------------------------------


def test_the_generic_draft_is_yellow_at_medium_confidence(
    settings: Settings, deps: PipelineDeps
) -> None:
    stage = MockRecommendationGenerator.from_settings(settings, deps)

    draft = stage.generate(generic_extraction(Species.CAT), generic_passages(2))

    assert draft.category == VTLCategory.YELLOW
    assert draft.confidence == ConfidenceLevel.MEDIUM
    assert draft.cited_ranks == [1]


def test_the_generic_rationale_says_no_model_ran() -> None:
    """A screenshot of a mock run must not read as a real recommendation (ADR-17)."""
    rationale = generic_draft().rationale.lower()

    assert "mock" in rationale
    assert "no model was called" in rationale


def test_the_generic_draft_cites_a_passage_that_exists() -> None:
    """An invalid citation would be dropped by the validator (FR-22).

    Then the generic path would always report `NO_VALID_CITATION`, which would
    mask the real thing that test is checking in 5.3.
    """
    ranks = {p.rank for p in generic_passages(2)}

    assert set(generic_draft().cited_ranks) <= ranks


# --- MockKBIndexer -------------------------------------------------------


def test_the_mock_indexer_indexes_nothing(settings: Settings, deps: PipelineDeps) -> None:
    stage = MockKBIndexer.from_settings(settings, deps)
    entry_id = uuid.uuid4()

    assert stage.index_entry(entry_id) == 0
    assert stage.remove_entry(entry_id) is None
