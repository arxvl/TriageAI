"""LLM entity extractor (M3)."""

from __future__ import annotations

import json
import time

from pydantic import ValidationError
from sqlalchemy import select

from app.models.knowledge_base import PresentingComplaint
from app.pipeline.errors import ExtractionFailed, LLMInvalidOutput
from app.pipeline.prompts import load_prompt
from app.pipeline.types import ExtractedComplaint, ExtractionOutput


class LLMEntityExtractor:
    def __init__(
        self, llm, prompt, complaint_codes: dict[str, str], timeout_s: float, max_retries: int
    ):
        self.llm, self.prompt = llm, prompt
        self.codes = complaint_codes  # code -> name
        self.timeout_s, self.max_retries = timeout_s, max_retries
        self.schema = ExtractionOutput.model_json_schema()
        self.last_latency_ms = 0

    @classmethod
    def from_settings(cls, settings, deps) -> LLMEntityExtractor:
        with deps.session_factory() as s:
            codes = {c.code: c.name for c in s.scalars(select(PresentingComplaint))}
        prompt = load_prompt("extraction", settings.EXTRACTION_PROMPT_VERSION)
        return cls(deps.llm, prompt, codes, deps.config.timeout_s, deps.config.max_retries)

    @property
    def model_id(self) -> str:
        return self.llm.model_id

    @property
    def prompt_version(self) -> str:
        return f"extraction/{self.prompt.version}"

    def extract(self, text: str, species, signalment: dict | None = None) -> ExtractionOutput:
        complaint_list = "\n".join(f"- {c}: {n}" for c, n in self.codes.items())
        user = self.prompt.render_user(
            complaint_list=complaint_list,
            species=getattr(species, "value", species),
            signalment=json.dumps(signalment or {}, ensure_ascii=False),
            description=text,
        )
        system = self.prompt.system.replace("$complaint_list", complaint_list)
        feedback = ""
        start = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                raw = self.llm.complete_json(
                    system=system,
                    user=user + feedback,
                    json_schema=self.schema,
                    timeout_s=self.timeout_s,
                )
                out = ExtractionOutput.model_validate(raw)
                result = self._postprocess(out, text, species)
                self.last_latency_ms = int((time.perf_counter() - start) * 1000)
                return result
            except (ValidationError, LLMInvalidOutput) as exc:
                if attempt >= self.max_retries:
                    raise ExtractionFailed("invalid extraction output after retry") from exc
                feedback = (
                    "\n\nYour previous answer was not valid for the schema. "
                    "Return only one JSON object that matches the schema exactly."
                )
        raise ExtractionFailed("unreachable")

    def _postprocess(self, out: ExtractionOutput, text: str, species) -> ExtractionOutput:
        out.species = species  # the form is authoritative
        complaints = [
            ExtractedComplaint(
                code=c.code if c.code in self.codes else "OTHER", is_primary=c.is_primary
            )
            for c in out.presenting_complaints
        ]
        if not complaints:
            complaints = [ExtractedComplaint(code="OTHER", is_primary=True)]
        seen, cleaned = set(), []
        for c in complaints:  # de-duplicate
            if c.code not in seen:
                seen.add(c.code)
                cleaned.append(c)
        primaries = [c for c in cleaned if c.is_primary]
        for i, c in enumerate(cleaned):  # exactly one primary
            c.is_primary = (c is primaries[0]) if primaries else (i == 0)
        out.presenting_complaints = cleaned
        # drop evidence spans the model invented (they must be exact substrings of the input)
        out.evidence_spans = [s for s in out.evidence_spans if s.text and s.text in text]
        return out
