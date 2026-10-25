"""`/exports`: de-identified case and audit exports (P09 §9.4, FR-47, BR-05, BR-08, SR-12, SR-17).

All data is fictitious (CLAUDE.md §9). The strings planted in the free-text and
identity fields are distinctive so that "nowhere in the body" is a meaningful
assertion.
"""

import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ActionSource,
    ActionStatus,
    ActionSuggestion,
    AdjustReason,
    AuditEntry,
    DecisionDirection,
    DecisionType,
    FinalAction,
    OwnerReference,
    Recommendation,
    User,
    UserRole,
    VTLCategory,
)
from app.services.audit_service import AuditAction, AuditService
from app.services.export_format import AUDIT_COLUMNS, CASE_COLUMNS
from tests.conftest import (
    make_case,
    make_clinical_note,
    make_owner_description,
    make_recommendation,
    make_staff_decision,
    make_user,
    sign_in,
)

PASSWORD = "Sampaguita2026"
EXPORTS = "/api/v1/exports"

OWNER_NAME = "Zzyzx Fictional-Owner"
PET_NAME = "Qwertyuiop"
NOTE_TEXT = "Distinctive clinical note text."
ACTION_TEXT = "Distinctive suggested action wording."
REASON_TEXT = "Distinctive reviewer reason wording."


def signed_in(client: TestClient, session: Session, role: UserRole, **kwargs: object) -> User:
    user = make_user(session, password=PASSWORD, role=role, **kwargs)
    sign_in(client, user.email, PASSWORD)
    return user


def as_admin(client: TestClient, session: Session) -> User:
    return signed_in(client, session, UserRole.ADMINISTRATOR)


def rows_of(body: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(body)))


def export_entries(session: Session) -> list[AuditEntry]:
    return list(
        session.execute(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.DATA_EXPORTED)
            .order_by(AuditEntry.id)
        ).scalars()
    )


def add_suggestion(
    session: Session,
    *,
    recommendation: Recommendation,
    source: ActionSource,
    generation: int = 1,
    rank: int = 1,
) -> ActionSuggestion:
    suggestion = ActionSuggestion(
        case_id=recommendation.case_id,
        recommendation_id=recommendation.id,
        generated_for_category=recommendation.category,
        rank=rank,
        text=ACTION_TEXT,
        source=source,
        model_id="mock",
        prompt_version="mock-0",
        generation=generation,
    )
    session.add(suggestion)
    session.flush()
    return suggestion


def add_final_action(
    session: Session, *, decision_id: uuid.UUID, case_id: uuid.UUID, status: ActionStatus, rank: int
) -> None:
    author = make_user(session, role=UserRole.VETERINARY_REVIEWER)
    session.add(
        FinalAction(
            case_id=case_id,
            decision_id=decision_id,
            rank=rank,
            text=ACTION_TEXT,
            source=ActionSource.BASELINE,
            status=status,
            finalized_by=author.id,
            finalized_at=datetime.now(UTC),
        )
    )
    session.flush()


@pytest.fixture
def decided_case(db_session: Session) -> dict[str, object]:
    """A case with every free-text and identity field filled, adjusted upward."""
    intake = make_user(db_session, full_name=OWNER_NAME)
    created = datetime(2026, 3, 1, 1, 0, tzinfo=UTC)
    case = make_case(
        db_session,
        created_by=intake,
        case_no="C-7001",
        created_at=created,
        pet_name=PET_NAME,
    )
    make_owner_description(db_session, case=case)
    db_session.add(OwnerReference(case_id=case.id, owner_name=OWNER_NAME, contact_number="0917000"))
    db_session.flush()
    make_clinical_note(db_session, case=case, text=NOTE_TEXT)

    recommendation = make_recommendation(
        db_session,
        case=case,
        category=VTLCategory.ORANGE,
        created_at=created + timedelta(seconds=40),
    )
    recommendation.safety_floor_applied = True
    recommendation.actions_rejected_count = 2
    # Two generations: only the newest set counts as shown.
    add_suggestion(db_session, recommendation=recommendation, source=ActionSource.BASELINE)
    add_suggestion(
        db_session, recommendation=recommendation, source=ActionSource.AI, rank=2, generation=1
    )
    for rank in (1, 2, 3):
        add_suggestion(
            db_session,
            recommendation=recommendation,
            source=ActionSource.BASELINE,
            generation=2,
            rank=rank,
        )
    for rank in (4, 5):
        add_suggestion(
            db_session,
            recommendation=recommendation,
            source=ActionSource.AI,
            generation=2,
            rank=rank,
        )

    reviewer = make_user(db_session, role=UserRole.VETERINARY_REVIEWER, full_name=OWNER_NAME)
    decision = make_staff_decision(
        db_session,
        case=case,
        final_category=VTLCategory.RED,
        decision_type=DecisionType.ADJUST,
        direction=DecisionDirection.UP,
        decided_by=reviewer,
        decided_at=created + timedelta(seconds=340),
        reason_code=AdjustReason.OTHER,
    )
    decision.reason_text = REASON_TEXT
    for rank, status in enumerate(
        (
            ActionStatus.KEPT,
            ActionStatus.KEPT,
            ActionStatus.EDITED,
            ActionStatus.REMOVED,
            ActionStatus.ADDED,
        ),
        start=1,
    ):
        add_final_action(
            db_session, decision_id=decision.id, case_id=case.id, status=status, rank=rank
        )
    return {"case": case, "reviewer": reviewer}


