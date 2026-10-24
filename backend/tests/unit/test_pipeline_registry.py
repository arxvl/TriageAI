"""The registry: mock by default, lazy about real stages, and never unsafe.

These are the three ADR-17 properties stated as tests. They run with no database
connection — `build_pipeline` takes an injectable `session_factory`, and a fully
mocked pipeline touches neither a provider nor a session.

The de-identification guard test is the one that must not be deleted. It is the
last line between a mock de-identifier that removes nothing and a real provider
that sends text off the server (IR-20, ADR-10).
"""

from typing import Any

import pytest

from app.adapters.embeddings.base import EmbeddingProvider
from app.adapters.embeddings.sentence_transformer import SentenceTransformerEmbedder
from app.adapters.llm.hosted import HostedLLMProvider
from app.adapters.llm.mock import MockLLMProvider
from app.adapters.llm.ollama import OllamaLLMProvider
from app.core.config import AppEnv, DeidentifierOption, LLMProviderOption, Settings
from app.pipeline import mocks
from app.pipeline.config import PipelineConfig
from app.pipeline.deidentify_rules import RuleBasedDeidentifier
from app.pipeline.generation_llm import LLMRecommendationGenerator
from app.pipeline.orchestrator import TriagePipeline
from app.pipeline.redflags_keywords import KeywordRedFlagScreener
from app.pipeline.registry import (
    PipelineDeps,
    StageNotImplementedError,
    UnsafePipelineConfigError,
    build_pipeline,
)
from app.pipeline.stages import (
    ActionSuggester,
    Deidentifier,
    EntityExtractor,
    KBIndexer,
    PipelineStage,
    RecommendationGenerator,
    RedFlagScreener,
    Retriever,
)
from app.services.red_flag_rules import active_rules_provider
from tests.test_config import settings_from_base_env

# The stage attribute on TriagePipeline, its expected mock class, and the
# Protocol it must satisfy.
MOCK_STAGES: list[tuple[str, type, type]] = [
    ("deidentifier", mocks.MockDeidentifier, Deidentifier),
    ("red_flag_screener", mocks.MockRedFlagScreener, RedFlagScreener),
    ("extractor", mocks.MockEntityExtractor, EntityExtractor),
    ("retriever", mocks.MockRetriever, Retriever),
    ("generator", mocks.MockRecommendationGenerator, RecommendationGenerator),
    ("action_suggester", mocks.MockActionSuggester, ActionSuggester),
    ("kb_indexer", mocks.MockKBIndexer, KBIndexer),
]

# The stages M1 has written, with the attribute the registry must put them on.
IMPLEMENTED_CASES: list[tuple[dict[str, str], str, type]] = [
    ({"PIPELINE_DEIDENTIFIER": "rules"}, "deidentifier", RuleBasedDeidentifier),
    ({"PIPELINE_REDFLAGS": "keywords"}, "red_flag_screener", KeywordRedFlagScreener),
]

# The LLM providers M2 has written. A provider is shared by every stage, so the
# registry puts it on `deps.llm` rather than on a stage attribute, which is why
# these cannot join IMPLEMENTED_CASES above. Each row selects a real
# de-identifier too, because a real provider with the mock one is refused
# outright (IR-20, ADR-10).
IMPLEMENTED_LLM_PROVIDER_CASES: list[tuple[dict[str, str], type]] = [
    ({"LLM_PROVIDER": "hosted", "PIPELINE_DEIDENTIFIER": "rules"}, HostedLLMProvider),
    ({"LLM_PROVIDER": "ollama", "PIPELINE_DEIDENTIFIER": "rules"}, OllamaLLMProvider),
]

# Every non-mock option whose module is still to be written, with the M-guide its
# error message must name. M1, M2 and M4 are merged, so `rules`, `keywords`,
# `hosted`, `ollama` and `sentence_transformer` are covered by the tests above and
# below instead of here. M5 and M6 are merged too, so `pgvector` (indexer and
# retriever) and the `llm` generator are covered by the tests further down.
NOT_IMPLEMENTED_CASES: list[tuple[dict[str, str], str, str]] = []


