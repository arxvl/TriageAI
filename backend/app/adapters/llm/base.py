"""The one port every language-model call goes through (CLAUDE.md §8.2, ADR-06).

Narrow on purpose. The application asks for JSON matching a schema and gets a
dict or an exception; it never sees a provider's response envelope, token counts
or streaming chunks. That is what makes `hosted`, `ollama` and `mock`
interchangeable by one line of `.env` (ADR-17), and what keeps the retry and
failure logic in the orchestrator instead of spread across providers.

Provider-specific code — request shaping, JSON-mode flags, auth headers — is
written manually in M2 under `app.adapters.llm.hosted` and
`app.adapters.llm.ollama`. Nothing in this package calls a real API.

**Only de-identified text may be passed to `complete_json`** (IR-20, ADR-10).
The registry refuses to start a non-mock provider while the de-identifier is
still the mock, so this cannot be got wrong by configuration alone.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model_id: str

    def complete_json(self, *, system: str, user: str, json_schema: dict, timeout_s: float) -> dict:
        """Return a dict satisfying `json_schema`.

        Raises:
            LLMTimeout: no answer within `timeout_s`.
            LLMUnavailable: unreachable, refused, or rate-limited.
            LLMInvalidOutput: answered, but not with conforming JSON.
        """
        ...
