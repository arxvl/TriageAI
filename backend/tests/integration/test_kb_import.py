"""The importer upserts files into the 8.1 workflow without going around it.

These are the four guarantees P08 §8.2 asks to be proved: schema validation
errors, an idempotent re-import, an ACTIVE entry that is never overwritten, and
a dry run that writes nothing (the last one lives in
`test_import_kb_script.py`, where the transaction is the script's).

Against the real database, through the rolled-back `db_session` fixture, because
the slug uniqueness and the revision pointer are schema facts and nothing else
can prove them. All content is fictitious (CLAUDE.md §9).
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AuditEntry,
    KBEntry,
    KBEntryKind,
    KBEntryStatus,
    RedFlagRule,
    Species,
    User,
    UserRole,
    VTLCategory,
)
from app.schemas.kb_import import parse_entry_file, parse_rules_file
from app.services.kb_import import ImportOutcome, ImportReport, KBImporter, revision_slug
from tests.conftest import make_kb_entry, make_red_flag_rule, make_user

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


# --- Fixtures -------------------------------------------------------------


@pytest.fixture
def author(db_session: Session) -> User:
    return make_user(db_session, role=UserRole.ADMINISTRATOR, email="admin@triageai.invalid")


@pytest.fixture
def importer(db_session: Session, author: User) -> KBImporter:
    return KBImporter(db_session, author=author)


def entry_document(**overrides: object) -> dict:
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
    return document


def entry_file(tmp_path: Path, document: dict) -> object:
    """Write `document` and parse it, failing the test if it does not validate."""
    path = tmp_path / f"{document['slug']}.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    parsed, errors = parse_entry_file(path)
    assert errors == [], [error.line() for error in errors]
    assert parsed is not None
    return parsed


def rule_file(tmp_path: Path, rules: list[dict]) -> list:
    path = tmp_path / "red_flags.yaml"
    path.write_text(yaml.safe_dump({"rules": rules}), encoding="utf-8")
    parsed, errors = parse_rules_file(path)
    assert errors == [], [error.line() for error in errors]
    return parsed


def rule_document(**overrides: object) -> dict:
    document: dict = {
        "code": RULE_CODE,
        "label": "Male cat unable to pass urine",
        "min_category": "ORANGE",
        "species": ["CAT"],
        "phrases_ref": RULE_CODE,
    }
    document.update(overrides)
    return document


def complaint(db_session: Session, code: str = "URINARY_OBSTRUCTION") -> None:
    """Create the presenting complaint the entry files reference.

    `make_kb_entry` inserts one as a side effect; a test that imports without
    creating an entry first needs it on its own.
    """
    make_kb_entry(db_session, complaint_code=code, title="placeholder for the complaint row")
    db_session.query(KBEntry).filter_by(title="placeholder for the complaint row").delete()
    db_session.flush()


def import_entries(importer: KBImporter, entries: list) -> ImportReport:
    report = ImportReport()
    importer.import_entries(entries, report)
    return report


def import_rules(importer: KBImporter, rules: list) -> ImportReport:
    report = ImportReport()
    importer.import_rules(rules, report)
    return report


def count(session: Session, model: type) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def stored(session: Session, slug: str) -> KBEntry | None:
    return session.scalars(select(KBEntry).where(KBEntry.slug == slug)).first()


# --- Creating drafts (FR-56) ----------------------------------------------


def test_an_entry_file_becomes_a_draft(
    db_session: Session, importer: KBImporter, author: User, tmp_path: Path
) -> None:
    complaint(db_session)
    report = import_entries(importer, [entry_file(tmp_path, entry_document())])

    assert [row.outcome for row in report.entries] == [ImportOutcome.CREATED]
    entry = stored(db_session, ENTRY_SLUG)
    assert entry is not None
    # Imported as a DRAFT and nothing more: approval is a person's act (FR-52).
    assert entry.status is KBEntryStatus.DRAFT
    assert entry.kind is KBEntryKind.COMPLAINT
    assert entry.approved_by is None
    assert entry.created_by == author.id
    assert entry.revises_entry_id is None
    assert entry.species == [Species.CAT]
    assert entry.source_publisher == "Fixture Publisher"
    assert entry.access_date.isoformat() == "2026-10-12"


def test_red_flag_codes_are_linked_to_the_entry(
    db_session: Session, importer: KBImporter, tmp_path: Path
) -> None:
    complaint(db_session)
    make_red_flag_rule(db_session, code=RULE_CODE, min_category=VTLCategory.ORANGE)

    import_entries(importer, [entry_file(tmp_path, entry_document(red_flag_codes=[RULE_CODE]))])

    entry = stored(db_session, ENTRY_SLUG)
    rule = db_session.scalars(select(RedFlagRule).where(RedFlagRule.code == RULE_CODE)).one()
    assert entry is not None
    assert rule.entry_id == entry.id


def test_an_unknown_red_flag_code_is_an_error_and_writes_nothing(
    db_session: Session, importer: KBImporter, tmp_path: Path
) -> None:
    complaint(db_session)
    before = count(db_session, KBEntry)

    report = import_entries(
        importer, [entry_file(tmp_path, entry_document(red_flag_codes=["NO_SUCH_RULE"]))]
    )

    assert [row.outcome for row in report.entries] == [ImportOutcome.ERROR]
    assert "NO_SUCH_RULE" in (report.entries[0].detail or "")
    assert count(db_session, KBEntry) == before


def test_an_unknown_complaint_code_is_an_error(
    db_session: Session, importer: KBImporter, tmp_path: Path
) -> None:
    report = import_entries(
        importer, [entry_file(tmp_path, entry_document(complaint_code="NO_SUCH_COMPLAINT"))]
    )

    assert [row.outcome for row in report.entries] == [ImportOutcome.ERROR]
    assert "NO_SUCH_COMPLAINT" in (report.entries[0].detail or "")
    assert stored(db_session, ENTRY_SLUG) is None


# --- Idempotence (FR-56) --------------------------------------------------


def test_re_importing_an_unchanged_file_does_nothing(
    db_session: Session, importer: KBImporter, tmp_path: Path
) -> None:
    """Not one row write and not one audit entry, so the command is safe to repeat."""
    complaint(db_session)
    parsed = entry_file(tmp_path, entry_document())
    import_entries(importer, [parsed])
    entries_before = count(db_session, KBEntry)
    audit_before = count(db_session, AuditEntry)

    report = import_entries(importer, [parsed])

    assert [row.outcome for row in report.entries] == [ImportOutcome.UNCHANGED]
    assert count(db_session, KBEntry) == entries_before
    assert count(db_session, AuditEntry) == audit_before


def test_a_changed_file_updates_a_draft_in_place(
    db_session: Session, importer: KBImporter, tmp_path: Path
) -> None:
    complaint(db_session)
    import_entries(importer, [entry_file(tmp_path, entry_document())])
    original_id = stored(db_session, ENTRY_SLUG).id

    report = import_entries(
        importer, [entry_file(tmp_path, entry_document(title="A revised title"))]
    )

    assert [row.outcome for row in report.entries] == [ImportOutcome.UPDATED]
    assert "title" in (report.entries[0].detail or "")
    entry = stored(db_session, ENTRY_SLUG)
    assert entry.id == original_id
    assert entry.title == "A revised title"


def test_dropping_a_red_flag_code_unlinks_the_rule(
    db_session: Session, importer: KBImporter, tmp_path: Path
) -> None:
    complaint(db_session)
    make_red_flag_rule(db_session, code=RULE_CODE, min_category=VTLCategory.ORANGE)
    import_entries(importer, [entry_file(tmp_path, entry_document(red_flag_codes=[RULE_CODE]))])

    report = import_entries(importer, [entry_file(tmp_path, entry_document(red_flag_codes=[]))])

    assert [row.outcome for row in report.entries] == [ImportOutcome.UPDATED]
    rule = db_session.scalars(select(RedFlagRule).where(RedFlagRule.code == RULE_CODE)).one()
    assert rule.entry_id is None


# --- An ACTIVE entry is never overwritten (ADR-14, DR-05) -----------------


def test_an_active_entry_is_never_modified_in_place(
    db_session: Session, importer: KBImporter, author: User, tmp_path: Path
) -> None:
    active = make_kb_entry(
        db_session,
        complaint_code="URINARY_OBSTRUCTION",
        status=KBEntryStatus.ACTIVE,
        slug=ENTRY_SLUG,
        title="The approved title",
        content=CONTENT,
        created_by=author,
        with_source=True,
    )

    report = import_entries(
        importer, [entry_file(tmp_path, entry_document(title="A title from the file"))]
    )

    assert [row.outcome for row in report.entries] == [ImportOutcome.REVISED]
    db_session.refresh(active)
    # Every column of the live row is as the approver left it.
    assert active.title == "The approved title"
    assert active.status is KBEntryStatus.ACTIVE
    assert active.slug == ENTRY_SLUG


def test_a_changed_file_for_an_active_entry_creates_a_draft_revision(
    db_session: Session, importer: KBImporter, author: User, tmp_path: Path
) -> None:
    active = make_kb_entry(
        db_session,
        complaint_code="URINARY_OBSTRUCTION",
        status=KBEntryStatus.ACTIVE,
        slug=ENTRY_SLUG,
        content=CONTENT,
        created_by=author,
        with_source=True,
    )

    import_entries(importer, [entry_file(tmp_path, entry_document(title="A revised title"))])

    revision = stored(db_session, f"{ENTRY_SLUG}-rev2")
    assert revision is not None
    assert revision.status is KBEntryStatus.DRAFT
    assert revision.revises_entry_id == active.id
    assert revision.title == "A revised title"


def test_re_importing_the_same_change_updates_the_revision_rather_than_stacking(
    db_session: Session, importer: KBImporter, author: User, tmp_path: Path
) -> None:
    """The reason `draft_revision_of` exists: no `-rev3` piles up on a re-run."""
    make_kb_entry(
        db_session,
        complaint_code="URINARY_OBSTRUCTION",
        status=KBEntryStatus.ACTIVE,
        slug=ENTRY_SLUG,
        content=CONTENT,
        created_by=author,
        with_source=True,
    )
    changed = entry_file(tmp_path, entry_document(title="A revised title"))
    import_entries(importer, [changed])

    second = import_entries(importer, [changed])
    third = import_entries(
        importer, [entry_file(tmp_path, entry_document(title="Revised once more"))]
    )

    assert [row.outcome for row in second.entries] == [ImportOutcome.UNCHANGED]
    assert [row.outcome for row in third.entries] == [ImportOutcome.UPDATED]
    assert stored(db_session, f"{ENTRY_SLUG}-rev3") is None
    assert stored(db_session, f"{ENTRY_SLUG}-rev2").title == "Revised once more"


def test_an_unchanged_file_for_an_active_entry_creates_no_revision(
    db_session: Session, importer: KBImporter, author: User, tmp_path: Path
) -> None:
    document = entry_document()
    make_kb_entry(
        db_session,
        complaint_code="URINARY_OBSTRUCTION",
        status=KBEntryStatus.ACTIVE,
        slug=ENTRY_SLUG,
        title=document["title"],
        content=CONTENT,
        created_by=author,
        with_source=True,
    )
    # `make_kb_entry`'s own fixture citation differs from the file's, so the
    # citation is aligned here to make the two genuinely identical.
    active = stored(db_session, ENTRY_SLUG)
    active.species = [Species.CAT]
    active.source_title = document["source"]["title"]
    active.source_publisher = document["source"]["publisher"]
    active.source_url = document["source"]["url"]
    active.access_date = datetime.fromisoformat(document["source"]["access_date"]).date()
    db_session.flush()

    report = import_entries(importer, [entry_file(tmp_path, document)])

    assert [row.outcome for row in report.entries] == [ImportOutcome.UNCHANGED]
    assert stored(db_session, f"{ENTRY_SLUG}-rev2") is None


def test_a_retired_entry_is_revised_rather_than_edited(
    db_session: Session, importer: KBImporter, author: User, tmp_path: Path
) -> None:
    """A published version still lists it, so it is never edited either (DR-05)."""
    retired = make_kb_entry(
        db_session,
        complaint_code="URINARY_OBSTRUCTION",
        status=KBEntryStatus.RETIRED,
        slug=ENTRY_SLUG,
        title="The retired title",
        content=CONTENT,
        created_by=author,
        with_source=True,
    )

    report = import_entries(importer, [entry_file(tmp_path, entry_document())])

    assert [row.outcome for row in report.entries] == [ImportOutcome.REVISED]
    db_session.refresh(retired)
    assert retired.title == "The retired title"
    assert stored(db_session, f"{ENTRY_SLUG}-rev2").revises_entry_id == retired.id


def test_an_entry_waiting_for_review_is_skipped(
    db_session: Session, importer: KBImporter, author: User, tmp_path: Path
) -> None:
    """Editing it would change what the approver is looking at (FR-51)."""
    pending = make_kb_entry(
        db_session,
        complaint_code="URINARY_OBSTRUCTION",
        status=KBEntryStatus.PENDING_REVIEW,
        slug=ENTRY_SLUG,
        title="The submitted title",
        content=CONTENT,
        created_by=author,
        with_source=True,
    )

    report = import_entries(importer, [entry_file(tmp_path, entry_document())])

    assert [row.outcome for row in report.entries] == [ImportOutcome.SKIPPED]
    assert "waiting for review" in (report.entries[0].detail or "")
    db_session.refresh(pending)
    assert pending.title == "The submitted title"
    assert stored(db_session, f"{ENTRY_SLUG}-rev2") is None


def test_revision_slug_skips_the_numbers_already_taken() -> None:
    assert revision_slug("cat", []) == "cat-rev2"
    assert revision_slug("cat", ["cat-rev2"]) == "cat-rev3"
    assert revision_slug("cat", ["cat-rev2", "cat-rev3"]) == "cat-rev4"


# --- Red-flag rules (NFR-08, BR-04) ---------------------------------------


def test_a_rule_is_imported_unapproved(
    db_session: Session, importer: KBImporter, tmp_path: Path
) -> None:
    report = import_rules(importer, rule_file(tmp_path, [rule_document()]))

    assert [row.outcome for row in report.rules] == [ImportOutcome.CREATED]
    rule = db_session.scalars(select(RedFlagRule).where(RedFlagRule.code == RULE_CODE)).one()
    # Unapproved and a placeholder, which together are what keeps it out of
    # `get_active_rules` outside development.
    assert rule.approved_at is None
    assert rule.approved_by is None
    assert rule.is_placeholder is True
    assert rule.retired_at is None
    assert rule.min_category is VTLCategory.ORANGE


def test_re_importing_an_unchanged_rule_does_nothing(
    db_session: Session, importer: KBImporter, tmp_path: Path
) -> None:
    rules = rule_file(tmp_path, [rule_document()])
    import_rules(importer, rules)
    audit_before = count(db_session, AuditEntry)

    report = import_rules(importer, rules)

    assert [row.outcome for row in report.rules] == [ImportOutcome.UNCHANGED]
    assert count(db_session, AuditEntry) == audit_before


def test_a_changed_file_updates_an_unapproved_rule_and_leaves_it_unapproved(
    db_session: Session, importer: KBImporter, tmp_path: Path
) -> None:
    import_rules(importer, rule_file(tmp_path, [rule_document()]))

    report = import_rules(
        importer, rule_file(tmp_path, [rule_document(min_category="RED", label="A new label")])
    )

    assert [row.outcome for row in report.rules] == [ImportOutcome.UPDATED]
    rule = db_session.scalars(select(RedFlagRule).where(RedFlagRule.code == RULE_CODE)).one()
    assert rule.min_category is VTLCategory.RED
    assert rule.label == "A new label"
    assert rule.approved_at is None


def test_an_approved_rule_is_never_changed_by_a_file(
    db_session: Session, importer: KBImporter, author: User, tmp_path: Path
) -> None:
    """Lowering the safety floor by editing a text file is what NFR-08 forbids."""
    approver = make_user(
        db_session,
        role=UserRole.VETERINARY_REVIEWER,
        can_approve_kb=True,
        email="approver@triageai.invalid",
    )
    rule = make_red_flag_rule(
        db_session,
        code=RULE_CODE,
        min_category=VTLCategory.ORANGE,
        approved_by=approver,
    )

    report = import_rules(importer, rule_file(tmp_path, [rule_document(min_category="BLUE")]))

    assert [row.outcome for row in report.rules] == [ImportOutcome.SKIPPED]
    assert "approved" in (report.rules[0].detail or "")
    db_session.refresh(rule)
    assert rule.min_category is VTLCategory.ORANGE
    assert rule.is_placeholder is False


def test_an_approved_rule_whose_file_matches_reports_unchanged(
    db_session: Session, importer: KBImporter, tmp_path: Path
) -> None:
    """Approval clears `is_placeholder`, which must not read as a pending change."""
    approver = make_user(
        db_session,
        role=UserRole.VETERINARY_REVIEWER,
        can_approve_kb=True,
        email="approver2@triageai.invalid",
    )
    make_red_flag_rule(
        db_session,
        code=RULE_CODE,
        min_category=VTLCategory.ORANGE,
        species=(Species.CAT,),
        approved_by=approver,
        phrases_ref=RULE_CODE,
    )

    report = import_rules(
        importer, rule_file(tmp_path, [rule_document(label=f"Fixture rule {RULE_CODE}")])
    )

    assert [row.outcome for row in report.rules] == [ImportOutcome.UNCHANGED]


def test_a_retired_rule_is_skipped(
    db_session: Session, importer: KBImporter, tmp_path: Path
) -> None:
    rule = make_red_flag_rule(
        db_session,
        code=RULE_CODE,
        min_category=VTLCategory.ORANGE,
        retired_at=datetime.now(UTC),
    )

    report = import_rules(importer, rule_file(tmp_path, [rule_document(min_category="RED")]))

    assert [row.outcome for row in report.rules] == [ImportOutcome.SKIPPED]
    assert "retired" in (report.rules[0].detail or "")
    db_session.refresh(rule)
    assert rule.min_category is VTLCategory.ORANGE


# --- Audit (FR-43, ADR-12, CLAUDE.md §9) ----------------------------------


def test_the_audit_entries_name_the_import_and_carry_no_content(
    db_session: Session, importer: KBImporter, tmp_path: Path
) -> None:
    complaint(db_session)
    import_entries(importer, [entry_file(tmp_path, entry_document())])

    entries = db_session.scalars(
        select(AuditEntry).where(AuditEntry.entity_type == "kb_entry")
    ).all()

    assert [entry.action for entry in entries] == ["KB_ENTRY_CREATED"]
    payload = entries[0].after
    assert payload["source"] == "import"
    assert payload["slug"] == ENTRY_SLUG
    assert payload["word_count"] > 0
    # Field *names*, never their values: the log cannot be corrected.
    assert "title" in payload["fields"]
    serialized = str(payload)
    assert CONTENT[:40] not in serialized
    assert "Fixture Source" not in serialized


def test_a_revision_records_the_entry_it_supersedes(
    db_session: Session, importer: KBImporter, author: User, tmp_path: Path
) -> None:
    active = make_kb_entry(
        db_session,
        complaint_code="URINARY_OBSTRUCTION",
        status=KBEntryStatus.ACTIVE,
        slug=ENTRY_SLUG,
        content=CONTENT,
        created_by=author,
        with_source=True,
    )

    import_entries(importer, [entry_file(tmp_path, entry_document(title="A revised title"))])

    entry = db_session.scalars(
        select(AuditEntry)
        .where(AuditEntry.entity_type == "kb_entry")
        .order_by(AuditEntry.id.desc())
    ).first()
    assert entry.after["revises_entry_id"] == str(active.id)
    assert entry.after["revises_slug"] == ENTRY_SLUG
