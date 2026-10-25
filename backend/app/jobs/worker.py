"""The background worker that runs queued jobs (P05 §5.4 task 2, ADR-08).

A thread inside the API process, not a second container. One queue with a handful
of jobs does not justify a broker, a worker image and another thing to explain in
the deliverables (ADR-01, ADR-08); if the load ever warrants it, `JobWorker` can
be started from its own entry point against the same table and nothing else
changes.

Two entry points, and the second one is why the tests are deterministic:

- `JobWorker` — `start()` from the FastAPI lifespan when `JOB_WORKER_ENABLED`,
  polling every `JOB_POLL_INTERVAL_S`.
- `run_pending_jobs_once` — drain the queue synchronously, in the caller's
  thread. Every integration test uses this, so a test asserts on a finished run
  rather than on a sleep (ADR-08).

**One bad job never stops the worker.** A job whose run raises is marked `FAILED`
with `UNEXPECTED_ERROR` and the loop continues. The alternative — a thread that
dies on the first unhandled exception — would leave every later case stuck in
`SUBMITTED` with nothing in the log to say why.

**A triage job has a time budget** — `2 × timeout_s + 10` seconds
(`PipelineConfig.job_timeout_s`, IR-19). A `PIPELINE_RUN` or `REGENERATE` runs on
its own thread and the worker waits for it that long. If it has not finished, the
worker sets the run's cancel event and takes the run's own failure path itself, so
the case reaches `MANUAL_TRIAGE_REQUIRED` (or, for a regeneration,
`AWAITING_REVIEW` with its previous recommendation) and the job `FAILED` exactly
as for a model timeout (NFR-09, P07 §7.1 task 5). A Python thread cannot be killed; the
abandoned run stops at its next checkpoint without writing, and a provider call
already in flight is bounded by the provider's own timeout.

Four job types are dispatched. `PIPELINE_RUN` triages a case; `REGENERATE` makes
the next recommendation version from a reviewer's corrected extraction, running
retrieval, generation and the safety validator only (P07 §7.2, FR-27);
`SUGGEST_ACTIONS` suggests actions for one stored recommendation, and its failure
is recorded on that recommendation and never on the case (FR-77, ADR-18 §3);
`KB_INDEX` indexes an approved knowledge-base entry and publishes the version
that contains it, and its failure leaves the entry awaiting review with nothing
published (FR-53, P08 §8.1). Anything else is refused rather than ignored, so a
job enqueued by a later phase against a worker that predates it fails loudly
instead of sitting `QUEUED` forever.

A fifth type, `EVAL_RUN`, runs the evaluation harness over a set of vignettes
(P09 §9.2). It can take many minutes, so it never shares a thread with the other
four: `JobWorker` takes a `job_types` filter, and the application starts one worker
for `LIVE_JOB_TYPES` and a second for `EVAL_RUN` alone. An evaluation therefore
cannot delay a case waiting for its recommendation (NFR-01, NFR-09).
"""

import logging
import threading
import uuid
from collections.abc import Iterable
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session, sessionmaker

from app.eval.runner import run_evaluation
from app.jobs.queue import EVAL_RUN_ID_KEY, REGENERATE_EXTRACTION_KEY, JobQueue
from app.models import Job, JobType, VTLCategory
from app.pipeline.orchestrator import (
    ACTIONS_JOB_CATEGORY_KEY,
    ACTIONS_JOB_GENERATION_KEY,
    ACTIONS_JOB_RECOMMENDATION_KEY,
)
from app.repositories.pipeline_repository import FIRST_ACTION_GENERATION
from app.services.kb_indexing import kb_index_job_target, run_kb_index

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.pipeline.orchestrator import PipelineRunResult, TriagePipeline

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_POLL_INTERVAL_S",
    "EVAL_JOB_TYPES",
    "INVALID_ACTIONS_TARGET",
    "LIVE_JOB_TYPES",
    "MISSING_CASE_ID",
    "MISSING_ENTRY_ID",
    "MISSING_EVAL_RUN_ID",
    "MISSING_EXTRACTION_ID",
    "MISSING_RECOMMENDATION_ID",
    "UNEXPECTED_ERROR",
    "UNSUPPORTED_JOB_TYPE",
    "JobWorker",
    "run_pending_jobs_once",
]