def _must_not_load(_self: object) -> None:
    raise AssertionError("building the embedder must not load the model")


class FakeSessionFactory:
    """Stands in for `SessionLocal` so these tests need no engine.

    `rules_provider` is the only thing that would open a session, and no test
    here calls it against real rows — `tests/integration` covers that.
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> Any:
        self.calls += 1
        raise AssertionError("a fully mocked pipeline must not open a session")


@pytest.fixture
def session_factory() -> FakeSessionFactory:
    return FakeSessionFactory()


def settings_with(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    """Settings with `overrides` applied and every other field on its default.

    Hermetic by way of `settings_from_base_env`: the dev `.env` reaches this
    container as environment variables, and these tests assert on what the
    *defaults* select (CLAUDE.md §10).
    """
    return settings_from_base_env(monkeypatch, **overrides)


@pytest.fixture
def pipeline(
    monkeypatch: pytest.MonkeyPatch, session_factory: FakeSessionFactory
) -> TriagePipeline:
    return build_pipeline(settings_with(monkeypatch), session_factory=session_factory)  # type: ignore[arg-type]


# --- Mock by default ------------------------------------------------------


def test_defaults_build_a_pipeline(pipeline: TriagePipeline) -> None:
    assert isinstance(pipeline, TriagePipeline)
    assert pipeline.config == PipelineConfig()
    assert pipeline.is_fully_mocked is True


@pytest.mark.parametrize(
    ("attribute", "expected", "_protocol"), MOCK_STAGES, ids=[c[0] for c in MOCK_STAGES]
)
def test_every_stage_defaults_to_its_mock(
    pipeline: TriagePipeline, attribute: str, expected: type, _protocol: type
) -> None:
    assert type(getattr(pipeline, attribute)) is expected


@pytest.mark.parametrize(
    ("attribute", "_expected", "protocol"), MOCK_STAGES, ids=[c[0] for c in MOCK_STAGES]
)
def test_every_mock_satisfies_its_protocol(
    pipeline: TriagePipeline, attribute: str, _expected: type, protocol: type
) -> None:
    """The mock and the real stage must be interchangeable (ADR-17)."""
    assert isinstance(getattr(pipeline, attribute), protocol)


@pytest.mark.parametrize(
    ("attribute", "_expected", "_protocol"), MOCK_STAGES, ids=[c[0] for c in MOCK_STAGES]
)
def test_every_stage_reports_mock_provenance(
    pipeline: TriagePipeline, attribute: str, _expected: type, _protocol: type
) -> None:
    """Provenance is filled on a mock run too, so storage has no special case.

    `model_id="mock"` is also how the evaluation screen knows to label a run as
    meaningless rather than reporting it as a result (FR-26, NFR-23, ADR-17).
    """
    stage = getattr(pipeline, attribute)

    assert isinstance(stage, PipelineStage)
    assert stage.model_id == "mock"
    assert stage.prompt_version == "mock-0"
    assert stage.last_latency_ms == 0


def test_no_provider_is_built_when_every_stage_is_mock(pipeline: TriagePipeline) -> None:
    """CI must need no API key and no model download (ADR-17)."""
    assert pipeline.deps.llm is None
    assert pipeline.deps.embedder is None


def test_deps_carry_the_config_and_session_factory(
    pipeline: TriagePipeline, session_factory: FakeSessionFactory
) -> None:
    assert isinstance(pipeline.deps, PipelineDeps)
    assert pipeline.deps.config is pipeline.config
    assert pipeline.deps.session_factory is session_factory
    assert callable(pipeline.deps.rules_provider)


def test_building_a_mock_pipeline_opens_no_session(
    pipeline: TriagePipeline, session_factory: FakeSessionFactory
) -> None:
    """Startup must not touch the database; the worker is what does (ADR-08)."""
    assert session_factory.calls == 0


def test_rules_provider_reads_rules_on_each_call() -> None:
    """A rule approved while the worker runs must take effect on the next case.

    Asserted by the session being opened per call rather than once at build time
    (FR-12, FR-23).
    """
    opened: list[int] = []

    class RecordingSession:
        def __enter__(self) -> "RecordingSession":
            opened.append(1)
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def scalars(self, _statement: object) -> list[Any]:
            return []

    provider = active_rules_provider(RecordingSession, AppEnv.DEV)  # type: ignore[arg-type]

    assert provider() == []
    assert provider() == []
    assert len(opened) == 2


# --- Lazy imports ---------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "attribute", "expected"),
    IMPLEMENTED_CASES,
    ids=["PIPELINE_DEIDENTIFIER=rules", "PIPELINE_REDFLAGS=keywords"],
)
def test_an_implemented_stage_is_built_instead_of_its_mock(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: FakeSessionFactory,
    overrides: dict[str, str],
    attribute: str,
    expected: type,
) -> None:
    """Selecting a stage M1 has written builds that class, not the mock.

    The other half of the lazy import: a module that exists is imported and
    constructed, so the setting is the only thing that has to change to run the
    real stage (ADR-17). Neither M1 stage opens a session in `from_settings` —
    `deps.rules_provider` is stored, not called — so this still needs no engine.
    """
    settings = settings_with(monkeypatch, **overrides)

    pipeline = build_pipeline(settings, session_factory=session_factory)  # type: ignore[arg-type]

    assert type(getattr(pipeline, attribute)) is expected
    assert pipeline.is_fully_mocked is False
    assert session_factory.calls == 0


@pytest.mark.parametrize(
    ("overrides", "expected"),
    IMPLEMENTED_LLM_PROVIDER_CASES,
    ids=["LLM_PROVIDER=hosted", "LLM_PROVIDER=ollama"],
)
def test_an_implemented_llm_provider_is_built_instead_of_its_mock(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: FakeSessionFactory,
    overrides: dict[str, str],
    expected: type,
) -> None:
    """Selecting a provider M2 has written builds that class onto `deps.llm`.

    The same half of the lazy import as the stage case above, one level down:
    the provider module exists, so it is imported and constructed and the
    setting is the only thing that had to change (ADR-06, ADR-17). Neither
    adapter opens a session or a connection in `from_settings` — the httpx
    client is built, not used — so this still needs no engine and no network.
    """
    settings = settings_with(monkeypatch, **overrides)

    pipeline = build_pipeline(settings, session_factory=session_factory)  # type: ignore[arg-type]

    assert type(pipeline.deps.llm) is expected
    assert pipeline.is_fully_mocked is False
    assert session_factory.calls == 0


@pytest.mark.parametrize(
    ("overrides", "expected_selection", "guide"),
    NOT_IMPLEMENTED_CASES,
    ids=[case[1] for case in NOT_IMPLEMENTED_CASES],
)
def test_real_stage_without_a_module_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: FakeSessionFactory,
    overrides: dict[str, str],
    expected_selection: str,
    guide: str,
) -> None:
    """A module M1–M6 has not written yet names its guide, not a traceback."""
    settings = settings_with(monkeypatch, **overrides)

    with pytest.raises(StageNotImplementedError) as raised:
        build_pipeline(settings, session_factory=session_factory)  # type: ignore[arg-type]

    message = str(raised.value)
    assert expected_selection in message
    assert "not implemented yet" in message
    assert guide in message


def test_the_message_says_how_to_get_back_to_a_working_configuration(
    monkeypatch: pytest.MonkeyPatch, session_factory: FakeSessionFactory
) -> None:
    """A broken real stage must be revertible in seconds during a demo (ADR-17).

    Every documented stage is implemented now (M1–M6b), so there is no real
    "not written yet" module left to select. This simulates one instead, by
    making only `app.pipeline.actions_llm` fail to import — every other import
    `build_pipeline` needs (the mock stages built before `action_suggester`)
    still goes through the real `importlib.import_module`.
    """
    import importlib

    real_import_module = importlib.import_module

    def fail_only_for_actions_llm(name: str, *args: object, **kwargs: object) -> Any:
        if name == "app.pipeline.actions_llm":
            raise ModuleNotFoundError(
                "No module named 'app.pipeline.actions_llm'", name="app.pipeline.actions_llm"
            )
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fail_only_for_actions_llm)
    settings = settings_with(monkeypatch, PIPELINE_ACTIONS="llm")

    with pytest.raises(StageNotImplementedError, match="PIPELINE_ACTIONS=mock"):
        build_pipeline(settings, session_factory=session_factory)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [{"KB_INDEXER": "pgvector"}, {"PIPELINE_RETRIEVER": "pgvector"}],
    ids=["KB_INDEXER=pgvector", "PIPELINE_RETRIEVER=pgvector"],
)
def test_a_pgvector_stage_without_an_embedder_says_what_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: FakeSessionFactory,
    overrides: dict[str, str],
) -> None:
    """M5 and M6 exist now; what is missing is the embedder they both need (M4)."""
    settings = settings_with(monkeypatch, **overrides)

    with pytest.raises(RuntimeError, match="EMBEDDING_PROVIDER"):
        build_pipeline(settings, session_factory=session_factory)  # type: ignore[arg-type]


def test_the_llm_generator_is_built_on_the_shared_provider(
    monkeypatch: pytest.MonkeyPatch, session_factory: FakeSessionFactory
) -> None:
    """`PIPELINE_GENERATOR=llm` builds M6's class onto `deps.llm`, opening nothing (ADR-17)."""
    settings = settings_with(
        monkeypatch,
        PIPELINE_GENERATOR="llm",
        LLM_PROVIDER="ollama",
        PIPELINE_DEIDENTIFIER="rules",
    )

    pipeline = build_pipeline(settings, session_factory=session_factory)  # type: ignore[arg-type]

    assert type(pipeline.generator) is LLMRecommendationGenerator
    assert pipeline.generator.llm is pipeline.deps.llm
    assert pipeline.generator.prompt_version == "generation/v1.0"
    assert session_factory.calls == 0


