"""The startup sweep that rescues abandoned jobs (P05 §5.4 task 3, ADR-08, NFR-13).

A worker that dies mid-run leaves two rows behind: a job in `RUNNING` that no
process is working on, and a case in `PROCESSING` that the queue shows with no
category. Nothing will ever move either on its own, so the next process to start
hands the job back to the queue and the pipeline runs the case again.

Re-running is safe because the orchestrator versions its outputs rather than
updating them: a second run writes extraction version 2 and recommendation
version 2, and the queue and the review screen read the latest (ADR-14). The
first run's rows stay as the record of what happened.

Why on startup and not on a timer: the only thing that can abandon a job in this
design is the process holding it going away (ADR-08 runs the worker inside the API
process), and the restart is exactly when that is known to have happened.
"""

import logging

from sqlalchemy.orm import sessionmaker

from app.jobs.queue import DEFAULT_STALE_AFTER_MINUTES, JobQueue

logger = logging.getLogger(__name__)

__all__ = ["recover_stale_jobs"]


def recover_stale_jobs(
    session_factory: sessionmaker,
    older_than_minutes: int = DEFAULT_STALE_AFTER_MINUTES,
) -> int:
    """Re-queue jobs left `RUNNING` too long; returns how many.

    Logged as a count and a threshold. No case identifier and no case content:
    this runs before any request, and a startup line that named the cases a crash
    interrupted would put clinical data in the container log (CLAUDE.md §9).
    """
    with session_factory() as session:
        recovered = JobQueue(session).recover_stale(older_than_minutes)

    if recovered:
        logger.info(
            "recovered stale jobs",
            extra={"recovered": recovered, "older_than_minutes": older_than_minutes},
        )
    else:
        logger.debug("no stale jobs to recover", extra={"older_than_minutes": older_than_minutes})
    return recovered
