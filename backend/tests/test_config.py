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


def settings_from_base_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    """`Settings` built from BASE_ENV plus `overrides`, and nothing else.

    Every other field falls back to the default declared on `Settings`. The
    clearing step is what makes that true: docker-compose hands the backend the
    development `.env` through `env_file`, so its values arrive in the container
    as real environment variables and `pydantic-settings` reads them. Without
    this, a test asserting on a default instead reads whichever stage the team
    happens to be running — `PIPELINE_DEIDENTIFIER=rules` once M1 is in use, or a
    `MOCK_LLM_BEHAVIOR` left on a failure value after a demo. Tests run on the
    mock stages (CLAUDE.md §10), whatever `.env` says.
    """
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    for key, value in {**BASE_ENV, **overrides}.items():
        monkeypatch.setenv(key, value)
    return Settings()


def test_all_mock_stages_are_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_from_base_env(monkeypatch)

    assert settings.llm_provider == "mock"
    assert settings.pipeline_deidentifier == "mock"


def test_real_llm_with_mock_deidentifier_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        settings_from_base_env(monkeypatch, LLM_PROVIDER="hosted", PIPELINE_DEIDENTIFIER="mock")


def test_blank_embedding_provider_env_var_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_from_base_env(monkeypatch, EMBEDDING_PROVIDER="")

    assert settings.embedding_provider is None


@pytest.mark.parametrize("behavior", ["ok", "invalid_json", "timeout", "flaky", "slow"])
def test_mock_llm_behavior_accepts_the_documented_values(
    monkeypatch: pytest.MonkeyPatch, behavior: str
) -> None:
    """P05 §5.2 and ADR-17 fix these five names; the mocks switch on them."""
    settings = settings_from_base_env(monkeypatch, MOCK_LLM_BEHAVIOR=behavior)

    assert settings.mock_llm_behavior == behavior


@pytest.mark.parametrize("behavior", ["invalid_output", "unavailable", "broken"])
def test_mock_llm_behavior_rejects_anything_else(
    monkeypatch: pytest.MonkeyPatch, behavior: str
) -> None:
    """A typo in .env must fail at startup, not silently mean `ok`."""
    with pytest.raises(ValidationError):
        settings_from_base_env(monkeypatch, MOCK_LLM_BEHAVIOR=behavior)


def test_pipeline_parameters_default_to_the_phase_prompt_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_from_base_env(monkeypatch)

    assert settings.pipeline_temperature == 0
    assert settings.pipeline_top_k == 5
    assert settings.pipeline_timeout_s == 30
    assert settings.pipeline_max_retries == 1
    assert settings.retrieval_min_score == 0.30
