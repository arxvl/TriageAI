import pytest
from pydantic import ValidationError

from app.core.config import Settings

BASE_ENV = {
    "DB_PASSWORD": "test",
    "DATABASE_URL": "postgresql+psycopg://triageai:test@localhost:5432/triageai",
    "TEST_DATABASE_URL": "postgresql+psycopg://triageai:test@localhost:5432/triageai_test",
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
