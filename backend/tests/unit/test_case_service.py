"""`CaseService`: intake rules and the Triage Queue (FR-01..FR-07, FR-29..FR-39).

These run against the real database, as every data test in this project does: the
FR-29 ordering is a SQL expression and the FR-05 immutability is a trigger, so a
fake session would prove neither.

The clock is injected rather than slept through — `at(minutes_ago=64)` is how a
case is placed past its target.

Every pet, owner and description here is invented (CLAUDE.md §9).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import CaseNotFound, SpeciesOutOfScope
from app.models import (
    AgeUnit,
    AuditEntry,
    CaseStatus,
    DecisionType,
    IntakeChannel,
    OwnerDescription,
    OwnerReference,
    Sex,
    Signalment,
    Species,
    User,
    UserRole,
    VTLCategory,
)
from app.schemas.case import CaseCreate, CaseQueueFilters, QueueCategoryFilter, SpeciesInput
from app.services.audit_service import AuditAction
from app.services.case_service import DEFAULT_INTAKE_CHANNEL, CaseService
from tests.conftest import (
    make_case,
    make_recommendation,
    make_red_flag_alert,
    make_staff_decision,
    make_user,
)

# A fixed instant, so "64 minutes ago" is exact.
NOW = datetime(2026, 10, 1, 9, 35, tzinfo=UTC)

DESCRIPTION = (
    "She has been limping on her left hind leg since this morning and will not put weight on it."
)
OWNER_NAME = "R. Bituin"
CONTACT_NUMBER = "0917-000-0000"


def at(minutes_ago: int = 0) -> datetime:
    return NOW - timedelta(minutes=minutes_ago)


@pytest.fixture
def intake_user(db_session: Session) -> User:
    return make_user(db_session, role=UserRole.INTAKE_STAFF)


@pytest.fixture
def service(db_session: Session) -> CaseService:
    return CaseService(db_session, now=lambda: NOW)


def payload(**overrides: object) -> CaseCreate:
    """A valid intake submission, with the given fields replaced."""
    return CaseCreate(**{"species": SpeciesInput.CAT, "description": DESCRIPTION, **overrides})


def queue(service: CaseService, **filters: object) -> list[str]:
    """The case numbers the queue returns, in order."""
    return [item.case_no for item in service.list_queue(CaseQueueFilters(**filters)).items]


# --- FR-02: dogs and cats only -------------------------------------------


def test_other_species_is_refused(service: CaseService, intake_user: User) -> None:
    with pytest.raises(SpeciesOutOfScope) as raised:
        service.create_case(payload(species=SpeciesInput.OTHER), intake_user)

    assert raised.value.code == "SPECIES_OUT_OF_SCOPE"
    assert raised.value.status_code == 422
    assert "triaged manually" in raised.value.message


def test_a_refused_species_writes_nothing_at_all(
    service: CaseService, intake_user: User, db_session: Session
) -> None:
    """Not the case, not the description, and not an audit entry.

    The audit log cannot be corrected (ADR-12), so a rejected submission must not
    leave a CASE_CREATED entry behind for a case that does not exist.
    """
    with pytest.raises(SpeciesOutOfScope):
        service.create_case(payload(species=SpeciesInput.OTHER), intake_user)

    assert service.list_queue(CaseQueueFilters()).items == []
    assert db_session.execute(select(OwnerDescription)).all() == []
    actions = db_session.execute(select(AuditEntry.action)).scalars().all()
    assert AuditAction.CASE_CREATED.value not in actions


# --- FR-01, FR-03, FR-05: what a submission stores ------------------------


def test_a_new_case_is_submitted_and_numbered(service: CaseService, intake_user: User) -> None:
    created = service.create_case(payload(), intake_user)

    assert created.status is CaseStatus.SUBMITTED
    assert created.case_no.startswith("C-")
    assert len(created.case_no) >= len("C-0001")


def test_case_numbers_do_not_repeat(service: CaseService, intake_user: User) -> None:
    first = service.create_case(payload(), intake_user)
    second = service.create_case(payload(), intake_user)

    assert first.case_no != second.case_no


def test_the_description_is_stored_verbatim(
    service: CaseService, intake_user: User, db_session: Session
) -> None:
    """FR-05: character for character, with the character count to match."""
    created = service.create_case(payload(), intake_user)

    stored = db_session.execute(
        select(OwnerDescription).where(OwnerDescription.case_id == created.id)
    ).scalar_one()
    assert stored.text == DESCRIPTION
    assert stored.char_count == len(DESCRIPTION)
    assert stored.submitted_at == NOW


def test_surrounding_whitespace_is_trimmed_before_the_length_check() -> None:
    """20 spaces is not a description; the stored text is the trimmed one."""
    assert payload(description=f"  {DESCRIPTION}  ").description == DESCRIPTION

    with pytest.raises(ValueError, match="at least 20"):
        payload(description=" " * 40)


def test_the_signalment_is_stored_as_entered(
    service: CaseService, intake_user: User, db_session: Session
) -> None:
    created = service.create_case(
        payload(
            pet_name="Luna",
            age_value=3,
            age_unit=AgeUnit.YEARS,
            sex=Sex.FEMALE,
            neutered=True,
            breed="Puspin",
            weight_kg="4.2",
        ),
        intake_user,
    )

    signalment = db_session.execute(
        select(Signalment).where(Signalment.case_id == created.id)
    ).scalar_one()
    assert signalment.pet_name == "Luna"
    assert float(signalment.age_value) == 3
    assert signalment.age_unit is AgeUnit.YEARS
    assert signalment.sex is Sex.FEMALE
    assert signalment.neutered is True
    assert signalment.breed == "Puspin"
    assert float(signalment.weight_kg) == pytest.approx(4.2)


def test_an_unstated_sex_is_recorded_as_unknown(
    service: CaseService, intake_user: User, db_session: Session
) -> None:
    """The column is not nullable: "not stated" is itself a finding."""
    created = service.create_case(payload(), intake_user)

    signalment = db_session.execute(
        select(Signalment).where(Signalment.case_id == created.id)
    ).scalar_one()
    assert signalment.sex is Sex.UNKNOWN


def test_an_unstated_intake_channel_defaults_to_walk_in(
    service: CaseService, intake_user: User, db_session: Session
) -> None:
    created = service.create_case(payload(), intake_user)

    assert DEFAULT_INTAKE_CHANNEL is IntakeChannel.WALK_IN
    status = service.get_status(created.id)
    assert status.status is CaseStatus.SUBMITTED


# --- FR-07, DR-04: the owner reference ------------------------------------


def test_no_owner_reference_row_when_neither_field_is_given(
    service: CaseService, intake_user: User, db_session: Session
) -> None:
    service.create_case(payload(), intake_user)

    assert db_session.execute(select(OwnerReference)).all() == []


@pytest.mark.parametrize(
    "fields",
    [
        {"owner_name": OWNER_NAME},
        {"contact_number": CONTACT_NUMBER},
        {"owner_name": OWNER_NAME, "contact_number": CONTACT_NUMBER},
    ],
)
def test_the_owner_reference_is_stored_in_its_own_table(
    service: CaseService, intake_user: User, db_session: Session, fields: dict[str, str]
) -> None:
    created = service.create_case(payload(**fields), intake_user)

    reference = db_session.execute(
        select(OwnerReference).where(OwnerReference.case_id == created.id)
    ).scalar_one()
    assert reference.owner_name == fields.get("owner_name")
    assert reference.contact_number == fields.get("contact_number")


def test_a_blank_owner_field_is_not_stored_as_a_value(
    service: CaseService, intake_user: User, db_session: Session
) -> None:
    """An untouched optional input arrives as an empty string, not as absent."""
    service.create_case(payload(owner_name="   ", contact_number=""), intake_user)

    assert db_session.execute(select(OwnerReference)).all() == []


# --- FR-43: the audit entry ----------------------------------------------


def audit_entry_for(db_session: Session, case_id: uuid.UUID) -> AuditEntry:
    return db_session.execute(
        select(AuditEntry).where(
            AuditEntry.action == AuditAction.CASE_CREATED.value,
            AuditEntry.entity_id == str(case_id),
        )
    ).scalar_one()


def test_creating_a_case_writes_an_audit_entry(
    service: CaseService, intake_user: User, db_session: Session
) -> None:
    created = service.create_case(payload(), intake_user)

    entry = audit_entry_for(db_session, created.id)
    assert entry.entity_type == "case"
    assert entry.user_id == intake_user.id
    assert entry.role is UserRole.INTAKE_STAFF
    assert entry.after["case_no"] == created.case_no
    assert entry.after["status"] == CaseStatus.SUBMITTED.value
    assert entry.after["description_char_count"] == len(DESCRIPTION)


def test_the_audit_entry_holds_no_clinical_or_personal_text(
    service: CaseService, intake_user: User, db_session: Session
) -> None:
    """CLAUDE.md §9. Asserted against the actual text, not an allow-list of keys,
    so a field added later cannot slip past this."""
    created = service.create_case(
        payload(owner_name=OWNER_NAME, contact_number=CONTACT_NUMBER, pet_name="Luna"),
        intake_user,
    )

    recorded = str(audit_entry_for(db_session, created.id).after)
    for secret in (DESCRIPTION, OWNER_NAME, CONTACT_NUMBER, "Luna"):
        assert secret not in recorded
    # It does say that there is a reference, without saying what it holds.
    assert audit_entry_for(db_session, created.id).after["has_owner_reference"] is True


# --- FR-29: queue ordering ------------------------------------------------


@pytest.fixture
def mixed_queue(db_session: Session) -> None:
    """One case per rank, deliberately created in the wrong order.

    Arrival times are staggered so that sorting by arrival alone, or by category
    alone, would both give a different answer than FR-29 does.
    """
    author = make_user(db_session)
    rows = {
        "C-GREEN": (VTLCategory.GREEN, 45),
        "C-RED": (VTLCategory.RED, 1),
        "C-BLUE": (VTLCategory.BLUE, 83),
        "C-ORANGE": (VTLCategory.ORANGE, 6),
        "C-YELLOW": (VTLCategory.YELLOW, 37),
    }
    for case_no, (category, minutes_ago) in rows.items():
        case = make_case(db_session, created_by=author, case_no=case_no, created_at=at(minutes_ago))
        make_recommendation(db_session, case=case, category=category)

    # No category at all: still processing, and handed to manual triage.
    make_case(
        db_session,
        created_by=author,
        case_no="C-NONE1",
        created_at=at(22),
        status=CaseStatus.MANUAL_TRIAGE_REQUIRED,
    )
    make_case(
        db_session,
        created_by=author,
        case_no="C-NONE2",
        created_at=at(4),
        status=CaseStatus.PROCESSING,
    )


def test_the_queue_is_ordered_by_rank_then_arrival(service: CaseService, mixed_queue: None) -> None:
    assert queue(service) == [
        "C-RED",
        # Both uncategorised cases, oldest first, directly below RED.
        "C-NONE1",
        "C-NONE2",
        "C-ORANGE",
        "C-YELLOW",
        "C-GREEN",
        "C-BLUE",
    ]


def test_a_confirmed_category_outranks_the_recommended_one(
    service: CaseService, db_session: Session
) -> None:
    """FR-29: the reviewer's decision is what the queue sorts and displays by."""
    case = make_case(db_session, case_no="C-ADJ", created_at=at(30))
    make_recommendation(db_session, case=case, category=VTLCategory.BLUE)
    make_staff_decision(
        db_session,
        case=case,
        final_category=VTLCategory.RED,
        decision_type=DecisionType.ADJUST,
    )
    other = make_case(db_session, case_no="C-ORA", created_at=at(31))
    make_recommendation(db_session, case=other, category=VTLCategory.ORANGE)

    items = service.list_queue(CaseQueueFilters()).items

    assert [item.case_no for item in items] == ["C-ADJ", "C-ORA"]
    adjusted = items[0]
    assert adjusted.category is VTLCategory.RED
    assert adjusted.confirmed_category is VTLCategory.RED
    # Both sources are reported, so the chip can say "Adjusted (Blue -> Red)".
    assert adjusted.recommended_category is VTLCategory.BLUE
    assert adjusted.decision_type is DecisionType.ADJUST


