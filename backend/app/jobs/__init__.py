"""The database-backed job queue and its worker (ADR-08).

The triage pipeline takes seconds, so `POST /cases` records the case and enqueues
a job rather than running it (FR-06, NFR-01). The queue lives in PostgreSQL — the
database the system already depends on — instead of in Redis or Celery, which
would add a broker, a second process type and another failure mode to explain
(ADR-01, ADR-08).

Three modules, in dependency order:

- `queue` — the rows: enqueue, claim, complete, fail, progress, recovery.
- `worker` — who calls the pipeline: a lifespan thread in production,
  `run_pending_jobs_once` in the tests.
- `recovery` — the startup sweep that rescues jobs a crash left `RUNNING`
  (NFR-13).
"""