# Half a second: fast enough that the "Processing…" state on W-03 is brief, slow
# enough that an idle clinic is not running two queries a second all day (NFR-01).
DEFAULT_POLL_INTERVAL_S = 0.5

# Which job types each worker takes. The two sets are disjoint and together cover
# every type, so no job is left for nobody (P09 §9.2).
EVAL_JOB_TYPES: tuple[JobType, ...] = (JobType.EVAL_RUN,)
LIVE_JOB_TYPES: tuple[JobType, ...] = tuple(
    job_type for job_type in JobType if job_type not in EVAL_JOB_TYPES
)

UNSUPPORTED_JOB_TYPE = "UNSUPPORTED_JOB_TYPE"
# The same code a pipeline bug reports (`FailureReason.INTERNAL_ERROR`), so a job
# that raised and a run that raised read alike in `last_error` (P07 §7.1 task 1).
UNEXPECTED_ERROR = "INTERNAL_ERROR"
MISSING_CASE_ID = "MISSING_CASE_ID"
MISSING_RECOMMENDATION_ID = "MISSING_RECOMMENDATION_ID"
MISSING_ENTRY_ID = "MISSING_ENTRY_ID"
MISSING_EXTRACTION_ID = "MISSING_EXTRACTION_ID"
MISSING_EVAL_RUN_ID = "MISSING_EVAL_RUN_ID"
# A `SUGGEST_ACTIONS` payload names a category or a generation that cannot be
# read: a job somebody built by hand (P07 §7.2b).
INVALID_ACTIONS_TARGET = "INVALID_ACTIONS_TARGET"


def _recommendation_id(job: Job) -> uuid.UUID | None:
    """The recommendation a `SUGGEST_ACTIONS` job is about, or None.

    Read out of the payload rather than a column; see
    `ACTIONS_JOB_RECOMMENDATION_KEY`. A value that is not a uuid is treated as
    missing: the only writer is the orchestrator, so anything else is a job
    somebody built by hand.
    """
    raw = (job.payload or {}).get(ACTIONS_JOB_RECOMMENDATION_KEY)
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None


def _actions_target(job: Job) -> tuple[VTLCategory | None, int] | None:
    """The category and set number a `SUGGEST_ACTIONS` job is for, or None if unreadable.

    Both are absent on the first run, which is for the recommendation's own
    category as set 1. A regeneration carries both (FR-78); a payload that has
    one but not the other, or a value that does not parse, is a job built by hand
    and is refused rather than guessed at.
    """
    payload = job.payload or {}
    raw_category = payload.get(ACTIONS_JOB_CATEGORY_KEY)
    raw_generation = payload.get(ACTIONS_JOB_GENERATION_KEY)
    if raw_category is None and raw_generation is None:
        return None, FIRST_ACTION_GENERATION
    try:
        category = VTLCategory(raw_category)
        generation = int(raw_generation)
    except (TypeError, ValueError):
        return None
    if isinstance(raw_generation, bool) or generation < FIRST_ACTION_GENERATION:
        return None
    return category, generation


def _extraction_id(job: Job) -> uuid.UUID | None:
    """The corrected extraction a `REGENERATE` job is about, or None.

    In the payload for the same reason as the recommendation id: `jobs` points at
    a case, and this job is about one *version* of that case's extraction.
    """
    raw = (job.payload or {}).get(REGENERATE_EXTRACTION_KEY)
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None


