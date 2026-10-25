"""The export column whitelists, pseudonyms and payload scrubbing (P09 §9.4, FR-47, BR-08).

Pure functions, no database. All data is fictitious (CLAUDE.md §9).
"""

import csv
import io
import uuid
from datetime import UTC, datetime

from app.core.csv_safety import text_cell
from app.models import UserRole
from app.services.export_format import (
    AUDIT_COLUMNS,
    CASE_COLUMNS,
    REDACTED,
    Pseudonymizer,
    audit_to_csv,
    cases_to_csv,
    scrub_payload,
)

# A column whose name contains one of these could carry personal or free text.
FORBIDDEN_WORDS = (
    "description",
    "owner",
    "name",
    "note",
    "reason_text",
    "rationale",
    "text",
    "user",
    "reviewer",
    "email",
    "contact",
)


def test_case_columns_are_the_documented_whitelist() -> None:
    assert CASE_COLUMNS == (
        "case_no",
        "species",
        "created_at",
        "status",
        "ai_category",
        "ai_confidence",
        "safety_floor_applied",
        "final_category",
        "decision_type",
        "reason_code",
        "direction",
        "seconds_submission_to_recommendation",
        "seconds_recommendation_to_decision",
        "actions_baseline_shown",
        "actions_tailored_suggested",
        "actions_tailored_rejected",
        "actions_final_kept",
        "actions_final_edited",
        "actions_final_removed",
        "actions_final_added",
    )


def test_case_columns_name_no_personal_or_free_text_field() -> None:
    for column in CASE_COLUMNS:
        assert not any(word in column for word in FORBIDDEN_WORDS), column


def test_audit_columns_are_the_documented_set() -> None:
    assert AUDIT_COLUMNS == (
        "ts",
        "actor_role",
        "actor_pseudonym",
        "action",
        "entity_type",
        "entity_id",
        "before",
        "after",
    )


def test_pseudonym_is_stable_within_one_instance() -> None:
    pseudonyms = Pseudonymizer()
    reviewer = uuid.uuid4()

    assert pseudonyms.label(reviewer, UserRole.VETERINARY_REVIEWER) == "REVIEWER-1"
    assert pseudonyms.label(reviewer, UserRole.VETERINARY_REVIEWER) == "REVIEWER-1"


def test_pseudonyms_are_numbered_per_role_in_order_of_first_appearance() -> None:
    pseudonyms = Pseudonymizer()

    first = pseudonyms.label(uuid.uuid4(), UserRole.VETERINARY_REVIEWER)
    admin = pseudonyms.label(uuid.uuid4(), UserRole.ADMINISTRATOR)
    second = pseudonyms.label(uuid.uuid4(), UserRole.VETERINARY_REVIEWER)
    intake = pseudonyms.label(uuid.uuid4(), UserRole.INTAKE_STAFF)

    assert (first, second) == ("REVIEWER-1", "REVIEWER-2")
    assert (admin, intake) == ("ADMIN-1", "INTAKE-1")


def test_pseudonyms_are_not_shared_between_instances() -> None:
    reviewer = uuid.uuid4()
    other = uuid.uuid4()

    first_export = Pseudonymizer()
    first_export.label(other, UserRole.VETERINARY_REVIEWER)
    second_export = Pseudonymizer()

    assert first_export.label(reviewer, UserRole.VETERINARY_REVIEWER) == "REVIEWER-2"
    assert second_export.label(reviewer, UserRole.VETERINARY_REVIEWER) == "REVIEWER-1"


def test_an_unknown_role_gets_a_generic_prefix() -> None:
    assert Pseudonymizer().label(uuid.uuid4(), None) == "USER-1"


def test_scrub_redacts_personal_keys_whatever_the_value() -> None:
    scrubbed = scrub_payload(
        {"email": "typed@example.invalid", "full_name": "Fictional Person", "reason": "inactive"},
        {},
        Pseudonymizer(),
    )

    assert scrubbed == {"email": REDACTED, "full_name": REDACTED, "reason": "inactive"}


def test_scrub_replaces_known_account_ids_at_any_depth() -> None:
    reviewer = uuid.uuid4()
    roles = {reviewer: UserRole.VETERINARY_REVIEWER}

    scrubbed = scrub_payload(
        {"changed": [{"user": str(reviewer)}], "by": str(reviewer), "count": 3},
        roles,
        Pseudonymizer(),
    )

    assert scrubbed == {"changed": [{"user": "REVIEWER-1"}], "by": "REVIEWER-1", "count": 3}


def test_scrub_leaves_unrelated_ids_and_values_alone() -> None:
    case_id = str(uuid.uuid4())

    scrubbed = scrub_payload(
        {"case": case_id, "status": "CONFIRMED", "floor": True, "n": None}, {}, Pseudonymizer()
    )

    assert scrubbed == {"case": case_id, "status": "CONFIRMED", "floor": True, "n": None}


def test_scrub_removes_anything_shaped_like_an_address() -> None:
    assert scrub_payload({"detail": "a@b.invalid"}, {}, Pseudonymizer()) == {"detail": REDACTED}