def test_the_latest_decision_wins(service: CaseService, db_session: Session) -> None:
    """An amendment supersedes the original without editing it (FR-48)."""
    case = make_case(db_session, case_no="C-AMEND", created_at=at(30))
    make_recommendation(db_session, case=case, category=VTLCategory.YELLOW)
    make_staff_decision(db_session, case=case, final_category=VTLCategory.YELLOW, decided_at=at(20))
    make_staff_decision(
        db_session,
        case=case,
        final_category=VTLCategory.GREEN,
        decision_type=DecisionType.ADJUST,
        decided_at=at(5),
    )

    item = service.list_queue(CaseQueueFilters()).items[0]

    assert item.confirmed_category is VTLCategory.GREEN
    assert item.category is VTLCategory.GREEN


def test_the_latest_recommendation_version_wins(service: CaseService, db_session: Session) -> None:
    """P07 regenerates a recommendation as a new version of the same case."""
    case = make_case(db_session, case_no="C-REGEN", created_at=at(10))
    make_recommendation(db_session, case=case, category=VTLCategory.BLUE, version=1)
    make_recommendation(db_session, case=case, category=VTLCategory.ORANGE, version=2)

    item = service.list_queue(CaseQueueFilters()).items[0]

    assert item.recommended_category is VTLCategory.ORANGE


