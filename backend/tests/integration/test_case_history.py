"""`GET /cases?scope=history` — Case History search (FR-44, FR-45, FR-46, W-07).

What only a request can prove: that closed cases are in the list, that every
filter narrows it and combines with the others, that the AI category and the
final category come back side by side with the disagreement flagged, that pages
are stable, who may call it, and that the queue itself is unchanged.

Every pet and case here is invented (CLAUDE.md §9).
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    Case,
    CaseStatus,
    DecisionType,
    PresentingComplaint,
    Recommendation,
    Species,
    User,
    UserRole,
    VTLCategory,
    extraction_complaints,
)
from tests.conftest import (
    make_case,
    make_recommendation,
    make_staff_decision,
    make_user,
    sign_in,
)

CASES_URL = "/api/v1/cases"
COMPLAINTS_URL = "/api/v1/cases/complaints"
PASSWORD = "Sampaguita2026"
HISTORY = {"scope": "history"}


def signed_in(client: TestClient, session: Session, role: UserRole) -> User:
    user = make_user(session, password=PASSWORD, role=role)
    sign_in(client, user.email, PASSWORD)
    return user


@pytest.fixture
def reader(api_client: TestClient, db_session: Session) -> TestClient:
    signed_in(api_client, db_session, UserRole.VETERINARY_REVIEWER)
    return api_client


def history(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get(CASES_URL, params={**HISTORY, **params})
    assert response.status_code == 200, response.text
    return response.json()


def case_nos(client: TestClient, **params: Any) -> list[str]:
    return [item["case_no"] for item in history(client, **params)["items"]]


def triaged(
    session: Session,
    case_no: str,
    *,
    ai: VTLCategory | None = None,
    final: VTLCategory | None = None,
    decision_type: DecisionType = DecisionType.CONFIRM,
    **case_fields: Any,
) -> Case:
    """A case with the AI category and the reviewer's final one, either optional."""
    case = make_case(session, case_no=case_no, **case_fields)
    if ai is not None:
        make_recommendation(session, case=case, category=ai)
    if final is not None:
        make_staff_decision(session, case=case, final_category=final, decision_type=decision_type)
    return case


def with_complaints(
    session: Session, recommendation: Recommendation, *, primary: str, others: tuple[str, ...] = ()
) -> None:
    """File complaints against the extraction a recommendation was made from."""
    for code in (primary, *others):
        if session.get(PresentingComplaint, code) is None:
            session.add(PresentingComplaint(code=code, name=f"{code} name", sort_order=1))
    session.flush()
    for code in (primary, *others):
        session.execute(
            extraction_complaints.insert().values(
                extraction_id=recommendation.extraction_id,
                complaint_code=code,
                is_primary=code == primary,
            )
        )
    session.flush()


def latest_recommendation(session: Session, case: Case) -> Recommendation:
    return (
        session.query(Recommendation)
        .filter(Recommendation.case_id == case.id)
        .order_by(Recommendation.version.desc())
        .first()
    )


# --- Scope ----------------------------------------------------------------


def test_history_includes_closed_cases_and_the_queue_still_does_not(
    reader: TestClient, db_session: Session
) -> None:
    triaged(db_session, "C-H-OPN", ai=VTLCategory.GREEN, status=CaseStatus.AWAITING_REVIEW)
    triaged(
        db_session,
        "C-H-CLS",
        ai=VTLCategory.GREEN,
        final=VTLCategory.GREEN,
        status=CaseStatus.CLOSED,
        closed_at=datetime.now(UTC),
    )

    assert set(case_nos(reader)) == {"C-H-OPN", "C-H-CLS"}
    queue = reader.get(CASES_URL).json()
    assert [item["case_no"] for item in queue["items"]] == ["C-H-OPN"]
    assert "counts" in queue


def test_an_unknown_scope_is_refused(reader: TestClient) -> None:
    response = reader.get(CASES_URL, params={"scope": "archive"})

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "scope"


def test_a_history_only_filter_is_refused_on_the_queue(reader: TestClient) -> None:
    response = reader.get(CASES_URL, params={"disagreement": "true"})

    assert response.status_code == 422


