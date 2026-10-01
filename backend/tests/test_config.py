import pytest
from pydantic import ValidationError

from app.core.config import Settings

BASE_ENV = {
    "DB_PASSWORD": "test",
    "DB_APP_PASSWORD": "test-app",
    "DATABASE_URL": "postgresql+psycopg://triageai_app:test-app@localhost:5432/triageai",
    "MIGRATION_DATABASE_URL": "postgresql+psycopg://triageai:test@localhost:5432/triageai",
    "TEST_DATABASE_URL": "postgresql+psycopg://triageai_app:test-app@localhost:5432/triageai_test",
    "SECRET_KEY": "test-secret",
}


def test_all_mock_stages_are_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)

    settings = Settings()

    assert settings.llm_provider == "mock"
    assert settings.pipeline_deidentifier == "mock"


def test_real_llm_with_mock_deidentifier_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("LLM_PROVIDER", "hosted")
    monkeypatch.setenv("PIPELINE_DEIDENTIFIER", "mock")

    with pytest.raises(ValidationError):
        Settings()


def test_blank_embedding_provider_env_var_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "")

    settings = Settings()

    assert settings.embedding_provider is None


@pytest.mark.parametrize("behavior", ["ok", "invalid_json", "timeout", "flaky", "slow"])
def test_mock_llm_behavior_accepts_the_documented_values(
    monkeypatch: pytest.MonkeyPatch, behavior: str
) -> None:
    """P05 §5.2 and ADR-17 fix these five names; the mocks switch on them."""
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("MOCK_LLM_BEHAVIOR", behavior)

    assert Settings().mock_llm_behavior == behavior


@pytest.mark.parametrize("behavior", ["invalid_output", "unavailable", "broken"])
def test_mock_llm_behavior_rejects_anything_else(
    monkeypatch: pytest.MonkeyPatch, behavior: str
) -> None:
    """A typo in .env must fail at startup, not silently mean `ok`."""
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("MOCK_LLM_BEHAVIOR", behavior)

    with pytest.raises(ValidationError):
        Settings()


def test_pipeline_parameters_default_to_the_phase_prompt_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)

    settings = Settings()

    assert settings.pipeline_temperature == 0
    assert settings.pipeline_top_k == 5
    assert settings.pipeline_timeout_s == 30
    assert settings.pipeline_max_retries == 1
    assert settings.retrieval_min_score == 0.30