# --- Cases ----------------------------------------------------------------


def test_cases_export_header_is_exactly_the_whitelist(
    api_client: TestClient, db_session: Session, decided_case: dict[str, object]
) -> None:
    as_admin(api_client, db_session)

    response = api_client.get(f"{EXPORTS}/cases")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    header = next(csv.reader(io.StringIO(response.text)))
    assert tuple(header) == CASE_COLUMNS


def test_cases_export_contains_no_personal_or_free_text(
    api_client: TestClient, db_session: Session, decided_case: dict[str, object]
) -> None:
    admin = as_admin(api_client, db_session)
    reviewer = decided_case["reviewer"]
    assert isinstance(reviewer, User)

    body = api_client.get(f"{EXPORTS}/cases").text

    for secret in (
        OWNER_NAME,
        PET_NAME,
        NOTE_TEXT,
        ACTION_TEXT,
        REASON_TEXT,
        "0917000",
        "limping",  # the owner description's text
        "Fixture recommendation.",  # the rationale
        reviewer.email,
        admin.email,
        str(reviewer.id),
        str(admin.id),
    ):
        assert secret not in body


def test_cases_export_row_values_and_action_counts(
    api_client: TestClient, db_session: Session, decided_case: dict[str, object]
) -> None:
    as_admin(api_client, db_session)

    (row,) = rows_of(api_client.get(f"{EXPORTS}/cases").text)

    assert row["case_no"] == "C-7001"
    assert row["species"] == "DOG"
    assert row["created_at"].startswith("2026-03-01T01:00:00")
    assert (row["ai_category"], row["ai_confidence"]) == ("ORANGE", "MEDIUM")
    assert row["safety_floor_applied"] == "true"
    assert (row["final_category"], row["decision_type"], row["direction"]) == (
        "RED",
        "ADJUST",
        "UP",
    )
    assert row["reason_code"] == "OTHER"
    assert row["seconds_submission_to_recommendation"] == "40"
    assert row["seconds_recommendation_to_decision"] == "300"
    # Generation 2 is the newest set; generation 1's rows do not count.
    assert row["actions_baseline_shown"] == "3"
    assert row["actions_tailored_suggested"] == "2"
    assert row["actions_tailored_rejected"] == "2"
    assert row["actions_final_kept"] == "2"
    assert row["actions_final_edited"] == "1"
    assert row["actions_final_removed"] == "1"
    assert row["actions_final_added"] == "1"


def test_an_undecided_case_has_blank_ai_and_final_columns(
    api_client: TestClient, db_session: Session
) -> None:
    make_case(db_session, case_no="C-7002")
    as_admin(api_client, db_session)

    (row,) = rows_of(api_client.get(f"{EXPORTS}/cases").text)

    assert row["case_no"] == "C-7002"
    assert row["ai_category"] == ""
    assert row["final_category"] == ""
    assert row["actions_baseline_shown"] == ""
    assert row["actions_final_kept"] == ""


