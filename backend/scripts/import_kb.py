"""Import curated knowledge-base files as drafts (P08 §8.2, FR-56).

    python -m scripts.import_kb --dry-run     # report, write nothing
    python -m scripts.import_kb               # rules, then entries
    python -m scripts.import_kb --entries     # entries only
    python -m scripts.import_kb --rules       # red-flag rules only

Rules are imported before entries, because an entry's `red_flag_codes` can only
be linked to rules that already exist.

Nothing imported here is live. Entries arrive as `DRAFT` and rules as unapproved
placeholders; a veterinary account holding `can_approve_kb` is still what makes
either of them take effect (FR-51, FR-52, BR-04, NFR-08). An ACTIVE entry is
never modified by an import — a changed file becomes a new draft revision
(ADR-14).

`--dry-run` is the same code path as a real run, rolled back instead of
committed. There is no second implementation to disagree with the first.

The script is a shell: argparse, a session, a summary table and an exit code.
The parsing lives in `app/schemas/kb_import.py` and the upsert rules in
`app/services/kb_import.py` (CLAUDE.md §7).
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models import User, UserRole
from app.services.kb_import import ImportReport, KBImporter, parse_all

# Exit codes. 1 is "some file was wrong", which a CI step should fail on; 2 is
# "the run could not start at all", which is the convention `scripts/seed.py`
# already uses for a refused --reset.
EXIT_OK = 0
EXIT_FILE_ERRORS = 1
EXIT_CANNOT_RUN = 2


def resolve_author(session: Session, email: str | None) -> User:
    """The account the imported drafts are attributed to.

    `kb_entries.created_by` is not nullable and an import is somebody's act, not
    the system's. Any administrator will do — the script picks the lowest email
    so two runs on the same database attribute to the same person — and `--author`
    names one explicitly.

    An administrator, because creating and editing drafts is the administrator's
    half of the workflow (P08 §8.1); a reviewer who could import drafts would be
    approving content they authored, which BR-04 separates.
    """
    statement = select(User).where(User.role == UserRole.ADMINISTRATOR)
    if email is not None:
        statement = statement.where(User.email == email)
    author = session.scalars(statement.order_by(User.email)).first()
    if author is None:
        named = f" with the email {email}" if email else ""
        raise LookupError(
            f"No administrator account{named} was found. Run "
            f"`python -m scripts.seed` first, or pass --author."
        )
    return author


def run(
    session: Session,
    *,
    knowledge_base_dir: Path,
    with_entries: bool,
    with_rules: bool,
    author_email: str | None,
) -> tuple[ImportReport, list[str]]:
    """Parse and import. Flushes; never commits — the caller decides.

    Returns the report and the file-level error lines, which are separate because
    a file that does not parse never reaches the importer and so has no row in
    the report.
    """
    rules, entries, failures = parse_all(
        knowledge_base_dir, with_entries=with_entries, with_rules=with_rules
    )

    report = ImportReport()
    author = resolve_author(session, author_email)
    importer = KBImporter(session, author=author)
    if with_rules:
        importer.import_rules(rules, report)
    if with_entries:
        importer.import_entries(entries, report)
    return report, [failure.line() for failure in failures]


def main(
    argv: list[str] | None = None,
    settings: Settings | None = None,
    session_factory: Callable[[], Session] | sessionmaker | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.import_kb",
        description="Import knowledge-base entries and red-flag rules from YAML files.",
    )
    parser.add_argument(
        "--entries", action="store_true", help="import entries/*.yaml (default: both)"
    )
    parser.add_argument(
        "--rules", action="store_true", help="import red_flags.yaml (default: both)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change and roll back without writing",
    )
    parser.add_argument(
        "--dir",
        dest="directory",
        default=None,
        help="the knowledge-base directory (default: KNOWLEDGE_BASE_DIR)",
    )
    parser.add_argument(
        "--author",
        default=None,
        help="email of the administrator the drafts are attributed to",
    )
    args = parser.parse_args(argv)
    settings = settings or get_settings()

    # Neither flag means both, which is what the verification command in P08
    # runs. Asking for one is how a curator re-imports just the rules.
    with_entries = args.entries or not args.rules
    with_rules = args.rules or not args.entries

    knowledge_base_dir = Path(args.directory or settings.knowledge_base_dir)
    if not knowledge_base_dir.is_dir():
        print(
            f"error: {knowledge_base_dir} is not a directory. Pass --dir, or set "
            f"KNOWLEDGE_BASE_DIR.",
            file=sys.stderr,
        )
        return EXIT_CANNOT_RUN

    open_session = session_factory or SessionLocal
    with open_session() as session:
        try:
            report, file_errors = run(
                session,
                knowledge_base_dir=knowledge_base_dir,
                with_entries=with_entries,
                with_rules=with_rules,
                author_email=args.author,
            )
        except LookupError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_CANNOT_RUN

        if args.dry_run:
            # Everything the importer did is discarded, including the audit
            # entries: a dry run is a question, not an action (FR-43).
            session.rollback()
        else:
            session.commit()

    if file_errors:
        print("Files that could not be imported:")
        for line in file_errors:
            print(line)
        print()

    for line in report.lines():
        print(line)

    if args.dry_run:
        print("\nDry run — nothing was written. Re-run without --dry-run to apply.")
    return EXIT_FILE_ERRORS if file_errors or report.has_errors else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
