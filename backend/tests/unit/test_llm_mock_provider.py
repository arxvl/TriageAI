"""The `LLMProvider` contract, through the mock provider (P05 §5.2, ADR-06).

`MockLLMProvider` is not what makes the mock pipeline work — the mock stages
return fixtures directly and never call a provider, which is why
`PipelineDeps.llm` is `None` when every stage is mock. It exists so the port
itself can be exercised before `hosted` and `ollama` are written in M2: that a
caller passes a system prompt, a user prompt, a schema and a timeout, and that
each of the three documented failures is raised as the contract says.

Nothing here makes a request or holds a credential (CLAUDE.md §9).
"""

import pytest

from app.adapters.llm.base import LLMProvider
from app.adapters.llm.mock import MockLLMProvider
from app.core.config import MOCK_SLOW_DELAY_S, MockLLMBehavior, Settings
from app.pipeline.config import PipelineConfig
from app.pipeline.errors import LLMInvalidOutput, LLMTimeout
from app.pipeline.registry import PipelineDeps
from tests.test_config import BASE_ENV

SCHEMA = {"type": "object", "properties": {"category": {"type": "string"}}}


def call(provider: MockLLMProvider) -> dict:
    """One call with every argument the contract requires (CLAUDE.md §8.2)."""
    return provider.complete_json(
        system="You classify urgency.",
        user="A de-identified description.",
        json_schema=SCHEMA,
        timeout_s=30.0,
    )


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    return Settings()


@pytest.fixture
def deps(settings: Settings) -> PipelineDeps:
    return PipelineDeps(
        config=PipelineConfig.from_settings(settings),
        session_factory=None,  # type: ignore[arg-type]
        llm=None,
        embedder=None,
        rules_provider=lambda: [],
    )


# --- The contract ---------------------------------------------------------


def test_the_mock_satisfies_the_provider_protocol() -> None:
    """`LLMProvider` is runtime_checkable, so this is the real structural check."""
    assert isinstance(MockLLMProvider(), LLMProvider)


def test_it_reports_itself_as_the_mock() -> None:
    provider = MockLLMProvider()

    assert provider.name == "mock"
    assert provider.model_id == "mock"


def test_from_settings_reads_the_behavior(settings: Settings, deps: PipelineDeps) -> None:
    provider = MockLLMProvider.from_settings(settings, deps)

    assert provider.behavior is MockLLMBehavior.OK


def test_ok_returns_an_empty_object() -> None:
    """Empty on purpose: a caller that accepts this is inventing a result."""
    assert call(MockLLMProvider(MockLLMBehavior.OK)) == {}


def test_every_call_is_counted() -> None:
    provider = MockLLMProvider(MockLLMBehavior.OK)
    call(provider)
    call(provider)

    assert provider.calls == 2


# --- The three documented failures ---------------------------------------


def test_timeout_raises_llm_timeout() -> None:
    with pytest.raises(LLMTimeout):
        call(MockLLMProvider(MockLLMBehavior.TIMEOUT))


def test_invalid_json_raises_llm_invalid_output_every_time() -> None:
    provider = MockLLMProvider(MockLLMBehavior.INVALID_JSON)

    with pytest.raises(LLMInvalidOutput):
        call(provider)
    with pytest.raises(LLMInvalidOutput):
        call(provider)


def test_flaky_fails_the_first_call_and_answers_the_retry() -> None:
    provider = MockLLMProvider(MockLLMBehavior.FLAKY)

    with pytest.raises(LLMInvalidOutput):
        call(provider)

    assert call(provider) == {}


def test_slow_answers_within_the_timeout() -> None:
    assert call(MockLLMProvider(MockLLMBehavior.SLOW)) == {}
    assert MOCK_SLOW_DELAY_S < PipelineConfig().timeout_s


def test_no_failure_message_quotes_the_prompt() -> None:
    """Messages reach the log and the job's `last_error` (CLAUDE.md §9)."""
    provider = MockLLMProvider(MockLLMBehavior.INVALID_JSON)

    with pytest.raises(LLMInvalidOutput) as raised:
        call(provider)

    assert "de-identified description" not in str(raised.value)
    assert "You classify urgency" not in str(raised.value)
