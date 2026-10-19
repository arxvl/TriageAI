"""The importer's file formats accept what P08 §8.2 documents and nothing else.

No database: these are the checks that happen before a row is looked at. Every
failure has to name the file and the field, because a curator fixing a YAML file
has nothing else to go on.
"""

from pathlib import Path

import pytest
import yaml

from app.models.enums import KBEntryKind, VTLCategory
from app.pipeline.action_validator import MAX_WORDS
from app.schemas.kb import (
    ACTIONS_MAX_LINES,
    ACTIONS_MIN_LINES,
    CONTENT_MAX_WORDS,
    CONTENT_MIN_WORDS,
)
from app.schemas.kb_import import (
    RULES_FILENAME,
    KBEntryFile,
    parse_entry_file,
    parse_rules_file,
)
from tests.conftest import baseline_actions_content

# The repository's own knowledge_base/. Three levels up from
# backend/tests/unit/ is the repository root on the host, and `/` inside the
# container, where docker-compose mounts the directory at /knowledge_base — so
# the same expression finds it in both layouts.
KNOWLEDGE_BASE = Path(__file__).resolve().parents[3] / "knowledge_base"

SAMPLE_MARKER = "SAMPLE - not source-verified"


def entry_document(**overrides: object) -> dict:
    """A valid entry document, with `overrides` applied."""
    document = {
        "slug": "urinary-straining-cat",
        "title": "Straining or inability to urinate - cats",
        "complaint_code": "URINARY_OBSTRUCTION",
        "species": ["CAT"],
        "content": content_of(CONTENT_MIN_WORDS),
        "source": {
            "title": "Fixture Source",
            "publisher": "Fixture Publisher",
            "url": "https://example.invalid/fixture",
            "access_date": "2026-10-12",
        },
        "red_flag_codes": ["MALE_CAT_NO_URINE"],
    }
    document.update(overrides)
    return {key: value for key, value in document.items() if value is not ...}


def actions_document(**overrides: object) -> dict:
    """A valid `URGENCY_ACTIONS` document, with `overrides` applied (8.2b).

    The shape M5 Part D writes: `kind` and `urgency_category` instead of a
    `complaint_code`, content of one imperative action per line, and no
    `red_flag_codes` — a baseline set explains no red flag.
    """
    document = {
        "slug": "actions-orange",
        "kind": "URGENCY_ACTIONS",
        "urgency_category": "ORANGE",
        "title": "Suggested staff actions - Orange (very urgent, within 15 minutes)",
        "species": ["DOG", "CAT"],
        "content": baseline_actions_content(),
        "source": {
            "title": "Fixture Source",
            "publisher": "Fixture Publisher",
            "url": "https://example.invalid/fixture",
            "access_date": "2026-10-12",
        },
    }
    document.update(overrides)
    return {key: value for key, value in document.items() if value is not ...}


def content_of(words: int) -> str:
    return " ".join(["word"] * words)


def write_entry(tmp_path: Path, document: dict, *, name: str | None = None) -> Path:
    path = tmp_path / f"{name or document.get('slug', 'entry')}.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def write_rules(tmp_path: Path, document: object) -> Path:
    path = tmp_path / RULES_FILENAME
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def rule_document(**overrides: object) -> dict:
    rule = {
        "code": "MALE_CAT_NO_URINE",
        "label": "Male cat producing no urine",
        "min_category": "ORANGE",
        "species": ["CAT"],
        "phrases_ref": "MALE_CAT_NO_URINE",
    }
    rule.update(overrides)
    return {key: value for key, value in rule.items() if value is not ...}


# --- Entries --------------------------------------------------------------


def test_a_complete_entry_file_parses(tmp_path: Path) -> None:
    entry, errors = parse_entry_file(write_entry(tmp_path, entry_document()))

    assert errors == []
    assert entry is not None
    assert entry.slug == "urinary-straining-cat"
    assert entry.source.publisher == "Fixture Publisher"
    assert entry.red_flag_codes == ["MALE_CAT_NO_URINE"]


@pytest.mark.parametrize(
    ("field", "expected_message"),
    [
        ("title", "Enter the title of the source this entry is written from."),
        ("publisher", "Enter the publisher of the source."),
        ("url", "Enter the link to the source."),
        ("access_date", "Enter the date you read the source, e.g. 2026-10-12."),
    ],
)
def test_every_missing_citation_field_is_named(
    tmp_path: Path, field: str, expected_message: str
) -> None:
    """FR-50: all four citation fields are required, and each says which it is."""
    source = entry_document()["source"]
    del source[field]

    _, errors = parse_entry_file(write_entry(tmp_path, entry_document(source=source)))

    assert [error.field for error in errors] == [f"source.{field}"]
    assert errors[0].message == expected_message