def test_closed_cases_are_not_in_the_queue(service: CaseService, db_session: Session) -> None:
    make_case(db_session, case_no="C-OPEN", created_at=at(5))
    make_case(
        db_session,
        case_no="C-SHUT",
        created_at=at(6),
        status=CaseStatus.CLOSED,
        closed_at=at(1),
    )

    assert queue(service) == ["C-OPEN"]


# --- FR-30: waiting time and the overdue flag -----------------------------


def test_waiting_time_is_measured_from_arrival(service: CaseService, db_session: Session) -> None:
    make_case(db_session, created_at=at(37))

    item = service.list_queue(CaseQueueFilters()).items[0]

    assert item.waiting_minutes == 37


def test_a_case_past_its_target_is_overdue(service: CaseService, db_session: Session) -> None:
    case = make_case(db_session, created_at=at(64))
    make_recommendation(db_session, case=case, category=VTLCategory.YELLOW)

    item = service.list_queue(CaseQueueFilters()).items[0]

    assert item.target_minutes == 60
    assert item.waiting_minutes == 64
    assert item.is_overdue is True


def test_a_case_exactly_at_its_target_is_not_yet_overdue(
    service: CaseService, db_session: Session
) -> None:
    case = make_case(db_session, created_at=at(60))
    make_recommendation(db_session, case=case, category=VTLCategory.YELLOW)

    assert service.list_queue(CaseQueueFilters()).items[0].is_overdue is False


