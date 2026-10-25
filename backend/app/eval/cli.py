"""`python -m app.eval`: import vignettes, run an evaluation, print the report (P09 §9.2).

    python -m app.eval import --file evaluation/vignettes/<name>.csv --name "<set name>"
    python -m app.eval run --set "<set name>"
    python -m app.eval report --run <id> [--format md|json]

A shell around `EvaluationService` and `run_evaluation`: argparse, a session, some
printing and an exit code. `run` executes the evaluation in this process, with the
pipeline the settings select, rather than queueing it for the API's worker - the
harness is what M7 drives from a terminal, and it needs no running server.

Exit codes follow `scripts/import_kb.py`: 0 done, 1 the file or the run had
problems, 2 it could not start at all (no such set, no administrator).

Progress goes to stderr and results to stdout, so `report > file.md` is just the
report.
"""

import argparse
import sys
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.errors import EvaluationNameInUse, EvaluationNotFound, InvalidVignetteFile
from app.eval.report import render_json, render_markdown
from app.eval.runner import run_evaluation
from app.models import JobStatus, User, UserRole
from app.repositories.evaluation_repository import EvaluationRepository
from app.services.evaluation_service import EvaluationService

EXIT_OK = 0
EXIT_PROBLEMS = 1
EXIT_CANNOT_RUN = 2


def resolve_author(session: Session, email: str | None) -> User:
    """The administrator the import and the run are attributed to.

    The lowest e-mail when none is named, so two invocations on the same database
    attribute to the same person.
    """
    statement = select(User).where(User.role == UserRole.ADMINISTRATOR, User.is_active.is_(True))
    if email is not None:
        statement = statement.where(User.email == email)
    author = session.scalars(statement.order_by(User.email)).first()
    if author is None:
        named = f" with the email {email}" if email else ""
        raise LookupError(
            f"No active administrator account{named} was found. Run "
            "`python -m scripts.seed` first, or pass --author."
        )
    return author


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.eval", description="The TriageAI evaluation harness."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    importing = commands.add_parser("import", help="import a vignette CSV as an evaluation set")
    importing.add_argument("--file", required=True, help="the vignette CSV (UTF-8)")
    importing.add_argument("--name", required=True, help="the name of the new set")
    importing.add_argument("--author", default=None, help="e-mail of the importing administrator")

    running = commands.add_parser("run", help="run an evaluation over a set, in this process")
    running.add_argument("--set", dest="set_name", required=True, help="the set's name")
    running.add_argument("--author", default=None, help="e-mail of the administrator starting it")

    reporting = commands.add_parser("report", help="print a finished run's report")
    reporting.add_argument("--run", required=True, help="the run's id")
    reporting.add_argument("--format", choices=("md", "json"), default="md")
    return parser


def _import(session: Session, args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"error: {path} is not a file.", file=sys.stderr)
        return EXIT_CANNOT_RUN
    try:
        author = resolve_author(session, args.author)
        stored = EvaluationService(session).import_set(args.name, path.read_bytes(), author)
    except LookupError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    except EvaluationNameInUse:
        print(f"error: a set named {args.name!r} already exists.", file=sys.stderr)
        return EXIT_CANNOT_RUN
    except InvalidVignetteFile as error:
        print(f"{path} was not imported. Nothing was stored.", file=sys.stderr)
        for item in error.rows:
            where = f"row {item['row']}" if item["row"] else "file"
            field = f" [{item['field']}]" if item["field"] else ""
            print(f"  {where}{field}: {item['message']}", file=sys.stderr)
        return EXIT_PROBLEMS

    print(f"Imported {stored.vignette_count} vignettes as set {stored.name!r} ({stored.id}).")
    for warning in stored.warnings:
        print(f"warning: {warning}")
    return EXIT_OK


def _run(
    session: Session,
    args: argparse.Namespace,
    settings: Settings,
    session_factory: Callable[[], Session] | sessionmaker,
) -> int:
    # Imported here: building a pipeline pulls in the registry and every stage
    # module a setting selects, which `import` and `report` do not need.
    from app.pipeline.registry import build_pipeline

    repo = EvaluationRepository(session)
    chosen = repo.get_set_by_name(args.set_name)
    if chosen is None:
        print(f"error: no evaluation set is named {args.set_name!r}.", file=sys.stderr)
        return EXIT_CANNOT_RUN
    try:
        author = resolve_author(session, args.author)
        started = EvaluationService(session).start_run(chosen.id, author, enqueue=False)
    except (LookupError, EvaluationNotFound) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    # Reading the run back began a transaction. End it before the run starts, so
    # this session is not left idle in a transaction for as long as the
    # evaluation takes, and the run's own sessions are not nested inside it.
    session.commit()

    pipeline = build_pipeline(settings, session_factory=session_factory)
    if pipeline.is_fully_mocked:
        print("MOCK MODE: every stage is a mock, so these are not model results.", file=sys.stderr)

    def progress(done: int, total: int) -> None:
        print(f"  {done}/{total} vignettes", file=sys.stderr)

    result = run_evaluation(session_factory, pipeline, started.id, on_progress=progress)
    if not result.succeeded:
        print(f"Run {started.id} failed: {result.failure_reason}.", file=sys.stderr)
        return EXIT_PROBLEMS
    print(f"Run {started.id} finished.")
    print(f"Report: python -m app.eval report --run {started.id} --format md")
    return EXIT_OK


def _report(session: Session, args: argparse.Namespace) -> int:
    try:
        run_id = uuid.UUID(args.run)
    except ValueError:
        print(f"error: {args.run!r} is not a run id.", file=sys.stderr)
        return EXIT_CANNOT_RUN
    try:
        run = EvaluationService(session).get_run(run_id)
    except EvaluationNotFound:
        print(f"error: no evaluation run has the id {run_id}.", file=sys.stderr)
        return EXIT_CANNOT_RUN
    print(render_markdown(run) if args.format == "md" else render_json(run))
    return EXIT_OK if run.status is JobStatus.DONE else EXIT_PROBLEMS


def main(
    argv: Sequence[str] | None = None,
    settings: Settings | None = None,
    session_factory: Callable[[], Session] | sessionmaker | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    settings = settings or get_settings()

    if session_factory is None:
        # Not at module scope: importing `app.db.session` creates the engine.
        from app.db.session import SessionLocal

        session_factory = SessionLocal

    with session_factory() as session:
        if args.command == "import":
            return _import(session, args)
        if args.command == "run":
            return _run(session, args, settings, session_factory)
        return _report(session, args)
