"""The parameters one pipeline run uses (P05 §5.1 task 5).

Read once from `Settings` by the registry and handed to every stage through
`PipelineDeps.config`, so a stage never reaches for global settings and a test
can run a stage with different numbers by passing a different config.

Frozen, because a run's parameters are part of what the run is: changing `top_k`
or `retrieval_min_score` halfway through would make the stored provenance a lie
(FR-26, NFR-23, ADR-14).

`model_id` and `prompt_version` here are the *configured* values. What is stored
on a row comes from the stage that produced it — every stage exposes its own
`model_id` and `prompt_version` (CLAUDE.md §8.2) — because a run can mix a mock
retriever with a real generator, and the row has to say which was which.
"""

from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class PipelineConfig:
    model_id: str = "mock"
    prompt_version: str = "mock-0"
    # Zero, always: the same description must give the same recommendation, or
    # the evaluation numbers measure nothing (NFR-23, ADR-14).
    temperature: float = 0.0
    top_k: int = 5
    timeout_s: float = 30.0
    # One retry, and only for a schema violation. The orchestrator owns that
    # decision (see `app.pipeline.errors`).
    max_retries: int = 1
    # Below this cosine similarity the retrieved passages are too weak to
    # support a confident recommendation; the safety validator caps confidence
    # at MEDIUM rather than discarding them (P05 §5.3 rule 3).
    retrieval_min_score: float = 0.30

    @classmethod
    def from_settings(cls, settings: Settings) -> "PipelineConfig":
        return cls(
            model_id=settings.pipeline_model_id,
            prompt_version=settings.pipeline_prompt_version,
            temperature=settings.pipeline_temperature,
            top_k=settings.pipeline_top_k,
            timeout_s=settings.pipeline_timeout_s,
            max_retries=settings.pipeline_max_retries,
            retrieval_min_score=settings.retrieval_min_score,
        )
