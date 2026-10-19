"""`python -m scripts.import_kb` writes when told to, and never on a dry run.

The script owns its transaction, so these tests hand it a `session_factory`
bound to the rolled-back test connection — the same trick
`tests/conftest.py::app_session_factory` exists for. A commit inside it releases
a savepoint, so the outer rollback still removes everything.

All content is fictitious (CLAUDE.md §9).
"""

from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.models import KBEntry, KBEntryStatus, RedFlagRule, User, UserRole
from scripts.import_kb import EXIT_CANNOT_RUN, EXIT_FILE_ERRORS, EXIT_OK, main
from tests.conftest import make_kb_entry, make_user

CONTENT = (
    "SAMPLE - not source-verified. Fixture entry content written only so the "
    "word count clears the fifty-word floor the knowledge-base workflow puts on "
    "an entry before it can be submitted for review. It names no medication, no "
    "dose and no diagnosis, and it describes no real animal, owner or clinic. "
    "Every word of it is invented for the test suite and nothing here is "
    "clinical guidance of any kind at all."
)

ENTRY_SLUG = "urinary-straining-cat"
RULE_CODE = "MALE_CAT_NO_URINE"


@pytest.fixture
def knowledge_base(tmp_path: Path) -> Path:
    """A knowledge-base directory holding one valid entry and one valid rule."""
    (tmp_path / "entries").mkdir()
    write_entry(tmp_path)
    write_rules(tmp_path)
    return tmp_path


def write_entry(root: Path, **overrides: object) -> Path:
    document: dict = {
        "slug": ENTRY_SLUG,
        "title": "Straining or inability to urinate - cats",
        "complaint_code": "URINARY_OBSTRUCTION",
        "species": ["CAT"],
        "content": CONTENT,
        "source": {
            "title": "Fixture Source",
            "publisher": "Fixture Publisher",
            "url": "https://example.invalid/fixture",
            "access_date": "2026-10-12",
        },
        "red_flag_codes": [],
    }
    document.update(overrides)
    path = root / "entries" / f"{document['slug']}.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def write_rules(root: Path, **overrides: object) -> Path:
    rule: dict = {
        "code": RULE_CODE,
        "label": "Male cat unable to pass urine",
        "min_category": "ORANGE",
        "species": ["CAT"],
        "phrases_ref": RULE_CODE,
    }
    rule.update(overrides)
    path = root / "red_flags.yaml"
    path.write_text(yaml.safe_dump({"rules": [rule]}), encoding="utf-8")
    return path


@pytest.fixture
def seeded(db_session: Session) -> User:
    """An administrator for the drafts, and the presenting complaint they cite."""
    admin = make_user(db_session, role=UserRole.ADMINISTRATOR, email="admin@triageai.invalid")
    # `make_kb_entry` creates the presenting_complaints row as a side effect;
    # the entry itself is removed so only the complaint is left behind.
    placeholder = make_kb_entry(db_session, complaint_code="URINARY_OBSTRUCTION")
    db_session.delete(placeholder)
    db_session.flush()
    return admin


def factory(db_connection: object) -> sessionmaker:
    return sessionmaker(bind=db_connection, join_transaction_mode="create_savepoint")


def count(session: Session, model: type) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def run(
    argv: list[str], knowledge_base: Path, db_connection: object, settings: Settings | None = None
) -> int:
    return main(
        [*argv, "--dir", str(knowledge_base)],
        settings=settings or get_settings(),
        session_factory=factory(db_connection),
    )


# --- Writing, and not writing ---------------------------------------------


def test_a_run_imports_the_rule_and_the_entry(
    db_session: Session, db_connection: object, knowledge_base: Path, seeded: User
) -> None:
    code = run([], knowledge_base, db_connection)

    assert code == EXIT_OK
    entry = db_session.scalars(select(KBEntry).where(KBEntry.slug == ENTRY_SLUG)).one()
    assert entry.status is KBEntryStatus.DRAFT
    assert db_session.scalars(select(RedFlagRule).where(RedFlagRule.code == RULE_CODE)).one()