def test_an_embedding_provider_is_built_only_when_one_is_selected(
    monkeypatch: pytest.MonkeyPatch, session_factory: FakeSessionFactory
) -> None:
    """Blank means no embedder; `sentence_transformer` builds M4's adapter.

    There is no mock embedder, because mock stages need no embeddings at all, so
    blank is a working configuration rather than a missing one (CLAUDE.md §8.3,
    ADR-07). `EMBEDDING_PROVIDER` is the only thing that differs between the two
    builds here: the safety guard keys off `LLM_PROVIDER`, which stays mock.

    The adapter loads its model on the first `embed`, not in `from_settings`, so
    building it imports neither `sentence_transformers` nor `torch` — asserted by
    a `_load` that fails the test if it is called, which is the one place the
    adapter would import either.
    """
    monkeypatch.setattr(SentenceTransformerEmbedder, "_load", _must_not_load)

    blank = build_pipeline(settings_with(monkeypatch), session_factory=session_factory)  # type: ignore[arg-type]

    assert blank.deps.embedder is None

    settings = settings_with(monkeypatch, EMBEDDING_PROVIDER="sentence_transformer")
    selected = build_pipeline(settings, session_factory=session_factory)  # type: ignore[arg-type]

    embedder = selected.deps.embedder
    assert type(embedder) is SentenceTransformerEmbedder
    assert isinstance(embedder, EmbeddingProvider)
    assert embedder.model_id == settings.embedding_model
    assert embedder.dim == settings.embedding_dim
    assert session_factory.calls == 0


