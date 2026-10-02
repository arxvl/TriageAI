from enum import StrEnum
from functools import lru_cache

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

    pipeline_deidentifier: DeidentifierOption = DeidentifierOption.MOCK
    pipeline_redflags: RedFlagsOption = RedFlagsOption.MOCK
    llm_provider: LLMProviderOption = LLMProviderOption.MOCK
    pipeline_extractor: ExtractorOption = ExtractorOption.MOCK
    embedding_provider: EmbeddingProviderOption | None = None
    kb_indexer: KBIndexerOption = KBIndexerOption.MOCK
    pipeline_retriever: RetrieverOption = RetrieverOption.MOCK
    pipeline_generator: GeneratorOption = GeneratorOption.MOCK

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
