"""LLM action suggester (M6b).

Produces up to ACTIONS_MAX_ITEMS case-specific suggested actions for the case's
final urgency category, grounded only in the retrieved knowledge-base passages.
This class does NOT enforce the safety rules (no drug/dose/diagnosis, citation
required, length limit) -- that is entirely the job of app.pipeline.action_validator
.validate(), which P05b already built and which the orchestrator calls after this
stage returns. Keeping that in exactly one place is the same pattern ADR-09 uses
for the safety floor on the VTL category itself.
"""

from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.models.enums import ActionSource, KBEntryKind, KBEntryStatus
from app.models.knowledge_base import KBEntry
from app.pipeline.errors import ActionsFailed, LLMInvalidOutput
from app.pipeline.prompts import load_prompt
from app.pipeline.types import SuggestedAction

log = logging.getLogger(__name__)

CATEGORY_MEANING = {
    "RED": "Immediate",
    "ORANGE": "Very urgent, within 15 minutes",
    "YELLOW": "Urgent, within 30 to 60 minutes",
    "GREEN": "Standard, within 120 minutes",
    "BLUE": "Non-urgent, within 240 minutes",
}


class _RawAction(BaseModel):
    text: str = Field(max_length=300)
    cited: list[int]


class _RawAnswer(BaseModel):
    actions: list[_RawAction]


def _fetch_current_baseline(session_factory, category) -> list[str]:
    """Return the baseline action lines already approved for this category.

    This is used ONLY to stop the model repeating what staff already see as the
    baseline (prompt rule 5 above) -- it is NOT the source of truth for what the
    UI displays. The UI and the audit trail always get the baseline from
    app.pipeline.action_validator.baseline_actions(), which is pinned to the
    exact kb_version_id the recommendation was generated against. Here we only
    need "good enough, right now" text to put in a prompt, so we read the
    current ACTIVE entry directly and never fail the whole stage if this lookup
    has a problem -- we just proceed with no baseline hint.
    """
    cat = getattr(category, "value", category)
    try:
        with session_factory() as s:
            entry = s.scalars(
                select(KBEntry)
                .where(KBEntry.kind == KBEntryKind.URGENCY_ACTIONS)
                .where(KBEntry.urgency_category == cat)
                .where(KBEntry.status == KBEntryStatus.ACTIVE)
                .order_by(KBEntry.approved_at.desc())
                .limit(1)
            ).first()
    except Exception:  # noqa: BLE001
        log.warning("baseline lookup failed for category=%s; continuing without it", cat)
        return []
    if entry is None:
        return []
    return [line.strip() for line in entry.content.splitlines() if line.strip()]


class LLMActionSuggester:
    def __init__(self, llm, prompt, session_factory, timeout_s: float, max_retries: int):
        self.llm, self.prompt = llm, prompt
        self.session_factory = session_factory
        self.timeout_s, self.max_retries = timeout_s, max_retries
        self.schema = _RawAnswer.model_json_schema()
        self.last_latency_ms = 0

    @classmethod
    def from_settings(cls, settings, deps) -> LLMActionSuggester:
        return cls(
            deps.llm,
            load_prompt("actions", settings.actions_prompt_version),
            deps.session_factory,
            deps.config.timeout_s,
            deps.config.max_retries,
        )

    @property
    def model_id(self) -> str:
        return self.llm.model_id

    @property
    def prompt_version(self) -> str:
        return f"actions/{self.prompt.version}"

    def suggest(self, extraction, category, passages, max_items) -> list[SuggestedAction]:
        """Matches the ActionSuggester Protocol in CLAUDE.md section 8.2 exactly --
        four positional arguments, nothing more -- so the mock stage from P05b and
        this real stage are interchangeable with no change to the orchestrator."""
        baseline = _fetch_current_baseline(self.session_factory, category)
        blocks = "\n\n".join(
            f"[{p.rank}] {p.entry_title} - {p.source_title}\n{p.text}" for p in passages
        )
        cat = getattr(category, "value", category)
        user = self.prompt.render_user(
            category=cat,
            category_meaning=CATEGORY_MEANING.get(cat, cat),
            baseline="\n".join(f"- {b}" for b in baseline) or "(none on file)",
            extraction_json=extraction.model_dump_json(exclude={"evidence_spans"}, indent=1),
            passages=blocks or "(no passages found)",
            max_items=str(max_items),
        )
        system = self.prompt.system.replace("$max_items", str(max_items))

        start = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                raw = _RawAnswer.model_validate(
                    self.llm.complete_json(
                        system=system, user=user, json_schema=self.schema, timeout_s=self.timeout_s
                    )
                )
                self.last_latency_ms = int((time.perf_counter() - start) * 1000)
                return [
                    SuggestedAction(
                        text=a.text.strip(),
                        cited_ranks=sorted(set(a.cited)),
                        source=ActionSource.AI,
                    )
                    for a in raw.actions
                ]
            except (ValidationError, LLMInvalidOutput) as exc:
                if attempt >= self.max_retries:
                    raise ActionsFailed("invalid action output after retry") from exc
                log.info("actions stage retrying after invalid output (attempt %s)", attempt + 1)
        raise ActionsFailed("unreachable")