def test_history_refuses_an_unknown_parameter(reader: TestClient) -> None:
    response = reader.get(CASES_URL, params={**HISTORY, "q": "Max"})

    assert response.status_code == 422


def test_history_is_newest_first(reader: TestClient, db_session: Session) -> None:
    author = make_user(db_session)
    for case_no, day in (("C-H-A", 1), ("C-H-C", 3), ("C-H-B", 2)):
        make_case(
            db_session,
            created_by=author,
            case_no=case_no,
            created_at=datetime(2026, 10, day, 6, 0, tzinfo=UTC),
        )

    assert case_nos(reader) == ["C-H-C", "C-H-B", "C-H-A"]


# --- Filters --------------------------------------------------------------


def test_case_number_matches_part_of_it_ignoring_case(
    reader: TestClient, db_session: Session
) -> None:
    make_case(db_session, case_no="C-0137")
    make_case(db_session, case_no="C-0138")

    assert case_nos(reader, case_no="0137") == ["C-0137"]
    assert set(case_nos(reader, case_no="c-013")) == {"C-0137", "C-0138"}


def test_case_number_treats_wildcards_as_text(reader: TestClient, db_session: Session) -> None:
    make_case(db_session, case_no="C-W_1")
    make_case(db_session, case_no="C-WX1")

    assert case_nos(reader, case_no="W_1") == ["C-W_1"]
    assert case_nos(reader, case_no="%") == []


def test_date_range_is_read_in_the_clinic_timezone(reader: TestClient, db_session: Session) -> None:
    author = make_user(db_session)
    # 16:30 UTC on the 10th is 00:30 on the 11th in Manila (UTC+8).
    make_case(
        db_session,
        created_by=author,
        case_no="C-D-11TH",
        created_at=datetime(2026, 10, 10, 16, 30, tzinfo=UTC),
    )
    make_case(
        db_session,
        created_by=author,
        case_no="C-D-10TH",
        created_at=datetime(2026, 10, 10, 15, 30, tzinfo=UTC),
    )

    assert case_nos(reader, date_from="2026-10-11", date_to="2026-10-11") == ["C-D-11TH"]
    assert case_nos(reader, date_from="2026-10-10", date_to="2026-10-10") == ["C-D-10TH"]
    assert case_nos(reader, date_from="2026-10-10", date_to="2026-10-11") == [
        "C-D-11TH",
        "C-D-10TH",
    ]


