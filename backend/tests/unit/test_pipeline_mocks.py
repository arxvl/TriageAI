"""The mock stages (P05 §5.2).

Three groups of tests, because the stages have three jobs. They replay the
recorded demo scenarios; they fall back to a generic answer for anything the
fixture file does not hold; and the two model stages simulate the failures
`MOCK_LLM_BEHAVIOR` selects, which is what lets P05 §5.4 exercise its retry and
failure paths with no network call.

Several assertions are load-bearing beyond the mocks themselves:

- `DEMO_1` must replay a **YELLOW** draft together with a `MALE_CAT_NO_URINE` hit
  at **ORANGE**. That pair is the input subphase 5.3's validator turns into the
  ORANGE a reviewer sees, and it is how FR-23 is demonstrated on screen.
- The generic passage score must stay *below* `retrieval_min_score`, and the
  generic primary complaint must stay `OTHER` — the validator turns both into
  `low_confidence_reasons`, and the walkthrough depends on an unrecognised
  description looking uncertain rather than confident.
- The screener must keep answering while the model stages are failing: a red-flag
  alert has to reach the queue even when nothing else does (NFR-05, FR-12).

All data here is fictitious (CLAUDE.md §9).
"""

import uuid

import pytest

from app.core.config import MOCK_SLOW_DELAY_S, MockLLMBehavior, Settings
from app.models.enums import ConfidenceLevel, Species, VTLCategory
from app.pipeline.config import PipelineConfig
from app.pipeline.errors import LLMInvalidOutput, LLMTimeout, PipelineError
from app.pipeline.mock_fixtures import MockFixture, load_fixtures
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

# The two stages that stand in for a model call, and so the two that simulate a
# model failure. The screener and the retriever deliberately do not (P05 §5.2).
MODEL_STAGES = [MockEntityExtractor, MockRecommendationGenerator]

WORKING_SCENARIOS = ["DEMO_1", "DEMO_2", "DEMO_3"]


def fixture(fixture_id: str) -> MockFixture:
    return load_fixtures()[fixture_id]


def call_model_stage(stage: object, fixture_id: str = "DEMO_1") -> object:
    """Invoke whichever model stage this is with that scenario's input.

    The behaviour matrix is the same for both, so the tests parametrise over the
    classes and let this adapt the call.
    """
    scenario = fixture(fixture_id)
    if isinstance(stage, MockEntityExtractor):
        return stage.extract(scenario.description, scenario.species)
    return stage.generate(scenario.extraction, scenario.passages)


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
    """The switch comes from settings, not from a constructor default."""
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


# --- Fixture replay (P05 §5.2) -------------------------------------------


@pytest.mark.parametrize("fixture_id", WORKING_SCENARIOS)
def test_the_screener_replays_the_recorded_hits(
    fixture_id: str, settings: Settings, deps: PipelineDeps
) -> None:
    scenario = fixture(fixture_id)
    stage = MockRedFlagScreener.from_settings(settings, deps)

    assert stage.screen(scenario.description, scenario.species, "MALE") == scenario.red_flags


@pytest.mark.parametrize("fixture_id", WORKING_SCENARIOS)
def test_the_extractor_replays_the_recorded_extraction(
    fixture_id: str, settings: Settings, deps: PipelineDeps
) -> None:
    scenario = fixture(fixture_id)
    stage = MockEntityExtractor.from_settings(settings, deps)

    assert stage.extract(scenario.description, scenario.species) == scenario.extraction


@pytest.mark.parametrize("fixture_id", WORKING_SCENARIOS)
def test_the_retriever_replays_the_recorded_passages(
    fixture_id: str, settings: Settings, deps: PipelineDeps
) -> None:
    """Found by the extraction alone — this stage never sees the text."""
    scenario = fixture(fixture_id)
    stage = MockRetriever.from_settings(settings, deps)

    assert stage.retrieve(scenario.extraction, uuid.uuid4(), k=5) == scenario.passages


@pytest.mark.parametrize("fixture_id", WORKING_SCENARIOS)
def test_the_generator_replays_the_recorded_draft(
    fixture_id: str, settings: Settings, deps: PipelineDeps
) -> None:
    scenario = fixture(fixture_id)
    stage = MockRecommendationGenerator.from_settings(settings, deps)

    assert stage.generate(scenario.extraction, scenario.passages) == scenario.draft


