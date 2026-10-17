"""`GET /cases/{id}` as the Case Review screen reads it (FR-13, FR-31, FR-12).

Driven through a real mocked pipeline run rather than hand-built rows, because
the point of most of these assertions is that what the pipeline stored and what
the review screen reports are the same thing — the evidence spans in particular,
which are only substrings of the stored de-identified text if the whole path
from de-identification to read-back agrees.

Every pet, owner and description is invented (CLAUDE.md §9).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.jobs.worker import run_pending_jobs_once
from app.models import (
    Case,
    CaseStatus,
    ExtractionResult,
    RedFlagAlert,
    User,
    UserRole,
    VTLCategory,
)
from scripts.seed import seed
from tests.conftest import (
    make_clinical_note,
    make_demo_case,
    make_staff_decision,
    make_user,
    sign_in,
)

CASES_URL = "/api/v1/cases"
PASSWORD = "Sampaguita2026"

OWNER_NAME = "R. Bituin"
CONTACT_NUMBER = "0917-000-0000"


def signed_in(client: TestClient, session: Session, role: UserRole) -> User:
    user = make_user(session, password=PASSWORD, role=role)
    sign_in(client, user.email, PASSWORD)
    return user


@pytest.fixture
def reviewer_client(api_client: TestClient, db_session: Session) -> TestClient:
    signed_in(api_client, db_session, UserRole.VETERINARY_REVIEWER)
    return api_client


@pytest.fixture
def demo_case(db_session: Session, pipeline, app_session_factory: sessionmaker) -> Case:
    """`DEMO_1` run to completion: ORANGE with the safety floor applied.

    The run is driven directly rather than through intake, as the other
    pipeline tests do: `pipeline.run` for the triage, then one worker pass for
    the `SUGGEST_ACTIONS` job it enqueues (ADR-08).

    The owner reference is set so the de-identification path is exercised and
    the FR-07 assertion below has something to fail on.
    """
    seed(db_session)
    db_session.flush()
    case = make_demo_case(
        db_session, "DEMO_1", owner_name=OWNER_NAME, contact_number=CONTACT_NUMBER
    )
    pipeline.run(case.id)
    run_pending_jobs_once(app_session_factory, pipeline)
    return case


def read(client: TestClient, case: Case) -> Any:
    return client.get(f"{CASES_URL}/{case.id}")


# --- The whole payload ----------------------------------------------------


def test_the_review_response_carries_every_section_w04_shows(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    """FR-31: description, extracted information, category with its target time,
    rationale, confidence and references, plus the decision bar's inputs."""
    body = read(reviewer_client, demo_case).json()

    assert {
        "header",
        "description",
        "extraction",
        "recommendation",
        "references",
        "configuration",
        "alerts",
        "decision",
        "notes",
        "permissions",
        "actions",
    } <= set(body)


