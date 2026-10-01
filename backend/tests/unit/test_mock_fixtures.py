"""The fixture loader behind the mock stages (P05 §5.2).

What is being protected here is determinism. The mock stages must replay the same
recorded answer for the same description on every run, in every environment, and
must find *no* match rather than a near match for anything the file does not hold
exactly — a half-matching fixture would attach passages to an extraction they do
not support.

All data is fictitious (CLAUDE.md §9).
"""

import uuid
from pathlib import Path

import pytest

from app.core.config import MockLLMBehavior
from app.models.enums import Species
from app.pipeline.mock_fixtures import (
    FIXTURE_PATH_ENV,
    MockFixture,
    coerce_signalment,
    find_by_extraction,
    find_by_text,
    fixture_path,
    load_fixtures,
    mock_chunk_id,
    mock_entry_id,
    normalize,
)
from app.pipeline.mocks import generic_extraction

EXPECTED_IDS = ["DEMO_1", "DEMO_2", "DEMO_3", "DEMO_4"]


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    """`load_fixtures` is cached per process; each test re-reads the file."""
    load_fixtures.cache_clear()
    yield
    load_fixtures.cache_clear()


@pytest.fixture
def demo_1() -> MockFixture:
    return load_fixtures()["DEMO_1"]


# --- Loading --------------------------------------------------------------


def test_every_demo_scenario_loads() -> None:
    assert list(load_fixtures()) == EXPECTED_IDS


def test_the_default_path_is_the_fixture_file_in_the_repository() -> None:
    assert fixture_path().name == "demo_cases.yaml"
    assert fixture_path().is_file()