def test_text_cell_prefixes_formula_characters() -> None:
    assert text_cell("=SUM(A1)") == "'=SUM(A1)"
    assert text_cell("-1") == "'-1"
    assert text_cell(None) == ""
    assert text_cell("C-0001") == "C-0001"


def case_row(**overrides: object) -> dict[str, object]:
    created = datetime(2026, 3, 1, 1, 0, tzinfo=UTC)
    row: dict[str, object] = {
        "case_no": "C-0001",
        "species": "DOG",
        "created_at": created,
        "status": "CONFIRMED",
        "recommendation_id": uuid.uuid4(),
        "ai_category": "ORANGE",
        "ai_confidence": "HIGH",
        "safety_floor_applied": True,
        "recommendation_at": datetime(2026, 3, 1, 1, 0, 30, tzinfo=UTC),
        "decision_id": uuid.uuid4(),
        "final_category": "RED",
        "decision_type": "ADJUST",
        "reason_code": "PATIENT_CONDITION",
        "direction": "UP",
        "decided_at": datetime(2026, 3, 1, 1, 5, 30, tzinfo=UTC),
        "baseline_shown": 3,
        "tailored_suggested": 2,
        "tailored_rejected": 1,
        "final_kept": 3,
        "final_edited": 1,
        "final_removed": 1,
        "final_added": 0,
    }
    row.update(overrides)
    return row


def parse(content: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content)))


def test_cases_csv_has_exactly_the_whitelisted_header() -> None:
    header = next(csv.reader(io.StringIO(cases_to_csv([case_row()]))))

    assert tuple(header) == CASE_COLUMNS


def test_cases_csv_row_values_and_intervals() -> None:
    (row,) = parse(cases_to_csv([case_row()]))

    assert row["ai_category"] == "ORANGE"
    assert row["safety_floor_applied"] == "true"
    assert row["final_category"] == "RED"
    assert row["seconds_submission_to_recommendation"] == "30"
    assert row["seconds_recommendation_to_decision"] == "300"
    assert (row["actions_baseline_shown"], row["actions_tailored_rejected"]) == ("3", "1")
    assert (row["actions_final_kept"], row["actions_final_added"]) == ("3", "0")


def test_a_case_with_nothing_yet_has_blank_ai_and_final_columns() -> None:
    (row,) = parse(
        cases_to_csv(
            [
                case_row(
                    recommendation_id=None,
                    ai_category=None,
                    ai_confidence=None,
                    safety_floor_applied=None,
                    recommendation_at=None,
                    decision_id=None,
                    final_category=None,
                    decision_type=None,
                    reason_code=None,
                    direction=None,
                    decided_at=None,
                    baseline_shown=None,
                    tailored_suggested=None,
                    tailored_rejected=None,
                    final_kept=None,
                    final_edited=None,
                    final_removed=None,
                    final_added=None,
                )
            ]
        )
    )

    blanks = [column for column in CASE_COLUMNS[4:] if row[column] == ""]
    assert blanks == list(CASE_COLUMNS[4:])


def audit_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts": datetime(2026, 3, 1, 2, 0, tzinfo=UTC),
        "user_id": None,
        "role": None,
        "action": "CASE_CREATED",
        "entity_type": "case",
        "entity_id": str(uuid.uuid4()),
        "before": None,
        "after": None,
    }
    row.update(overrides)
    return row


def test_audit_csv_uses_one_pseudonym_per_person_in_a_file() -> None:
    reviewer = uuid.uuid4()
    other = uuid.uuid4()
    roles = {reviewer: UserRole.VETERINARY_REVIEWER, other: UserRole.VETERINARY_REVIEWER}
    rows = [
        audit_row(user_id=reviewer, role=UserRole.VETERINARY_REVIEWER),
        audit_row(user_id=other, role=UserRole.VETERINARY_REVIEWER),
        audit_row(user_id=reviewer, role=UserRole.VETERINARY_REVIEWER),
    ]

    parsed = parse(audit_to_csv(rows, roles))

    assert [r["actor_pseudonym"] for r in parsed] == ["REVIEWER-1", "REVIEWER-2", "REVIEWER-1"]
    assert {r["actor_role"] for r in parsed} == {"VETERINARY_REVIEWER"}


def test_audit_csv_replaces_account_ids_and_addresses_everywhere() -> None:
    target = uuid.uuid4()
    roles = {target: UserRole.INTAKE_STAFF}
    rows = [
        audit_row(
            action="USER_UPDATED",
            entity_type="user",
            entity_id=str(target),
            before={"role": "INTAKE_STAFF"},
            after={"role": "INTAKE_STAFF", "is_active": False},
        ),
        audit_row(
            action="LOGIN_FAILURE",
            entity_type="user",
            entity_id="unknown",
            after={"email": "someone@example.invalid", "reason": "no_such_account"},
        ),
    ]

    content = audit_to_csv(rows, roles)
    parsed = parse(content)

    assert str(target) not in content
    assert "someone@example.invalid" not in content
    assert parsed[0]["entity_id"] == "INTAKE-1"
    assert parsed[0]["before"] == '{"role":"INTAKE_STAFF"}'
    assert parsed[1]["entity_id"] == "unknown"
    assert parsed[1]["actor_pseudonym"] == ""
    assert f'"email":"{REDACTED}"' in parsed[1]["after"]
