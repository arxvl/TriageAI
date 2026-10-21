"""LLM recommendation generator (M6).

Produces ONLY the urgency category, rationale, and citations. Suggested actions
are a separate pipeline stage (SUGGEST_ACTIONS job, built manually in M6b) and
are NOT part of this stage's output (ADR-18).

Citation and safety-floor enforcement happen afterward, in the deterministic
SafetyValidator (P05, ADR-09) -- this class only calls the model and validates
the JSON shape.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, Field, ValidationError

from app.models.enums import ConfidenceLevel, VTLCategory
from app.pipeline.errors import GenerationFailed, LLMInvalidOutput
from app.pipeline.prompts import load_prompt
from app.pipeline.types import DraftRecommendation


class _RawAnswer(BaseModel):
    category: VTLCategory
    rationale: str = Field(max_length=900)
    cited: list[int]
    confidence: ConfidenceLevel


class LLMRecommendationGenerator:
    def __init__(self, llm, prompt, timeout_s: float, max_retries: int):
        self.llm, self.prompt = llm, prompt
        self.timeout_s, self.max_retries = timeout_s, max_retries
        self.schema = _RawAnswer.model_json_schema()
        self.last_latency_ms = 0

    @classmethod
    def from_settings(cls, settings, deps) -> LLMRecommendationGenerator:
        prompt = load_prompt("generation", settings.GENERATION_PROMPT_VERSION)
        return cls(deps.llm, prompt, deps.config.timeout_s, deps.config.max_retries)

    @property
    def model_id(self) -> str:
        return self.llm.model_id

    @property
    def prompt_version(self) -> str:
        return f"generation/{self.prompt.version}"

    def generate(self, extraction, passages) -> DraftRecommendation:
        blocks = "\n\n".join(
            f"[{p.rank}] {p.entry_title} — {p.source_title}\n{p.text}" for p in passages
        )
        user = self.prompt.render_user(
            species=extraction.species.value,
            extraction_json=extraction.model_dump_json(exclude={"evidence_spans"}, indent=1),
            passages=blocks or "(no passages found)",
        )
        feedback, start = "", time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                raw = _RawAnswer.model_validate(
                    self.llm.complete_json(
                        system=self.prompt.system,
                        user=user + feedback,
                        json_schema=self.schema,
                        timeout_s=self.timeout_s,
                    )
                )
                self.last_latency_ms = int((time.perf_counter() - start) * 1000)
                return DraftRecommendation(
                    category=raw.category,
                    rationale=raw.rationale.strip(),
                    cited_ranks=sorted(set(raw.cited)),
                    confidence=raw.confidence,
                )
            except (ValidationError, LLMInvalidOutput) as exc:
                if attempt >= self.max_retries:
                    raise GenerationFailed("invalid generation output after retry") from exc
                feedback = (
                    "\n\nYour previous answer was invalid. Return only the JSON object described."
                )
        raise GenerationFailed("unreachable")
