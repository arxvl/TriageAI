"""The assembled pipeline (P05 §5.1 task 4; `run()` arrives in §5.4).

`TriagePipeline` is what `app.pipeline.registry.build_pipeline` returns: the
stages chosen from settings, plus the config and deps they were built with. It is
built once at startup and shared; the stages hold no per-case state beyond
`last_latency_ms`, which the orchestrator reads immediately after each call.

Subphase 5.1 defines the object only. `run(case_id)` is subphase 5.4 and will
execute these steps, in this order (P05 §5.4 task 4):

1. `PROCESSING`, audit `PIPELINE_STARTED`.
2. `deidentify` — the owner reference goes to this stage and nowhere else.
3. `screen`, then insert each `RedFlagAlert` and **commit immediately**, so an
   alert reaches the queue even if everything after it fails (NFR-05, FR-12).
4. `extract`, retrying `config.max_retries` times on `LLMInvalidOutput` only.
5. Store the `ExtractionResult` and its complaint rows.
6. Resolve the latest `KBVersion`, then `retrieve` and `generate`.
7. `SafetyValidator.finalize`, then store the `Recommendation` and its
   `RetrievedReference` rows.
8. Copy each stage's `model_id`, `prompt_version` and `last_latency_ms` onto the
   rows they produced (FR-26, NFR-23, ADR-14).
9. `AWAITING_REVIEW`, audit `RECOMMENDATION_CREATED` — category and confidence
   only, never the text (CLAUDE.md §9).

Any pipeline error takes the failure path: `MANUAL_TRIAGE_REQUIRED`, the reason
code in the job's `last_error`, audit `PIPELINE_FAILED`. A case is never lost and
never left in `PROCESSING` (NFR-09, ADR-08).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.pipeline.config import PipelineConfig
from app.pipeline.stages import (
    Deidentifier,
    EntityExtractor,
    KBIndexer,
    RecommendationGenerator,
    RedFlagScreener,
    Retriever,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.pipeline.registry import PipelineDeps


@dataclass(frozen=True)
class TriagePipeline:
    config: PipelineConfig
    deps: "PipelineDeps"
    deidentifier: Deidentifier
    red_flag_screener: RedFlagScreener
    extractor: EntityExtractor
    retriever: Retriever
    generator: RecommendationGenerator
    # Not used by a triage run; selected by the same registry and handed to the
    # knowledge-base approval workflow (P08).
    kb_indexer: KBIndexer

    @property
    def is_fully_mocked(self) -> bool:
        """True when every stage is a mock.

        W-10 shows a persistent "MOCK MODE" banner on this, because evaluation
        numbers from a mock run mean nothing (ADR-17).
        """
        return all(
            getattr(stage, "model_id", None) == "mock"
            for stage in (
                self.deidentifier,
                self.red_flag_screener,
                self.extractor,
                self.retriever,
                self.generator,
            )
        )