def test_an_end_date_before_the_start_date_is_refused_plainly(reader: TestClient) -> None:
    response = reader.get(
        CASES_URL, params={**HISTORY, "date_from": "2026-10-12", "date_to": "2026-10-11"}
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["field"] == "date_to"
    assert error["message"] == "The end date cannot be before the start date."


def test_species_status_and_the_two_categories_each_filter(
    reader: TestClient, db_session: Session
) -> None:
    triaged(
        db_session,
        "C-F-CAT",
        ai=VTLCategory.ORANGE,
        final=VTLCategory.RED,
        decision_type=DecisionType.ADJUST,
        species=Species.CAT,
        status=CaseStatus.ADJUSTED,
    )
    triaged(
        db_session,
        "C-F-DOG",
        ai=VTLCategory.GREEN,
        final=VTLCategory.GREEN,
        species=Species.DOG,
        status=CaseStatus.CONFIRMED,
    )

    assert case_nos(reader, species="CAT") == ["C-F-CAT"]
    assert case_nos(reader, status="CONFIRMED") == ["C-F-DOG"]
    assert case_nos(reader, ai_category="ORANGE") == ["C-F-CAT"]
    assert case_nos(reader, final_category="RED") == ["C-F-CAT"]
    assert case_nos(reader, ai_category="RED") == []


def test_complaint_matches_any_complaint_on_the_extraction(
    reader: TestClient, db_session: Session
) -> None:
    both = triaged(db_session, "C-C-TWO", ai=VTLCategory.YELLOW)
    with_complaints(
        db_session,
        latest_recommendation(db_session, both),
        primary="HIST_VOMITING",
        others=("HIST_LIMPING",),
    )
    one = triaged(db_session, "C-C-ONE", ai=VTLCategory.YELLOW)
    with_complaints(db_session, latest_recommendation(db_session, one), primary="HIST_COUGH")

    assert case_nos(reader, complaint_code="HIST_LIMPING") == ["C-C-TWO"]
    assert case_nos(reader, complaint_code="HIST_COUGH") == ["C-C-ONE"]

    items = {item["case_no"]: item for item in history(reader)["items"]}
    # The row shows the primary complaint, however the search found it.
    assert items["C-C-TWO"]["primary_complaint_code"] == "HIST_VOMITING"
    assert items["C-C-TWO"]["primary_complaint_name"] == "HIST_VOMITING name"


def test_filters_combine(reader: TestClient, db_session: Session) -> None:
    triaged(db_session, "C-M-1", ai=VTLCategory.RED, species=Species.CAT)
    triaged(db_session, "C-M-2", ai=VTLCategory.RED, species=Species.DOG)
    triaged(db_session, "C-M-3", ai=VTLCategory.BLUE, species=Species.CAT)

    assert case_nos(reader, species="CAT", ai_category="RED") == ["C-M-1"]


def test_blank_text_filters_are_ignored(reader: TestClient, db_session: Session) -> None:
    make_case(db_session, case_no="C-B-1")

    assert case_nos(reader, case_no="  ", complaint_code="") == ["C-B-1"]


# --- AI against final -----------------------------------------------------


def test_the_ai_and_final_categories_come_back_side_by_side(
    reader: TestClient, db_session: Session
) -> None:
    triaged(
        db_session,
        "C-S-ADJ",
        ai=VTLCategory.ORANGE,
        final=VTLCategory.RED,
        decision_type=DecisionType.ADJUST,
        status=CaseStatus.ADJUSTED,
    )

    (item,) = history(reader)["items"]

    assert item["ai_category"] == "ORANGE"
    assert item["final_category"] == "RED"
    assert item["decision_type"] == "ADJUST"
    assert item["is_disagreement"] is True


def test_disagreement_keeps_only_cases_where_ai_and_final_differ(
    reader: TestClient, db_session: Session
) -> None:
    triaged(
        db_session,
        "C-G-DIFF",
        ai=VTLCategory.YELLOW,
        final=VTLCategory.GREEN,
        decision_type=DecisionType.ADJUST,
    )
    triaged(db_session, "C-G-SAME", ai=VTLCategory.GREEN, final=VTLCategory.GREEN)
    triaged(db_session, "C-G-UNDEC", ai=VTLCategory.GREEN)
    # Triaged by hand: no AI category, so nothing to disagree with.
    triaged(
        db_session,
        "C-G-MANUAL",
        final=VTLCategory.YELLOW,
        decision_type=DecisionType.MANUAL,
        status=CaseStatus.MANUALLY_TRIAGED,
    )

    assert case_nos(reader, disagreement="true") == ["C-G-DIFF"]

    rows = {item["case_no"]: item for item in history(reader)["items"]}
    assert rows["C-G-DIFF"]["is_disagreement"] is True
    for matching in ("C-G-SAME", "C-G-UNDEC", "C-G-MANUAL"):
        assert rows[matching]["is_disagreement"] is False
    assert rows["C-G-MANUAL"]["ai_category"] is None
    assert rows["C-G-MANUAL"]["final_category"] == "YELLOW"


def test_disagreement_false_is_the_same_as_leaving_it_out(
    reader: TestClient, db_session: Session
) -> None:
    triaged(db_session, "C-G-SAME", ai=VTLCategory.GREEN, final=VTLCategory.GREEN)

    assert case_nos(reader, disagreement="false") == ["C-G-SAME"]


def test_the_ai_category_is_the_latest_recommendation_version(
    reader: TestClient, db_session: Session
) -> None:
    case = triaged(db_session, "C-V-2", ai=VTLCategory.YELLOW)
    make_recommendation(db_session, case=case, category=VTLCategory.RED, version=2)

    (item,) = history(reader)["items"]

    assert item["ai_category"] == "RED"
    assert case_nos(reader, ai_category="YELLOW") == []


def test_the_final_category_is_the_latest_decision(reader: TestClient, db_session: Session) -> None:
    case = triaged(db_session, "C-V-AMEND", ai=VTLCategory.YELLOW, final=VTLCategory.GREEN)
    amended = make_staff_decision(
        db_session,
        case=case,
        final_category=VTLCategory.ORANGE,
        decision_type=DecisionType.ADJUST,
        decided_at=datetime(2999, 1, 1, tzinfo=UTC),
    )

    (item,) = history(reader)["items"]

    assert amended.final_category is VTLCategory.ORANGE
    assert item["final_category"] == "ORANGE"


# --- Pagination -----------------------------------------------------------


def make_many(session: Session, count: int) -> None:
    author = make_user(session)
    for index in range(count):
        make_case(
            session,
            created_by=author,
            case_no=f"C-P-{index:03d}",
            created_at=datetime(2026, 9, 1, 0, index, tzinfo=UTC),
        )


def test_the_default_page_is_twenty_five_rows(reader: TestClient, db_session: Session) -> None:
    make_many(db_session, 30)

    body = history(reader)

    assert len(body["items"]) == 25
    assert (body["total"], body["page"], body["limit"]) == (30, 1, 25)


def test_pages_do_not_overlap_and_cover_everything(reader: TestClient, db_session: Session) -> None:
    make_many(db_session, 30)

    first = case_nos(reader, page=1, limit=10)
    second = case_nos(reader, page=2, limit=10)
    third = case_nos(reader, page=3, limit=10)
    beyond = history(reader, page=4, limit=10)

    assert len({*first, *second, *third}) == 30
    assert first[0] == "C-P-029" and third[-1] == "C-P-000"
    assert beyond["items"] == []
    assert beyond["total"] == 30


def test_the_total_follows_the_filters(reader: TestClient, db_session: Session) -> None:
    make_many(db_session, 12)

    body = history(reader, case_no="C-P-00", limit=5)

    assert body["total"] == 10
    assert len(body["items"]) == 5


@pytest.mark.parametrize(
    ("params", "field"),
    [({"page": 0}, "page"), ({"limit": 0}, "limit"), ({"limit": 9999}, "limit")],
)
def test_a_bad_page_is_refused_with_its_field(
    reader: TestClient, params: dict[str, int], field: str
) -> None:
    response = reader.get(CASES_URL, params={**HISTORY, **params})

    assert response.status_code == 422
    assert response.json()["error"]["field"] == field


# --- Access ---------------------------------------------------------------


@pytest.mark.parametrize(
    "role", [UserRole.INTAKE_STAFF, UserRole.VETERINARY_REVIEWER, UserRole.ADMINISTRATOR]
)
def test_every_role_can_read_history_and_the_complaint_list(
    api_client: TestClient, db_session: Session, role: UserRole
) -> None:
    signed_in(api_client, db_session, role)
    make_case(db_session, case_no="C-R-1")

    assert api_client.get(CASES_URL, params=HISTORY).status_code == 200
    assert api_client.get(COMPLAINTS_URL).status_code == 200


def test_history_needs_a_session(api_client: TestClient) -> None:
    assert api_client.get(CASES_URL, params=HISTORY).status_code == 401
    assert api_client.get(COMPLAINTS_URL).status_code == 401


def test_the_complaint_list_is_in_clinical_order(reader: TestClient, db_session: Session) -> None:
    db_session.add_all(
        [
            PresentingComplaint(code="ZZ_LAST", name="Zed", sort_order=900),
            PresentingComplaint(code="AA_FIRST", name="Aye", sort_order=-5),
        ]
    )
    db_session.flush()

    codes = [option["code"] for option in reader.get(COMPLAINTS_URL).json()]

    assert codes[0] == "AA_FIRST"
    assert codes[-1] == "ZZ_LAST"
    assert set(reader.get(COMPLAINTS_URL).json()[0]) == {"code", "name"}


def test_no_history_row_carries_an_owner_reference(reader: TestClient, db_session: Session) -> None:
    triaged(db_session, "C-O-1", ai=VTLCategory.GREEN, final=VTLCategory.GREEN)

    (item,) = history(reader)["items"]

    assert not {"owner_name", "contact_number", "owner"} & set(item)
