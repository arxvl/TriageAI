"""The FastAPI application, and the lifespan that owns the job worker (ADR-08).

Three things happen at startup, in this order, and the order is the point:

1. **The pipeline is built** (`build_pipeline`), always — including when the
   worker is disabled. It is the only place a stage configuration is validated, so
   a `.env` that selects a stage nobody has written yet, or a real LLM behind the
   mock de-identifier, is a startup failure rather than a case that fails halfway
   through (CLAUDE.md §8.3, IR-20, ADR-10, ADR-17).
2. **Stale jobs are recovered** — jobs a crash left `RUNNING` go back to `QUEUED`,
   so the cases they were working on are not stuck in `PROCESSING` (NFR-13).
3. **The worker thread starts**, and is stopped before the process exits.

Steps 2 and 3 are skipped when `JOB_WORKER_ENABLED` is false. That is the test
configuration: the tests drive the queue with `run_pending_jobs_once` so a run is
finished when the assertion reads it, and nothing in a test touches the
development database through a background thread.

`create_app` takes `settings` so a test can build the app with the worker off
without reaching into the cached `get_settings()`.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware import CSRFMiddleware, SessionCookieMiddleware
from app.api.v1 import router as api_v1_router
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.jobs.recovery import recover_stale_jobs
from app.jobs.worker import JobWorker
from app.pipeline.registry import build_pipeline

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(title="TriageAI API", version="0.0.1", lifespan=_lifespan)
    app.state.settings = settings

    # Middleware added last runs first, so the CSRF check rejects a forged
    # request before the session cookie is refreshed for it.
    app.add_middleware(SessionCookieMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(api_v1_router, prefix="/api/v1")

    return app


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    # Imported here, not at module scope: importing `app.db.session` creates the
    # engine, and that should happen when the app starts, not when it is imported.
    from app.db.session import SessionLocal

    app.state.pipeline = build_pipeline(settings, session_factory=SessionLocal)
    logger.info(
        "pipeline built",
        extra={
            "fully_mocked": app.state.pipeline.is_fully_mocked,
            "mock_llm_behavior": str(settings.mock_llm_behavior),
        },
    )

    worker: JobWorker | None = None
    if settings.job_worker_enabled:
        recover_stale_jobs(SessionLocal, settings.job_stale_after_minutes)
        worker = JobWorker(
            SessionLocal,
            app.state.pipeline,
            poll_interval_s=settings.job_poll_interval_s,
        )
        worker.start()
    else:
        logger.info("job worker disabled (JOB_WORKER_ENABLED=false)")

    app.state.job_worker = worker
    try:
        yield
    finally:
        if worker is not None:
            worker.stop()


app = create_app()
