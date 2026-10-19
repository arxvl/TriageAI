from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class DeidentifierOption(StrEnum):
    MOCK = "mock"
    RULES = "rules"


class RedFlagsOption(StrEnum):
    MOCK = "mock"
    KEYWORDS = "keywords"


class LLMProviderOption(StrEnum):
    MOCK = "mock"
    HOSTED = "hosted"
    OLLAMA = "ollama"


class ExtractorOption(StrEnum):
    MOCK = "mock"
    LLM = "llm"


class EmbeddingProviderOption(StrEnum):
    SENTENCE_TRANSFORMER = "sentence_transformer"


class KBIndexerOption(StrEnum):
    MOCK = "mock"
    PGVECTOR = "pgvector"


class RetrieverOption(StrEnum):
    MOCK = "mock"
    PGVECTOR = "pgvector"


class GeneratorOption(StrEnum):
    MOCK = "mock"
    LLM = "llm"


class ActionsOption(StrEnum):
    MOCK = "mock"
    LLM = "llm"


class MockLLMBehavior(StrEnum):
    """Which failure the mock stages simulate (P05 §5.2, ADR-17).

    These are the paths that have to be demonstrable without a network call:
    `invalid_json` fails every attempt, `flaky` fails the first and succeeds on
    the retry, `timeout` and `slow` exercise the latency budget.
    """

    OK = "ok"
    INVALID_JSON = "invalid_json"
    TIMEOUT = "timeout"
    FLAKY = "flaky"
    SLOW = "slow"


# How long `slow` delays one model call. Long enough to show a real latency in
# the stored `stage_ms` and in the UI, short enough that a test suite running the
# whole behaviour matrix stays quick, and far inside `PIPELINE_TIMEOUT_S` — `slow`
# means late, not timed out (P05 §5.2). It lives here, next to the enum that
# selects it, so the mock stages and the mock provider share one value without
# either importing the other.
MOCK_SLOW_DELAY_S = 0.25


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    db_password: str
    db_app_password: str
    database_url: str
    migration_database_url: str
    test_database_url: str

    secret_key: str
    session_idle_minutes: int = 30

    cors_origins: str = "http://localhost:5173"

    app_env: AppEnv = AppEnv.DEV
    tz_display: str = "Asia/Manila"

    # Where the curated knowledge-base files live: `entries/*.yaml`,
    # `red_flags.yaml` and `red_flag_phrases.yaml` (P08 §8.2, FR-56). The default
    # is the container mount path from docker-compose.yml, which is also what
    # `app/pipeline/redflags_keywords.py` reads; `scripts.import_kb --dir` points
    # it elsewhere when the importer is run on the host.
    knowledge_base_dir: str = "/knowledge_base"

    EXTRACTION_PROMPT_VERSION: str = "v1.0"

    # ---- LLM provider (M2) ----
    LLM_PROVIDER: Literal["mock", "hosted", "ollama"] = "mock"
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    LLM_TEMPERATURE: str = ""
    LLM_SEED: str = ""
    LLM_JSON_MODE: Literal["json_schema", "json_object", "prompt_only"] = "json_schema"
    LLM_SCHEMA_IN_PROMPT: bool = True
    LLM_SCHEMA_SIMPLIFY: bool = True
    LLM_REASONING_EFFORT: str = ""
    LLM_MAX_RPM: int = 0
    LLM_HTTP_RETRIES: int = 2
    LLM_RATE_LIMIT_WAIT_S: float = 20.0
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434/v1"
    OLLAMA_MODEL: str = ""
    OLLAMA_JSON_MODE: Literal["json_schema", "json_object", "prompt_only"] = "json_schema"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = ""
    GEMINI_RPM: int = 0
    GEMINI_REASONING_EFFORT: str = ""
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = ""
    GROQ_RPM: int = 0
    GROQ_JSON_MODE: Literal["json_schema", "json_object", "prompt_only"] = "json_object"

    EMBEDDING_PROVIDER: Literal["", "sentence_transformer"] = ""  # blank = no embedder is built
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    embedding_device: str = "cpu"
    embedding_batch_size: int = 32
    EMBEDDING_WARMUP: bool = True

    pipeline_deidentifier: DeidentifierOption = DeidentifierOption.MOCK
    pipeline_redflags: RedFlagsOption = RedFlagsOption.MOCK
    llm_provider: LLMProviderOption = LLMProviderOption.MOCK
    pipeline_extractor: ExtractorOption = ExtractorOption.MOCK
    embedding_provider: EmbeddingProviderOption | None = None
    kb_indexer: KBIndexerOption = KBIndexerOption.MOCK
    pipeline_retriever: RetrieverOption = RetrieverOption.MOCK
    pipeline_generator: GeneratorOption = GeneratorOption.MOCK
    pipeline_actions: ActionsOption = ActionsOption.MOCK

    mock_llm_behavior: MockLLMBehavior = MockLLMBehavior.OK

    # The background job worker (P05 §5.4 task 2, ADR-08). Enabled by default so
    # a clean `docker compose up` triages the cases it is given; `false` in tests,
    # where `run_pending_jobs_once` runs the queue synchronously instead.
    job_worker_enabled: bool = True
    job_poll_interval_s: float = 0.5
    # How long a job may sit in RUNNING before the startup sweep assumes the
    # worker holding it is gone (NFR-13).
    job_stale_after_minutes: int = 2

    # Pipeline run parameters (P05 §5.1 task 5). Read once into
    # `app.pipeline.config.PipelineConfig`, which is what the stages receive;
    # nothing outside the registry reads these fields directly.
    pipeline_model_id: str = "mock"
    pipeline_prompt_version: str = "mock-0"
    pipeline_temperature: float = 0.0
    pipeline_top_k: int = 5
    pipeline_timeout_s: float = 30.0
    pipeline_max_retries: int = 1
    retrieval_min_score: float = 0.30

    # Suggested actions (P05b §5b.3, ADR-18). `actions_prompt_version` is the
    # real stage's prompt version (M6b); a mock reports its own `mock-0`, as
    # every other mock stage does. `actions_max_items` caps the tailored list
    # the validator keeps — the baseline set is never capped, because it is
    # curated content for one category (FR-71, FR-72).
    actions_prompt_version: str = "v1.0"
    actions_max_items: int = 5

    @field_validator("embedding_provider", mode="before")
    @classmethod
    def _blank_embedding_provider_is_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @model_validator(mode="after")
    def _enforce_deidentify_before_real_llm(self) -> "Settings":
        # De-identified text only must ever leave the server (IR-20, ADR-10).
        real_llm = self.llm_provider != LLMProviderOption.MOCK
        mock_deidentifier = self.pipeline_deidentifier == DeidentifierOption.MOCK
        if real_llm and mock_deidentifier:
            raise ValueError(
                "LLM_PROVIDER cannot be non-mock while PIPELINE_DEIDENTIFIER is mock "
                "(CLAUDE.md §8.3 safety guard)"
            )
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