def test_an_uncategorised_case_has_no_target_and_is_not_overdue(
    service: CaseService, db_session: Session
) -> None:
    make_case(db_session, created_at=at(500), status=CaseStatus.MANUAL_TRIAGE_REQUIRED)

    item = service.list_queue(CaseQueueFilters()).items[0]

    assert item.category is None
    assert item.target_minutes is None
    assert item.is_overdue is False


def test_every_row_is_measured_against_one_instant(
    service: CaseService, db_session: Session
) -> None:
    """`generated_at` is the instant the whole snapshot was taken (IR-22)."""
    make_case(db_session, created_at=at(10))
    make_case(db_session, created_at=at(10))

    response = service.list_queue(CaseQueueFilters())

    assert response.generated_at == NOW
    assert {item.waiting_minutes for item in response.items} == {10}


# --- FR-12: the red-flag indicator ---------------------------------------


def test_a_case_with_an_alert_is_flagged(service: CaseService, db_session: Session) -> None:
    case = make_case(db_session, created_at=at(2))
    make_red_flag_alert(db_session, case=case, rule_code="FIXTURE_NOT_BREATHING")

    assert service.list_queue(CaseQueueFilters()).items[0].has_red_flag is True
    assert service.get_status(case.id).has_red_flag is True


def test_a_case_without_an_alert_is_not_flagged(service: CaseService, db_session: Session) -> None:
    case = make_case(db_session, created_at=at(2))

    assert service.list_queue(CaseQueueFilters()).items[0].has_red_flag is False
    assert service.get_status(case.id).has_red_flag is False


