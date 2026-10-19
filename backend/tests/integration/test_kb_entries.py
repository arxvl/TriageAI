"""The `/kb/entries` endpoints: roles, validation and transitions (P08 §8.1).

One success, one validation failure and one wrong-role refusal per endpoint
(CLAUDE.md §10), plus the two refusals the phase exists for:

* an administrator cannot approve — approval is the KB approver's (BR-04);
* a Veterinary Reviewer **without** `can_approve_kb` cannot either (FR-52).

All data here is fictitious (CLAUDE.md §9).
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    KBEntryKind,
    KBEntryStatus,
    PresentingComplaint,
    User,
    UserRole,
    VTLCategory,
)
from tests.conftest import (
    baseline_actions_content,
    csrf_headers,
    kb_entry_content,
    make_kb_entry,
    make_red_flag_rule,
    make_user,
    sign_in,
)

PASSWORD = "Sampaguita2026"
ENTRIES_URL = "/api/v1/kb/entries"
COMPLAINTS_URL = "/api/v1/kb/complaints"
COMPLAINT = "LETHARGY"


def entry_body(**overrides: object) -> dict:
    body: dict = {
        "title": "Fixture entry about a fictitious sign",
        "complaint_code": COMPLAINT,
        "species": ["DOG", "CAT"],
        "content": kb_entry_content(),
        "source_title": "Fixture Source Title",
        "source_publisher": "Fixture Publisher",
        "source_url": "https://example.invalid/fixture",
        "access_date": str(date(2026, 10, 12)),
        "slug": "fixture-entry",
    }
    body.update(overrides)
    return body


def actions_body(**overrides: object) -> dict:
    """A baseline action set as W-08's editor will post one (8.2b, ADR-18)."""
    body: dict = {
        "kind": KBEntryKind.URGENCY_ACTIONS.value,
        "urgency_category": VTLCategory.ORANGE.value,
        "title": "Suggested staff actions - Orange",
        "species": ["DOG", "CAT"],
        "content": baseline_actions_content(),
        "source_title": "Fixture Source Title",
        "source_publisher": "Fixture Publisher",
        "source_url": "https://example.invalid/fixture",
        "access_date": str(date(2026, 10, 12)),
        "slug": "actions-orange",
    }
    body.update(overrides)
    return body


def make_baseline_set(
    session: Session,
    *,
    category: VTLCategory = VTLCategory.ORANGE,
    status: KBEntryStatus = KBEntryStatus.ACTIVE,
    slug: str | None = None,
):
    return make_kb_entry(
        session,
        kind=KBEntryKind.URGENCY_ACTIONS,
        complaint_code=None,
        urgency_category=category,
        status=status,
        slug=slug,
        title=f"Suggested staff actions - {category.value}",
        content=baseline_actions_content(),
        with_source=True,
    )


def ensure_complaint(session: Session) -> None:
    if session.get(PresentingComplaint, COMPLAINT) is None:
        session.add(PresentingComplaint(code=COMPLAINT, name="Lethargy", sort_order=1))
        session.flush()


def signed_in(
    client: TestClient,
    session: Session,
    role: UserRole,
    *,
    can_approve_kb: bool = False,
) -> User:
    user = make_user(session, password=PASSWORD, role=role, can_approve_kb=can_approve_kb)
    sign_in(client, user.email, PASSWORD)
    return user


def as_admin(client: TestClient, session: Session) -> User:
    return signed_in(client, session, UserRole.ADMINISTRATOR)


def as_approver(client: TestClient, session: Session) -> User:
    return signed_in(client, session, UserRole.VETERINARY_REVIEWER, can_approve_kb=True)


# --- Creating (FR-49, FR-50) ---------------------------------------------


def test_an_administrator_creates_a_draft(api_client: TestClient, db_session: Session) -> None:
    ensure_complaint(db_session)
    as_admin(api_client, db_session)

    response = api_client.post(ENTRIES_URL, json=entry_body(), headers=csrf_headers(api_client))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == KBEntryStatus.DRAFT.value
    assert body["kind"] == "COMPLAINT"
    assert body["word_count"] == 60
    assert body["source"]["publisher"] == "Fixture Publisher"