def test_a_missing_source_block_is_reported_as_one_error(tmp_path: Path) -> None:
    _, errors = parse_entry_file(write_entry(tmp_path, entry_document(source=...)))

    assert [error.field for error in errors] == ["source"]
    assert "source block" in errors[0].message


@pytest.mark.parametrize("words", [CONTENT_MIN_WORDS - 1, CONTENT_MAX_WORDS + 1])
def test_content_outside_the_word_bounds_is_rejected(tmp_path: Path, words: int) -> None:
    _, errors = parse_entry_file(write_entry(tmp_path, entry_document(content=content_of(words))))

    assert [error.field for error in errors] == ["content"]
    assert "between 50 and 1,500 words" in errors[0].message


@pytest.mark.parametrize("words", [CONTENT_MIN_WORDS, CONTENT_MAX_WORDS])
def test_content_on_the_word_bounds_is_accepted(tmp_path: Path, words: int) -> None:
    entry, errors = parse_entry_file(
        write_entry(tmp_path, entry_document(content=content_of(words)))
    )

    assert errors == []
    assert entry is not None


def test_a_slug_that_is_not_a_slug_is_rejected(tmp_path: Path) -> None:
    document = entry_document(slug="Urinary_Straining")

    _, errors = parse_entry_file(write_entry(tmp_path, document, name="Urinary_Straining"))

    assert [error.field for error in errors] == ["slug"]
    assert "lower-case letters" in errors[0].message


def test_the_slug_must_equal_the_filename(tmp_path: Path) -> None:
    """A file whose two names disagree would be upserted under the unread one."""
    _, errors = parse_entry_file(write_entry(tmp_path, entry_document(), name="something-else"))

    assert [error.field for error in errors] == ["slug"]
    assert "'something-else'" in errors[0].message


@pytest.mark.parametrize("key", ["red_flag_code", "sources", "category"])
def test_an_unknown_key_is_rejected_by_name(tmp_path: Path, key: str) -> None:
    """The misspellings `extra="forbid"` exists for.

    `red_flag_code` left alone would import an entry citing no rule at all, and
    `category` is the near-miss for `urgency_category` now that subphase 8.2b has
    added it (ADR-18).
    """
    _, errors = parse_entry_file(write_entry(tmp_path, entry_document(**{key: "COMPLAINT"})))

    assert [error.field for error in errors] == [key]
    assert errors[0].message == "is not a field of this file format. Remove it."


def test_an_empty_species_list_is_rejected(tmp_path: Path) -> None:
    _, errors = parse_entry_file(write_entry(tmp_path, entry_document(species=[])))

    assert [error.field for error in errors] == ["species"]
    assert errors[0].message == "Choose at least one species: dog, cat, or both."


def test_every_problem_in_one_file_is_reported_together(tmp_path: Path) -> None:
    """P08 §8.2: "Report every error with its file and field"."""
    document = entry_document(title="", species=[], content=content_of(3))

    _, errors = parse_entry_file(write_entry(tmp_path, document))

    assert sorted(error.field or "" for error in errors) == ["content", "species", "title"]
    assert all(error.path.name == "urinary-straining-cat.yaml" for error in errors)


def test_a_file_error_line_names_the_file_and_the_field(tmp_path: Path) -> None:
    _, errors = parse_entry_file(write_entry(tmp_path, entry_document(species=[])))

    assert errors[0].line().strip().startswith("urinary-straining-cat.yaml [species]:")


def test_species_are_deduplicated() -> None:
    entry = KBEntryFile.model_validate(entry_document(species=["CAT", "CAT", "DOG"]))

    assert [str(species) for species in entry.species] == ["CAT", "DOG"]


# --- Urgency-action entries (P08 §8.2b, ADR-18) ---------------------------
# A baseline action set is an entry like any other, and the format differs in
# exactly three ways: `kind`, `urgency_category` in place of `complaint_code`,
# and content that is lines rather than prose.


def test_an_urgency_actions_file_parses() -> None:
    entry = KBEntryFile.model_validate(actions_document())

    assert entry.kind is KBEntryKind.URGENCY_ACTIONS
    assert entry.urgency_category is VTLCategory.ORANGE
    assert entry.complaint_code is None
    assert entry.red_flag_codes == []


def test_an_entry_file_without_a_kind_is_a_complaint_entry() -> None:
    """Every file written before 8.2b still means what it did (ADR-18)."""
    entry = KBEntryFile.model_validate(entry_document())

    assert entry.kind is KBEntryKind.COMPLAINT
    assert entry.urgency_category is None


