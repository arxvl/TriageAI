"""The de-identified export files, as plain functions (P09 §9.4, FR-47, BR-08).

No database and no web framework here: the repository hands over rows as mappings
and these functions turn them into CSV text. That keeps the one rule that matters
— what is allowed into an export — in two short column lists a test can compare
word for word.

**Cases.** One row per case, counts and categories only. The columns are a
whitelist: nothing is exported because it happened to be on the row. No
description, owner reference, pet name, note, rationale, reason text or action
text, and no reviewer — a decision carries its type and reason *code*, which is
all the analysis needs (SR-17).

**Audit.** People become a role and a pseudonym such as `REVIEWER-1`, numbered in
order of first appearance, so the numbering is stable within one file and does
not link two files together. The `before`/`after` payloads are kept but scrubbed:
the audit log holds the e-mail someone typed on a failed sign-in, and the id of
every account an administrator touched.
"""

import csv
import io
import json
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from app.core.csv_safety import text_cell
from app.models import UserRole

__all__ = [
    "AUDIT_COLUMNS",
    "CASE_COLUMNS",
    "REDACTED",
    "Pseudonymizer",
    "audit_to_csv",
    "cases_to_csv",
    "scrub_payload",
]

CASE_COLUMNS = (
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

AUDIT_COLUMNS = (
    "ts",
    "actor_role",
    "actor_pseudonym",
    "action",
    "entity_type",
    "entity_id",
    "before",
    "after",
)

REDACTED = "[redacted]"

# Payload keys that hold a person's identity. Matched on the key, whatever the
# value, so a field added later under one of these names is covered.
_PERSONAL_KEYS = frozenset(
    {"email", "full_name", "name", "owner_name", "contact_number", "pet_name", "password"}
)
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+")

_PSEUDONYM_PREFIX = {
    UserRole.INTAKE_STAFF: "INTAKE",
    UserRole.VETERINARY_REVIEWER: "REVIEWER",
    UserRole.ADMINISTRATOR: "ADMIN",
}
_UNKNOWN_PREFIX = "USER"


class Pseudonymizer:
    """`REVIEWER-1`, `ADMIN-1`, … for the people in one export.

    A new instance per export: the same account is `REVIEWER-1` everywhere in one
    file and may be `REVIEWER-3` in the next, so two exports cannot be joined on
    the pseudonym.
    """

    def __init__(self) -> None:
        self._labels: dict[uuid.UUID, str] = {}
        self._counts: dict[str, int] = {}

    def label(self, user_id: uuid.UUID, role: UserRole | None) -> str:
        known = self._labels.get(user_id)
        if known is not None:
            return known
        prefix = _PSEUDONYM_PREFIX.get(role, _UNKNOWN_PREFIX) if role else _UNKNOWN_PREFIX
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        label = f"{prefix}-{self._counts[prefix]}"
        self._labels[user_id] = label
        return label


def _as_user_id(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _scrub_string(
    value: str, roles: Mapping[uuid.UUID, UserRole | None], pseudonyms: Pseudonymizer
) -> str:
    """An account id becomes its pseudonym; anything shaped like an address goes."""
    user_id = _as_user_id(value)
    if user_id is not None and user_id in roles:
        return pseudonyms.label(user_id, roles[user_id])
    if _EMAIL.search(value):
        return REDACTED
    return value


def scrub_payload(
    value: Any, roles: Mapping[uuid.UUID, UserRole | None], pseudonyms: Pseudonymizer
) -> Any:
    """A copy of an audit payload with no account identity left in it."""
    if isinstance(value, Mapping):
        return {
            key: REDACTED
            if str(key).lower() in _PERSONAL_KEYS
            else scrub_payload(item, roles, pseudonyms)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub_payload(item, roles, pseudonyms) for item in value]
    if isinstance(value, str):
        return _scrub_string(value, roles, pseudonyms)
    return value


def _instant(value: datetime | None) -> str:
    return "" if value is None else value.isoformat()


def _seconds(start: datetime | None, end: datetime | None) -> int | str:
    if start is None or end is None:
        return ""
    return int((end - start).total_seconds())


def _enum(value: Any) -> str:
    return "" if value is None else str(getattr(value, "value", value))


def _flag(value: bool | None) -> str:
    return "" if value is None else ("true" if value else "false")


def _count(value: int | None, present: bool) -> int | str:
    """A count, or blank when there is nothing it could be counting."""
    return int(value or 0) if present else ""


def case_record(row: Mapping[str, Any]) -> list[Any]:
    """One case's cells, in `CASE_COLUMNS` order."""
    has_recommendation = row["recommendation_id"] is not None
    has_decision = row["decision_id"] is not None
    return [
        text_cell(row["case_no"]),
        _enum(row["species"]),
        _instant(row["created_at"]),
        _enum(row["status"]),
        _enum(row["ai_category"]),
        _enum(row["ai_confidence"]),
        _flag(row["safety_floor_applied"]),
        _enum(row["final_category"]),
        _enum(row["decision_type"]),
        _enum(row["reason_code"]),
        _enum(row["direction"]),
        _seconds(row["created_at"], row["recommendation_at"]),
        _seconds(row["recommendation_at"], row["decided_at"]),
        _count(row["baseline_shown"], has_recommendation),
        _count(row["tailored_suggested"], has_recommendation),
        _count(row["tailored_rejected"], has_recommendation),
        _count(row["final_kept"], has_decision),
        _count(row["final_edited"], has_decision),
        _count(row["final_removed"], has_decision),
        _count(row["final_added"], has_decision),
    ]


def _write(columns: Sequence[str], records: Iterable[Sequence[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(records)
    return buffer.getvalue()


def cases_to_csv(rows: Iterable[Mapping[str, Any]]) -> str:
    return _write(CASE_COLUMNS, (case_record(row) for row in rows))


def _json_cell(value: Any) -> str:
    if value is None:
        return ""
    return text_cell(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def audit_to_csv(
    rows: Iterable[Mapping[str, Any]], roles: Mapping[uuid.UUID, UserRole | None]
) -> str:
    """The audit rows with every person replaced by a role and a pseudonym.

    Within a row the actor is labelled first, then the entity, then the payloads,
    so the numbering follows the order a reader meets the people in the file.
    """
    pseudonyms = Pseudonymizer()
    records: list[list[Any]] = []
    for row in rows:
        user_id: uuid.UUID | None = row["user_id"]
        actor = (
            "" if user_id is None else pseudonyms.label(user_id, roles.get(user_id, row["role"]))
        )
        records.append(
            [
                _instant(row["ts"]),
                _enum(row["role"]),
                actor,
                text_cell(row["action"]),
                text_cell(row["entity_type"]),
                text_cell(_scrub_string(str(row["entity_id"]), roles, pseudonyms)),
                _json_cell(scrub_payload(row["before"], roles, pseudonyms)),
                _json_cell(scrub_payload(row["after"], roles, pseudonyms)),
            ]
        )
    return _write(AUDIT_COLUMNS, records)
