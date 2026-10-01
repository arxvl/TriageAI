"""Builds the pipeline from settings, with lazy imports (CLAUDE.md §8.3, ADR-17).

One place decides which implementation of each stage runs. Everything else
depends on the Protocols in `app.pipeline.stages`, so turning a component from
placeholder to real is a line in `.env` and no application code moves — and a
broken real stage can be reverted to its mock in seconds during a demonstration.

Three properties this module has to hold:

**Lazy imports.** `app.pipeline.deidentify_rules`, `app.pipeline.extraction_llm`,
`app.adapters.llm.hosted` and the rest are written manually in M1–M6 and do not
exist yet. They are imported only if selected, and a missing one produces
`StageNotImplementedError` naming its guide rather than an ImportError
traceback. A module that exists but fails to import for its own reasons is *not*
disguised — that error propagates.

**Mock by default.** Every stage setting defaults to `mock`, so a clean checkout
starts, serves and passes its tests with no API key, no model download and no
network (ADR-17).

**The de-identification guard.** The application refuses to start if a non-mock
`LLM_PROVIDER` is selected while `PIPELINE_DEIDENTIFIER` is still the mock, which
returns text unchanged. Only de-identified text may leave the server (IR-20,
ADR-10).

Construction order follows CLAUDE.md §8.3: config, session_factory, llm, embedder,
rules_provider, then the stages. The provider objects are built once and shared,
and stay `None` when nothing needs them.
"""

import importlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import (
    DeidentifierOption,
    EmbeddingProviderOption,
    ExtractorOption,
    GeneratorOption,
    KBIndexerOption,
    LLMProviderOption,
    RedFlagsOption,
    RetrieverOption,
    Settings,
)
from app.models.knowledge_base import RedFlagRule
from app.pipeline.config import PipelineConfig
from app.pipeline.errors import PipelineError
from app.pipeline.orchestrator import TriagePipeline

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.adapters.embeddings.base import EmbeddingProvider
    from app.adapters.llm.base import LLMProvider


class StageNotImplementedError(PipelineError):
    """A setting selected a real stage whose module has not been written yet.

    Deliberately not one of the six errors in `app.pipeline.errors`: that list is
    fixed by P05 §5.1 task 3 and describes failures of a *running* pipeline. This
    is a configuration failure, raised at startup, before any case is touched.
    """


class UnsafePipelineConfigError(PipelineError):
    """The configuration would send text that has not been de-identified."""


@dataclass(frozen=True)
class _StageSpec:
    """Where a setting value's implementation lives, and who writes it."""

    target: str  # "module:Class"
    guide: str | None = None  # the M-guide, for the not-implemented message


_GUIDE_FILES = {
    "M1": "docs/dev-prompts/M1-deidentification-redflags.md",
    "M2": "docs/dev-prompts/M2-llm-provider-setup.md",
    "M3": "docs/dev-prompts/M3-entity-extraction.md",
    "M4": "docs/dev-prompts/M4-pgvector-embeddings.md",
    "M5": "docs/dev-prompts/M5-kb-chunking-indexing.md",
    "M6": "docs/dev-prompts/M6-retrieval-generation.md",
}

# The CLAUDE.md §8.3 / ADR-17 table, as data. The module paths and class names of
# the real stages are fixed by those documents: the manual guides create exactly
# these, so nothing here changes when they appear.

DEIDENTIFIER_SPECS: dict[DeidentifierOption, _StageSpec] = {
    DeidentifierOption.MOCK: _StageSpec("app.pipeline.mocks:MockDeidentifier"),
    DeidentifierOption.RULES: _StageSpec(
        "app.pipeline.deidentify_rules:RuleBasedDeidentifier", "M1"
    ),
}

REDFLAGS_SPECS: dict[RedFlagsOption, _StageSpec] = {
    RedFlagsOption.MOCK: _StageSpec("app.pipeline.mocks:MockRedFlagScreener"),
    RedFlagsOption.KEYWORDS: _StageSpec(
        "app.pipeline.redflags_keywords:KeywordRedFlagScreener", "M1"
    ),
}

LLM_PROVIDER_SPECS: dict[LLMProviderOption, _StageSpec] = {
    LLMProviderOption.MOCK: _StageSpec("app.adapters.llm.mock:MockLLMProvider"),
    LLMProviderOption.HOSTED: _StageSpec("app.adapters.llm.hosted:HostedLLMProvider", "M2"),
    LLMProviderOption.OLLAMA: _StageSpec("app.adapters.llm.ollama:OllamaLLMProvider", "M2"),
}

