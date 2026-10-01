"""`PipelineConfig` defaults and the settings they come from (P05 §5.1 task 5).

The defaults are asserted literally because two of them are safety-relevant:
`temperature=0` is what makes a run reproducible (ADR-14), and
`retrieval_min_score=0.30` is the threshold the validator uses to decide that the
evidence is too weak to be confident about (P05 §5.3 rule 3). Neither should
drift by accident.
"""

import pytest

from app.core.config import Settings
from app.pipeline.config import PipelineConfig
from tests.test_config import BASE_ENV


def settings_with(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    for key, value in {**BASE_ENV, **overrides}.items():
        monkeypatch.setenv(key, value)
    return Settings()


def test_defaults_match_the_phase_prompt() -> None:
    config = PipelineConfig()

    assert config.model_id == "mock"
    assert config.prompt_version == "mock-0"
    assert config.temperature == 0
    assert config.top_k == 5
    assert config.timeout_s == 30
    assert config.max_retries == 1
    assert config.retrieval_min_score == 0.30


def test_from_settings_uses_the_same_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """A clean .env and a bare PipelineConfig() must agree.

    Otherwise the documented defaults and the running ones diverge, and the
    `.env.example` comments stop being true.
    """
    assert PipelineConfig.from_settings(settings_with(monkeypatch)) == PipelineConfig()


def test_from_settings_reads_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_with(
        monkeypatch,
        PIPELINE_MODEL_ID="fictitious-model-7b",
        PIPELINE_PROMPT_VERSION="extraction/v1.0",
        PIPELINE_TOP_K="8",
        PIPELINE_TIMEOUT_S="12.5",
        PIPELINE_MAX_RETRIES="2",
        RETRIEVAL_MIN_SCORE="0.45",
    )

    config = PipelineConfig.from_settings(settings)

    assert config.model_id == "fictitious-model-7b"
    assert config.prompt_version == "extraction/v1.0"
    assert config.top_k == 8
    assert config.timeout_s == 12.5
    assert config.max_retries == 2
    assert config.retrieval_min_score == 0.45


def test_config_is_frozen() -> None:
    """A run's parameters cannot change mid-run, or its provenance is a lie."""
    config = PipelineConfig()

    with pytest.raises(Exception, match="frozen|immutable|cannot assign"):
        config.top_k = 99  # type: ignore[misc]