def test_an_urgency_actions_file_without_a_category_is_rejected(tmp_path: Path) -> None:
    """P08 §8.2b task 1: the file must name the category it is for."""
    _, errors = parse_entry_file(
        write_entry(tmp_path, actions_document(urgency_category=...), name="actions-orange")
    )

    assert [error.field for error in errors] == ["urgency_category"]
    assert "RED, ORANGE, YELLOW, GREEN or BLUE" in errors[0].message


def test_a_complaint_entry_that_sets_an_urgency_category_is_rejected(tmp_path: Path) -> None:
    """The two kinds are exclusive (ck_kb_entries_urgency_category_iff_urgency_actions)."""
    _, errors = parse_entry_file(write_entry(tmp_path, entry_document(urgency_category="ORANGE")))

    assert [error.field for error in errors] == ["urgency_category"]
    assert "baseline action set" in errors[0].message


def test_an_urgency_actions_file_that_sets_a_complaint_code_is_rejected(tmp_path: Path) -> None:
    _, errors = parse_entry_file(
        write_entry(
            tmp_path,
            actions_document(complaint_code="URINARY_OBSTRUCTION"),
            name="actions-orange",
        )
    )

    assert [error.field for error in errors] == ["complaint_code"]
    assert "urgency category" in errors[0].message


def test_a_complaint_entry_without_a_complaint_code_is_rejected(tmp_path: Path) -> None:
    _, errors = parse_entry_file(write_entry(tmp_path, entry_document(complaint_code=...)))

    assert [error.field for error in errors] == ["complaint_code"]


def test_an_urgency_actions_file_may_cite_no_red_flag_rule(tmp_path: Path) -> None:
    """`red_flag_rules.entry_id` names the entry that *explains* a rule (FR-49).

    A baseline action set explains nothing: it is not retrievable and is never
    cited in a rationale.
    """
    _, errors = parse_entry_file(
        write_entry(
            tmp_path,
            actions_document(red_flag_codes=["MALE_CAT_NO_URINE"]),
            name="actions-orange",
        )
    )

    assert [error.field for error in errors] == ["red_flag_codes"]


@pytest.mark.parametrize("lines", [ACTIONS_MIN_LINES - 1, ACTIONS_MAX_LINES + 1])
def test_an_urgency_actions_file_outside_the_line_bounds_is_rejected(
    tmp_path: Path, lines: int
) -> None:
    """M5 Part D: three to six actions per category, one per line."""
    _, errors = parse_entry_file(
        write_entry(
            tmp_path,
            actions_document(content=baseline_actions_content(lines)),
            name="actions-orange",
        )
    )

    assert [error.field for error in errors] == ["content"]
    assert f"between {ACTIONS_MIN_LINES} and {ACTIONS_MAX_LINES} actions" in errors[0].message


@pytest.mark.parametrize("lines", [ACTIONS_MIN_LINES, ACTIONS_MAX_LINES])
def test_an_urgency_actions_file_on_the_line_bounds_is_accepted(tmp_path: Path, lines: int) -> None:
    entry, errors = parse_entry_file(
        write_entry(
            tmp_path,
            actions_document(content=baseline_actions_content(lines)),
            name="actions-orange",
        )
    )

    assert errors == []
    assert entry is not None


def test_a_baseline_set_is_not_held_to_the_fifty_word_floor(tmp_path: Path) -> None:
    """Three short imperatives are about twenty words, and that is the point."""
    content = baseline_actions_content()
    assert len(content.split()) < CONTENT_MIN_WORDS

    entry, errors = parse_entry_file(
        write_entry(tmp_path, actions_document(content=content), name="actions-orange")
    )

    assert errors == []
    assert entry is not None


def test_a_baseline_line_over_the_word_limit_is_rejected(tmp_path: Path) -> None:
    long_line = " ".join(["monitor"] * (MAX_WORDS + 1))
    _, errors = parse_entry_file(
        write_entry(
            tmp_path,
            actions_document(content=f"{baseline_actions_content()}\n{long_line}"),
            name="actions-orange",
        )
    )

    assert [error.field for error in errors] == ["content"]
    assert f"Line 4 is longer than {MAX_WORDS} words" in errors[0].message


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Give butorphanol for the pain", "names a medication"),
        ("Give 0.2 mg/kg of the usual analgesic", "names a dose"),
        ("The cat has a urethral obstruction", "states a diagnosis"),
    ],
)
def test_a_baseline_line_past_the_fr28_boundary_is_rejected(
    tmp_path: Path, line: str, expected: str
) -> None:
    """FR-28: baseline text is shown verbatim and never passes the validator."""
    _, errors = parse_entry_file(
        write_entry(
            tmp_path,
            actions_document(content=f"Alert the veterinarian immediately\n{line}\nPrepare oxygen"),
            name="actions-orange",
        )
    )

    assert [error.field for error in errors] == ["content"]
    assert errors[0].message.startswith("Line 2 ")
    assert expected in errors[0].message