def test_the_final_columns_follow_the_latest_decision(
    api_client: TestClient, db_session: Session
) -> None:
    case = make_case(db_session, case_no="C-7003")
    make_recommendation(db_session, case=case, category=VTLCategory.YELLOW)
    first = make_staff_decision(
        db_session,
        case=case,
        final_category=VTLCategory.YELLOW,
        decided_at=datetime(2026, 3, 1, 3, 0, tzinfo=UTC),
    )
    make_staff_decision(
        db_session,
        case=case,
        final_category=VTLCategory.ORANGE,
        decision_type=DecisionType.ADJUST,
        direction=DecisionDirection.UP,
        decided_at=datetime(2026, 3, 1, 4, 0, tzinfo=UTC),
        amends_id=first.id,
    )
    as_admin(api_client, db_session)

    (row,) = rows_of(api_client.get(f"{EXPORTS}/cases").text)

    assert (row["final_category"], row["decision_type"]) == ("ORANGE", "ADJUST")


def test_cases_date_range_is_inclusive_manila_days(
    api_client: TestClient, db_session: Session
) -> None:
    # 2026-03-01 00:30 Manila is 2026-02-28 16:30 UTC: a Manila-day filter keeps
    # it on March 1st, a UTC-day filter would put it on February 28th.
    make_case(db_session, case_no="C-0001", created_at=datetime(2026, 2, 28, 16, 30, tzinfo=UTC))
    # 2026-03-01 23:30 Manila is 15:30 UTC the same day.
    make_case(db_session, case_no="C-0002", created_at=datetime(2026, 3, 1, 15, 30, tzinfo=UTC))
    # 2026-03-02 00:30 Manila.
    make_case(
        db_session,
        case_no="C-0003",
        created_at=datetime(2026, 2, 28, 16, 30, tzinfo=UTC) + timedelta(days=1),
    )
    as_admin(api_client, db_session)

    on_the_first = rows_of(api_client.get(f"{EXPORTS}/cases?from=2026-03-01&to=2026-03-01").text)
    from_the_second = rows_of(api_client.get(f"{EXPORTS}/cases?from=2026-03-02").text)
    to_the_first = rows_of(api_client.get(f"{EXPORTS}/cases?to=2026-03-01").text)

    assert [r["case_no"] for r in on_the_first] == ["C-0001", "C-0002"]
    assert [r["case_no"] for r in from_the_second] == ["C-0003"]
    assert [r["case_no"] for r in to_the_first] == ["C-0001", "C-0002"]


def test_cases_export_writes_one_audit_entry_without_content(
    api_client: TestClient, db_session: Session, decided_case: dict[str, object]
) -> None:
    admin = as_admin(api_client, db_session)

    api_client.get(f"{EXPORTS}/cases?from=2026-03-01&to=2026-03-02")

    (entry,) = export_entries(db_session)
    assert entry.user_id == admin.id
    assert entry.role is UserRole.ADMINISTRATOR
    assert (entry.entity_type, entry.entity_id) == ("export", "cases")
    assert entry.after == {
        "from": "2026-03-01",
        "to": "2026-03-02",
        "format": "csv",
        "row_count": 1,
    }
    assert "C-7001" not in json.dumps(entry.after)


# --- Audit ----------------------------------------------------------------


def test_audit_export_has_no_user_ids_or_addresses(
    api_client: TestClient, db_session: Session
) -> None:
    admin = as_admin(api_client, db_session)
    target = make_user(db_session, role=UserRole.INTAKE_STAFF)
    audit = AuditService(db_session)
    audit.record(
        action=AuditAction.USER_UPDATED,
        entity_type="user",
        entity_id=str(target.id),
        user_id=admin.id,
        role=admin.role,
        before={"role": "INTAKE_STAFF"},
        after={"role": "INTAKE_STAFF", "is_active": False},
    )
    audit.record(
        action=AuditAction.LOGIN_FAILURE,
        entity_type="user",
        entity_id="unknown",
        after={"email": "stranger@example.invalid", "reason": "no_such_account"},
    )

    response = api_client.get(f"{EXPORTS}/audit")

    assert response.status_code == 200
    header = next(csv.reader(io.StringIO(response.text)))
    assert tuple(header) == AUDIT_COLUMNS
    for secret in (str(admin.id), str(target.id), admin.email, target.email, "stranger@"):
        assert secret not in response.text
    updated = next(r for r in rows_of(response.text) if r["action"] == "USER_UPDATED")
    assert updated["actor_role"] == "ADMINISTRATOR"
    assert updated["actor_pseudonym"].startswith("ADMIN-")
    assert updated["entity_id"].startswith("INTAKE-")
    assert json.loads(updated["before"]) == {"role": "INTAKE_STAFF"}
    assert json.loads(updated["after"]) == {"role": "INTAKE_STAFF", "is_active": False}


