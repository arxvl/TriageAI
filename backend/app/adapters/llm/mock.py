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

from typing import TYPE_CHECKING

from app.core.config import MockLLMBehavior, Settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.pipeline.registry import PipelineDeps


class MockLLMProvider:
    name = "mock"
    model_id = "mock"

    def __init__(self, behavior: MockLLMBehavior = MockLLMBehavior.OK) -> None:
        self.behavior = behavior

    @classmethod
    def from_settings(cls, settings: Settings, deps: "PipelineDeps") -> "MockLLMProvider":
        return cls(behavior=settings.mock_llm_behavior)

    def complete_json(self, *, system: str, user: str, json_schema: dict, timeout_s: float) -> dict:
        """Return an empty object. No request is made.

        An empty dict rather than a plausible-looking one on purpose: a caller
        that quietly accepts this would be producing a recommendation out of
        nothing, and the test that catches it should fail loudly.
        """
        # TODO(P05.2): honour MOCK_LLM_BEHAVIOR — raise LLMInvalidOutput for
        # `invalid_json`, LLMTimeout for `timeout`, fail once then succeed for
        # `flaky`, and sleep within the budget for `slow`.
        return {}