def test_content_outside_the_word_bounds_is_a_422_naming_the_field(
    api_client: TestClient, db_session: Session
) -> None:
    ensure_complaint(db_session)
    as_admin(api_client, db_session)

    response = api_client.post(
        ENTRIES_URL,
        json=entry_body(content="Far too short."),
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["field"] == "content"
    assert "50" in error["message"]


@pytest.mark.parametrize("field", ["source_title", "source_publisher", "source_url", "access_date"])
def test_a_missing_citation_field_is_a_422(
    api_client: TestClient, db_session: Session, field: str
) -> None:
    """FR-50: no entry without the title, publisher, URL and access date."""
    ensure_complaint(db_session)
    as_admin(api_client, db_session)
    body = entry_body()
    del body[field]

    response = api_client.post(ENTRIES_URL, json=body, headers=csrf_headers(api_client))

    assert response.status_code == 422
    assert response.json()["error"]["field"] == field


def test_a_reviewer_cannot_create_an_entry(api_client: TestClient, db_session: Session) -> None:
    """Curation is the administrator's work (BR-02, BR-05)."""
    as_approver(api_client, db_session)

    response = api_client.post(ENTRIES_URL, json=entry_body(), headers=csrf_headers(api_client))

    assert response.status_code == 403


def test_intake_staff_cannot_read_the_knowledge_base(
    api_client: TestClient, db_session: Session
) -> None:
    signed_in(api_client, db_session, UserRole.INTAKE_STAFF)

    assert api_client.get(ENTRIES_URL).status_code == 403


# --- Reading (FR-51) -----------------------------------------------------


def test_the_list_carries_the_tab_counts_and_the_published_version(
    api_client: TestClient, db_session: Session
) -> None:
    make_kb_entry(db_session, status=KBEntryStatus.DRAFT, slug="fixture-draft")
    make_kb_entry(db_session, status=KBEntryStatus.ACTIVE, slug="fixture-active")
    as_admin(api_client, db_session)

    body = api_client.get(ENTRIES_URL).json()

    assert body["counts"]["DRAFT"] >= 1
    assert body["counts"]["ACTIVE"] >= 1
    assert "published_version_no" in body
    assert body["active_entry_count"] == body["counts"]["ACTIVE"]


def test_the_list_carries_each_entrys_source_title(
    api_client: TestClient, db_session: Session
) -> None:
    """The W-08 Source column (FR-50, P08 §8.3)."""
    make_kb_entry(db_session, status=KBEntryStatus.DRAFT, slug="fixture-sourced", with_source=True)
    as_admin(api_client, db_session)

    body = api_client.get(f"{ENTRIES_URL}?status=DRAFT").json()

    rows = {item["slug"]: item["source_title"] for item in body["items"]}
    assert rows["fixture-sourced"] == "Fixture Source Title"


def test_the_list_can_be_filtered_by_status(api_client: TestClient, db_session: Session) -> None:
    make_kb_entry(db_session, status=KBEntryStatus.RETIRED, slug="fixture-retired")
    as_admin(api_client, db_session)

    body = api_client.get(f"{ENTRIES_URL}?status=RETIRED").json()

    assert [item["slug"] for item in body["items"]] == ["fixture-retired"]


def test_an_approver_can_read_an_entry(api_client: TestClient, db_session: Session) -> None:
    entry = make_kb_entry(db_session, status=KBEntryStatus.PENDING_REVIEW, slug="fixture-read")
    as_approver(api_client, db_session)

    response = api_client.get(f"{ENTRIES_URL}/{entry.id}")

    assert response.status_code == 200
    assert response.json()["slug"] == "fixture-read"


def test_an_unknown_entry_is_404(api_client: TestClient, db_session: Session) -> None:
    as_admin(api_client, db_session)

    response = api_client.get(f"{ENTRIES_URL}/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# --- Editing and submitting (FR-51, ADR-14) ------------------------------


def test_a_draft_can_be_edited(api_client: TestClient, db_session: Session) -> None:
    entry = make_kb_entry(db_session, status=KBEntryStatus.DRAFT, slug="fixture-edit")
    as_admin(api_client, db_session)

    response = api_client.patch(
        f"{ENTRIES_URL}/{entry.id}",
        json={"title": "A clearer fixture title"},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 200
    assert response.json()["title"] == "A clearer fixture title"


def test_an_active_entry_cannot_be_edited(api_client: TestClient, db_session: Session) -> None:
    """The rule the whole versioning scheme rests on (ADR-14, DR-05)."""
    entry = make_kb_entry(db_session, status=KBEntryStatus.ACTIVE, slug="fixture-no-edit")
    as_admin(api_client, db_session)

    response = api_client.patch(
        f"{ENTRIES_URL}/{entry.id}",
        json={"title": "Not allowed"},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_an_unknown_field_in_an_edit_is_refused(
    api_client: TestClient, db_session: Session
) -> None:
    entry = make_kb_entry(db_session, status=KBEntryStatus.DRAFT, slug="fixture-extra")
    as_admin(api_client, db_session)

    response = api_client.patch(
        f"{ENTRIES_URL}/{entry.id}",
        json={"status": "ACTIVE"},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 422


def test_clearing_a_required_field_is_a_422_naming_it(
    api_client: TestClient, db_session: Session
) -> None:
    """`{"title": null}` has no meaning, and must not reach the database."""
    entry = make_kb_entry(db_session, status=KBEntryStatus.DRAFT, slug="fixture-null-title")
    as_admin(api_client, db_session)

    response = api_client.patch(
        f"{ENTRIES_URL}/{entry.id}",
        json={"title": None},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "title"


def test_a_complete_draft_is_submitted(api_client: TestClient, db_session: Session) -> None:
    ensure_complaint(db_session)
    entry = make_kb_entry(
        db_session,
        status=KBEntryStatus.DRAFT,
        complaint_code=COMPLAINT,
        content=kb_entry_content(),
        with_source=True,
        slug="fixture-submit",
    )
    as_admin(api_client, db_session)

    response = api_client.post(f"{ENTRIES_URL}/{entry.id}/submit", headers=csrf_headers(api_client))

    assert response.status_code == 200
    assert response.json()["status"] == KBEntryStatus.PENDING_REVIEW.value


def test_an_incomplete_draft_cannot_be_submitted(
    api_client: TestClient, db_session: Session
) -> None:
    """A draft from the YAML importer never passed through `KBEntryCreate`."""
    entry = make_kb_entry(
        db_session, status=KBEntryStatus.DRAFT, content=kb_entry_content(), slug="fixture-bare"
    )
    as_admin(api_client, db_session)

    response = api_client.post(f"{ENTRIES_URL}/{entry.id}/submit", headers=csrf_headers(api_client))

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "source_title"


def test_submitting_twice_is_a_conflict(api_client: TestClient, db_session: Session) -> None:
    entry = make_kb_entry(
        db_session,
        status=KBEntryStatus.PENDING_REVIEW,
        content=kb_entry_content(),
        with_source=True,
        slug="fixture-resubmit",
    )
    as_admin(api_client, db_session)

    response = api_client.post(f"{ENTRIES_URL}/{entry.id}/submit", headers=csrf_headers(api_client))

    assert response.status_code == 409


# --- Approval and rejection (FR-52, FR-53, BR-04) ------------------------


def test_an_approver_approves_and_indexing_is_queued(
    api_client: TestClient, db_session: Session
) -> None:
    entry = make_kb_entry(db_session, status=KBEntryStatus.PENDING_REVIEW, slug="fixture-approve")
    as_approver(api_client, db_session)

    response = api_client.post(
        f"{ENTRIES_URL}/{entry.id}/approve", headers=csrf_headers(api_client)
    )

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"] is not None
    # Still awaiting review: the entry goes live inside the job (FR-53).
    assert body["status"] == KBEntryStatus.PENDING_REVIEW.value


def test_an_administrator_cannot_approve(api_client: TestClient, db_session: Session) -> None:
    """Clinical content is approved by a veterinarian, not by an administrator."""
    entry = make_kb_entry(
        db_session, status=KBEntryStatus.PENDING_REVIEW, slug="fixture-admin-approve"
    )
    as_admin(api_client, db_session)

    response = api_client.post(
        f"{ENTRIES_URL}/{entry.id}/approve", headers=csrf_headers(api_client)
    )

    assert response.status_code == 403


def test_a_reviewer_without_the_kb_permission_cannot_approve(
    api_client: TestClient, db_session: Session
) -> None:
    """`can_approve_kb` is a separate capability from the role (FR-58, BR-04)."""
    entry = make_kb_entry(
        db_session, status=KBEntryStatus.PENDING_REVIEW, slug="fixture-no-permission"
    )
    signed_in(api_client, db_session, UserRole.VETERINARY_REVIEWER, can_approve_kb=False)

    response = api_client.post(
        f"{ENTRIES_URL}/{entry.id}/approve", headers=csrf_headers(api_client)
    )

    assert response.status_code == 403


def test_a_reviewer_without_the_kb_permission_cannot_reject(
    api_client: TestClient, db_session: Session
) -> None:
    entry = make_kb_entry(db_session, status=KBEntryStatus.PENDING_REVIEW, slug="fixture-no-reject")
    signed_in(api_client, db_session, UserRole.VETERINARY_REVIEWER, can_approve_kb=False)

    response = api_client.post(
        f"{ENTRIES_URL}/{entry.id}/reject",
        json={"comments": "Not yet."},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 403


def test_a_rejection_sends_the_entry_back_with_comments(
    api_client: TestClient, db_session: Session
) -> None:
    entry = make_kb_entry(db_session, status=KBEntryStatus.PENDING_REVIEW, slug="fixture-reject")
    as_approver(api_client, db_session)

    response = api_client.post(
        f"{ENTRIES_URL}/{entry.id}/reject",
        json={"comments": "Cite the source edition."},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 200
    assert response.json()["status"] == KBEntryStatus.DRAFT.value
    assert api_client.get(f"{ENTRIES_URL}/{entry.id}").json()["review_comments"] == (
        "Cite the source edition."
    )


@pytest.mark.parametrize("comments", ["", "   "])
def test_a_rejection_without_comments_is_refused(
    api_client: TestClient, db_session: Session, comments: str
) -> None:
    """A rejection with no reason gives the author nothing to act on."""
    entry = make_kb_entry(
        db_session, status=KBEntryStatus.PENDING_REVIEW, slug="fixture-blank-reject"
    )
    as_approver(api_client, db_session)

    response = api_client.post(
        f"{ENTRIES_URL}/{entry.id}/reject",
        json={"comments": comments},
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "comments"


def test_a_draft_cannot_be_approved(api_client: TestClient, db_session: Session) -> None:
    entry = make_kb_entry(db_session, status=KBEntryStatus.DRAFT, slug="fixture-draft-approve")
    as_approver(api_client, db_session)

    response = api_client.post(
        f"{ENTRIES_URL}/{entry.id}/approve", headers=csrf_headers(api_client)
    )

    assert response.status_code == 409


# --- Retirement (FR-53, FR-54) -------------------------------------------


def test_an_administrator_retires_an_active_entry(
    api_client: TestClient, db_session: Session
) -> None:
    entry = make_kb_entry(db_session, status=KBEntryStatus.ACTIVE, slug="fixture-retire")
    as_admin(api_client, db_session)

    response = api_client.post(f"{ENTRIES_URL}/{entry.id}/retire", headers=csrf_headers(api_client))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == KBEntryStatus.RETIRED.value
    assert body["version_no"] == 1


def test_a_draft_cannot_be_retired(api_client: TestClient, db_session: Session) -> None:
    entry = make_kb_entry(db_session, status=KBEntryStatus.DRAFT, slug="fixture-retire-draft")
    as_admin(api_client, db_session)

    response = api_client.post(f"{ENTRIES_URL}/{entry.id}/retire", headers=csrf_headers(api_client))

    assert response.status_code == 409


def test_intake_staff_cannot_retire_an_entry(api_client: TestClient, db_session: Session) -> None:
    entry = make_kb_entry(db_session, status=KBEntryStatus.ACTIVE, slug="fixture-retire-403")
    signed_in(api_client, db_session, UserRole.INTAKE_STAFF)

    response = api_client.post(f"{ENTRIES_URL}/{entry.id}/retire", headers=csrf_headers(api_client))

    assert response.status_code == 403


# --- Urgency-action entries (P08 §8.2b, ADR-18) ---------------------------


def test_an_administrator_creates_a_baseline_action_set(
    api_client: TestClient, db_session: Session
) -> None:
    as_admin(api_client, db_session)

    response = api_client.post(ENTRIES_URL, json=actions_body(), headers=csrf_headers(api_client))

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == KBEntryKind.URGENCY_ACTIONS.value
    assert body["urgency_category"] == VTLCategory.ORANGE.value
    assert body["complaint_code"] is None
    assert body["status"] == KBEntryStatus.DRAFT.value


def test_a_clinical_entry_cannot_set_an_urgency_category(
    api_client: TestClient, db_session: Session
) -> None:
    """The two kinds are exclusive, answered as a 422 naming the field."""
    ensure_complaint(db_session)
    as_admin(api_client, db_session)

    response = api_client.post(
        ENTRIES_URL,
        json=entry_body(urgency_category=VTLCategory.ORANGE.value),
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "urgency_category"


def test_a_baseline_set_with_too_few_actions_is_a_422(
    api_client: TestClient, db_session: Session
) -> None:
    as_admin(api_client, db_session)

    response = api_client.post(
        ENTRIES_URL,
        json=actions_body(content=baseline_actions_content(2)),
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["field"] == "content"
    assert "one per line" in error["message"]


def test_intake_staff_cannot_create_a_baseline_action_set(
    api_client: TestClient, db_session: Session
) -> None:
    signed_in(api_client, db_session, UserRole.INTAKE_STAFF)

    response = api_client.post(ENTRIES_URL, json=actions_body(), headers=csrf_headers(api_client))

    assert response.status_code == 403


def test_approving_a_second_set_for_one_category_is_a_409(
    api_client: TestClient, db_session: Session
) -> None:
    """P08 §8.2b task 2: one ACTIVE baseline set per category (FR-72)."""
    make_baseline_set(db_session, slug="actions-orange-live")
    replacement = make_baseline_set(
        db_session, status=KBEntryStatus.PENDING_REVIEW, slug="actions-orange"
    )
    as_approver(api_client, db_session)

    response = api_client.post(
        f"{ENTRIES_URL}/{replacement.id}/approve", headers=csrf_headers(api_client)
    )

    assert response.status_code == 409
    assert "ORANGE" in response.json()["error"]["message"]


def test_retiring_a_baseline_set_answers_with_the_fallback_warning(
    api_client: TestClient, db_session: Session
) -> None:
    entry = make_baseline_set(db_session, category=VTLCategory.BLUE, slug="actions-blue")
    as_admin(api_client, db_session)

    response = api_client.post(f"{ENTRIES_URL}/{entry.id}/retire", headers=csrf_headers(api_client))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == KBEntryStatus.RETIRED.value
    assert "BLUE cases will show no baseline actions" in body["warning"]


def test_the_entry_list_can_be_filtered_to_baseline_sets(
    api_client: TestClient, db_session: Session
) -> None:
    """W-08's kind filter: the five sets have to be findable among the entries."""
    make_baseline_set(db_session, slug="actions-orange")
    make_kb_entry(db_session, status=KBEntryStatus.ACTIVE, slug="fixture-clinical")
    as_admin(api_client, db_session)

    body = api_client.get(f"{ENTRIES_URL}?kind={KBEntryKind.URGENCY_ACTIONS.value}").json()

    assert [item["slug"] for item in body["items"]] == ["actions-orange"]
    assert body["counts"][KBEntryStatus.ACTIVE.value] == 2


# --- Red-flag rule links (FR-49) -----------------------------------------


def test_an_entry_can_be_created_with_its_red_flag_rules(
    api_client: TestClient, db_session: Session
) -> None:
    ensure_complaint(db_session)
    make_red_flag_rule(db_session, code="FIXTURE_LINKED_RULE")
    as_admin(api_client, db_session)

    response = api_client.post(
        ENTRIES_URL,
        json=entry_body(red_flag_codes=["FIXTURE_LINKED_RULE"]),
        headers=csrf_headers(api_client),
    )

    assert response.status_code == 201
    assert response.json()["red_flag_codes"] == ["FIXTURE_LINKED_RULE"]


# --- The complaint list (FR-10, P08 §8.3) --------------------------------


def test_an_administrator_reads_the_complaint_list(
    api_client: TestClient, db_session: Session
) -> None:
    """The fixed list W-08's editor files an entry under, in `sort_order`."""
    db_session.add_all(
        [
            PresentingComplaint(code="SECOND_SIGN", name="Second fixture sign", sort_order=2),
            PresentingComplaint(code="FIRST_SIGN", name="First fixture sign", sort_order=1),
        ]
    )
    db_session.flush()
    as_admin(api_client, db_session)

    response = api_client.get(COMPLAINTS_URL)

    assert response.status_code == 200
    codes = [item["code"] for item in response.json()]
    assert codes.index("FIRST_SIGN") < codes.index("SECOND_SIGN")
    assert {"code": "FIRST_SIGN", "name": "First fixture sign"} in response.json()


def test_an_approver_reads_the_complaint_list(api_client: TestClient, db_session: Session) -> None:
    """An approver reads the catalogue, so the detail panel can name a complaint."""
    ensure_complaint(db_session)
    as_approver(api_client, db_session)

    response = api_client.get(COMPLAINTS_URL)

    assert response.status_code == 200
    assert [item["code"] for item in response.json()] == [COMPLAINT]


def test_intake_staff_cannot_read_the_complaint_list(
    api_client: TestClient, db_session: Session
) -> None:
    signed_in(api_client, db_session, UserRole.INTAKE_STAFF)

    assert api_client.get(COMPLAINTS_URL).status_code == 403
