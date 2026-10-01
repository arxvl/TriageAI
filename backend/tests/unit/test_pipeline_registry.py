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

from app.adapters.llm.mock import MockLLMProvider
from app.core.config import DeidentifierOption, LLMProviderOption, Settings
from app.pipeline import mocks
from app.pipeline.config import PipelineConfig
from app.pipeline.orchestrator import TriagePipeline
from app.pipeline.registry import (
    PipelineDeps,
    StageNotImplementedError,
    UnsafePipelineConfigError,
    all_red_flag_rules,
    build_pipeline,
)
from app.pipeline.stages import (
    Deidentifier,
    EntityExtractor,
    KBIndexer,
    PipelineStage,
    RecommendationGenerator,
    RedFlagScreener,
    Retriever,
)
from tests.test_config import BASE_ENV

# The stage attribute on TriagePipeline, its expected mock class, and the
# Protocol it must satisfy.
MOCK_STAGES: list[tuple[str, type, type]] = [
    ("deidentifier", mocks.MockDeidentifier, Deidentifier),
    ("red_flag_screener", mocks.MockRedFlagScreener, RedFlagScreener),
    ("extractor", mocks.MockEntityExtractor, EntityExtractor),
    ("retriever", mocks.MockRetriever, Retriever),
    ("generator", mocks.MockRecommendationGenerator, RecommendationGenerator),
    ("kb_indexer", mocks.MockKBIndexer, KBIndexer),
]

# Every non-mock option, with the M-guide its error message must name. The
# LLM_PROVIDER and EMBEDDING_PROVIDER rows also set a real de-identifier, so it
# is the missing module that trips and not the safety guard.
NOT_IMPLEMENTED_CASES: list[tuple[dict[str, str], str, str]] = [
    ({"PIPELINE_DEIDENTIFIER": "rules"}, "PIPELINE_DEIDENTIFIER=rules", "M1"),
    ({"PIPELINE_REDFLAGS": "keywords"}, "PIPELINE_REDFLAGS=keywords", "M1"),
    ({"PIPELINE_EXTRACTOR": "llm"}, "PIPELINE_EXTRACTOR=llm", "M3"),
    ({"KB_INDEXER": "pgvector"}, "KB_INDEXER=pgvector", "M5"),
    ({"PIPELINE_RETRIEVER": "pgvector"}, "PIPELINE_RETRIEVER=pgvector", "M6"),
    ({"PIPELINE_GENERATOR": "llm"}, "PIPELINE_GENERATOR=llm", "M6"),
    (
        {"LLM_PROVIDER": "hosted", "PIPELINE_DEIDENTIFIER": "rules"},
        "LLM_PROVIDER=hosted",
        "M2",
    ),
    (
        {"LLM_PROVIDER": "ollama", "PIPELINE_DEIDENTIFIER": "rules"},
        "LLM_PROVIDER=ollama",
        "M2",
    ),
    (
        {"EMBEDDING_PROVIDER": "sentence_transformer", "PIPELINE_DEIDENTIFIER": "rules"},
        "EMBEDDING_PROVIDER=sentence_transformer",
        "M4",
    ),
]


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
    for key, value in {**BASE_ENV, **overrides}.items():
        monkeypatch.setenv(key, value)
    return Settings()


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

    provider = all_red_flag_rules(RecordingSession)  # type: ignore[arg-type]

    assert provider() == []
    assert provider() == []
    assert len(opened) == 2


# --- Lazy imports ---------------------------------------------------------


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
    """A broken real stage must be revertible in seconds during a demo (ADR-17)."""
    settings = settings_with(monkeypatch, PIPELINE_EXTRACTOR="llm")

    with pytest.raises(StageNotImplementedError, match="PIPELINE_EXTRACTOR=mock"):
        build_pipeline(settings, session_factory=session_factory)  # type: ignore[arg-type]


def test_embedding_provider_is_told_to_be_left_blank(
    monkeypatch: pytest.MonkeyPatch, session_factory: FakeSessionFactory
) -> None:
    """There is no mock embedder; mock stages need no embeddings (CLAUDE.md §8.3)."""
    settings = settings_with(
        monkeypatch, EMBEDDING_PROVIDER="sentence_transformer", PIPELINE_DEIDENTIFIER="rules"
    )

    with pytest.raises(StageNotImplementedError, match="blank"):
        build_pipeline(settings, session_factory=session_factory)  # type: ignore[arg-type]


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
    for key, value in {**BASE_ENV, "LLM_PROVIDER": "hosted"}.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(Exception, match="PIPELINE_DEIDENTIFIER"):
        Settings()


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