def test_a_missing_fixture_file_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment without `tests/` must still start (ADR-17).

    Every stage then takes its generic path, which is a working pipeline — just
    one with no recorded demo scenarios.
    """
    monkeypatch.setenv(FIXTURE_PATH_ENV, "/nonexistent/demo_cases.yaml")

    assert load_fixtures() == {}
    assert find_by_text("anything at all") is None


def test_the_path_override_is_honoured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    smaller = tmp_path / "demo_cases.yaml"
    smaller.write_text(
        "cases:\n"
        "  - id: ONLY\n"
        "    species: DOG\n"
        "    description: He is limping on his front left leg since this morning.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(FIXTURE_PATH_ENV, str(smaller))

    fixtures = load_fixtures()

    assert list(fixtures) == ["ONLY"]
    assert fixtures["ONLY"].red_flags == []
    assert fixtures["ONLY"].extraction is None
    assert fixtures["ONLY"].passages == []
    assert fixtures["ONLY"].draft is None
    assert fixtures["ONLY"].failure is None


# --- Normalisation and lookup by description ------------------------------


def test_normalize_collapses_every_run_of_whitespace() -> None:
    assert normalize("  He  cries\twhen he\n squats.  ") == "He cries when he squats."


def test_a_rewrapped_description_still_matches(demo_1: MockFixture) -> None:
    """Intake pastes text; line breaks and double spaces must not matter."""
    rewrapped = demo_1.description.replace(" ", "\n  ", 3)
    doubled = demo_1.description.replace(" ", "  ")

    assert find_by_text(demo_1.description) is demo_1
    assert find_by_text(f"  {demo_1.description}\n") is demo_1
    assert find_by_text(rewrapped) is demo_1
    assert find_by_text(doubled) is demo_1


def test_one_changed_word_matches_nothing(demo_1: MockFixture) -> None:
    """Equality, not similarity. A near miss is a non-match, by design."""
    assert find_by_text(demo_1.description.replace("litter box", "garden")) is None


def test_matching_is_case_sensitive(demo_1: MockFixture) -> None:
    """P05 §5.2 fixes the rule as equality after *whitespace* normalisation.

    Anything more — folding case, stripping punctuation — would be the start of
    matching logic this module must not contain (CLAUDE.md §8).
    """
    assert find_by_text(demo_1.description.lower()) is None


def test_an_unrelated_description_matches_nothing() -> None:
    assert find_by_text("She has been sneezing since yesterday.") is None


# --- Lookup by extraction -------------------------------------------------


@pytest.mark.parametrize("fixture_id", ["DEMO_1", "DEMO_2", "DEMO_3"])
def test_each_recorded_extraction_finds_its_own_fixture(fixture_id: str) -> None:
    """The retriever and generator never see the text, only this (CLAUDE.md §8.2)."""
    fixture = load_fixtures()[fixture_id]

    assert find_by_extraction(fixture.extraction) is fixture


def test_a_modified_extraction_finds_nothing(demo_1: MockFixture) -> None:
    modified = demo_1.extraction.model_copy(update={"onset_duration": "since this morning"})

    assert find_by_extraction(modified) is None


def test_the_generic_extraction_finds_nothing() -> None:
    assert find_by_extraction(generic_extraction(Species.CAT)) is None


# --- Derived values -------------------------------------------------------


def test_species_and_signalment_come_from_the_case(demo_1: MockFixture) -> None:
    """Not written in the YAML, so the extraction cannot drift from its case."""
    assert demo_1.species == Species.CAT
    assert demo_1.extraction.species == Species.CAT
    assert demo_1.extraction.signalment["pet_name"] == "Miso"
    assert demo_1.extraction.signalment["age_value"] == "3"


def test_signalment_numbers_and_flags_become_strings() -> None:
    assert coerce_signalment({"age_value": 3, "neutered": False, "breed": None}) == {
        "age_value": "3",
        "neutered": "False",
        "breed": None,
    }


def test_passages_are_ranked_from_one_in_file_order(demo_1: MockFixture) -> None:
    assert [p.rank for p in demo_1.passages] == [1, 2, 3]
    assert demo_1.passages[0].score > demo_1.passages[-1].score


def test_chunk_ids_are_the_uuid5_values_p05_specifies(demo_1: MockFixture) -> None:
    assert [p.chunk_id for p in demo_1.passages] == [
        mock_chunk_id("DEMO_1", rank) for rank in (1, 2, 3)
    ]
    assert mock_chunk_id("DEMO_1", 1) == uuid.uuid5(uuid.NAMESPACE_URL, "DEMO_11")


def test_passages_from_one_entry_share_an_entry_id(demo_1: MockFixture) -> None:
    """The review screen groups citations by entry."""
    first, second, third = demo_1.passages

    assert first.entry_title == second.entry_title
    assert first.entry_id == second.entry_id == mock_entry_id("DEMO_1", first.entry_title)
    assert third.entry_id != first.entry_id


def test_derived_ids_are_stable_across_reloads(demo_1: MockFixture) -> None:
    before = [p.chunk_id for p in demo_1.passages]
    load_fixtures.cache_clear()

    assert [p.chunk_id for p in load_fixtures()["DEMO_1"].passages] == before


def test_ids_differ_between_scenarios_and_ranks() -> None:
    assert mock_chunk_id("DEMO_1", 1) != mock_chunk_id("DEMO_2", 1)
    assert mock_chunk_id("DEMO_1", 1) != mock_chunk_id("DEMO_1", 2)


# --- The forced-failure scenario ------------------------------------------


def test_demo_4_records_a_failure_and_no_outputs() -> None:
    """The failure path demo (FR-15, NFR-09): it never reaches a later stage."""
    fixture = load_fixtures()["DEMO_4"]

    assert fixture.failure is MockLLMBehavior.INVALID_JSON
    assert fixture.extraction is None
    assert fixture.passages == []
    assert fixture.draft is None


def test_the_working_scenarios_record_no_failure() -> None:
    for fixture_id in ("DEMO_1", "DEMO_2", "DEMO_3"):
        assert load_fixtures()[fixture_id].failure is None