def test_a_fixture_run_never_returns_more_than_k(settings: Settings, deps: PipelineDeps) -> None:
    """DEMO_1 records three passages; `top_k` still caps what retrieval returns."""
    scenario = fixture("DEMO_1")
    stage = MockRetriever.from_settings(settings, deps)

    assert len(scenario.passages) == 3
    assert [p.rank for p in stage.retrieve(scenario.extraction, uuid.uuid4(), k=2)] == [1, 2]


def test_demo_1_pairs_a_yellow_draft_with_an_orange_hit(
    settings: Settings, deps: PipelineDeps
) -> None:
    """The FR-23 demonstration, end to end through the mocks.

    Subphase 5.3's validator must raise this YELLOW to the ORANGE the red flag
    requires. If the fixture ever drifted so the draft already matched the floor,
    the safety floor would stop being visible in the walkthrough and the queue
    would show the right answer for the wrong reason.
    """
    scenario = fixture("DEMO_1")
    screener = MockRedFlagScreener.from_settings(settings, deps)
    extractor = MockEntityExtractor.from_settings(settings, deps)
    retriever = MockRetriever.from_settings(settings, deps)
    generator = MockRecommendationGenerator.from_settings(settings, deps)

    hits = screener.screen(scenario.description, Species.CAT, "MALE")
    extraction = extractor.extract(scenario.description, Species.CAT)
    passages = retriever.retrieve(extraction, uuid.uuid4(), k=5)
    draft = generator.generate(extraction, passages)

    assert [(h.rule_code, h.min_category) for h in hits] == [
        ("MALE_CAT_NO_URINE", VTLCategory.ORANGE)
    ]
    assert draft.category == VTLCategory.YELLOW
    assert all(p.score >= deps.config.retrieval_min_score for p in passages)
    assert set(draft.cited_ranks) <= {p.rank for p in passages}


# --- MOCK_LLM_BEHAVIOR (P05 §5.2) ----------------------------------------


@pytest.mark.parametrize("mock_class", MODEL_STAGES, ids=lambda c: c.__name__)
def test_ok_answers_normally(mock_class: type, deps: PipelineDeps) -> None:
    stage = mock_class(config=deps.config, behavior=MockLLMBehavior.OK)

    assert call_model_stage(stage) is not None


@pytest.mark.parametrize("mock_class", MODEL_STAGES, ids=lambda c: c.__name__)
def test_invalid_json_fails_every_attempt(mock_class: type, deps: PipelineDeps) -> None:
    """The orchestrator retries this one, then gives up (P05 §5.4 step 4)."""
    stage = mock_class(config=deps.config, behavior=MockLLMBehavior.INVALID_JSON)

    with pytest.raises(LLMInvalidOutput):
        call_model_stage(stage)
    with pytest.raises(LLMInvalidOutput):
        call_model_stage(stage)


@pytest.mark.parametrize("mock_class", MODEL_STAGES, ids=lambda c: c.__name__)
def test_timeout_raises_llm_timeout(mock_class: type, deps: PipelineDeps) -> None:
    """Not retried: a timeout under load is not transient (app.pipeline.errors)."""
    stage = mock_class(config=deps.config, behavior=MockLLMBehavior.TIMEOUT)

    with pytest.raises(LLMTimeout):
        call_model_stage(stage)


@pytest.mark.parametrize("mock_class", MODEL_STAGES, ids=lambda c: c.__name__)
def test_flaky_fails_once_then_succeeds(mock_class: type, deps: PipelineDeps) -> None:
    stage = mock_class(config=deps.config, behavior=MockLLMBehavior.FLAKY)

    with pytest.raises(LLMInvalidOutput):
        call_model_stage(stage)

    assert call_model_stage(stage) is not None


@pytest.mark.parametrize("mock_class", MODEL_STAGES, ids=lambda c: c.__name__)
def test_flaky_flakes_once_for_every_case_not_once_per_process(
    mock_class: type, deps: PipelineDeps
) -> None:
    """The attempt count is per call, not per stage instance.

    The registry builds each stage once at startup and shares it, so a per-stage
    flag would flake on the first case the process ever saw and never again —
    which would make the retry path untestable for everything after it.
    """
    stage = mock_class(config=deps.config, behavior=MockLLMBehavior.FLAKY)

    for fixture_id in WORKING_SCENARIOS:
        with pytest.raises(LLMInvalidOutput):
            call_model_stage(stage, fixture_id)
        assert call_model_stage(stage, fixture_id) is not None