def _eval_run_id(job: Job) -> uuid.UUID | None:
    """The evaluation run an `EVAL_RUN` job is about, or None.

    In the payload for the same reason as the recommendation id: see
    `EVAL_RUN_ID_KEY`. Anything that is not a uuid is a job somebody built by hand.
    """
    raw = (job.payload or {}).get(EVAL_RUN_ID_KEY)
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None


def _run_with_budget(
    pipeline: "TriagePipeline", job: Job, budget_s: float | None
) -> "PipelineRunResult":
    """Run a triage or regeneration job on a watchdog thread; fail it if it overruns.

    The ids are read off the job before the thread starts: the `Job` belongs to
    the worker's session, and the run opens its own.
    """
    case_id, job_id = job.case_id, job.id
    extraction_id = _extraction_id(job) if job.type is JobType.REGENERATE else None
    budget = pipeline.config.job_timeout_s if budget_s is None else budget_s
    cancel = threading.Event()
    outcome: dict[str, object] = {}

    def target() -> None:
        try:
            if extraction_id is not None:
                outcome["result"] = pipeline.regenerate(
                    case_id, extraction_id, job_id=job_id, cancel=cancel
                )
            else:
                outcome["result"] = pipeline.run(case_id, job_id=job_id, cancel=cancel)
        except BaseException as error:  # noqa: BLE001 - handed back to the worker thread
            outcome["error"] = error

    thread = threading.Thread(target=target, name=f"triageai-run-{job_id}", daemon=True)
    thread.start()
    thread.join(timeout=budget)

    if thread.is_alive():
        cancel.set()
        logger.error(
            "job exceeded its time budget",
            extra={
                "job_id": str(job_id),
                "case_id": str(case_id),
                "job_type": str(job.type),
                "budget_s": budget,
            },
        )
        if extraction_id is not None:
            return pipeline.fail_regeneration_timed_out(case_id, extraction_id, job_id=job_id)
        return pipeline.fail_timed_out(case_id, job_id=job_id)

    error = outcome.get("error")
    if isinstance(error, BaseException):
        raise error
    return outcome["result"]  # type: ignore[return-value]


def run_job(
    session: Session,
    pipeline: "TriagePipeline",
    job: Job,
    *,
    budget_s: float | None = None,
) -> None:
    """Dispatch one claimed job and set its final state.

    `budget_s` overrides the triage job's time budget; the default is
    `pipeline.config.job_timeout_s`. Tests pass a small one.

    The run's own failure path has already put the *case* where it belongs
    (NFR-09) — or, for `SUGGEST_ACTIONS`, has recorded the failure on the
    recommendation and left the case alone (FR-77). This records the same
    outcome on the job, so `last_error` and what the reviewer sees can never
    disagree.
    """
    queue = JobQueue(session)
    context = {"job_id": str(job.id), "job_type": str(job.type), "attempts": job.attempts}

    try:
        if job.type is JobType.PIPELINE_RUN:
            if job.case_id is None:
                logger.error("PIPELINE_RUN job without a case", extra=context)
                queue.fail(job, MISSING_CASE_ID)
                return
            result = _run_with_budget(pipeline, job, budget_s)

        elif job.type is JobType.REGENERATE:
            if job.case_id is None or _extraction_id(job) is None:
                logger.error("REGENERATE job without a case or an extraction", extra=context)
                queue.fail(job, MISSING_EXTRACTION_ID)
                return
            result = _run_with_budget(pipeline, job, budget_s)

        elif job.type is JobType.KB_INDEX:
            entry_id, approver_id = kb_index_job_target(job)
            if entry_id is None:
                logger.error("KB_INDEX job without an entry", extra=context)
                queue.fail(job, MISSING_ENTRY_ID)
                return
            # The indexer the registry selected, shared with the pipeline: one
            # process holds one indexer, mock or real (CLAUDE.md §8.3).
            result = run_kb_index(
                session, pipeline.kb_indexer, entry_id=entry_id, approver_id=approver_id
            )

        elif job.type is JobType.SUGGEST_ACTIONS:
            recommendation_id = _recommendation_id(job)
            if recommendation_id is None:
                logger.error("SUGGEST_ACTIONS job without a recommendation", extra=context)
                queue.fail(job, MISSING_RECOMMENDATION_ID)
                return
            target = _actions_target(job)
            if target is None:
                logger.error("SUGGEST_ACTIONS job with an unreadable target", extra=context)
                queue.fail(job, INVALID_ACTIONS_TARGET)
                return
            category, generation = target
            result = pipeline.run_actions(
                recommendation_id, job_id=job.id, category=category, generation=generation
            )

        elif job.type is JobType.EVAL_RUN:
            run_id = _eval_run_id(job)
            if run_id is None:
                logger.error("EVAL_RUN job without a run", extra=context)
                queue.fail(job, MISSING_EVAL_RUN_ID)
                return
            # No time budget: a run is as long as its set, and each vignette is
            # already bounded by the provider's own timeout.
            result = run_evaluation(pipeline.deps.session_factory, pipeline, run_id)

        else:
            logger.error("job type not supported by this worker", extra=context)
            queue.fail(job, UNSUPPORTED_JOB_TYPE)
            return
    except Exception:
        # Never let one job take the worker down with it.
        logger.exception("job raised", extra=context)
        session.rollback()
        queue.fail(job, UNEXPECTED_ERROR)
        return

    if result.succeeded:
        queue.complete(job)
    else:
        queue.fail(job, str(result.failure_reason))