def test_an_unrelated_import_error_is_not_disguised(
    monkeypatch: pytest.MonkeyPatch, session_factory: FakeSessionFactory
) -> None:
    """A real stage with a broken dependency is a different problem.

    Reporting it as "not implemented yet" would send the team to the wrong guide
    looking for code they had already written.
    """
    import importlib

    def fail_with_a_missing_dependency(name: str) -> None:
        raise ModuleNotFoundError(
            "No module named 'sentence_transformers'", name="sentence_transformers"
        )

    monkeypatch.setattr(importlib, "import_module", fail_with_a_missing_dependency)
    settings = settings_with(monkeypatch, PIPELINE_EXTRACTOR="llm")

    with pytest.raises(ModuleNotFoundError, match="sentence_transformers"):
        build_pipeline(settings, session_factory=session_factory)  # type: ignore[arg-type]


# --- The de-identification guard (IR-20, ADR-10) --------------------------


def test_settings_reject_a_real_llm_with_the_mock_deidentifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first of two gates: configuration cannot even be loaded."""
    with pytest.raises(Exception, match="PIPELINE_DEIDENTIFIER"):
        settings_with(monkeypatch, LLM_PROVIDER="hosted")


@pytest.mark.parametrize("provider", [LLMProviderOption.HOSTED, LLMProviderOption.OLLAMA])
def test_the_registry_refuses_the_combination_settings_cannot_express(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: FakeSessionFactory,
    provider: LLMProviderOption,
) -> None:
    """The second gate, for a Settings that skipped validation.

    `model_construct` is how a `Settings` can exist without its validators
    running. The guard must hold on the object it is handed, whatever made it:
    text that has not been de-identified must never reach a provider (IR-20,
    ADR-10).
    """
    valid = settings_with(monkeypatch)
    unsafe = Settings.model_construct(
        **{
            **valid.model_dump(),
            "llm_provider": provider,
            "pipeline_deidentifier": DeidentifierOption.MOCK,
        }
    )

    with pytest.raises(UnsafePipelineConfigError, match="de-identified"):
        build_pipeline(unsafe, session_factory=session_factory)  # type: ignore[arg-type]


def test_the_guard_runs_before_anything_is_imported(
    monkeypatch: pytest.MonkeyPatch, session_factory: FakeSessionFactory
) -> None:
    """The unsafe configuration must be refused, not merely fail later by luck."""
    import importlib

    def must_not_be_called(name: str) -> None:
        raise AssertionError(f"imported {name} despite an unsafe configuration")

    monkeypatch.setattr(importlib, "import_module", must_not_be_called)
    valid = settings_with(monkeypatch)
    unsafe = Settings.model_construct(
        **{
            **valid.model_dump(),
            "llm_provider": LLMProviderOption.HOSTED,
            "pipeline_deidentifier": DeidentifierOption.MOCK,
        }
    )

    with pytest.raises(UnsafePipelineConfigError):
        build_pipeline(unsafe, session_factory=session_factory)  # type: ignore[arg-type]


# --- The LLM provider contract -------------------------------------------


def test_mock_llm_provider_satisfies_the_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Used only by tests of the adapter contract (P05 §5.2)."""
    from app.adapters.llm.base import LLMProvider

    settings = settings_with(monkeypatch)
    deps = PipelineDeps(
        config=PipelineConfig.from_settings(settings),
        session_factory=FakeSessionFactory(),  # type: ignore[arg-type]
        llm=None,
        embedder=None,
        rules_provider=lambda: [],
    )

    provider = MockLLMProvider.from_settings(settings, deps)

    assert isinstance(provider, LLMProvider)
    assert provider.name == "mock"
    assert provider.model_id == "mock"
    assert provider.complete_json(system="s", user="u", json_schema={}, timeout_s=1.0) == {}
