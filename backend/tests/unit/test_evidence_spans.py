"""Locating evidence spans in the de-identified text (FR-13, FR-31).

Deterministic string work, so it is tested without a database. Every description
here is invented (CLAUDE.md §9).
"""

from app.services.evidence_spans import locate

TEXT = (
    "Since this morning he keeps going to the litter box and cries, but nothing "
    "comes out. He also vomited twice."
)


def span(field: str, text: str) -> dict:
    return {"field": field, "text": text}


# --- Found spans ----------------------------------------------------------


def test_a_span_is_located_at_its_offsets() -> None:
    located = locate([span("onset_duration", "Since this morning")], TEXT)

    assert len(located) == 1
    found = located[0]
    assert found.found is True
    assert found.start == 0
    assert found.end == len("Since this morning")
    assert TEXT[found.start : found.end] == "Since this morning"


def test_the_offsets_slice_the_text_back_out_for_every_span() -> None:
    """The property that matters to W-04: `text[start:end] == text`."""
    spans = [
        span("onset_duration", "Since this morning"),
        span("frequency_severity", "vomited twice"),
        span("associated_signs", "cries"),
    ]

    for located in locate(spans, TEXT):
        assert located.found is True
        assert TEXT[located.start : located.end] == located.text


def test_spans_come_back_in_the_order_they_were_stored() -> None:
    """Not sorted by offset: the order is the extraction's, so the panel lists
    the fields in the order the stage reported them."""
    spans = [span("a", "vomited twice"), span("b", "Since this morning")]

    assert [located.field for located in locate(spans, TEXT)] == ["a", "b"]


# --- Repeated text --------------------------------------------------------


def test_two_spans_quoting_the_same_phrase_get_successive_occurrences() -> None:
    """Searching from the start each time would stack both highlights on the
    first occurrence and leave the second one unmarked."""
    text = "He vomited once, then vomited again."
    located = locate([span("a", "vomited"), span("b", "vomited")], text)

    assert [item.start for item in located] == [3, 22]
    assert all(item.found for item in located)
    assert text[located[1].start : located[1].end] == "vomited"


def test_a_phrase_cited_more_often_than_it_occurs_runs_out() -> None:
    """The surplus span reports `found=false`. A wrong highlight is worse than
    a missing one."""
    located = locate([span("a", "vomited twice"), span("b", "vomited twice")], TEXT)

    assert located[0].found is True
    assert located[1].found is False
    assert located[1].start is None


def test_a_repeated_phrase_does_not_disturb_a_different_one() -> None:
    """The cursor is per distinct text, so one phrase running out does not push
    another phrase's search forward."""
    text = "cries, cries, and nothing comes out"
    located = locate(
        [span("a", "cries"), span("b", "cries"), span("c", "nothing comes out")],
        text,
    )

    assert [item.found for item in located] == [True, True, True]
    assert text[located[2].start : located[2].end] == "nothing comes out"


# --- Missing spans --------------------------------------------------------


def test_a_span_that_no_longer_matches_is_returned_and_marked() -> None:
    """Returned rather than dropped, so the panel can show the quoted evidence
    as text beside the value even when it cannot highlight it in place."""
    located = locate([span("relevant_history", "ate rat poison")], TEXT)

    assert len(located) == 1
    assert located[0].found is False
    assert located[0].start is None
    assert located[0].end is None
    assert located[0].text == "ate rat poison"


def test_every_span_is_unfound_when_there_is_no_stored_text() -> None:
    """An extraction written before migration 0004 has no `input_text`, and it
    cannot be reconstructed."""
    located = locate([span("onset_duration", "Since this morning")], None)

    assert [item.found for item in located] == [False]


def test_an_empty_stored_text_finds_nothing() -> None:
    assert [item.found for item in locate([span("a", "cries")], "")] == [False]


def test_an_empty_span_text_is_not_a_span() -> None:
    assert locate([span("a", "")], TEXT)[0].found is False


# --- Defensive reads of the JSONB column ----------------------------------


def test_no_spans_at_all_yields_an_empty_list() -> None:
    assert locate([], TEXT) == []


def test_a_malformed_column_yields_no_spans_rather_than_raising() -> None:
    """`evidence_spans` comes out of JSONB. A row written in an unexpected
    shape must not make the case unreadable."""
    assert locate(None, TEXT) == []
    assert locate({"field": "a"}, TEXT) == []
    assert locate("not a list", TEXT) == []


def test_malformed_entries_are_skipped_and_the_rest_survive() -> None:
    spans = [
        "not an object",
        {"field": "a"},
        {"text": "cries"},
        {"field": 7, "text": "cries"},
        {"field": "associated_signs", "text": "cries"},
    ]

    located = locate(spans, TEXT)

    assert [item.field for item in located] == ["associated_signs"]
    assert located[0].found is True
