"""Vignette CSV validation: every problem found, reported by row (P09 §9.2 task 1).

All data is fictitious (CLAUDE.md §9).
"""

from pathlib import Path

from app.eval.importer import MAX_FILE_BYTES, MAX_ROWS, parse_vignette_csv
from app.models import Species, VTLCategory

HEADER = "external_id,species,description,reference_category,relevant_entry_slugs\n"
LONG_ENOUGH = "Two days of limping on the left hind leg, still eating well."
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "vignettes_mock.csv"


def parse(body: str, header: str = HEADER) -> object:
    return parse_vignette_csv((header + body).encode("utf-8"))


def row(external_id: str = "V-1", species: str = "DOG", category: str = "GREEN") -> str:
    return f'{external_id},{species},"{LONG_ENOUGH}",{category},\n'


def test_the_mock_fixture_is_a_valid_set_of_ten() -> None:
    result = parse_vignette_csv(FIXTURE.read_bytes())

    assert result.errors == []
    assert len(result.vignettes) == 10
    assert [v.external_id for v in result.vignettes][:2] == ["V-001", "V-002"]


def test_a_valid_row_is_parsed_with_its_slugs() -> None:
    body = (
        f'V-1,cat,"{LONG_ENOUGH}",orange, urinary-obstruction-cat ; skin-itch-dog;;skin-itch-dog\n'
    )

    result = parse(body)

    assert result.errors == []
    (vignette,) = result.vignettes
    assert vignette.species is Species.CAT
    assert vignette.reference_category is VTLCategory.ORANGE
    assert vignette.relevant_slugs == ["urinary-obstruction-cat", "skin-itch-dog"]
    assert vignette.row == 2


def test_every_problem_in_the_file_is_reported_with_its_row() -> None:
    body = (
        row("V-1")  # row 2, fine
        + row("V-2", species="HORSE")  # row 3
        + row("V-3", category="PURPLE")  # row 4
        + 'V-4,DOG,"too short",GREEN,\n'  # row 5
        + row("")  # row 6
    )

    result = parse(body)

    assert [(e.row, e.field) for e in result.errors] == [
        (3, "species"),
        (4, "reference_category"),
        (5, "description"),
        (6, "external_id"),
    ]
    assert [v.external_id for v in result.vignettes] == ["V-1"]


def test_a_quoted_description_over_several_lines_is_reported_at_the_line_it_starts_on() -> None:
    body = (
        row("V-1")  # line 2
        # Lines 3 to 5: one record whose description is quoted over three lines.
        + f'V-2,DOG,"{LONG_ENOUGH}\nSecond line of the same.\nThird line.",NOPE,\n'
        + row("V-3", species="HORSE")  # line 6
    )

    result = parse(body)

    assert [(e.row, e.field) for e in result.errors] == [(3, "reference_category"), (6, "species")]


def test_a_repeated_external_id_points_at_the_first_use() -> None:
    result = parse(row("V-1") + row("V-1"))

    (error,) = result.errors
    assert (error.row, error.field) == (3, "external_id")
    assert "row 2" in error.message


def test_a_missing_header_column_is_one_file_error() -> None:
    result = parse(row(), header="external_id,species,description,reference_category\n")

    (error,) = result.errors
    assert error.row == 1
    assert "relevant_entry_slugs" in error.message
    assert result.vignettes == []


def test_a_byte_order_mark_is_ignored() -> None:
    content = ("﻿" + HEADER + row()).encode("utf-8")

    result = parse_vignette_csv(content)

    assert result.errors == []
    assert len(result.vignettes) == 1


def test_a_file_that_is_not_utf8_is_refused() -> None:
    result = parse_vignette_csv(b"\xff\xfe\x00 not utf-8")

    (error,) = result.errors
    assert "UTF-8" in error.message


def test_a_file_with_no_rows_is_refused() -> None:
    (error,) = parse_vignette_csv(HEADER.encode()).errors
    assert "no vignettes" in error.message


def test_a_file_over_the_size_limit_is_refused_before_it_is_read() -> None:
    (error,) = parse_vignette_csv(b"x" * (MAX_FILE_BYTES + 1)).errors
    assert "larger than" in error.message


def test_a_file_over_the_row_limit_is_refused() -> None:
    body = "".join(row(f"V-{n}") for n in range(MAX_ROWS + 1))

    result = parse(body)

    assert any("more than" in error.message for error in result.errors)