def test_the_header_identifies_the_patient_and_the_wait(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    header = read(reviewer_client, demo_case).json()["header"]

    assert header["case_no"] == demo_case.case_no
    assert header["species"] == "CAT"
    assert header["pet_name"] == "Miso"
    assert header["sex"] == "MALE"
    assert header["intake_channel"] == "WALK_IN"
    assert header["created_by_name"] is not None
    assert header["closed_at"] is None
    # ORANGE's target, carried so the header never shows a wait with no yardstick.
    assert header["target_minutes"] == 15
    assert header["waiting_minutes"] >= 0


def test_the_recommendation_is_orange_with_its_target_and_safety_floor(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    """DEMO_1's draft is YELLOW and the red flag raises it to ORANGE (FR-23)."""
    recommendation = read(reviewer_client, demo_case).json()["recommendation"]

    assert recommendation["category"] == VTLCategory.ORANGE.value
    assert recommendation["target_minutes"] == 15
    assert recommendation["safety_floor_applied"] is True
    assert recommendation["rationale"]
    assert recommendation["confidence"] in {"HIGH", "MEDIUM", "LOW"}


def test_the_safety_floor_names_the_rule_in_words(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    """IR-03: W-04 says which red flag raised the category, and
    `MALE_CAT_NO_URINE` is not a sentence."""
    rules = read(reviewer_client, demo_case).json()["recommendation"]["safety_floor_rules"]

    assert [rule["code"] for rule in rules] == ["MALE_CAT_NO_URINE"]
    assert rules[0]["label"]
    assert rules[0]["label"] != rules[0]["code"]


def test_the_references_are_ranked_and_say_which_were_cited(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    """FR-22: only ranks the validator kept are marked cited."""
    references = read(reviewer_client, demo_case).json()["references"]

    assert references
    assert [reference["rank"] for reference in references] == list(range(1, len(references) + 1))
    assert any(reference["is_cited"] for reference in references)
    for reference in references:
        assert reference["entry_title"]
        assert reference["passage_text"]


def test_the_configuration_footnote_records_what_produced_the_answer(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    """FR-26, NFR-23: the provenance a re-run would have to match."""
    configuration = read(reviewer_client, demo_case).json()["configuration"]

    assert configuration["model_id"] == "mock"
    assert configuration["prompt_version"] == "mock-0"
    # Seeded as version 0, and 0 is a real version number, not "absent".
    assert configuration["kb_version_no"] == 0
    assert configuration["generated_at"]


def test_the_extraction_is_reported_with_its_complaints_and_questions(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    """Panel 2, including "Ask the owner" (missing information)."""
    extraction = read(reviewer_client, demo_case).json()["extraction"]

    assert extraction["version"] == 1
    assert extraction["is_corrected"] is False
    assert extraction["species"] == "CAT"
    primary = [c for c in extraction["presenting_complaints"] if c["is_primary"]]
    assert len(primary) == 1
    assert primary[0]["name"]
    assert extraction["red_flags"]
    assert extraction["missing_information"]


# --- Evidence spans (FR-13) -----------------------------------------------


def test_evidence_offsets_slice_the_de_identified_text_back_out(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    """The property W-04 depends on: a `<mark>` placed at these offsets wraps
    exactly the quoted evidence."""
    body = read(reviewer_client, demo_case).json()
    text = body["description"]["deidentified_text"]
    spans = body["extraction"]["evidence_spans"]

    assert text is not None
    assert spans, "DEMO_1 records evidence spans"
    for span in spans:
        assert span["found"] is True
        assert text[span["start"] : span["end"]] == span["text"]


def test_the_de_identified_text_the_run_used_is_the_text_that_is_returned(
    reviewer_client: TestClient, demo_case: Case, db_session: Session
) -> None:
    """ADR-10: `input_text` is what the stages were given, stored by the run."""
    stored = db_session.scalars(
        select(ExtractionResult.input_text).where(ExtractionResult.case_id == demo_case.id)
    ).one()
    body = read(reviewer_client, demo_case).json()

    assert stored is not None
    assert body["description"]["deidentified_text"] == stored


def test_a_span_that_does_not_match_comes_back_marked_rather_than_dropped(
    reviewer_client: TestClient, demo_case: Case, db_session: Session
) -> None:
    """A stored span the text no longer contains is still reported, so the
    panel can show the evidence as text instead of silently showing less."""
    extraction = db_session.scalars(
        select(ExtractionResult).where(ExtractionResult.case_id == demo_case.id)
    ).one()
    entities = dict(extraction.entities)
    entities["evidence_spans"] = [
        *entities.get("evidence_spans", []),
        {"field": "relevant_history", "text": "ate rat poison last week"},
    ]
    extraction.entities = entities
    db_session.flush()

    spans = read(reviewer_client, demo_case).json()["extraction"]["evidence_spans"]

    missing = [span for span in spans if span["field"] == "relevant_history"]
    assert len(missing) == 1
    assert missing[0]["found"] is False
    assert missing[0]["start"] is None
    assert missing[0]["text"] == "ate rat poison last week"


def test_an_extraction_with_no_stored_text_reports_no_highlights(
    reviewer_client: TestClient, demo_case: Case, db_session: Session
) -> None:
    """An extraction written before migration 0004. There is nothing to search,
    so every span is unfound rather than guessed at."""
    extraction = db_session.scalars(
        select(ExtractionResult).where(ExtractionResult.case_id == demo_case.id)
    ).one()
    extraction.input_text = None
    db_session.flush()

    body = read(reviewer_client, demo_case).json()

    assert body["description"]["deidentified_text"] is None
    assert body["description"]["differs"] is False
    assert all(span["found"] is False for span in body["extraction"]["evidence_spans"])


def test_the_verbatim_description_is_returned_as_submitted(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    """FR-05: panel 1 shows what the owner said, never a cleaned-up version."""
    description = read(reviewer_client, demo_case).json()["description"]

    assert description["text"]
    assert "litter box" in description["text"]


# --- Red-flag alerts and acknowledgement (FR-12) --------------------------


def test_the_alerts_carry_the_rule_label_and_not_the_matched_text(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    """`matched_text` is a substring of the owner's description; the screen
    needs the clinic's label (CLAUDE.md §9, DR-04)."""
    alerts = read(reviewer_client, demo_case).json()["alerts"]

    assert [alert["rule_code"] for alert in alerts] == ["MALE_CAT_NO_URINE"]
    assert alerts[0]["rule_label"]
    assert alerts[0]["min_category"] == VTLCategory.ORANGE.value
    assert "matched_text" not in alerts[0]


def test_opening_the_case_as_a_reviewer_acknowledges_its_alerts(
    reviewer_client: TestClient, demo_case: Case, db_session: Session
) -> None:
    """P06 §6.1 task 2: this is what clears the W-02 banner."""
    before = db_session.scalars(
        select(RedFlagAlert.acknowledged_at).where(RedFlagAlert.case_id == demo_case.id)
    ).all()
    assert all(value is None for value in before)

    body = read(reviewer_client, demo_case).json()

    after = db_session.scalars(
        select(RedFlagAlert.acknowledged_at).where(RedFlagAlert.case_id == demo_case.id)
    ).all()
    assert after and all(value is not None for value in after)
    assert all(alert["acknowledged_at"] is not None for alert in body["alerts"])


def test_the_banner_clears_once_a_reviewer_has_opened_the_case(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    """The queue's `red_flag_alerts` is the banner, and it lists only
    unacknowledged alerts."""
    before = reviewer_client.get(CASES_URL).json()["red_flag_alerts"]
    assert any(alert["case_no"] == demo_case.case_no for alert in before)

    read(reviewer_client, demo_case)

    after = reviewer_client.get(CASES_URL).json()["red_flag_alerts"]
    assert all(alert["case_no"] != demo_case.case_no for alert in after)


def test_acknowledgement_keeps_the_first_reviewer_s_timestamp(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    """It records when the alert was first seen, not the most recent page load."""
    first = read(reviewer_client, demo_case).json()["alerts"][0]["acknowledged_at"]
    second = read(reviewer_client, demo_case).json()["alerts"][0]["acknowledged_at"]

    assert first == second


@pytest.mark.parametrize("role", [UserRole.INTAKE_STAFF, UserRole.ADMINISTRATOR])
def test_a_read_by_anyone_else_acknowledges_nothing(
    api_client: TestClient,
    db_session: Session,
    demo_case: Case,
    role: UserRole,
) -> None:
    """Neither is the person the alert escalates to, so neither read means the
    alert has been seen (BR-02)."""
    signed_in(api_client, db_session, role)

    body = api_client.get(f"{CASES_URL}/{demo_case.id}").json()

    assert all(alert["acknowledged_at"] is None for alert in body["alerts"])
    still_unacknowledged = db_session.scalars(
        select(RedFlagAlert.acknowledged_at).where(RedFlagAlert.case_id == demo_case.id)
    ).all()
    assert all(value is None for value in still_unacknowledged)


# --- Decision, notes and permissions --------------------------------------


def test_an_undecided_case_reports_no_decision(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    """IR-04: until there is a decision, the category is the AI's and is
    labelled as pending."""
    body = read(reviewer_client, demo_case).json()

    assert body["decision"] is None
    assert body["status"] == CaseStatus.AWAITING_REVIEW.value
    assert body["confirmed_category"] is None


def test_a_decided_case_reports_the_decision_with_who_made_it(
    reviewer_client: TestClient, demo_case: Case, db_session: Session
) -> None:
    make_staff_decision(db_session, case=demo_case, final_category=VTLCategory.RED)
    db_session.flush()

    decision = read(reviewer_client, demo_case).json()["decision"]

    assert decision["final_category"] == VTLCategory.RED.value
    assert decision["target_minutes"] == 0
    assert decision["decided_by_name"] is not None
    assert decision["decided_at"]


def test_notes_are_returned_oldest_first_with_their_authors(
    reviewer_client: TestClient, demo_case: Case, db_session: Session
) -> None:
    earlier = datetime.now(UTC) - timedelta(minutes=5)
    make_clinical_note(db_session, case=demo_case, text="First observation.", created_at=earlier)
    make_clinical_note(
        db_session,
        case=demo_case,
        text="Second observation.",
        created_at=earlier + timedelta(minutes=1),
    )
    db_session.flush()

    notes = read(reviewer_client, demo_case).json()["notes"]

    assert [note["text"] for note in notes] == [
        "First observation.",
        "Second observation.",
    ]
    assert all(note["author_name"] for note in notes)


def test_a_reviewer_may_decide_but_not_regenerate_or_close_yet(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    """`can_regenerate` is false until P07; `can_close` needs a decision."""
    permissions = read(reviewer_client, demo_case).json()["permissions"]

    assert permissions == {
        "can_decide": True,
        "can_regenerate": False,
        "can_close": False,
    }


def test_closing_becomes_available_once_the_case_is_decided(
    reviewer_client: TestClient, demo_case: Case, db_session: Session
) -> None:
    make_staff_decision(db_session, case=demo_case, final_category=VTLCategory.ORANGE)
    demo_case.status = CaseStatus.CONFIRMED
    db_session.flush()

    permissions = read(reviewer_client, demo_case).json()["permissions"]

    assert permissions["can_close"] is True
    # Still true: an amendment is a decision a reviewer may still record (FR-48).
    assert permissions["can_decide"] is True


@pytest.mark.parametrize("role", [UserRole.INTAKE_STAFF, UserRole.ADMINISTRATOR])
def test_only_a_reviewer_is_told_they_may_decide(
    api_client: TestClient, db_session: Session, demo_case: Case, role: UserRole
) -> None:
    """BR-02: W-04 is read-only for everyone else."""
    signed_in(api_client, db_session, role)

    permissions = api_client.get(f"{CASES_URL}/{demo_case.id}").json()["permissions"]

    assert permissions["can_decide"] is False
    assert permissions["can_close"] is False


# --- Privacy and access ---------------------------------------------------


def test_no_owner_name_or_contact_number_appears_anywhere_in_the_response(
    reviewer_client: TestClient, demo_case: Case
) -> None:
    """FR-07, DR-04, IR-20. Checked against the whole serialised body, because
    this response is the largest in the API and the easiest to leak through."""
    raw = read(reviewer_client, demo_case).text

    assert OWNER_NAME not in raw
    assert CONTACT_NUMBER not in raw
    assert "owner_name" not in raw
    assert "contact_number" not in raw


def test_a_case_that_does_not_exist_is_404(reviewer_client: TestClient) -> None:
    response = reviewer_client.get(f"{CASES_URL}/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_an_unauthenticated_read_is_401(api_client: TestClient, demo_case: Case) -> None:
    assert api_client.get(f"{CASES_URL}/{demo_case.id}").status_code == 401