# --- Malformed files ------------------------------------------------------


def test_unparsable_yaml_becomes_an_error_not_an_exception(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("slug: broken\n  title: [unclosed\n", encoding="utf-8")

    entry, errors = parse_entry_file(path)

    assert entry is None
    assert [error.field for error in errors] == [None]
    assert "not valid YAML" in errors[0].message


def test_an_empty_file_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("# nothing but a comment\n", encoding="utf-8")

    _, errors = parse_entry_file(path)

    assert errors[0].message == "is empty."


def test_a_document_that_is_not_a_mapping_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- one\n- two\n", encoding="utf-8")

    _, errors = parse_entry_file(path)

    assert "must be a mapping" in errors[0].message


# --- Red-flag rules -------------------------------------------------------


def test_a_rules_file_parses(tmp_path: Path) -> None:
    rules, errors = parse_rules_file(write_rules(tmp_path, {"rules": [rule_document()]}))

    assert errors == []
    assert [rule.code for rule in rules] == ["MALE_CAT_NO_URINE"]


def test_an_imported_rule_is_a_placeholder_by_default(tmp_path: Path) -> None:
    """A rule that arrived from a file has not been approved (NFR-08, BR-04)."""
    rules, _ = parse_rules_file(write_rules(tmp_path, {"rules": [rule_document()]}))

    assert rules[0].is_placeholder is True


def test_a_bad_minimum_category_is_rejected(tmp_path: Path) -> None:
    document = {"rules": [rule_document(min_category="PURPLE")]}

    _, errors = parse_rules_file(write_rules(tmp_path, document))

    assert [error.field for error in errors] == ["rules.0.min_category"]
    assert "lowest urgency category" in errors[0].message


def test_a_bad_rule_code_is_rejected(tmp_path: Path) -> None:
    _, errors = parse_rules_file(write_rules(tmp_path, {"rules": [rule_document(code="no urine")]}))

    assert [error.field for error in errors] == ["rules.0.code"]
    assert "capital letters" in errors[0].message


def test_a_duplicate_rule_code_is_rejected(tmp_path: Path) -> None:
    """Two rules with one code would let the upsert order decide the winner."""
    document = {"rules": [rule_document(), rule_document(label="A second definition")]}

    _, errors = parse_rules_file(write_rules(tmp_path, document))

    assert [error.field for error in errors] == ["rules"]
    assert "more than once" in errors[0].message


def test_an_empty_rules_list_is_rejected(tmp_path: Path) -> None:
    _, errors = parse_rules_file(write_rules(tmp_path, {"rules": []}))

    assert [error.field for error in errors] == ["rules"]


def test_an_unknown_key_in_a_rule_is_rejected(tmp_path: Path) -> None:
    """`phrases` in particular: the phrases are maintained by hand (M1)."""
    document = {"rules": [rule_document(phrases=["no urine"])]}

    _, errors = parse_rules_file(write_rules(tmp_path, document))

    assert [error.field for error in errors] == ["rules.0.phrases"]


# --- The files this repository ships --------------------------------------


def test_the_shipped_rules_file_parses() -> None:
    rules, errors = parse_rules_file(KNOWLEDGE_BASE / RULES_FILENAME)

    assert errors == []
    assert len(rules) >= 1
    assert all(rule.is_placeholder for rule in rules), (
        "no rule in the repository has been approved; approval happens in W-08"
    )


def test_the_shipped_sample_entries_parse_and_are_marked_as_samples() -> None:
    """The two entries in `entries/` are placeholders replaced in M5.

    Asserted so an unreplaced sample cannot quietly become the content the
    evaluation runs against (CLAUDE.md §9).
    """
    paths = sorted((KNOWLEDGE_BASE / "entries").glob("*.yaml"))

    assert len(paths) == 2
    for path in paths:
        entry, errors = parse_entry_file(path)
        assert errors == [], f"{path.name}: {[error.line() for error in errors]}"
        assert entry is not None
        assert entry.content.startswith(SAMPLE_MARKER)
        assert entry.source.title == SAMPLE_MARKER
