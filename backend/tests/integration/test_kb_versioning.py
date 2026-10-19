"""Immutable published versions, end to end (FR-53, FR-54, DR-05, ADR-14).

This is the file that proves the four properties the phase is for:

1. approving an entry publishes a version containing exactly the ACTIVE entries;
2. retiring one publishes the next version, and the earlier one is unchanged;
3. a published version's entry list cannot be updated — the database refuses;
4. an indexing failure publishes nothing and leaves the entry awaiting review.

The approval runs through the real path: the endpoint enqueues a `KB_INDEX` job,
and `run_pending_jobs_once` drains the queue in this thread so the assertion
reads a finished run (ADR-08).
"""

import uuid
from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.jobs.worker import run_pending_jobs_once
from app.models import (
    JobStatus,
    KBChunk,
    KBEntryKind,
    KBEntryStatus,
    KBVersion,
    UserRole,
    VTLCategory,
    kb_version_entries,
)
from app.repositories.pipeline_repository import PipelineRepository
from tests.conftest import (
    baseline_actions_content,
    csrf_headers,
    kb_entry_content,
    make_kb_entry,
    make_kb_version,
    make_user,
    sign_in,
)

PASSWORD = "Sampaguita2026"
ENTRIES_URL = "/api/v1/kb/entries"
VERSIONS_URL = "/api/v1/kb/versions"


class _FailingIndexer:
    """Chunking that fails, as a missing embedding model would."""

    def index_entry(self, entry_id: uuid.UUID) -> int:
        raise RuntimeError("indexing is unavailable")

    def remove_entry(self, entry_id: uuid.UUID) -> None:
        return None


def as_approver(client: TestClient, session: Session):
    user = make_user(
        session,
        password=PASSWORD,
        role=UserRole.VETERINARY_REVIEWER,
        can_approve_kb=True,
        full_name="An Approver",
    )
    sign_in(client, user.email, PASSWORD)
    return user


def as_admin(client: TestClient, session: Session):
    user = make_user(session, password=PASSWORD, role=UserRole.ADMINISTRATOR)
    sign_in(client, user.email, PASSWORD)
    return user


def pending(session: Session, slug: str):
    return make_kb_entry(
        session,
        status=KBEntryStatus.PENDING_REVIEW,
        content=kb_entry_content(),
        with_source=True,
        slug=slug,
    )


def pending_baseline_set(session: Session, slug: str, category: VTLCategory):
    return make_kb_entry(
        session,
        kind=KBEntryKind.URGENCY_ACTIONS,
        complaint_code=None,
        urgency_category=category,
        status=KBEntryStatus.PENDING_REVIEW,
        title=f"Suggested staff actions - {category.value}",
        content=baseline_actions_content(),
        with_source=True,
        slug=slug,
    )


def version_count(session: Session) -> int:
    return session.scalars(select(func.count()).select_from(KBVersion)).one()


def approve(client: TestClient, entry_id: uuid.UUID):
    return client.post(f"{ENTRIES_URL}/{entry_id}/approve", headers=csrf_headers(client))


# --- Approval publishes a version ----------------------------------------


