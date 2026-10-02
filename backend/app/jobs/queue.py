"""The `jobs` table, as operations rather than queries (P05 §5.4 task 1, ADR-08).

No business rules here (CLAUDE.md §7) — this module decides nothing about triage.
It answers four questions a worker asks: what is there to do, I have taken it,
I finished it, I could not.

Three things are worth reading before changing them.

**`claim_next` uses `FOR UPDATE SKIP LOCKED`.** Two workers polling the same
table must not take the same job, and `SKIP LOCKED` is what makes the second one
walk past the row the first is holding instead of blocking on it. The claim is
committed immediately, so the lock is held for one statement rather than for the
length of a pipeline run.

**`attempts` is incremented by the claim, not by the failure.** A job that is
claimed and then lost to a crash has still been attempted; counting on the way in
is what keeps a poison job from being retried forever once a retry policy is added
(P07).

**Progress is a field on `payload`, not a column.** `set_stage` is called six
times per run and commits each time, because `GET /cases/{id}/status` reports
`pipeline_stage` from it while the run is still going (IR-22). Keeping it in the
existing JSONB column means this subphase adds no migration.

`last_error` holds a reason **code** and a timestamp, never a model response, a
prompt or an owner description (CLAUDE.md §9). It is read back by the retry
endpoint in P07 and shown to a reviewer as the W-06 banner wording, so the codes
are part of the contract, not debug text.
"""

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job, JobStatus, JobType

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_STALE_AFTER_MINUTES", "STAGE_KEY", "JobStage", "JobQueue"]

# How long a job may sit in `RUNNING` before the startup sweep assumes the worker
# that held it is gone. Two minutes, per ADR-08: comfortably longer than the job
# timeout budget (`2 × timeout_s + 10`) at the default 30 s, so a slow run is
# never mistaken for a dead one.
DEFAULT_STALE_AFTER_MINUTES = 2

# Where `set_stage` keeps the progress marker inside `jobs.payload`.
STAGE_KEY = "stage"


class JobStage(StrEnum):
    """How far a `PIPELINE_RUN` job has got (P05 §5.4 task 6).

    Reported by `GET /cases/{id}/status` so W-03 can say what is happening rather
    than only "processing". The names are the orchestrator's steps, so a stuck
    case says which stage it is stuck in.

    `QUEUED`, `DONE` and `FAILED` are derived from `Job.status` rather than
    written: a job that has not started cannot have recorded a stage, and one
    that has finished should not report the last stage it was in.
    """

    QUEUED = "queued"
    DEIDENTIFY = "deidentify"
    SCREEN = "screen"
    EXTRACT = "extract"
    RETRIEVE = "retrieve"
    GENERATE = "generate"
    DONE = "done"
    FAILED = "failed"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JobQueue:
    """Operations on `jobs` for one session.

    `enqueue` flushes and leaves the transaction to its caller — a job is
    committed together with the case that needs it (ADR-08). Every other method
    commits, because each is one complete step of a worker's bookkeeping and must
    be durable before the next thing happens.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- Producing ---------------------------------------------------------

    def enqueue(
        self,
        job_type: JobType,
        *,
        case_id: uuid.UUID | None = None,
        vignette_id: uuid.UUID | None = None,
        payload: dict | None = None,
        run_after: datetime | None = None,
    ) -> Job:
        """Add a `QUEUED` job. Flushes, never commits.

        Deliberately not committing is the point: `CaseService.create_case` puts
        this in the same transaction as the case, its description and its audit
        entry, so there can be no case that no worker will ever pick up, and no
        job pointing at a case that was rolled back (ADR-08).
        """
        job = Job(
            type=job_type,
            case_id=case_id,
            vignette_id=vignette_id,
            payload=payload,
            status=JobStatus.QUEUED,
            attempts=0,
            run_after=run_after,
        )
        self._session.add(job)
        self._session.flush()
        return job

    # --- Consuming ---------------------------------------------------------

    def claim_next(self, types: Iterable[JobType] | None = None) -> Job | None:
        """Take the oldest eligible job, or None. Commits the claim.

        `FOR UPDATE SKIP LOCKED` is the whole concurrency story: the row is
        locked for the moment it takes to mark it `RUNNING`, and any other worker
        reading at the same time skips it rather than queuing behind it.

        `run_after` in the future is not eligible — that is how P07's retry
        backoff will schedule a second attempt without a scheduler.
        """
        statement = (
            select(Job)
            .where(
                Job.status == JobStatus.QUEUED,
                (Job.run_after.is_(None)) | (Job.run_after <= _utc_now()),
            )
            .order_by(Job.created_at.asc(), Job.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if types is not None:
            statement = statement.where(Job.type.in_(list(types)))

        job = self._session.scalars(statement).first()
        if job is None:
            # Release the read transaction rather than hold it open until the
            # next poll, half a second away.
            self._session.rollback()
            return None

        job.status = JobStatus.RUNNING
        job.attempts += 1
        self._session.commit()
        self._session.refresh(job)
        return job

    def complete(self, job: Job) -> Job:
        """Mark a finished job `DONE`. Commits."""
        job.status = JobStatus.DONE
        self._session.commit()
        return job

    def fail(self, job: Job, error: str) -> Job:
        """Mark a job `FAILED` and record why. Commits.

        `error` is a reason code, not prose and never model output: it is stored
        in a column P07 reads back and the review screen explains (NFR-09,
        CLAUDE.md §9). The timestamp is appended here so every reason in the
        table is written the same way.
        """
        job.status = JobStatus.FAILED
        job.last_error = f"{error} at {_utc_now().isoformat()}"
        self._session.commit()
        return job

    # --- Progress ----------------------------------------------------------

    def set_stage(self, job_id: uuid.UUID, stage: JobStage) -> None:
        """Record which stage a run has reached. Commits.

        A missing job is not an error: the orchestrator can be driven without one
        (the evaluation harness does, M7), and a stage marker is reporting, not
        state the run depends on.

        The dict is replaced rather than mutated in place, because SQLAlchemy does
        not track mutations inside a JSONB value.
        """
        job = self._session.get(Job, job_id)
        if job is None:
            return
        job.payload = {**(job.payload or {}), STAGE_KEY: str(stage)}
        self._session.commit()

    # --- Recovery (ADR-08, NFR-13) ----------------------------------------

    def recover_stale(self, older_than_minutes: int = DEFAULT_STALE_AFTER_MINUTES) -> int:
        """Return jobs stuck in `RUNNING` to `QUEUED`; returns how many. Commits.

        This is what makes a crash mid-pipeline safe. The case it was working on
        was left in `PROCESSING`, which the queue shows with no category — so the
        job has to come back, or that case waits forever (NFR-09, NFR-13).

        `attempts` is left as it is. The attempt happened; forgetting it would let
        a job that crashes the worker do so indefinitely.
        """
        cutoff = _utc_now() - timedelta(minutes=older_than_minutes)
        stale = list(
            self._session.scalars(
                select(Job).where(Job.status == JobStatus.RUNNING, Job.updated_at < cutoff)
            )
        )
        for job in stale:
            job.status = JobStatus.QUEUED
        self._session.commit()
        return len(stale)