def run_pending_jobs_once(
    session_factory: sessionmaker,
    pipeline: "TriagePipeline",
    *,
    max_jobs: int | None = None,
    budget_s: float | None = None,
    job_types: Iterable[JobType] | None = None,
) -> int:
    """Run every job that is ready now, in this thread; returns how many.

    The synchronous entry point the tests use. `max_jobs` bounds one pass, which
    is what keeps a test that enqueues a job whose run enqueues another from
    looping forever. `job_types` narrows which jobs are taken; None takes any.
    """
    ran = 0
    with session_factory() as session:
        queue = JobQueue(session)
        while max_jobs is None or ran < max_jobs:
            job = queue.claim_next(job_types)
            if job is None:
                break
            run_job(session, pipeline, job, budget_s=budget_s)
            ran += 1
    return ran


class JobWorker:
    """A daemon thread that polls the queue until it is stopped.

    `stop()` sets an event the loop waits on instead of sleeping, so shutdown is
    immediate rather than up to one poll interval late — which matters because the
    FastAPI lifespan waits for it before the process exits.
    """

    def __init__(
        self,
        session_factory: sessionmaker,
        pipeline: "TriagePipeline",
        *,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        budget_s: float | None = None,
        job_types: Iterable[JobType] | None = None,
        name: str = "triageai-job-worker",
    ) -> None:
        self._session_factory = session_factory
        self._job_types = None if job_types is None else tuple(job_types)
        self._name = name
        self._pipeline = pipeline
        self._budget_s = budget_s
        self._poll_interval_s = poll_interval_s
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._loop, name=self._name, daemon=True)
        self._thread.start()
        logger.info(
            "job worker started",
            extra={"worker": self._name, "poll_interval_s": self._poll_interval_s},
        )

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stopping.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout_s)
        logger.info("job worker stopped", extra={"worker": self._name})

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                ran = run_pending_jobs_once(
                    self._session_factory,
                    self._pipeline,
                    budget_s=self._budget_s,
                    job_types=self._job_types,
                )
            except Exception:
                # A database that has gone away must not kill the thread; the next
                # poll reconnects through the pool's pre-ping.
                logger.exception("job worker poll failed")
                ran = 0
            # Only wait when there was nothing to do, so a backlog is drained at
            # full speed instead of one job per interval.
            if ran == 0:
                self._stopping.wait(self._poll_interval_s)
