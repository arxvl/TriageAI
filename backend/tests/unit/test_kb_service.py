"""`KBService`: the completeness rules, the workflow and what it audits.

The endpoint tests prove the roles and the status codes; this module proves the
rules underneath them, which is where the clinical guarantees live:

* an entry cannot be submitted for review without its full source citation
  (FR-50) or with content outside 50–1,500 words;
* approving writes a job and **not** an ACTIVE entry (FR-52, FR-53);
* a rejection's comments reach the author and never the audit log (FR-43).

All data here is fictitious (CLAUDE.md §9).
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import AppEnv
from app.core.errors import InvalidKBEntry, InvalidKBTransition, KBNotFound
from app.models import (
    AuditEntry,
    Job,
    JobType,
    KBEntry,
    KBEntryKind,
    KBEntryStatus,
    Species,
    User,
    UserRole,
    VTLCategory,
)
from app.schemas.kb import (
    KBEntryCreate,
    KBEntryFilters,
    KBEntryUpdate,
    KBRejection,
    RedFlagRuleCreate,
    RedFlagRuleUpdate,
)
from app.services.kb_service import KBService
from tests.conftest import (
    audit_actions,
    baseline_actions_content,
    kb_entry_content,
    make_kb_entry,
    make_red_flag_rule,
    make_user,
)

COMPLAINT = "LETHARGY"


def service(session: Session, **kwargs: object) -> KBService:
    return KBService(session, app_env=AppEnv.DEV, **kwargs)  # type: ignore[arg-type]


def admin(session: Session) -> User:
    return make_user(session, role=UserRole.ADMINISTRATOR, full_name="An Administrator")


def approver(session: Session) -> User:
    return make_user(
        session, role=UserRole.VETERINARY_REVIEWER, can_approve_kb=True, full_name="An Approver"
    )


def entry_payload(**overrides: object) -> KBEntryCreate:
    """A complete, fictitious draft entry (FR-49, FR-50)."""
    fields: dict[str, object] = {
        "title": "Fixture entry about a fictitious sign",
        "complaint_code": COMPLAINT,
        "species": [Species.DOG, Species.CAT],
        "content": kb_entry_content(),
        "source_title": "Fixture Source Title",
        "source_publisher": "Fixture Publisher",
        "source_url": "https://example.invalid/fixture",
        "access_date": date(2026, 10, 12),
        "slug": "fixture-entry",
    }
    fields.update(overrides)
    return KBEntryCreate(**fields)  # type: ignore[arg-type]


def actions_payload(**overrides: object) -> KBEntryCreate:
    """A complete, fictitious baseline action set (FR-72, ADR-18)."""
    fields: dict[str, object] = {
        "kind": KBEntryKind.URGENCY_ACTIONS,
        "urgency_category": VTLCategory.ORANGE,
        "complaint_code": None,
        "title": "Suggested staff actions - Orange",
        "species": [Species.DOG, Species.CAT],
        "content": baseline_actions_content(),
        "source_title": "Fixture Source Title",
        "source_publisher": "Fixture Publisher",
        "source_url": "https://example.invalid/fixture",
        "access_date": date(2026, 10, 12),
        "slug": "actions-orange",
    }
    fields.update(overrides)
    return KBEntryCreate(**fields)  # type: ignore[arg-type]


def make_baseline_set(
    session: Session,
    *,
    category: VTLCategory = VTLCategory.ORANGE,
    status: KBEntryStatus = KBEntryStatus.ACTIVE,
    slug: str | None = None,
    lines: int = 3,
) -> KBEntry:
    """An `URGENCY_ACTIONS` entry straight into the table, as the seed writes one."""
    return make_kb_entry(
        session,
        kind=KBEntryKind.URGENCY_ACTIONS,
        complaint_code=None,
        urgency_category=category,
        status=status,
        slug=slug,
        title=f"Suggested staff actions - {category.value}",
        content=baseline_actions_content(lines),
        with_source=True,
    )


def ensure_complaint(session: Session) -> None:
    """The complaint list is seeded; the unit tests run on a bare database."""
    make_kb_entry(session, complaint_code=COMPLAINT)


# --- Authoring (FR-49, FR-50) --------------------------------------------


def test_a_created_entry_is_a_complaint_draft(db_session: Session) -> None:
    ensure_complaint(db_session)
    user = admin(db_session)

    entry = service(db_session).create_entry(entry_payload(), user)

    assert entry.status is KBEntryStatus.DRAFT
    assert entry.kind is KBEntryKind.COMPLAINT
    assert entry.slug == "fixture-entry"
    assert entry.created_by_name == "An Administrator"
    assert entry.word_count == 60
    assert entry.indexing is None


def test_creating_an_entry_is_audited_without_its_content(db_session: Session) -> None:
    """The log cannot be corrected, so curated clinical text never enters it."""
    ensure_complaint(db_session)
    user = admin(db_session)

    service(db_session).create_entry(entry_payload(), user)

    entries = list(db_session.execute(select(Job)).all())  # noqa: F841 - readability
    assert "KB_ENTRY_CREATED" in audit_actions(db_session, user.id)
    payloads = _audit_payloads(db_session)
    assert all("content" not in (payload or {}) for payload in payloads)


def _audit_payloads(session: Session) -> list[dict | None]:
    from app.models import AuditEntry

    rows = session.execute(select(AuditEntry.before, AuditEntry.after)).all()
    return [value for row in rows for value in row]


def test_an_unknown_complaint_is_refused_by_field(db_session: Session) -> None:
    user = admin(db_session)

    with pytest.raises(InvalidKBEntry) as error:
        service(db_session).create_entry(entry_payload(complaint_code="NOT_A_COMPLAINT"), user)

    assert error.value.field == "complaint_code"
    assert error.value.status_code == 422


def test_a_slug_that_is_taken_is_refused(db_session: Session) -> None:
    ensure_complaint(db_session)
    user = admin(db_session)
    service(db_session).create_entry(entry_payload(), user)

    with pytest.raises(InvalidKBEntry) as error:
        service(db_session).create_entry(entry_payload(), user)

    assert error.value.field == "slug"


@pytest.mark.parametrize("words", [49, 1_501])
def test_content_outside_the_word_bounds_is_refused(db_session: Session, words: int) -> None:
    """50-1,500 words: long enough to be a passage, short enough to chunk.

    Refused by the service rather than by `KBEntryCreate`, because the bound
    depends on the kind: a baseline action set is lines, not prose (8.2b).
    """
    ensure_complaint(db_session)
    user = admin(db_session)

    with pytest.raises(InvalidKBEntry) as error:
        service(db_session).create_entry(entry_payload(content=kb_entry_content(words)), user)

    assert error.value.field == "content"
    assert "between 50 and 1,500 words" in str(error.value)


@pytest.mark.parametrize("field", ["source_title", "source_publisher", "source_url", "access_date"])
def test_every_citation_field_is_required_by_the_schema(field: str) -> None:
    """FR-50: no entry without the title, publisher, URL and access date."""
    fields = entry_payload().model_dump()
    del fields[field]

    with pytest.raises(ValueError, match=field):
        KBEntryCreate(**fields)


def test_an_edit_changes_only_what_was_sent(db_session: Session) -> None:
    ensure_complaint(db_session)
    user = admin(db_session)
    created = service(db_session).create_entry(entry_payload(), user)

    edited = service(db_session).update_entry(
        created.id, KBEntryUpdate(title="A different fixture title"), user
    )

    assert edited.title == "A different fixture title"
    assert edited.content == created.content
    assert edited.source.publisher == "Fixture Publisher"
    assert "KB_ENTRY_UPDATED" in audit_actions(db_session, user.id)


def test_an_edit_to_an_entry_awaiting_review_is_a_conflict(db_session: Session) -> None:
    user = admin(db_session)
    entry = make_kb_entry(db_session, status=KBEntryStatus.PENDING_REVIEW)

    with pytest.raises(InvalidKBTransition):
        service(db_session).update_entry(entry.id, KBEntryUpdate(title="Nope"), user)


def test_an_unknown_entry_is_a_not_found(db_session: Session) -> None:
    with pytest.raises(KBNotFound):
        service(db_session).get_entry(uuid.uuid4())


# --- Submitting (FR-50, FR-51) -------------------------------------------


def test_a_complete_draft_can_be_submitted(db_session: Session) -> None:
    ensure_complaint(db_session)
    user = admin(db_session)
    created = service(db_session).create_entry(entry_payload(), user)

    result = service(db_session).submit_entry(created.id, user)

    assert result.status is KBEntryStatus.PENDING_REVIEW
    assert "KB_ENTRY_SUBMITTED" in audit_actions(db_session, user.id)


def test_a_draft_with_no_citation_cannot_be_submitted(db_session: Session) -> None:
    """The importer writes drafts straight to the table, so this is re-checked."""
    user = admin(db_session)
    entry = make_kb_entry(db_session, content=kb_entry_content(), with_source=False)

    with pytest.raises(InvalidKBEntry) as error:
        service(db_session).submit_entry(entry.id, user)

    assert error.value.field == "source_title"


def test_a_draft_that_is_too_short_cannot_be_submitted(db_session: Session) -> None:
    user = admin(db_session)
    entry = make_kb_entry(db_session, content="Three words only", with_source=True)

    with pytest.raises(InvalidKBEntry) as error:
        service(db_session).submit_entry(entry.id, user)

    assert error.value.field == "content"
    assert "50" in error.value.message


def test_a_complaint_entry_with_no_complaint_is_refused(db_session: Session) -> None:
    """Checked on the object rather than through a row.

    `ck_kb_entries_complaint_code_iff_complaint` makes this combination
    impossible to store at all, so the only way to prove the service answers
    422 naming the field — rather than letting an integrity error reach the
    client — is to hand it the object the importer would have built (8.2).
    """
    entry = KBEntry(
        kind=KBEntryKind.COMPLAINT,
        complaint_code=None,
        title="Fixture entry",
        content=kb_entry_content(),
        species=[Species.DOG],
        source_title="Fixture Source Title",
        source_publisher="Fixture Publisher",
        source_url="https://example.invalid/fixture",
        access_date=date(2026, 10, 12),
    )

    with pytest.raises(InvalidKBEntry) as error:
        service(db_session)._require_complete(entry)

    assert error.value.field == "complaint_code"


# --- Approval and rejection (FR-52, FR-53) -------------------------------


def test_approving_enqueues_indexing_and_leaves_the_entry_pending(db_session: Session) -> None:
    """The entry goes live in the job, not in the request (FR-53, ADR-08)."""
    reviewer = approver(db_session)
    entry = make_kb_entry(
        db_session,
        status=KBEntryStatus.PENDING_REVIEW,
        content=kb_entry_content(),
        with_source=True,
    )

    result = service(db_session).approve_entry(entry.id, reviewer)

    db_session.refresh(entry)
    assert entry.status is KBEntryStatus.PENDING_REVIEW
    assert result.job_id is not None
    job = db_session.get(Job, result.job_id)
    assert job is not None
    assert job.type is JobType.KB_INDEX
    assert job.payload == {"entry_id": str(entry.id), "approved_by": str(reviewer.id)}
    assert "KB_ENTRY_APPROVED" in audit_actions(db_session, reviewer.id)


def test_the_approval_response_reports_the_indexing_state(db_session: Session) -> None:
    reviewer = approver(db_session)
    entry = make_kb_entry(db_session, status=KBEntryStatus.PENDING_REVIEW)

    service(db_session).approve_entry(entry.id, reviewer)
    detail = service(db_session).get_entry(entry.id)

    assert detail.indexing is not None
    assert detail.indexing.error is None


def test_rejecting_sends_the_entry_back_with_its_comments(db_session: Session) -> None:
    reviewer = approver(db_session)
    entry = make_kb_entry(db_session, status=KBEntryStatus.PENDING_REVIEW)

    result = service(db_session).reject_entry(
        entry.id, KBRejection(comments="Cite the source edition."), reviewer
    )

    assert result.status is KBEntryStatus.DRAFT
    detail = service(db_session).get_entry(entry.id)
    assert detail.review_comments == "Cite the source edition."


def test_the_rejection_comments_are_not_written_to_the_audit_log(db_session: Session) -> None:
    reviewer = approver(db_session)
    entry = make_kb_entry(db_session, status=KBEntryStatus.PENDING_REVIEW)

    service(db_session).reject_entry(
        entry.id, KBRejection(comments="Cite the source edition."), reviewer
    )

    payloads = _audit_payloads(db_session)
    assert "KB_ENTRY_REJECTED" in audit_actions(db_session, reviewer.id)
    assert all("Cite the source edition." not in str(payload) for payload in payloads)
    assert any(
        (payload or {}).get("comment_char_count") == len("Cite the source edition.")
        for payload in payloads
    )


def test_submitting_again_clears_the_rejection_comments(db_session: Session) -> None:
    ensure_complaint(db_session)
    author = admin(db_session)
    reviewer = approver(db_session)
    entry = make_kb_entry(
        db_session,
        status=KBEntryStatus.PENDING_REVIEW,
        complaint_code=COMPLAINT,
        content=kb_entry_content(),
        with_source=True,
    )
    service(db_session).reject_entry(entry.id, KBRejection(comments="Needs work."), reviewer)

    service(db_session).submit_entry(entry.id, author)

    assert service(db_session).get_entry(entry.id).review_comments is None


# --- Retirement (FR-53, FR-54) -------------------------------------------


class _RecordingIndexer:
    def __init__(self) -> None:
        self.removed: list[uuid.UUID] = []

    def index_entry(self, entry_id: uuid.UUID) -> int:
        return 0

    def remove_entry(self, entry_id: uuid.UUID) -> None:
        self.removed.append(entry_id)


def test_retiring_removes_the_chunks_and_publishes_a_version(db_session: Session) -> None:
    user = admin(db_session)
    entry = make_kb_entry(db_session, status=KBEntryStatus.ACTIVE, slug="fixture-retire")
    indexer = _RecordingIndexer()

    result = service(db_session, indexer=indexer).retire_entry(entry.id, user)

    assert result.status is KBEntryStatus.RETIRED
    assert result.version_no == 1
    assert indexer.removed == [entry.id]
    assert "KB_ENTRY_RETIRED" in audit_actions(db_session, user.id)


def test_retiring_a_draft_is_a_conflict(db_session: Session) -> None:
    user = admin(db_session)
    entry = make_kb_entry(db_session, status=KBEntryStatus.DRAFT)

    with pytest.raises(InvalidKBTransition):
        service(db_session, indexer=_RecordingIndexer()).retire_entry(entry.id, user)


# --- Urgency-action entries (P08 §8.2b, FR-72, ADR-18) --------------------
# A baseline action set goes through the same workflow as clinical content, with
# two rules of its own: one ACTIVE set per category, and a warning when retiring
# one leaves the category with nothing.


def test_a_baseline_action_set_can_be_authored(db_session: Session) -> None:
    user = admin(db_session)

    detail = service(db_session).create_entry(actions_payload(), user)

    assert detail.kind is KBEntryKind.URGENCY_ACTIONS
    assert detail.urgency_category is VTLCategory.ORANGE
    assert detail.complaint_code is None
    assert detail.status is KBEntryStatus.DRAFT


def test_a_baseline_action_set_is_not_held_to_the_fifty_word_floor(db_session: Session) -> None:
    """Three short imperatives are about twenty words (M5 Part D)."""
    user = admin(db_session)
    content = baseline_actions_content()
    assert len(content.split()) < 50

    detail = service(db_session).create_entry(actions_payload(content=content), user)
    result = service(db_session).submit_entry(detail.id, user)

    assert result.status is KBEntryStatus.PENDING_REVIEW


@pytest.mark.parametrize("lines", [2, 7])
def test_a_baseline_set_outside_the_line_bounds_is_refused(db_session: Session, lines: int) -> None:
    user = admin(db_session)

    with pytest.raises(InvalidKBEntry) as error:
        service(db_session).create_entry(
            actions_payload(content=baseline_actions_content(lines)), user
        )

    assert error.value.field == "content"
    assert "one per line" in str(error.value)


def test_a_baseline_line_naming_a_drug_is_refused(db_session: Session) -> None:
    """FR-28: baseline text is shown verbatim and never passes the validator."""
    user = admin(db_session)
    content = "Alert the veterinarian now\nGive butorphanol for pain\nPrepare oxygen"

    with pytest.raises(InvalidKBEntry) as error:
        service(db_session).create_entry(actions_payload(content=content), user)

    assert error.value.field == "content"
    assert "Line 2 names a medication" in str(error.value)


def test_a_complaint_entry_that_sets_an_urgency_category_is_refused(db_session: Session) -> None:
    """P08 §8.2b: the two kinds are exclusive (ADR-18)."""
    ensure_complaint(db_session)
    user = admin(db_session)

    with pytest.raises(InvalidKBEntry) as error:
        service(db_session).create_entry(entry_payload(urgency_category=VTLCategory.ORANGE), user)

    assert error.value.field == "urgency_category"
    assert error.value.status_code == 422


def test_editing_a_complaint_draft_cannot_give_it_an_urgency_category(
    db_session: Session,
) -> None:
    ensure_complaint(db_session)
    user = admin(db_session)
    detail = service(db_session).create_entry(entry_payload(), user)

    with pytest.raises(InvalidKBEntry) as error:
        service(db_session).update_entry(
            detail.id, KBEntryUpdate(urgency_category=VTLCategory.ORANGE), user
        )

    assert error.value.field == "urgency_category"


def test_a_baseline_set_that_sets_a_complaint_code_is_refused(db_session: Session) -> None:
    ensure_complaint(db_session)
    user = admin(db_session)

    with pytest.raises(InvalidKBEntry) as error:
        service(db_session).create_entry(actions_payload(complaint_code=COMPLAINT), user)

    assert error.value.field == "complaint_code"


def test_a_baseline_set_may_cite_no_red_flag_rule(db_session: Session) -> None:
    """A baseline set explains no rule: it is never retrieved or cited (FR-49)."""
    user = admin(db_session)
    make_red_flag_rule(db_session, code="FIXTURE_RULE")

    with pytest.raises(InvalidKBEntry) as error:
        service(db_session).create_entry(actions_payload(red_flag_codes=["FIXTURE_RULE"]), user)

    assert error.value.field == "red_flag_codes"


def test_approving_a_second_set_for_one_category_is_a_conflict(db_session: Session) -> None:
    """P08 §8.2b task 2: at most one ACTIVE baseline set per category (FR-72).

    409 rather than 422: nothing about the entry is wrong, the category is taken,
    and `baseline_actions` must never find two answers for one category.
    """
    author = admin(db_session)
    reviewer = approver(db_session)
    make_baseline_set(db_session, category=VTLCategory.ORANGE)
    replacement = service(db_session).create_entry(actions_payload(), author)
    service(db_session).submit_entry(replacement.id, author)

    with pytest.raises(InvalidKBTransition) as error:
        service(db_session).approve_entry(replacement.id, reviewer)

    assert "ORANGE" in str(error.value)
    assert error.value.status_code == 409
    assert db_session.scalars(select(Job).where(Job.type == JobType.KB_INDEX)).first() is None


def test_approving_a_set_for_a_free_category_is_accepted(db_session: Session) -> None:
    """The ACTIVE set of *another* category is no obstacle."""
    author = admin(db_session)
    reviewer = approver(db_session)
    make_baseline_set(db_session, category=VTLCategory.RED)
    entry = service(db_session).create_entry(actions_payload(), author)
    service(db_session).submit_entry(entry.id, author)

    result = service(db_session).approve_entry(entry.id, reviewer)

    assert result.job_id is not None
    assert result.status is KBEntryStatus.PENDING_REVIEW


def test_two_drafts_for_one_category_may_both_be_written(db_session: Session) -> None:
    """A replacement is written and reviewed while the current set is still live."""
    user = admin(db_session)
    make_baseline_set(db_session, category=VTLCategory.ORANGE, slug="actions-orange-live")

    first = service(db_session).create_entry(actions_payload(slug="actions-orange"), user)
    second = service(db_session).create_entry(actions_payload(slug="actions-orange-again"), user)

    assert first.status is KBEntryStatus.DRAFT
    assert second.status is KBEntryStatus.DRAFT


def test_retiring_a_baseline_set_warns_that_the_category_falls_back(
    db_session: Session,
) -> None:
    """P08 §8.2b task 2: no baseline actions until a replacement is approved."""
    user = admin(db_session)
    entry = make_baseline_set(db_session, category=VTLCategory.ORANGE, slug="actions-orange")
    indexer = _RecordingIndexer()

    result = service(db_session, indexer=indexer).retire_entry(entry.id, user)

    assert result.status is KBEntryStatus.RETIRED
    assert result.warning is not None
    assert "ORANGE cases will show no baseline actions" in result.warning
    # Nothing to drop: a baseline set is never chunked (ADR-18 §2).
    assert indexer.removed == []


def test_retiring_a_clinical_entry_carries_no_warning(db_session: Session) -> None:
    user = admin(db_session)
    entry = make_kb_entry(db_session, status=KBEntryStatus.ACTIVE, slug="fixture-no-warning")

    result = service(db_session, indexer=_RecordingIndexer()).retire_entry(entry.id, user)

    assert result.warning is None


def test_the_retirement_audit_entry_records_the_category_and_the_gap(
    db_session: Session,
) -> None:
    user = admin(db_session)
    entry = make_baseline_set(db_session, category=VTLCategory.BLUE, slug="actions-blue")

    service(db_session, indexer=_RecordingIndexer()).retire_entry(entry.id, user)

    recorded = db_session.scalars(
        select(AuditEntry).where(AuditEntry.action == "KB_ENTRY_RETIRED")
    ).one()
    assert recorded.after["urgency_category"] == "BLUE"
    assert recorded.after["left_category_without_baseline"] is True
    assert "content" not in recorded.after


# --- Listing (FR-51, FR-54) ----------------------------------------------


def test_the_counts_describe_the_whole_knowledge_base(db_session: Session) -> None:
    """Filtering the rows must not move the numbers beside the tabs."""
    make_kb_entry(db_session, status=KBEntryStatus.DRAFT, slug="fixture-list-1")
    make_kb_entry(db_session, status=KBEntryStatus.ACTIVE, slug="fixture-list-2")
    make_kb_entry(db_session, status=KBEntryStatus.ACTIVE, slug="fixture-list-3")

    listed = service(db_session).list_entries(KBEntryFilters(status=KBEntryStatus.DRAFT))

    assert [item.slug for item in listed.items] == ["fixture-list-1"]
    assert listed.counts[KBEntryStatus.ACTIVE] == 2
    assert listed.counts[KBEntryStatus.DRAFT] == 1
    assert listed.active_entry_count == 2


def test_the_header_shows_the_published_version_only(db_session: Session) -> None:
    """Version 0 is seeded and unpublished, so the header has nothing to show."""
    from tests.conftest import make_kb_version

    make_kb_version(db_session, version_no=0)

    assert service(db_session).list_entries(KBEntryFilters()).published_version_no is None


# --- Red-flag rules (NFR-08) ---------------------------------------------


def rule_payload(**overrides: object) -> RedFlagRuleCreate:
    fields: dict[str, object] = {
        "code": "FIXTURE_NEW_RULE",
        "label": "Fixture rule for the tests",
        "min_category": VTLCategory.ORANGE,
        "species": [Species.CAT],
        "phrases_ref": "FIXTURE_NEW_RULE",
    }
    fields.update(overrides)
    return RedFlagRuleCreate(**fields)  # type: ignore[arg-type]


def test_a_created_rule_is_unapproved_and_screens_nothing(db_session: Session) -> None:
    user = admin(db_session)

    rule = service(db_session).create_rule(rule_payload(), user)

    assert rule.approved_at is None
    assert rule.is_active is False
    assert "RED_FLAG_RULE_CREATED" in audit_actions(db_session, user.id)


def test_a_duplicate_rule_code_is_refused(db_session: Session) -> None:
    user = admin(db_session)
    make_red_flag_rule(db_session, code="FIXTURE_NEW_RULE")

    with pytest.raises(InvalidKBEntry) as error:
        service(db_session).create_rule(rule_payload(), user)

    assert error.value.field == "code"


def test_approving_a_rule_clears_the_placeholder_flag_and_publishes(db_session: Session) -> None:
    reviewer = approver(db_session)
    rule = make_red_flag_rule(db_session, code="FIXTURE_TO_APPROVE", is_placeholder=True)

    result = service(db_session).approve_rule(rule.id, reviewer)

    assert result.version_no == 1
    db_session.refresh(rule)
    assert rule.approved_by == reviewer.id
    assert rule.is_placeholder is False
    assert "RED_FLAG_RULE_APPROVED" in audit_actions(db_session, reviewer.id)


def test_an_approved_rule_cannot_be_edited(db_session: Session) -> None:
    reviewer = approver(db_session)
    user = admin(db_session)
    rule = make_red_flag_rule(db_session, code="FIXTURE_LOCKED", approved_by=reviewer)

    with pytest.raises(InvalidKBTransition):
        service(db_session).update_rule(rule.id, RedFlagRuleUpdate(label="Changed"), user)


def test_an_unapproved_rule_can_be_edited(db_session: Session) -> None:
    user = admin(db_session)
    rule = make_red_flag_rule(db_session, code="FIXTURE_OPEN")

    updated = service(db_session).update_rule(
        rule.id, RedFlagRuleUpdate(label="A clearer label", min_category=VTLCategory.RED), user
    )

    assert updated.label == "A clearer label"
    assert updated.min_category is VTLCategory.RED
    assert "RED_FLAG_RULE_UPDATED" in audit_actions(db_session, user.id)


def test_retiring_a_rule_publishes_a_version_and_stops_it_firing(db_session: Session) -> None:
    reviewer = approver(db_session)
    rule = make_red_flag_rule(db_session, code="FIXTURE_TO_RETIRE", approved_by=reviewer)

    result = service(db_session).retire_rule(rule.id, reviewer)

    assert result.version_no == 1
    db_session.refresh(rule)
    assert rule.retired_at is not None
    listed = {item.code: item for item in service(db_session).list_rules()}
    assert listed["FIXTURE_TO_RETIRE"].is_active is False


def test_a_rule_cannot_be_retired_twice(db_session: Session) -> None:
    reviewer = approver(db_session)
    rule = make_red_flag_rule(db_session, code="FIXTURE_RETIRE_ONCE", approved_by=reviewer)
    service(db_session).retire_rule(rule.id, reviewer)

    with pytest.raises(InvalidKBTransition):
        service(db_session).retire_rule(rule.id, reviewer)


def test_an_entry_can_cite_its_red_flag_rules(db_session: Session) -> None:
    """The W-08 rule picker: the rules a reader of this entry should know about."""
    ensure_complaint(db_session)
    user = admin(db_session)
    make_red_flag_rule(db_session, code="FIXTURE_LINKED")

    entry = service(db_session).create_entry(entry_payload(red_flag_codes=["FIXTURE_LINKED"]), user)

    assert entry.red_flag_codes == ["FIXTURE_LINKED"]


def test_citing_a_rule_that_does_not_exist_is_refused(db_session: Session) -> None:
    ensure_complaint(db_session)
    user = admin(db_session)

    with pytest.raises(InvalidKBEntry) as error:
        service(db_session).create_entry(entry_payload(red_flag_codes=["NO_SUCH_RULE"]), user)

    assert error.value.field == "red_flag_codes"
