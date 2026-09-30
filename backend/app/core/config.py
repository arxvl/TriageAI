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
    OK = "ok"
    TIMEOUT = "timeout"
    INVALID_OUTPUT = "invalid_output"
    UNAVAILABLE = "unavailable"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    db_password: str
    database_url: str
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