def test_a_dry_run_writes_nothing(
    db_session: Session,
    db_connection: object,
    knowledge_base: Path,
    seeded: User,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A dry run is a question, not an action — not even an audit entry (FR-43)."""
    entries_before = count(db_session, KBEntry)
    rules_before = count(db_session, RedFlagRule)

    code = run(["--dry-run"], knowledge_base, db_connection)

    assert code == EXIT_OK
    assert count(db_session, KBEntry) == entries_before
    assert count(db_session, RedFlagRule) == rules_before
    printed = capsys.readouterr().out
    assert "created" in printed
    assert "nothing was written" in printed


def test_rules_only_touches_no_entries(
    db_session: Session, db_connection: object, knowledge_base: Path, seeded: User
) -> None:
    entries_before = count(db_session, KBEntry)

    code = run(["--rules"], knowledge_base, db_connection)

    assert code == EXIT_OK
    assert count(db_session, KBEntry) == entries_before
    assert db_session.scalars(select(RedFlagRule).where(RedFlagRule.code == RULE_CODE)).one()


def test_entries_only_touches_no_rules(
    db_session: Session, db_connection: object, knowledge_base: Path, seeded: User
) -> None:
    rules_before = count(db_session, RedFlagRule)

    code = run(["--entries"], knowledge_base, db_connection)

    assert code == EXIT_OK
    assert count(db_session, RedFlagRule) == rules_before
    assert db_session.scalars(select(KBEntry).where(KBEntry.slug == ENTRY_SLUG)).one()


# --- Exit codes -----------------------------------------------------------


def test_a_file_that_does_not_validate_exits_one(
    db_session: Session,
    db_connection: object,
    knowledge_base: Path,
    seeded: User,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_entry(knowledge_base, content="too short")

    code = run([], knowledge_base, db_connection)

    assert code == EXIT_FILE_ERRORS
    printed = capsys.readouterr().out
    assert "urinary-straining-cat.yaml [content]" in printed
    # The rule in the same run still imported: one bad file does not stop the rest.
    assert db_session.scalars(select(RedFlagRule).where(RedFlagRule.code == RULE_CODE)).one()


def test_an_entry_naming_a_missing_rule_exits_one(
    db_session: Session, db_connection: object, knowledge_base: Path, seeded: User
) -> None:
    write_entry(knowledge_base, red_flag_codes=["NO_SUCH_RULE"])

    code = run(["--entries"], knowledge_base, db_connection)

    assert code == EXIT_FILE_ERRORS
    assert db_session.scalars(select(KBEntry).where(KBEntry.slug == ENTRY_SLUG)).first() is None


def test_no_administrator_account_exits_two(
    db_connection: object, knowledge_base: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`kb_entries.created_by` is not nullable: an import is somebody's act."""
    code = run([], knowledge_base, db_connection)

    assert code == EXIT_CANNOT_RUN
    assert "No administrator account" in capsys.readouterr().err


def test_an_unknown_author_exits_two(
    db_connection: object, knowledge_base: Path, seeded: User, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run(["--author", "nobody@triageai.invalid"], knowledge_base, db_connection)

    assert code == EXIT_CANNOT_RUN
    assert "nobody@triageai.invalid" in capsys.readouterr().err


def test_a_missing_directory_exits_two(
    db_connection: object, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run([], tmp_path / "not-here", db_connection)

    assert code == EXIT_CANNOT_RUN
    assert "is not a directory" in capsys.readouterr().err


def test_a_knowledge_base_with_no_entry_files_is_reported(
    db_connection: object, tmp_path: Path, seeded: User, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "entries").mkdir()
    write_rules(tmp_path)

    code = run([], tmp_path, db_connection)

    assert code == EXIT_FILE_ERRORS
    assert "nothing to import" in capsys.readouterr().out