# --- The W-02 counters ---------------------------------------------------


@pytest.fixture
def counted_queue(db_session: Session) -> None:
    """The W-02 sample queue: one of each category, one manual, one awaiting."""
    author = make_user(db_session)
    for case_no, category in (
        ("C-C-RED", VTLCategory.RED),
        ("C-C-ORA", VTLCategory.ORANGE),
        ("C-C-YE1", VTLCategory.YELLOW),
        ("C-C-YE2", VTLCategory.YELLOW),
        ("C-C-GRE", VTLCategory.GREEN),
        ("C-C-BLU", VTLCategory.BLUE),
    ):
        case = make_case(
            db_session,
            created_by=author,
            case_no=case_no,
            created_at=at(10),
            status=CaseStatus.AWAITING_REVIEW,
        )
        make_recommendation(db_session, case=case, category=category)

    make_case(
        db_session,
        created_by=author,
        case_no="C-C-MAN",
        created_at=at(20),
        status=CaseStatus.MANUAL_TRIAGE_REQUIRED,
    )
    make_case(
        db_session,
        created_by=author,
        case_no="C-C-OUT",
        created_at=at(300),
        status=CaseStatus.CLOSED,
        closed_at=at(100),
    )


def test_the_counters_cover_every_open_case(service: CaseService, counted_queue: None) -> None:
    counts = service.list_queue(CaseQueueFilters()).counts

    assert counts.by_category == {
        VTLCategory.RED: 1,
        VTLCategory.ORANGE: 1,
        VTLCategory.YELLOW: 2,
        VTLCategory.GREEN: 1,
        VTLCategory.BLUE: 1,
    }
    assert counts.manual_count == 1
    assert counts.awaiting_review_count == 6
    # The closed case is in none of them.
    assert counts.total == 7


def test_the_counters_ignore_the_filters(service: CaseService, counted_queue: None) -> None:
    """The confirmed behaviour: the counters describe the queue, not the rows.

    If they moved with the filter, filtering to RED would zero every other tile
    and the counter bar could not be used to navigate.
    """
    unfiltered = service.list_queue(CaseQueueFilters()).counts
    filtered = service.list_queue(CaseQueueFilters(category=QueueCategoryFilter.RED))

    assert filtered.counts == unfiltered
    assert len(filtered.items) == 1


def test_every_category_appears_in_the_counters_even_at_zero(
    service: CaseService, db_session: Session
) -> None:
    """The five tiles are always drawn, so the response always has five keys."""
    make_case(db_session, created_at=at(1))

    counts = service.list_queue(CaseQueueFilters()).counts

    assert set(counts.by_category) == set(VTLCategory)
    assert sum(counts.by_category.values()) == 0
    assert counts.total == 1


# --- FR-39: the filters --------------------------------------------------


def test_filter_by_species(service: CaseService, db_session: Session) -> None:
    make_case(db_session, case_no="C-DOG", species=Species.DOG, created_at=at(5))
    make_case(db_session, case_no="C-CAT", species=Species.CAT, created_at=at(5))

    assert queue(service, species=Species.CAT) == ["C-CAT"]


