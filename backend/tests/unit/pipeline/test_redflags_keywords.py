import time

import pytest

from app.models.enums import Species, VTLCategory
from app.pipeline.redflags_keywords import KeywordRedFlagScreener


class FakeRule:
    def __init__(self, code, min_category):
        self.code = code
        self.min_category = min_category


# Mirrors the seeded placeholder rules; edit if yours differ.
ACTIVE_RULES = [
    FakeRule("NOT_BREATHING", VTLCategory.RED),
    FakeRule("UNRESPONSIVE", VTLCategory.RED),
    FakeRule("ACTIVE_SEIZURE", VTLCategory.RED),
    FakeRule("UNCONTROLLED_BLEEDING", VTLCategory.RED),
    FakeRule("BLUE_GUMS_CYANOSIS", VTLCategory.RED),
    FakeRule("PALE_GUMS", VTLCategory.ORANGE),
    FakeRule("MALE_CAT_NO_URINE", VTLCategory.ORANGE),
    FakeRule("TOXIN_INGESTION", VTLCategory.ORANGE),
]


@pytest.fixture
def screener():
    import yaml

    with open(
        "/knowledge_base/red_flag_phrases.yaml",
        encoding="utf-8",
    ) as fh:
        phrases = yaml.safe_load(fh)

    return KeywordRedFlagScreener(
        phrases,
        lambda: ACTIVE_RULES,
    )


# (case id, text, species, sex, expected rule codes)
CASES = [
    (
        "male cat straining",
        "He keeps going to the litter box but nothing comes out.",
        Species.CAT,
        "MALE",
        {"MALE_CAT_NO_URINE"},
    ),
    (
        "unknown sex still fires",
        "He keeps going to the litter box but nothing comes out.",
        Species.CAT,
        "UNKNOWN",
        {"MALE_CAT_NO_URINE"},
    ),
    (
        "female cat does not fire",
        "She keeps going to the litter box but nothing comes out.",
        Species.CAT,
        "FEMALE",
        set(),
    ),
    (
        "negation suppresses",
        "No seizures, just vomiting.",
        Species.DOG,
        None,
        set(),
    ),
    (
        "dog bluish gums",
        "The dog has bluish gums.",
        Species.DOG,
        None,
        {"BLUE_GUMS_CYANOSIS"},
    ),
    (   "pale gums float to orange, not red",
        "His gums look pale this morning.",
        Species.DOG,
        None,
        {"PALE_GUMS"}),
    (
        "dog seizure 10 minutes ago",
        "The dog had a seizure 10 minutes ago.",
        Species.DOG,
        None,
        {"ACTIVE_SEIZURE"},
    ),
    (
        "dog ate rat poison",
        "The dog ate rat poison.",
        Species.DOG,
        None,
        {"TOXIN_INGESTION"},
    ),
    (
        "dog itching for two weeks",
        "The dog has been itching for two weeks.",
        Species.DOG,
        None,
        set(),
    ),
    (
        "dog with male cat urinary wording",
        "The dog keeps going to the litter box but nothing comes out.",
        Species.DOG,
        "MALE",
        set(),
    ),
]


@pytest.mark.parametrize(
    "case_id,text,species,sex,expected",
    CASES,
    ids=[case[0] for case in CASES],
)
def test_screen(screener, case_id, text, species, sex, expected):
    assert {
        hit.rule_code
        for hit in screener.screen(text, species, sex)
    } == expected


def test_unapproved_rule_never_fires(screener):
    screener._rules_provider = lambda: []

    assert screener.screen(
        "not breathing",
        Species.DOG,
        None,
    ) == []


def test_is_fast(screener):
    text = "the dog is vomiting and lethargic " * 60

    start = time.perf_counter()

    screener.screen(
        text,
        Species.DOG,
        None,
    )

    elapsed = time.perf_counter() - start

    assert elapsed < 0.05
