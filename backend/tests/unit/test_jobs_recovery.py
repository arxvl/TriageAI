"""The startup sweep (P05 §5.4 task 3, ADR-08, NFR-13).

Two things to prove: a job a crash left `RUNNING` comes back, and the line that
says so names a count and nothing else. A startup log that listed the cases a
crash interrupted would put clinical data in the container log (CLAUDE.md §9).

All data here is fictitious.
"""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.jobs.recovery import recover_stale_jobs
from app.models import JobStatus
from tests.conftest import make_case, make_job

PET_NAME = "Tabby Placeholder"


def test_a_stale_running_job_is_requeued(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    job = make_job(
        db_session,
        case=make_case(db_session),
        status=JobStatus.RUNNING,
        updated_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    assert recover_stale_jobs(app_session_factory, older_than_minutes=2) == 1

    db_session.refresh(job)
    assert job.status is JobStatus.QUEUED


def test_nothing_to_recover_returns_zero(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    make_job(db_session, case=make_case(db_session), status=JobStatus.QUEUED)

    assert recover_stale_jobs(app_session_factory, older_than_minutes=2) == 0


def test_the_log_line_names_a_count_and_no_case_data(
    db_session: Session,
    app_session_factory: sessionmaker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    case = make_case(db_session, pet_name=PET_NAME)
    job = make_job(
        db_session,
        case=case,
        status=JobStatus.RUNNING,
        updated_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    with caplog.at_level(logging.DEBUG, logger="app.jobs.recovery"):
        recover_stale_jobs(app_session_factory, older_than_minutes=2)

    assert any(record.__dict__.get("recovered") == 1 for record in caplog.records)
    for record in caplog.records:
        rendered = record.getMessage() + repr(record.__dict__)
        assert PET_NAME not in rendered
        assert str(case.id) not in rendered
        assert str(job.id) not in rendered