def test_filter_by_category(service: CaseService, mixed_queue: None) -> None:
    assert queue(service, category=QueueCategoryFilter.YELLOW) == ["C-YELLOW"]


def test_filter_by_manual_selects_cases_needing_manual_triage(
    service: CaseService, mixed_queue: None
) -> None:
    """MANUAL is a status, not a VTL category, so it is matched on the status."""
    assert queue(service, category=QueueCategoryFilter.MANUAL) == ["C-NONE1"]


def test_filter_by_status(service: CaseService, mixed_queue: None) -> None:
    assert queue(service, status=CaseStatus.PROCESSING) == ["C-NONE2"]


def test_filter_by_closed_status_returns_nothing(service: CaseService, db_session: Session) -> None:
    """The queue is open cases by definition, so this combination is empty."""
    make_case(db_session, case_no="C-SHUT", status=CaseStatus.CLOSED, closed_at=at(1))

    assert queue(service, status=CaseStatus.CLOSED) == []


def test_filter_by_date_uses_the_clinic_day_not_the_utc_day(
    service: CaseService, db_session: Session
) -> None:
    """Asia/Manila is UTC+8, so the clinic's 1 October starts at 30 Sep 16:00 UTC.

    A case entered at 08:00 Manila is 00:00 UTC on the same date, which a UTC-day
    filter would also catch. The one that proves the timezone is handled is the
    case entered at 09:00 Manila on 30 September — 01:00 UTC on the 30th — which
    must *not* appear in the 1 October list.
    """
    make_case(
        db_session,
        case_no="C-SEP30",
        created_at=datetime(2026, 9, 30, 1, 0, tzinfo=UTC),
    )
    make_case(
        db_session,
        case_no="C-OCT01",
        created_at=datetime(2026, 10, 1, 0, 0, tzinfo=UTC),
    )

    october = {"date_from": "2026-10-01", "date_to": "2026-10-01"}
    assert queue(service, **october) == ["C-OCT01"]


def test_filter_by_date_range_is_inclusive_at_both_ends(
    service: CaseService, db_session: Session
) -> None:
    for case_no, moment in (
        ("C-D29", datetime(2026, 9, 29, 4, 0, tzinfo=UTC)),
        ("C-D30", datetime(2026, 9, 30, 4, 0, tzinfo=UTC)),
        ("C-D01", datetime(2026, 10, 1, 4, 0, tzinfo=UTC)),
    ):
        make_case(db_session, case_no=case_no, created_at=moment)

    found = queue(service, date_from="2026-09-30", date_to="2026-10-01")

    assert set(found) == {"C-D30", "C-D01"}


@pytest.mark.parametrize("term", ["C-0142", "c-0142", "0142"])
def test_search_matches_the_case_number(
    service: CaseService, db_session: Session, term: str
) -> None:
    make_case(db_session, case_no="C-0142", created_at=at(5))
    make_case(db_session, case_no="C-0143", created_at=at(5))

    assert queue(service, q=term) == ["C-0142"]


def test_search_matches_the_pet_name_ignoring_case(
    service: CaseService, db_session: Session
) -> None:
    make_case(db_session, case_no="C-PET", created_at=at(5), pet_name="Mingming")
    make_case(db_session, case_no="C-OTH", created_at=at(5), pet_name="Bantay")

    assert queue(service, q="mingming") == ["C-PET"]


def test_search_treats_a_wildcard_as_a_literal_character(
    service: CaseService, db_session: Session
) -> None:
    """Otherwise "%" would match every case in the clinic."""
    make_case(db_session, case_no="C-PCT", created_at=at(5), pet_name="100%")
    make_case(db_session, case_no="C-OTH", created_at=at(5), pet_name="Bantay")

    assert queue(service, q="%") == ["C-PCT"]


