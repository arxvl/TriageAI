"""`python -m app.eval`: import, run and report (P09 §9.2 task 5, NFR-01/16/17).

The commands run in the test process against the test transaction, with the mock
pipeline. All data is fictitious (CLAUDE.md §9).
"""

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.eval.cli import EXIT_CANNOT_RUN, EXIT_OK, EXIT_PROBLEMS, main
from app.models import EvaluationRun, EvaluationSet, Job, JobStatus, JobType, UserRole
from scripts.seed import seed
from tests.conftest import make_user
from tests.conftest import test_settings as pipeline_settings

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "vignettes_mock.csv"


@pytest.fixture
def admin_exists(db_session: Session) -> None:
    seed(db_session)
    make_user(db_session, role=UserRole.ADMINISTRATOR, email="cli-admin@triageai.invalid")


def cli(factory: sessionmaker, *argv: str) -> int:
    return main(list(argv), pipeline_settings(), factory)


def import_mock_set(factory: sessionmaker, name: str = "mock-set") -> int:
    return cli(factory, "import", "--file", str(FIXTURE), "--name", name)


def run_mock_set(factory: sessionmaker, capsys: pytest.CaptureFixture[str]) -> str:
    import_mock_set(factory)
    capsys.readouterr()
    assert cli(factory, "run", "--set", "mock-set") == EXIT_OK
    match = re.search(r"Run ([0-9a-f-]{36}) finished", capsys.readouterr().out)
    assert match, "the run id is printed"
    return match.group(1)


# --- import -----------------------------------------------------------------


def test_import_stores_the_set_and_prints_the_count_and_warnings(
    db_session: Session,
    app_session_factory: sessionmaker,
    admin_exists: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert import_mock_set(app_session_factory) == EXIT_OK

    out = capsys.readouterr().out
    assert "Imported 10 vignettes as set 'mock-set'" in out
    assert "warning: Unknown knowledge-base entry slug: skin-itch-dog" in out
    assert db_session.scalar(select(func.count()).select_from(EvaluationSet)) == 1


def test_import_refuses_a_repeated_name_and_a_missing_file(
    app_session_factory: sessionmaker,
    admin_exists: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import_mock_set(app_session_factory)

    assert import_mock_set(app_session_factory) == EXIT_CANNOT_RUN
    assert cli(app_session_factory, "import", "--file", "/nope.csv", "--name", "x") == (
        EXIT_CANNOT_RUN
    )
    assert "already exists" in capsys.readouterr().err


def test_import_prints_the_rows_of_a_bad_file_and_stores_nothing(
    db_session: Session,
    app_session_factory: sessionmaker,
    admin_exists: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "external_id,species,description,reference_category,relevant_entry_slugs\n"
        'V-1,HORSE,"A description that is certainly long enough.",GREEN,\n',
        encoding="utf-8",
    )

    code = cli(app_session_factory, "import", "--file", str(bad), "--name", "bad")

    assert code == EXIT_PROBLEMS
    assert "row 2 [species]" in capsys.readouterr().err
    assert db_session.scalar(select(func.count()).select_from(EvaluationSet)) == 0


def test_import_needs_an_administrator(
    app_session_factory: sessionmaker, capsys: pytest.CaptureFixture[str]
) -> None:
    assert import_mock_set(app_session_factory) == EXIT_CANNOT_RUN
    assert "No active administrator" in capsys.readouterr().err


# --- run --------------------------------------------------------------------


def test_run_executes_in_this_process_and_queues_no_job(
    db_session: Session,
    app_session_factory: sessionmaker,
    admin_exists: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_id = run_mock_set(app_session_factory, capsys)

    run = db_session.get(EvaluationRun, run_id)
    assert run.status is JobStatus.DONE
    assert run.metrics["counts"]["total"] == 10
    # A queued job as well would have the API's worker run it a second time.
    assert (
        db_session.scalar(select(func.count()).select_from(Job).where(Job.type == JobType.EVAL_RUN))
        == 0
    )


def test_run_of_an_unknown_set_cannot_start(
    app_session_factory: sessionmaker, admin_exists: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli(app_session_factory, "run", "--set", "nope") == EXIT_CANNOT_RUN
    assert "no evaluation set is named 'nope'" in capsys.readouterr().err


def test_run_says_when_every_stage_is_a_mock(
    app_session_factory: sessionmaker, admin_exists: None, capsys: pytest.CaptureFixture[str]
) -> None:
    import_mock_set(app_session_factory)
    capsys.readouterr()

    cli(app_session_factory, "run", "--set", "mock-set")

    assert "MOCK MODE" in capsys.readouterr().err


# --- report -----------------------------------------------------------------


def test_the_markdown_report_prints_the_targets_with_a_mark_for_each(
    app_session_factory: sessionmaker, admin_exists: None, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = run_mock_set(app_session_factory, capsys)

    assert cli(app_session_factory, "report", "--run", run_id, "--format", "md") == EXIT_OK

    report = capsys.readouterr().out
    assert "MOCK MODE – results are not model results" in report
    # The SRS targets, each on its own row with a PASS / FAIL / n/a mark.
    for label, target, requirement in (
        ("Macro-F1", "≥ 0.7", "NFR-16"),
        ("Red+Orange recall", "≥ 0.9", "NFR-16"),
        ("Under-triage rate", "≤ 10%", "NFR-16"),
        ("Recall@5", "≥ 0.8", "NFR-17"),
        ("MRR", "≥ 0.7", "NFR-17"),
        ("Latency p50", "≤ 10 s", "NFR-01"),
        ("Latency p95", "≤ 20 s", "NFR-01"),
    ):
        row = next(line for line in report.splitlines() if line.startswith(f"| {label} |"))
        assert target in row and requirement in row
        assert re.search(r"\| (PASS|FAIL|n/a) \|$", row)
    assert "## Confusion matrix" in report
    assert "## Under-triaged vignettes" in report
    assert "Failed (excluded from the metrics):** 1" in report


def test_the_json_report_is_the_run_as_the_api_reports_it(
    app_session_factory: sessionmaker, admin_exists: None, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = run_mock_set(app_session_factory, capsys)

    assert cli(app_session_factory, "report", "--run", run_id, "--format", "json") == EXIT_OK

    body = json.loads(capsys.readouterr().out)
    assert body["id"] == run_id
    assert body["metrics"]["counts"]["scored"] == 9
    assert len(body["targets"]) == 7


def test_report_of_an_unknown_or_malformed_run(
    app_session_factory: sessionmaker, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli(app_session_factory, "report", "--run", "not-an-id") == EXIT_CANNOT_RUN
    assert cli(app_session_factory, "report", "--run", "00000000-0000-0000-0000-000000000000") == (
        EXIT_CANNOT_RUN
    )