EXTRACTOR_SPECS: dict[ExtractorOption, _StageSpec] = {
    ExtractorOption.MOCK: _StageSpec("app.pipeline.mocks:MockEntityExtractor"),
    ExtractorOption.LLM: _StageSpec("app.pipeline.extraction_llm:LLMEntityExtractor", "M3"),
}

EMBEDDING_PROVIDER_SPECS: dict[EmbeddingProviderOption, _StageSpec] = {
    EmbeddingProviderOption.SENTENCE_TRANSFORMER: _StageSpec(
        "app.adapters.embeddings.sentence_transformer:SentenceTransformerEmbedder", "M4"
    ),
}

KB_INDEXER_SPECS: dict[KBIndexerOption, _StageSpec] = {
    KBIndexerOption.MOCK: _StageSpec("app.pipeline.mocks:MockKBIndexer"),
    KBIndexerOption.PGVECTOR: _StageSpec("app.kb.indexer_pgvector:PgVectorKBIndexer", "M5"),
}

RETRIEVER_SPECS: dict[RetrieverOption, _StageSpec] = {
    RetrieverOption.MOCK: _StageSpec("app.pipeline.mocks:MockRetriever"),
    RetrieverOption.PGVECTOR: _StageSpec("app.pipeline.retrieval_pgvector:PgVectorRetriever", "M6"),
}

GENERATOR_SPECS: dict[GeneratorOption, _StageSpec] = {
    GeneratorOption.MOCK: _StageSpec("app.pipeline.mocks:MockRecommendationGenerator"),
    GeneratorOption.LLM: _StageSpec("app.pipeline.generation_llm:LLMRecommendationGenerator", "M6"),
}


@dataclass(frozen=True)
class PipelineDeps:
    """What every stage's `from_settings` is given (CLAUDE.md §8.3).

    Fields in the order the registry fills them. `llm` and `embedder` are `None`
    when no selected stage needs them — a fully mocked pipeline calls no provider
    at all, which is what lets CI run without an API key or a model download.
    """

    config: PipelineConfig
    session_factory: sessionmaker
    llm: "LLMProvider | None"
    embedder: "EmbeddingProvider | None"
    rules_provider: Callable[[], list[RedFlagRule]]


def all_red_flag_rules(session_factory: sessionmaker) -> Callable[[], list[RedFlagRule]]:
    """The default `rules_provider`: every row of `red_flag_rules`.

    A fresh session per call, not a cached list: a rule approved while the worker
    is running must take effect on the next case, and a red-flag rule is the one
    thing that should never be stale (FR-12, FR-23).

    TODO(P08): replace with `get_active_rules`, which will exclude placeholder
    rules once a veterinarian has approved real ones. Until then the seeded
    placeholders are all there is, and screening with them beats screening with
    nothing.
    """

    def provider() -> list[RedFlagRule]:
        with session_factory() as session:
            return list(session.scalars(select(RedFlagRule).order_by(RedFlagRule.code)))

    return provider


def _guide_reference(spec: _StageSpec) -> str:
    """How the not-implemented message names the guide that writes this stage."""
    if spec.guide is None:
        return "docs/dev-prompts/P05-pipeline-framework.md"
    return f"{spec.guide}: {_GUIDE_FILES[spec.guide]}"


def _fallback_hint(setting: str) -> str:
    """How to get back to a working configuration.

    `EMBEDDING_PROVIDER` has no mock: mock stages need no embeddings at all, so
    the way back is to leave it unset (CLAUDE.md §8.3).
    """
    if setting == "EMBEDDING_PROVIDER":
        return "Leave EMBEDDING_PROVIDER blank; the mock stages need no embeddings."
    return f"Set {setting}=mock to run on the deterministic placeholder."


def _load_class(spec: _StageSpec, setting: str, value: str) -> type[Any]:
    """Import `spec.target` now, or explain which guide has not been written.

    Only a missing *target module* becomes `StageNotImplementedError`. An
    ImportError from inside a module that does exist propagates unchanged — a real
    stage with a broken dependency must not look like a stage nobody wrote yet.
    """
    module_path, _, class_name = spec.target.partition(":")
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as error:
        if error.name != module_path and not module_path.startswith(f"{error.name}."):
            raise
        raise StageNotImplementedError(
            f"Stage {setting}={value} selected but module not implemented yet "
            f"(see {_guide_reference(spec)}). {_fallback_hint(setting)}"
        ) from error

    try:
        return getattr(module, class_name)
    except AttributeError as error:
        raise StageNotImplementedError(
            f"Stage {setting}={value} selected: {module_path} exists but defines no "
            f"{class_name}. The class name is fixed by CLAUDE.md §8.3."
        ) from error


