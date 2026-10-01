"""Plain-language wording for every validated request field (IR-05).

Pydantic's own messages are written for developers — "String should have at
least 20 characters", "Input should be a valid decimal". IR-05 requires the
opposite: a sentence that says what went wrong and how to fix it, with no
technical code and no field name in the prose. This module is the single place
that wording lives, so the API and the forms in W-03 cannot drift apart.

The lookup is keyed by field name, then by Pydantic's error `type`, because one
field fails in several ways that deserve different sentences — a missing
description is not the same problem as one that is three characters long. `"*"`
is the per-field fallback.

It sits in `core` rather than next to the schemas so that `core/errors.py`,
which every service imports, never has to import `app.schemas`.
"""

from collections.abc import Sequence

# Matched when no entry exists for the specific Pydantic error type.
ANY_ERROR = "*"

MESSAGES: dict[str, dict[str, str]] = {
    # --- Case intake, W-03 (FR-01, FR-04) --------------------------------
    "species": {
        ANY_ERROR: "Choose the species.",
    },
    "description": {
        "missing": "Enter the owner's description of the problem.",
        "string_too_short": (
            "The description must be at least 20 characters. "
            "Add a little more detail about what the owner reported."
        ),
        "string_too_long": (
            "The description must be 2,000 characters or fewer. Shorten it a little."
        ),
        ANY_ERROR: (
            "Enter the owner's description of the problem, between 20 and 2,000 characters."
        ),
    },
    "intake_channel": {
        ANY_ERROR: "Choose how the case arrived: walk-in, phone, or message.",
    },
    "pet_name": {
        "string_too_long": "The pet name can be at most 60 characters.",
        ANY_ERROR: "Enter the pet name as text, or leave it blank.",
    },
    "age_value": {
        "greater_than_equal": "Enter an age between 0 and 40.",
        "less_than_equal": "Enter an age between 0 and 40.",
        ANY_ERROR: "Enter the age as a number, e.g. 3.",
    },
    "age_unit": {
        ANY_ERROR: "Choose whether the age is in months or years.",
    },
    "sex": {
        ANY_ERROR: "Choose the sex: male, female, or unknown.",
    },
    "neutered": {
        ANY_ERROR: "Choose whether the pet is neutered, or leave it blank.",
    },
    "breed": {
        "string_too_long": "The breed can be at most 60 characters.",
        ANY_ERROR: "Enter the breed as text, or leave it blank.",
    },
    # The wording W-03 shows under the weight field.
    "weight_kg": {
        "greater_than_equal": "Enter a weight between 0.1 and 120 kg.",
        "less_than_equal": "Enter a weight between 0.1 and 120 kg.",
        ANY_ERROR: "Enter the weight as a number, e.g. 4.2.",
    },
    "owner_name": {
        "string_too_long": "The owner name can be at most 80 characters.",
        ANY_ERROR: "Enter the owner name as text, or leave it blank.",
    },
    "contact_number": {
        "string_too_long": "The contact number can be at most 30 characters.",
        ANY_ERROR: "Enter the contact number as text, or leave it blank.",
    },
    # --- Triage Queue filters, W-02 (FR-39) ------------------------------
    "category": {
        ANY_ERROR: "Choose a category: red, orange, yellow, green, blue, or manual triage.",
    },
    "status": {
        ANY_ERROR: "Choose a case status from the list.",
    },
    "date_from": {
        ANY_ERROR: "Enter the start date as a calendar date, e.g. 2026-10-01.",
    },
    "date_to": {
        ANY_ERROR: "Enter the end date as a calendar date, e.g. 2026-10-01.",
    },
    "q": {
        "string_too_long": "The search text can be at most 100 characters.",
        ANY_ERROR: "Enter the text to search for.",
    },
    "limit": {
        ANY_ERROR: "Ask for between 1 and 500 cases at a time.",
    },
    "offset": {
        ANY_ERROR: "The number of cases to skip must be 0 or more.",
    },
}

# Where Pydantic puts the part of the request a field came from. Dropped from
# the reported field name, which the form matches against its own inputs.
_LOCATION_PREFIXES = frozenset({"body", "query", "path", "header", "cookie"})


def field_from_location(location: Sequence[object]) -> str | None:
    """The field name a Pydantic error points at, or None if it names no field.

    A whole-body error (`loc == ("body",)`) belongs to no single input, so the
    form has nothing to attach it to and gets None.
    """
    parts = [str(part) for part in location if str(part) not in _LOCATION_PREFIXES]
    if not parts:
        return None
    return ".".join(parts)


def plain_message(field: str | None, error_type: str) -> str | None:
    """The plain sentence for this failure, or None when there is no wording.

    The caller falls back to Pydantic's own message, so an unregistered field is
    a worse message rather than a missing one.
    """
    if field is None:
        return None
    # Nested fields are registered under their leaf name.
    by_type = MESSAGES.get(field.rsplit(".", 1)[-1])
    if by_type is None:
        return None
    return by_type.get(error_type) or by_type.get(ANY_ERROR)
