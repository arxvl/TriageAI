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

Job types other than `PIPELINE_RUN` are refused rather than ignored, so a job
enqueued by a later phase against a worker that predates it fails loudly instead
of sitting `QUEUED` forever: `REGENERATE` arrives in P07, `KB_INDEX` in P08 and
`EVAL_RUN` with the evaluation harness (M7).
"""

import logging
import threading
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session, sessionmaker

from app.jobs.queue import JobQueue
from app.models import Job, JobType

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.pipeline.orchestrator import TriagePipeline

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_POLL_INTERVAL_S",
    "UNEXPECTED_ERROR",
    "UNSUPPORTED_JOB_TYPE",
    "JobWorker",
    "run_pending_jobs_once",
]

# Half a second: fast enough that the "Processing…" state on W-03 is brief, slow
# enough that an idle clinic is not running two queries a second all day (NFR-01).
DEFAULT_POLL_INTERVAL_S = 0.5

UNSUPPORTED_JOB_TYPE = "UNSUPPORTED_JOB_TYPE"
UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


def run_job(session: Session, pipeline: "TriagePipeline", job: Job) -> None:
    """Dispatch one claimed job and set its final state.

    The pipeline's own failure path has already put the *case* where it belongs
    (NFR-09); this records the same outcome on the job, so `last_error` and the
    case status can never disagree.
    """
    queue = JobQueue(session)
    context = {"job_id": str(job.id), "job_type": str(job.type), "attempts": job.attempts}

    try:
        if job.type is not JobType.PIPELINE_RUN:
            logger.error("job type not supported by this worker", extra=context)
            queue.fail(job, UNSUPPORTED_JOB_TYPE)
            return

        if job.case_id is None:
            logger.error("PIPELINE_RUN job without a case", extra=context)
            queue.fail(job, "MISSING_CASE_ID")
            return

        result = pipeline.run(job.case_id, job_id=job.id)
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
) -> int:
    """Run every job that is ready now, in this thread; returns how many.

    The synchronous entry point the tests use. `max_jobs` bounds one pass, which
    is what keeps a test that enqueues a job whose run enqueues another from
    looping forever.
    """
    ran = 0
    with session_factory() as session:
        queue = JobQueue(session)
        while max_jobs is None or ran < max_jobs:
            job = queue.claim_next()
            if job is None:
                break
            run_job(session, pipeline, job)
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
    ) -> None:
        self._session_factory = session_factory
        self._pipeline = pipeline
        self._poll_interval_s = poll_interval_s
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._loop, name="triageai-job-worker", daemon=True)
        self._thread.start()
        logger.info("job worker started", extra={"poll_interval_s": self._poll_interval_s})

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stopping.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout_s)
        logger.info("job worker stopped")

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                ran = run_pending_jobs_once(self._session_factory, self._pipeline)
            except Exception:
                # A database that has gone away must not kill the thread; the next
                # poll reconnects through the pool's pre-ping.
                logger.exception("job worker poll failed")
                ran = 0
            # Only wait when there was nothing to do, so a backlog is drained at
            # full speed instead of one job per interval.
            if ran == 0:
                self._stopping.wait(self._poll_interval_s)