@pytest.mark.parametrize("mock_class", MODEL_STAGES, ids=lambda c: c.__name__)
def test_resetting_the_attempt_counts_makes_flaky_flake_again(
    mock_class: type, deps: PipelineDeps
) -> None:
    stage = mock_class(config=deps.config, behavior=MockLLMBehavior.FLAKY)

    with pytest.raises(LLMInvalidOutput):
        call_model_stage(stage)
    call_model_stage(stage)
    stage.reset_attempts()

    with pytest.raises(LLMInvalidOutput):
        call_model_stage(stage)


@pytest.mark.parametrize("mock_class", MODEL_STAGES, ids=lambda c: c.__name__)
def test_slow_answers_late_but_answers(mock_class: type, deps: PipelineDeps) -> None:
    """`slow` means late, not timed out, and the delay must stay inside the budget."""
    stage = mock_class(config=deps.config, behavior=MockLLMBehavior.SLOW)

    assert call_model_stage(stage) is not None
    assert stage.last_latency_ms >= int(MOCK_SLOW_DELAY_S * 1000)
    assert MOCK_SLOW_DELAY_S < deps.config.timeout_s


@pytest.mark.parametrize("mock_class", MODEL_STAGES, ids=lambda c: c.__name__)
@pytest.mark.parametrize(
    "behavior", [MockLLMBehavior.INVALID_JSON, MockLLMBehavior.TIMEOUT], ids=lambda b: b.value
)
def test_latency_is_recorded_even_when_a_call_fails(
    mock_class: type, deps: PipelineDeps, behavior: MockLLMBehavior
) -> None:
    """A failed attempt still took time, and the orchestrator stores what it reports."""
    stage = mock_class(config=deps.config, behavior=behavior)

    with pytest.raises(PipelineError):
        call_model_stage(stage)

    assert stage.last_latency_ms >= 0


@pytest.mark.parametrize("behavior", list(MockLLMBehavior), ids=lambda b: b.value)
def test_the_screener_answers_whatever_the_model_stages_are_doing(
    deps: PipelineDeps, behavior: MockLLMBehavior
) -> None:
    """A red-flag alert must reach the queue even when the model path is down.

    P05 §5.4 commits the alert rows before extraction runs, precisely so a failing
    model cannot hide an urgent case (NFR-05, FR-12). That is only testable if the
    screener itself refuses to fail with the rest.
    """
    scenario = fixture("DEMO_2")
    stage = MockRedFlagScreener(config=deps.config, behavior=behavior)

    assert stage.screen(scenario.description, scenario.species, "MALE") == scenario.red_flags


@pytest.mark.parametrize("behavior", list(MockLLMBehavior), ids=lambda b: b.value)
def test_the_retriever_answers_whatever_the_model_stages_are_doing(
    deps: PipelineDeps, behavior: MockLLMBehavior
) -> None:
    """Retrieval is a database query in the real stage, not a model call."""
    scenario = fixture("DEMO_2")
    stage = MockRetriever(config=deps.config, behavior=behavior)

    assert stage.retrieve(scenario.extraction, uuid.uuid4(), k=5) == scenario.passages


# --- The forced-failure scenario (P05 §5.2, FR-15, NFR-09) ---------------


def test_demo_4_fails_however_the_behavior_switch_is_set(
    settings: Settings, deps: PipelineDeps
) -> None:
    """Its fixture forces the failure, so the walkthrough needs no `.env` change."""
    scenario = fixture("DEMO_4")
    stage = MockEntityExtractor.from_settings(settings, deps)

    assert settings.mock_llm_behavior is MockLLMBehavior.OK
    with pytest.raises(LLMInvalidOutput):
        stage.extract(scenario.description, scenario.species)
    with pytest.raises(LLMInvalidOutput):
        stage.extract(scenario.description, scenario.species)


def test_demo_4_failing_does_not_affect_the_other_scenarios(
    settings: Settings, deps: PipelineDeps
) -> None:
    """One stage instance serves every case; a forced failure is per description."""
    stage = MockEntityExtractor.from_settings(settings, deps)

    with pytest.raises(LLMInvalidOutput):
        stage.extract(fixture("DEMO_4").description, Species.DOG)

    for fixture_id in WORKING_SCENARIOS:
        scenario = fixture(fixture_id)
        assert stage.extract(scenario.description, scenario.species) == scenario.extraction
