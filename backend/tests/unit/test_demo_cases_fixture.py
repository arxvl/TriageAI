"""`demo_cases.yaml` parses and its values are real enum members.

The demo scenarios are referenced by the phase prompts from P05 onwards, so a
typo here would surface much later. These checks keep the fixture and the
domain constants (CLAUDE.md §6) from drifting apart.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.models import AgeUnit, CaseStatus, IntakeChannel, Sex, Species, VTLCategory
from scripts.seed import RED_FLAG_RULES

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "demo_cases.yaml"

EXPECTED_IDS = ["DEMO_1", "DEMO_2", "DEMO_3", "DEMO_4"]
SEEDED_RULE_CODES = {rule.code for rule in RED_FLAG_RULES}


@pytest.fixture(scope="module")
def demo_cases() -> list[dict[str, Any]]:
    return yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]


def test_fixture_holds_the_four_demo_scenarios(demo_cases: list[dict[str, Any]]) -> None:
    assert [case["id"] for case in demo_cases] == EXPECTED_IDS


def test_enum_valued_fields_are_valid(demo_cases: list[dict[str, Any]]) -> None:
    for case in demo_cases:
        Species(case["species"])
        IntakeChannel(case["intake_channel"])
        CaseStatus(case["expected_status"])
        if case["expected_category"] is not None:
            VTLCategory(case["expected_category"])

        signalment = case["signalment"]
        Sex(signalment["sex"])
        AgeUnit(signalment["age_unit"])


def test_expected_red_flags_are_rules_the_seeder_creates(
    demo_cases: list[dict[str, Any]],
) -> None:
    for case in demo_cases:
        assert set(case["expected_red_flag_codes"]) <= SEEDED_RULE_CODES


def test_descriptions_are_non_empty(demo_cases: list[dict[str, Any]]) -> None:
    for case in demo_cases:
        assert case["description"].strip()
        assert case["notes"].strip()


def test_demo_1_demonstrates_the_safety_floor(demo_cases: list[dict[str, Any]]) -> None:
    case = next(c for c in demo_cases if c["id"] == "DEMO_1")

    assert case["species"] == Species.CAT
    assert case["signalment"]["sex"] == Sex.MALE
    assert case["expected_category"] == VTLCategory.ORANGE
    assert "MALE_CAT_NO_URINE" in case["expected_red_flag_codes"]


def test_demo_2_is_the_most_urgent(demo_cases: list[dict[str, Any]]) -> None:
    case = next(c for c in demo_cases if c["id"] == "DEMO_2")

    assert case["expected_category"] == VTLCategory.RED
    assert case["expected_red_flag_codes"]


def test_demo_3_has_no_red_flags(demo_cases: list[dict[str, Any]]) -> None:
    case = next(c for c in demo_cases if c["id"] == "DEMO_3")

    assert case["expected_category"] == VTLCategory.BLUE
    assert case["expected_red_flag_codes"] == []


def test_demo_4_produces_no_category(demo_cases: list[dict[str, Any]]) -> None:
    case = next(c for c in demo_cases if c["id"] == "DEMO_4")

    assert case["force_failure"] is True
    # A failed pipeline never leaves a category behind (FR-15, NFR-09).
    assert case["expected_category"] is None
    assert case["expected_status"] == CaseStatus.MANUAL_TRIAGE_REQUIRED