def _build_stage(
    specs: dict[Any, _StageSpec],
    option: Any,
    setting: str,
    settings: Settings,
    deps: PipelineDeps,
) -> Any:
    stage_class = _load_class(specs[option], setting, str(option))
    return stage_class.from_settings(settings, deps)


def _requires_provider(settings: Settings) -> bool:
    """True when any stage is real, so the shared providers must be built.

    A fully mocked pipeline needs neither an LLM nor an embedder, and building
    one anyway would import a provider module that may not exist (ADR-17).
    """
    return (
        settings.pipeline_deidentifier != DeidentifierOption.MOCK
        or settings.pipeline_redflags != RedFlagsOption.MOCK
        or settings.pipeline_extractor != ExtractorOption.MOCK
        or settings.kb_indexer != KBIndexerOption.MOCK
        or settings.pipeline_retriever != RetrieverOption.MOCK
        or settings.pipeline_generator != GeneratorOption.MOCK
    )


def _assert_deidentification_before_llm(settings: Settings) -> None:
    """Refuse a configuration that could send raw text off the server.

    `Settings` already rejects this combination in its own validator, so in
    normal operation this never fires. It is repeated here because
    `build_pipeline` can be handed a `Settings` built with `model_construct` or
    mutated after validation, and this is the one guard that must not be
    bypassable by the way the object was made (IR-20, ADR-10).
    """
    if (
        settings.llm_provider != LLMProviderOption.MOCK
        and settings.pipeline_deidentifier == DeidentifierOption.MOCK
    ):
        raise UnsafePipelineConfigError(
            f"LLM_PROVIDER={settings.llm_provider} with PIPELINE_DEIDENTIFIER=mock would "
            "send text that has not been de-identified to an external service. Select a "
            "real de-identifier (IR-20, ADR-10)."
        )


def build_pipeline(
    settings: Settings, session_factory: sessionmaker | None = None
) -> TriagePipeline:
    """Build the pipeline for this configuration.

    Called once from the FastAPI lifespan, so a misconfiguration is a startup
    failure rather than a case that fails halfway through. `session_factory` is
    injectable for tests; it defaults to the application's.
    """
    _assert_deidentification_before_llm(settings)

    if session_factory is None:
        # Imported here, not at module scope: importing `app.db.session` creates
        # the engine, and `import app.pipeline.registry` should not do that.
        from app.db.session import SessionLocal

        session_factory = SessionLocal

    config = PipelineConfig.from_settings(settings)
    deps = PipelineDeps(
        config=config,
        session_factory=session_factory,
        llm=None,
        embedder=None,
        rules_provider=all_red_flag_rules(session_factory),
    )

    # The providers are built before the stages and shared by all of them, so one
    # process holds one client and one loaded embedding model (ADR-06, ADR-07).
    if _requires_provider(settings):
        llm = _build_stage(
            LLM_PROVIDER_SPECS, settings.llm_provider, "LLM_PROVIDER", settings, deps
        )
        deps = replace(deps, llm=llm)

    if settings.embedding_provider is not None:
        embedder = _build_stage(
            EMBEDDING_PROVIDER_SPECS,
            settings.embedding_provider,
            "EMBEDDING_PROVIDER",
            settings,
            deps,
        )
        deps = replace(deps, embedder=embedder)

    return TriagePipeline(
        config=config,
        deps=deps,
        deidentifier=_build_stage(
            DEIDENTIFIER_SPECS,
            settings.pipeline_deidentifier,
            "PIPELINE_DEIDENTIFIER",
            settings,
            deps,
        ),
        red_flag_screener=_build_stage(
            REDFLAGS_SPECS, settings.pipeline_redflags, "PIPELINE_REDFLAGS", settings, deps
        ),
        extractor=_build_stage(
            EXTRACTOR_SPECS, settings.pipeline_extractor, "PIPELINE_EXTRACTOR", settings, deps
        ),
        retriever=_build_stage(
            RETRIEVER_SPECS, settings.pipeline_retriever, "PIPELINE_RETRIEVER", settings, deps
        ),
        generator=_build_stage(
            GENERATOR_SPECS, settings.pipeline_generator, "PIPELINE_GENERATOR", settings, deps
        ),
        kb_indexer=_build_stage(
            KB_INDEXER_SPECS, settings.kb_indexer, "KB_INDEXER", settings, deps
        ),
    )
