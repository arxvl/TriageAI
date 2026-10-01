"""Every validation message is something a user can act on (IR-05).

IR-05 forbids technical codes and developer wording in anything the UI shows, and
`i18n/strings.ts` adds that no displayed string may contain an API field name.
These checks hold the whole table to that, so a message added in a later phase
cannot quietly reintroduce "Input should be a valid decimal".
"""

import pytest

from app.core.validation_messages import (
    ANY_ERROR,
    MESSAGES,
    field_from_location,
    plain_message,
)

# Wording that means the sentence was written for a developer, not for staff.
JARGON = (
    "Input should",
    "String should",
    "Value error",
    "Assertion failed",
    "pydantic",
    "None",
    "null",
)

ALL_SENTENCES = [
    (field, error_type, sentence)
    for field, by_type in MESSAGES.items()
    for error_type, sentence in by_type.items()
]


@pytest.mark.parametrize(("field", "error_type", "sentence"), ALL_SENTENCES)
def test_every_message_is_a_plain_sentence(field: str, error_type: str, sentence: str) -> None:
    assert sentence == sentence.strip()
    assert sentence[0].isupper(), sentence
    assert sentence.endswith((".", "?")), sentence


@pytest.mark.parametrize(("field", "error_type", "sentence"), ALL_SENTENCES)
def test_no_message_names_a_field_or_an_error_type(
    field: str, error_type: str, sentence: str
) -> None:
    """Field names are snake_case, which is the giveaway worth testing for."""
    assert "_" not in sentence, sentence
    for term in JARGON:
        assert term not in sentence, f"{sentence!r} contains developer wording {term!r}"


@pytest.mark.parametrize("field", list(MESSAGES))
def test_every_field_has_a_fallback_message(field: str) -> None:
    """Without one, an unexpected error type would fall through to Pydantic."""
    assert ANY_ERROR in MESSAGES[field], field


def test_a_specific_error_type_wins_over_the_fallback() -> None:
    assert plain_message("description", "missing") == MESSAGES["description"]["missing"]
    assert plain_message("description", "missing") != MESSAGES["description"][ANY_ERROR]


def test_an_unregistered_error_type_falls_back_within_the_field() -> None:
    assert plain_message("weight_kg", "no_such_error") == MESSAGES["weight_kg"][ANY_ERROR]


def test_the_weight_message_is_the_wording_from_the_wireframe() -> None:
    """W-03 shows this sentence under the weight field; the API must match it."""
    expected = "Enter the weight as a number, e.g. 4.2."
    assert plain_message("weight_kg", "decimal_parsing") == expected


def test_an_unregistered_field_has_no_message() -> None:
    """The caller then falls back to Pydantic's own, rather than inventing one."""
    assert plain_message("not_a_field", "missing") is None
    assert plain_message(None, "missing") is None


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        (("body", "weight_kg"), "weight_kg"),
        (("query", "limit"), "limit"),
        (("path", "case_id"), "case_id"),
        (("body", "signalment", "weight_kg"), "signalment.weight_kg"),
    ],
)
def test_field_from_location_drops_the_request_part(
    location: tuple[str, ...], expected: str
) -> None:
    assert field_from_location(location) == expected


def test_a_whole_body_error_names_no_field() -> None:
    """There is no input to attach it to, so the form shows it at the top."""
    assert field_from_location(("body",)) is None


def test_a_nested_field_resolves_by_its_leaf_name() -> None:
    assert (
        plain_message("signalment.weight_kg", "decimal_parsing")
        == (MESSAGES["weight_kg"][ANY_ERROR])
    )
