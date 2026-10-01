"""A no-network `LLMProvider` (CLAUDE.md §8.3, ADR-06).

This provider is **not** what makes the mock pipeline work. The mock stages in
`app.pipeline.mocks` return fixtures directly and never call a provider at all,
which is why `PipelineDeps.llm` is `None` when every stage is mock.

It exists so the `LLMProvider` contract itself can be tested — that a stage calls
`complete_json` with a system prompt, a user prompt, a schema and a timeout, and
that it handles each of the three errors — before `hosted` or `ollama` exist
(M2). Tests also use it as a seam for forcing a specific failure.

It calls nothing and holds no credentials.
"""

from time import sleep
from typing import TYPE_CHECKING

from app.core.config import MOCK_SLOW_DELAY_S, MockLLMBehavior, Settings
from app.pipeline.errors import LLMInvalidOutput, LLMTimeout

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.pipeline.registry import PipelineDeps


class MockLLMProvider:
    name = "mock"
    model_id = "mock"

    def __init__(self, behavior: MockLLMBehavior = MockLLMBehavior.OK) -> None:
        self.behavior = behavior
        self.calls = 0

    @classmethod
    def from_settings(cls, settings: Settings, deps: "PipelineDeps") -> "MockLLMProvider":
        return cls(behavior=settings.mock_llm_behavior)

    def complete_json(self, *, system: str, user: str, json_schema: dict, timeout_s: float) -> dict:
        """Return an empty object, or raise what `MOCK_LLM_BEHAVIOR` asks for.

        An empty dict rather than a plausible-looking one on purpose: a caller
        that quietly accepted this would be producing a recommendation out of
        nothing, and the test that catches it should fail loudly.

        `flaky` counts calls on this instance, which is all a contract test needs
        — unlike the stages, this provider is built per test rather than once per
        process. Messages name the behaviour and never the prompt (CLAUDE.md §9).
        """
        self.calls += 1

        if self.behavior is MockLLMBehavior.TIMEOUT:
            raise LLMTimeout(
                f"mock provider simulating a timeout after {timeout_s}s "
                f"(MOCK_LLM_BEHAVIOR={self.behavior})"
            )

        if self.behavior is MockLLMBehavior.INVALID_JSON:
            raise LLMInvalidOutput(
                f"mock provider simulating unusable output (MOCK_LLM_BEHAVIOR={self.behavior})"
            )

        if self.behavior is MockLLMBehavior.FLAKY and self.calls == 1:
            raise LLMInvalidOutput(
                f"mock provider simulating a first-attempt failure "
                f"(MOCK_LLM_BEHAVIOR={self.behavior}); the retry succeeds"
            )

        if self.behavior is MockLLMBehavior.SLOW:
            sleep(min(MOCK_SLOW_DELAY_S, timeout_s))

        return {}