def test_audit_pseudonyms_are_stable_within_one_export(
    api_client: TestClient, db_session: Session
) -> None:
    as_admin(api_client, db_session)
    first = make_user(db_session, role=UserRole.VETERINARY_REVIEWER)
    second = make_user(db_session, role=UserRole.VETERINARY_REVIEWER)
    audit = AuditService(db_session)
    for actor in (first, second, first, first):
        audit.record(
            action=AuditAction.NOTE_ADDED,
            entity_type="case",
            entity_id=str(uuid.uuid4()),
            user_id=actor.id,
            role=actor.role,
        )

    notes = [
        r for r in rows_of(api_client.get(f"{EXPORTS}/audit").text) if r["action"] == "NOTE_ADDED"
    ]

    assert [r["actor_pseudonym"] for r in notes] == [
        "REVIEWER-1",
        "REVIEWER-2",
        "REVIEWER-1",
        "REVIEWER-1",
    ]


def test_audit_date_range_filters_on_the_timestamp(
    api_client: TestClient, db_session: Session
) -> None:
    as_admin(api_client, db_session)
    old = AuditEntry(
        ts=datetime(2026, 1, 5, 4, 0, tzinfo=UTC),
        action="CASE_CREATED",
        entity_type="case",
        entity_id="old-case",
    )
    db_session.add(old)
    db_session.flush()

    january = rows_of(api_client.get(f"{EXPORTS}/audit?from=2026-01-01&to=2026-01-31").text)
    after_january = rows_of(api_client.get(f"{EXPORTS}/audit?from=2026-02-01").text)

    assert [r["entity_id"] for r in january] == ["old-case"]
    assert "old-case" not in {r["entity_id"] for r in after_january}


def test_audit_export_writes_an_audit_entry_that_is_not_in_its_own_file(
    api_client: TestClient, db_session: Session
) -> None:
    admin = as_admin(api_client, db_session)

    response = api_client.get(f"{EXPORTS}/audit")

    (entry,) = export_entries(db_session)
    assert (entry.user_id, entry.entity_id) == (admin.id, "audit")
    assert entry.after is not None
    assert entry.after["format"] == "csv"
    assert entry.after["row_count"] == len(rows_of(response.text))
    assert "DATA_EXPORTED" not in response.text


# --- Access and validation ------------------------------------------------


@pytest.mark.parametrize("path", ["cases", "audit"])
def test_exports_require_a_session(api_client: TestClient, path: str) -> None:
    assert api_client.get(f"{EXPORTS}/{path}").status_code == 401


@pytest.mark.parametrize("path", ["cases", "audit"])
@pytest.mark.parametrize(
    ("role", "kwargs"),
    [
        (UserRole.INTAKE_STAFF, {}),
        (UserRole.VETERINARY_REVIEWER, {}),
        (UserRole.VETERINARY_REVIEWER, {"can_approve_kb": True}),
    ],
)
def test_only_an_administrator_can_export(
    api_client: TestClient,
    db_session: Session,
    path: str,
    role: UserRole,
    kwargs: dict[str, object],
) -> None:
    signed_in(api_client, db_session, role, **kwargs)

    response = api_client.get(f"{EXPORTS}/{path}")

    assert response.status_code == 403
    assert export_entries(db_session) == []


@pytest.mark.parametrize("path", ["cases", "audit"])
@pytest.mark.parametrize(
    "query", ["from=2026-03-05&to=2026-03-01", "from=yesterday", "to=2026-13-40"]
)
def test_a_bad_range_is_422_and_is_not_audited(
    api_client: TestClient, db_session: Session, path: str, query: str
) -> None:
    as_admin(api_client, db_session)

    response = api_client.get(f"{EXPORTS}/{path}?{query}")

    assert response.status_code == 422
    assert export_entries(db_session) == []


def test_a_start_after_the_end_names_the_field(api_client: TestClient, db_session: Session) -> None:
    as_admin(api_client, db_session)

    response = api_client.get(f"{EXPORTS}/cases?from=2026-03-05&to=2026-03-01")

    assert response.json()["error"]["field"] == "to"


def test_only_csv_is_offered(api_client: TestClient, db_session: Session) -> None:
    as_admin(api_client, db_session)

    assert api_client.get(f"{EXPORTS}/cases?format=json").status_code == 422
