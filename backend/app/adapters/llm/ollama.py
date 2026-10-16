"""Local Ollama adapter (M2). Same wire format as the hosted adapter."""

from __future__ import annotations

from app.adapters.llm.hosted import HostedLLMProvider, opt_float, opt_int


class OllamaLLMProvider(HostedLLMProvider):
    name = "ollama"

    @classmethod
    def from_settings(cls, settings, deps=None) -> OllamaLLMProvider:
        temperature = opt_float(settings.LLM_TEMPERATURE)
        return cls(
            settings.OLLAMA_BASE_URL,
            None,
            settings.OLLAMA_MODEL,
            # A local model honours temperature, so default to 0 for reproducibility (NFR-23).
            temperature=0.0 if temperature is None else temperature,
            seed=opt_int(settings.LLM_SEED),
            json_mode=settings.OLLAMA_JSON_MODE,
            schema_in_prompt=settings.LLM_SCHEMA_IN_PROMPT,
            simplify=settings.LLM_SCHEMA_SIMPLIFY,
            max_rpm=0,
            http_retries=1,
            rate_limit_wait_s=5.0,
        )
