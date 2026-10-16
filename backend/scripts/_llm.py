"""Shared helper for the M2 dev scripts (not imported by the application)."""

from app.adapters.llm.hosted import HostedLLMProvider
from app.adapters.llm.ollama import OllamaLLMProvider


def provider_from_settings(settings):
    if settings.llm_provider == "hosted":
        return HostedLLMProvider.from_settings(settings)
    if settings.llm_provider == "ollama":
        return OllamaLLMProvider.from_settings(settings)
    raise SystemExit(
        "LLM_PROVIDER is 'mock'. Set it to 'hosted' or 'ollama' in .env, "
        "then restart: docker compose up -d --build backend"
    )
