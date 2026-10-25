"""Run an evaluation: every vignette of a set through the pipeline (P09 §9.2, FR-65).

`run_evaluation` is the body of an `EVAL_RUN` job, and the CLI calls it directly in
its own process. It owns no pipeline logic: each vignette goes through
`TriagePipeline.run_vignette`, which is the code a live case runs, and this module
only decides the order, records what came back, and computes the metrics when the
last vignette is done.

What is recorded, and why it is enough to reproduce a run (NFR-23):

- **A configuration snapshot** on the run, taken when it starts: every `PIPELINE_*`
  selection, each stage's `model_id` and `prompt_version`, the knowledge-base
  version, `top_k`, the temperatures and the timeouts. The knowledge-base version
  is resolved once for the whole run, so every vignette is answered from the same
  one.
- **One `EvaluationResult` per vignette,** committed as it finishes, with the
  predicted category, the stage latencies, and a payload holding the red-flag hits,
  the retrieved entry ids in rank order, the primary complaint and the safety-floor
  flag.

A vignette that fails records its reason code and the run goes on to the next. A
run that is picked up again after a crash skips the vignettes that already have a
result, so the worker restarting costs the unfinished vignettes and nothing more.

Nothing here logs a description or a model response: identifiers, counts and
timings only (CLAUDE.md §9).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session, sessionmaker

from app.eval.metrics import DEFAULT_K, compute_metrics
from app.models import JobStatus
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.pipeline_repository import PipelineRepository

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.pipeline.orchestrator import TriagePipeline, VignetteRunResult

logger = logging.getLogger(__name__)

__all__ = [
    "EVAL_RUN_NOT_FOUND",
    "NO_KNOWLEDGE_BASE_VERSION",
    "EvaluationRunResult",
    "config_snapshot",
    "run_evaluation",
]

# Reason codes for a run that could not start. They land in `jobs.last_error`.
EVAL_RUN_NOT_FOUND = "EVAL_RUN_NOT_FOUND"
NO_KNOWLEDGE_BASE_VERSION = "NO_KNOWLEDGE_BASE_VERSION"
INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class EvaluationRunResult:
    """What a run did, for the worker that called it (the `PipelineRunResult` of 9.2)."""

    run_id: uuid.UUID
    failure_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure_reason is None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def config_snapshot(pipeline: "TriagePipeline", kb_version_id: uuid.UUID) -> dict[str, Any]:
    """Everything that decides what the pipeline does, as plain JSON (NFR-23).

    The stage selection comes from the settings the pipeline was built with; the
    ids and prompt versions come from the stages themselves, because a run can mix
    a mock retriever with a real generator and the snapshot has to say which was
    which. No key, URL or prompt text.
    """
    config = pipeline.config
    stages = {
        name: {
            "model_id": getattr(stage, "model_id", None),
            "prompt_version": getattr(stage, "prompt_version", None),
        }
        for name, stage in (
            ("deidentifier", pipeline.deidentifier),
            ("red_flag_screener", pipeline.red_flag_screener),
            ("extractor", pipeline.extractor),
            ("retriever", pipeline.retriever),
            ("generator", pipeline.generator),
        )
    }
    return {
        **pipeline.settings_snapshot,
        "stages": stages,
        "model_id": config.model_id,
        "prompt_version": config.prompt_version,
        "kb_version_id": str(kb_version_id),
        "top_k": config.top_k,
        "temperature": config.temperature,
        "timeout_s": config.timeout_s,
        "max_retries": config.max_retries,
        "retrieval_min_score": config.retrieval_min_score,
        "fully_mocked": pipeline.is_fully_mocked,
    }


def _result_payload(result: "VignetteRunResult") -> dict[str, Any]:
    return {
        "red_flag_hits": [
            {
                "rule_code": hit.rule_code,
                "min_category": hit.min_category.value,
                "matched_text": hit.matched_text,
            }
            for hit in result.red_flag_hits
        ],
        "retrieved_entry_ids": [str(entry_id) for entry_id in result.retrieved_entry_ids],
        "primary_complaint": result.primary_complaint,
        "confidence": None if result.confidence is None else result.confidence.value,
        "safety_floor_applied": result.safety_floor_applied,
    }


def _record(repo: EvaluationRepository, run_id: uuid.UUID, result: "VignetteRunResult") -> None:
    repo.add_result(
        run_id=run_id,
        vignette_id=result.vignette_id,
        recommendation_id=result.recommendation_id,
        extraction_id=result.extraction_id,
        predicted_category=result.category,
        stage_latencies={**result.stage_ms, "total": result.total_ms},
        error=None if result.failure_reason is None else str(result.failure_reason),
        payload=_result_payload(result),
    )


def _fail_run(session: Session, run_id: uuid.UUID) -> None:
    """Mark the run FAILED. Best effort: the caller is already on a failure path."""
    try:
        session.rollback()
        run = EvaluationRepository(session).get_run(run_id)
        if run is not None:
            run.status = JobStatus.FAILED
            run.finished_at = _utc_now()
            session.commit()
    except Exception:
        session.rollback()
        logger.exception("evaluation run could not be marked failed", extra={"run_id": str(run_id)})


def run_evaluation(
    session_factory: sessionmaker,
    pipeline: "TriagePipeline",
    run_id: uuid.UUID,
    *,
    on_progress: "Any | None" = None,
) -> EvaluationRunResult:
    """Run every vignette of the run's set that has no result yet. Never raises.

    `on_progress(done, total)` is called after each vignette; the CLI uses it to
    print a line. It is reporting only and its failure cannot affect the run.
    """
    with session_factory() as session:
        try:
            return _run(session, pipeline, run_id, on_progress)
        except Exception:
            logger.exception("evaluation run raised", extra={"run_id": str(run_id)})
            _fail_run(session, run_id)
            return EvaluationRunResult(run_id, INTERNAL_ERROR)


def _run(
    session: Session,
    pipeline: "TriagePipeline",
    run_id: uuid.UUID,
    on_progress: "Any | None",
) -> EvaluationRunResult:
    repo = EvaluationRepository(session)
    run = repo.get_run(run_id)
    if run is None:
        logger.error("evaluation run not found", extra={"run_id": str(run_id)})
        return EvaluationRunResult(run_id, EVAL_RUN_NOT_FOUND)
    if run.status is JobStatus.DONE:
        # A job picked up twice (the startup sweep re-queues RUNNING jobs): the work
        # is finished, and doing it again would only add result rows.
        return EvaluationRunResult(run_id)

    # One knowledge-base version for the whole run, and the same one on a resume.
    kb_version_id = run.kb_version_id or PipelineRepository(session).latest_kb_version_id()
    if kb_version_id is None:
        logger.error("evaluation run: no knowledge base version", extra={"run_id": str(run_id)})
        _fail_run(session, run_id)
        return EvaluationRunResult(run_id, NO_KNOWLEDGE_BASE_VERSION)

    run.kb_version_id = kb_version_id
    if run.config is None:
        run.config = config_snapshot(pipeline, kb_version_id)
    run.status = JobStatus.RUNNING
    run.started_at = run.started_at or _utc_now()
    session.commit()

    # Plain ids, read once: each commit below expires the loaded rows, and a
    # vignette row refreshed from the database would hold a transaction open for the
    # whole of a model call.
    vignette_ids = [vignette.id for vignette in repo.vignettes_for_set(run.set_id)]
    done = repo.completed_vignette_ids(run_id)
    total = len(vignette_ids)
    failed = 0

    for vignette_id in vignette_ids:
        if vignette_id in done:
            continue
        result = pipeline.run_vignette(vignette_id, kb_version_id)
        _record(repo, run_id, result)
        session.commit()
        done.add(vignette_id)
        failed += 0 if result.succeeded else 1
        logger.info(
            "evaluation vignette finished",
            extra={
                "run_id": str(run_id),
                "vignette_id": str(vignette_id),
                "failure_reason": None
                if result.failure_reason is None
                else str(result.failure_reason),
                "total_ms": result.total_ms,
                "done": len(done),
                "total": total,
            },
        )
        if on_progress is not None:
            try:
                on_progress(len(done), total)
            except Exception:  # reporting must never stop a run
                logger.warning("evaluation progress callback raised", exc_info=True)

    top_k = int(run.config.get("top_k", DEFAULT_K)) if run.config else DEFAULT_K
    run.metrics = compute_metrics(repo.outcomes(run_id), k=top_k)
    run.status = JobStatus.DONE
    run.finished_at = _utc_now()
    session.commit()
    logger.info(
        "evaluation run finished",
        extra={"run_id": str(run_id), "vignettes": total, "failed_this_pass": failed},
    )
    return EvaluationRunResult(run_id)