def test_search_ignores_surrounding_whitespace(service: CaseService, db_session: Session) -> None:
    make_case(db_session, case_no="C-PET", created_at=at(5), pet_name="Mingming")

    assert queue(service, q="  Mingming  ") == ["C-PET"]


def test_filters_combine(service: CaseService, db_session: Session) -> None:
    wanted = make_case(
        db_session, case_no="C-WANT", species=Species.CAT, created_at=at(5), pet_name="Luna"
    )
    make_recommendation(db_session, case=wanted, category=VTLCategory.ORANGE)
    other = make_case(
        db_session, case_no="C-SKIP", species=Species.DOG, created_at=at(5), pet_name="Luna"
    )
    make_recommendation(db_session, case=other, category=VTLCategory.ORANGE)

    found = queue(service, species=Species.CAT, category=QueueCategoryFilter.ORANGE, q="Luna")

    assert found == ["C-WANT"]


def test_the_page_size_bounds_the_response(service: CaseService, db_session: Session) -> None:
    for index in range(3):
        make_case(db_session, case_no=f"C-P{index}", created_at=at(10 - index))

    assert queue(service, limit=2) == ["C-P0", "C-P1"]
    assert queue(service, limit=2, offset=2) == ["C-P2"]


# --- GET /cases/{id}/status ----------------------------------------------


def test_get_status_reports_a_new_case(
    service: CaseService, intake_user: User, db_session: Session
) -> None:
    created = service.create_case(payload(), intake_user)

    status = service.get_status(created.id)

    assert status.status is CaseStatus.SUBMITTED
    assert status.category is None
    assert status.has_red_flag is False
    assert status.updated_at == NOW


def test_get_status_reports_the_displayed_category(
    service: CaseService, db_session: Session
) -> None:
    case = make_case(db_session, created_at=at(10), status=CaseStatus.CONFIRMED)
    make_recommendation(db_session, case=case, category=VTLCategory.YELLOW)
    make_staff_decision(db_session, case=case, final_category=VTLCategory.YELLOW)

    assert service.get_status(case.id).category is VTLCategory.YELLOW


def test_updated_at_moves_when_a_recommendation_lands(
    service: CaseService, db_session: Session
) -> None:
    """It is derived, so a client polling it sees related rows appear.

    The `cases` row itself does not change when the pipeline finishes, so a stored
    `updated_at` column would have to be touched by P05 to say anything useful.
    """
    case = make_case(db_session, created_at=at(30))
    before = service.get_status(case.id).updated_at
    assert before == at(30)

    make_recommendation(db_session, case=case, category=VTLCategory.GREEN, created_at=at(10))

    assert service.get_status(case.id).updated_at == at(10)


def test_updated_at_moves_when_a_decision_lands(service: CaseService, db_session: Session) -> None:
    # Pinned to the fixed clock like every other row here. Left to the database
    # default, the recommendation lands at the real current time, which is later
    # than NOW for most of the day and makes the assertion below depend on when
    # the suite is run.
    case = make_case(db_session, created_at=at(30))
    make_recommendation(db_session, case=case, category=VTLCategory.GREEN, created_at=at(10))
    before = service.get_status(case.id).updated_at

    make_staff_decision(db_session, case=case, final_category=VTLCategory.GREEN, decided_at=NOW)

    assert service.get_status(case.id).updated_at == NOW
    assert service.get_status(case.id).updated_at > before


def test_get_status_still_answers_for_a_closed_case(
    service: CaseService, db_session: Session
) -> None:
    """It is out of the queue, but a client holding its id may still read it."""
    case = make_case(db_session, created_at=at(300), status=CaseStatus.CLOSED, closed_at=NOW)

    assert service.get_status(case.id).status is CaseStatus.CLOSED


def test_get_status_on_an_unknown_case_is_not_found(service: CaseService) -> None:
    with pytest.raises(CaseNotFound) as raised:
        service.get_status(uuid.uuid4())

    assert raised.value.status_code == 404