def test_approving_publishes_a_version_listing_the_active_entries(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    make_kb_entry(db_session, status=KBEntryStatus.ACTIVE, slug="fixture-already-active")
    draft = make_kb_entry(db_session, status=KBEntryStatus.DRAFT, slug="fixture-draft")
    entry = pending(db_session, "fixture-approved")
    as_approver(api_client, db_session)

    assert approve(api_client, entry.id).status_code == 202
    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    db_session.refresh(entry)
    assert entry.status is KBEntryStatus.ACTIVE
    versions = api_client.get(VERSIONS_URL).json()
    assert versions[0]["version_no"] == 1
    assert versions[0]["published_by_name"] == "An Approver"
    detail = api_client.get(f"{VERSIONS_URL}/{versions[0]['id']}").json()
    slugs = {item["slug"] for item in detail["entries"]}
    assert slugs == {"fixture-already-active", "fixture-approved"}
    assert draft.slug not in slugs
    assert detail["entry_count"] == 2


def test_the_published_version_shows_in_the_entry_list_header(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    """W-08's "Published version: vN" header (P08 §8.3 task 1)."""
    entry = pending(db_session, "fixture-header")
    as_approver(api_client, db_session)
    approve(api_client, entry.id)
    run_pending_jobs_once(app_session_factory, pipeline)

    assert api_client.get(ENTRIES_URL).json()["published_version_no"] == 1


def test_retiring_publishes_the_next_version_and_leaves_the_first_alone(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    """Verification step 4 of the P08 prompt."""
    entry = pending(db_session, "fixture-lifecycle")
    as_approver(api_client, db_session)
    approve(api_client, entry.id)
    run_pending_jobs_once(app_session_factory, pipeline)
    first = api_client.get(VERSIONS_URL).json()[0]
    first_detail = api_client.get(f"{VERSIONS_URL}/{first['id']}").json()

    as_admin(api_client, db_session)
    retired = api_client.post(f"{ENTRIES_URL}/{entry.id}/retire", headers=csrf_headers(api_client))

    assert retired.status_code == 200
    assert retired.json()["version_no"] == 2
    versions = api_client.get(VERSIONS_URL).json()
    assert [version["version_no"] for version in versions] == [2, 1]
    # Version 1 still lists the entry it contained, and still says who published
    # it and when. Its membership is frozen; what moves is the entry's own
    # status, which is live data and now reads RETIRED (ADR-14, DR-05).
    again = api_client.get(f"{VERSIONS_URL}/{first['id']}").json()
    assert {item["id"] for item in again["entries"]} == {
        item["id"] for item in first_detail["entries"]
    }
    assert again["entry_count"] == first_detail["entry_count"]
    assert again["published_at"] == first_detail["published_at"]
    assert [item["status"] for item in again["entries"]] == [KBEntryStatus.RETIRED.value]
    # And the new version contains nothing: the only active entry has just gone.
    assert api_client.get(f"{VERSIONS_URL}/{versions[0]['id']}").json()["entries"] == []


def test_a_version_number_is_never_reused(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    first = pending(db_session, "fixture-seq-1")
    second = pending(db_session, "fixture-seq-2")
    as_approver(api_client, db_session)

    approve(api_client, first.id)
    run_pending_jobs_once(app_session_factory, pipeline)
    approve(api_client, second.id)
    run_pending_jobs_once(app_session_factory, pipeline)

    assert [version["version_no"] for version in api_client.get(VERSIONS_URL).json()] == [2, 1]


# --- A published version is immutable (DR-05) ----------------------------


def test_a_published_versions_entry_list_cannot_be_updated(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    """The guarantee is a trigger, not service discipline (migration 0002)."""
    entry = pending(db_session, "fixture-immutable")
    as_approver(api_client, db_session)
    approve(api_client, entry.id)
    run_pending_jobs_once(app_session_factory, pipeline)
    version_id = api_client.get(VERSIONS_URL).json()[0]["id"]

    try:
        db_session.execute(
            text(
                "UPDATE kb_version_entries SET entry_id = entry_id "
                "WHERE kb_version_id = :version_id"
            ),
            {"version_id": version_id},
        )
    except Exception as error:  # noqa: BLE001 - the message is the assertion
        assert "append-only" in str(error)
    else:
        raise AssertionError("UPDATE on kb_version_entries was not rejected")
    finally:
        db_session.rollback()


# --- Indexing failure publishes nothing (FR-53) --------------------------


def test_an_indexing_failure_publishes_no_version(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    entry = pending(db_session, "fixture-index-failure")
    as_approver(api_client, db_session)
    db_session.commit()
    before = version_count(db_session)

    assert approve(api_client, entry.id).status_code == 202
    run_pending_jobs_once(app_session_factory, replace(pipeline, kb_indexer=_FailingIndexer()))

    db_session.refresh(entry)
    assert entry.status is KBEntryStatus.PENDING_REVIEW
    assert version_count(db_session) == before
    assert api_client.get(VERSIONS_URL).json() == []


def test_the_failure_is_reported_on_the_entry(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    """W-08's approver view shows indexing errors (P08 §8.3 task 4)."""
    entry = pending(db_session, "fixture-index-error-shown")
    as_approver(api_client, db_session)
    db_session.commit()
    approve(api_client, entry.id)
    run_pending_jobs_once(app_session_factory, replace(pipeline, kb_indexer=_FailingIndexer()))

    indexing = api_client.get(f"{ENTRIES_URL}/{entry.id}").json()["indexing"]

    assert indexing["status"] == "FAILED"
    assert indexing["error"].startswith("KB_INDEXING_FAILED")


# --- What the pipeline then uses (task 6, IR-14) -------------------------


def test_a_run_is_pinned_to_the_published_version(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    """Published wins over the seeded placeholder version 0 (P08 §8.1 task 6)."""
    seeded = make_kb_version(db_session, version_no=0)
    entry = pending(db_session, "fixture-pinned")
    as_approver(api_client, db_session)
    approve(api_client, entry.id)
    run_pending_jobs_once(app_session_factory, pipeline)

    published_id = uuid.UUID(api_client.get(VERSIONS_URL).json()[0]["id"])

    assert PipelineRepository(db_session).latest_kb_version_id() == published_id
    assert published_id != seeded.id


def test_with_nothing_published_a_run_falls_back_to_the_seeded_version(
    db_session: Session,
) -> None:
    """A clean checkout keeps triaging before the first approval."""
    seeded = make_kb_version(db_session, version_no=0)

    assert PipelineRepository(db_session).latest_kb_version_id() == seeded.id


def test_the_version_list_is_readable_by_an_administrator(
    api_client: TestClient, db_session: Session
) -> None:
    as_admin(api_client, db_session)

    assert api_client.get(VERSIONS_URL).status_code == 200


def test_intake_staff_cannot_read_the_versions(api_client: TestClient, db_session: Session) -> None:
    user = make_user(db_session, password=PASSWORD, role=UserRole.INTAKE_STAFF)
    sign_in(api_client, user.email, PASSWORD)

    assert api_client.get(VERSIONS_URL).status_code == 403


def test_an_unknown_version_is_404(api_client: TestClient, db_session: Session) -> None:
    as_admin(api_client, db_session)

    response = api_client.get(f"{VERSIONS_URL}/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404


def test_the_version_entries_table_is_only_ever_inserted_into(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    """Belt and braces for DR-05: the rows are there, and they are append-only."""
    entry = pending(db_session, "fixture-rows")
    as_approver(api_client, db_session)
    approve(api_client, entry.id)
    run_pending_jobs_once(app_session_factory, pipeline)

    rows = db_session.execute(select(kb_version_entries)).all()

    assert len(rows) == 1


# --- Urgency-action entries are versioned like any other (8.2b task 4) ----


def test_approving_a_baseline_set_publishes_a_version_that_lists_it(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    """A baseline action set is versioned with the content it is shown beside.

    Which is the whole reason ADR-18 put the baseline actions in the knowledge
    base rather than in a configuration file (BR-10).
    """
    clinical = make_kb_entry(db_session, status=KBEntryStatus.ACTIVE, slug="fixture-clinical")
    actions = pending_baseline_set(db_session, "actions-orange", VTLCategory.ORANGE)
    as_approver(api_client, db_session)

    assert approve(api_client, actions.id).status_code == 202
    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    db_session.refresh(actions)
    assert actions.status is KBEntryStatus.ACTIVE
    versions = api_client.get(VERSIONS_URL).json()
    detail = api_client.get(f"{VERSIONS_URL}/{versions[0]['id']}").json()
    listed = {item["slug"]: item["kind"] for item in detail["entries"]}
    assert listed == {
        clinical.slug: KBEntryKind.COMPLAINT.value,
        "actions-orange": KBEntryKind.URGENCY_ACTIONS.value,
    }


def test_an_approved_baseline_set_is_never_chunked(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline,
) -> None:
    """P08 §8.2b task 3: retrieval can never return an urgency-action chunk.

    Asserted on `kb_chunks`, which is what retrieval searches: with no row for
    the entry there is nothing for a similarity search to find, whether the
    retriever is the mock or the pgvector one M6 writes (ADR-18 §2).
    """
    actions = pending_baseline_set(db_session, "actions-red", VTLCategory.RED)
    as_approver(api_client, db_session)

    assert approve(api_client, actions.id).status_code == 202
    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    db_session.refresh(actions)
    assert actions.status is KBEntryStatus.ACTIVE
    chunks = db_session.scalars(select(KBChunk).where(KBChunk.entry_id == actions.id)).all()
    assert chunks == []
    detail = api_client.get(f"{ENTRIES_URL}/{actions.id}").json()
    assert detail["indexing"]["status"] == JobStatus.DONE.value
    assert detail["indexing"]["error"] is None
