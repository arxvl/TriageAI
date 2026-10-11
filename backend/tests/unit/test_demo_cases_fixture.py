"""`demo_cases.yaml` parses and its values are real enum members.

The demo scenarios are referenced by the phase prompts from P05 onwards, so a
typo here would surface much later. These checks keep the fixture and the
domain constants (CLAUDE.md §6) from drifting apart.

From P05 §5.2 the file also holds the recorded answers the mock stages replay, so
the second half of this module checks the invariants those recordings have to
hold: red-flag codes the seeder actually creates, floors no weaker than the
seeded rule's, evidence spans that really are substrings of the description, and
citations that point at a passage the same scenario recorded. The loader itself is
tested in `test_mock_fixtures.py`; here the subject is the file's content.

P05b §5b.3 adds the recorded suggested actions, whose invariant is stricter than
the others: every one of them has to survive the deterministic action validator
unchanged. A recorded action that named a drug, a dose or a diagnosis would make
the demo show a rejection tally instead of a checklist, and would be a fixture
that contradicts FR-28.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.vtl import more_urgent
from app.models import (
    AgeUnit,
    CaseStatus,
    ConfidenceLevel,
    IntakeChannel,
    Sex,
    Species,
    VTLCategory,
)
from app.models.enums import ActionSource
from app.pipeline.action_validator import MAX_WORDS, validate
from app.pipeline.mock_fixtures import load_fixtures
from scripts.seed import COMPLAINTS, OTHER_COMPLAINT, RED_FLAG_RULES

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "demo_cases.yaml"

EXPECTED_IDS = ["DEMO_1", "DEMO_2", "DEMO_3", "DEMO_4"]
SEEDED_RULES = {rule.code: rule for rule in RED_FLAG_RULES}
SEEDED_RULE_CODES = set(SEEDED_RULES)
SEEDED_COMPLAINT_CODES = {code for code, _ in COMPLAINTS} | {OTHER_COMPLAINT[0]}

# The keys P05 §5.2 adds. Species and signalment are deliberately absent: the
# loader fills them from the case, so they cannot drift from it.
MOCK_EXTRACTION_FIELDS = {
    "presenting_complaints",
    "onset_duration",
    "frequency_severity",
    "associated_signs",
    "negated_findings",
    "exposure_history",
    "relevant_history",
    "red_flags",
    "missing_information",
    "evidence_spans",
}


def normalized_description(case: dict[str, Any]) -> str:
    return " ".join(case["description"].split())


def working_cases(demo_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The scenarios that run to a recommendation, i.e. all but the forced failure."""
    return [case for case in demo_cases if case.get("mock_failure") is None]


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


# --- The recorded mock outputs (P05 §5.2) --------------------------------


def test_every_scenario_records_its_red_flag_hits(demo_cases: list[dict[str, Any]]) -> None:
    """`mock_red_flags` is what the screener replays, so every case needs the key."""
    for case in demo_cases:
        hits = case["mock_red_flags"]
        assert [hit["rule_code"] for hit in hits] == case["expected_red_flag_codes"]


def test_recorded_hits_name_rules_the_seeder_creates(demo_cases: list[dict[str, Any]]) -> None:
    for case in demo_cases:
        for hit in case["mock_red_flags"]:
            assert hit["rule_code"] in SEEDED_RULE_CODES


def test_a_recorded_floor_is_never_weaker_than_the_rule(
    demo_cases: list[dict[str, Any]],
) -> None:
    """The replayed floor must not understate what the seeded rule requires (FR-23)."""
    for case in demo_cases:
        for hit in case["mock_red_flags"]:
            recorded = VTLCategory(hit["min_category"])
            seeded = SEEDED_RULES[hit["rule_code"]].min_category
            assert recorded == seeded or more_urgent(recorded, seeded)


def test_matched_text_is_a_substring_of_the_description(
    demo_cases: list[dict[str, Any]],
) -> None:
    """A hit quotes the text it fired on; the review screen highlights it."""
    for case in demo_cases:
        description = normalized_description(case)
        for hit in case["mock_red_flags"]:
            assert hit["matched_text"] in description


def test_every_working_scenario_records_a_full_extraction(
    demo_cases: list[dict[str, Any]],
) -> None:
    for case in working_cases(demo_cases):
        assert set(case["mock_extraction"]) == MOCK_EXTRACTION_FIELDS


def test_recorded_complaints_are_codes_the_seeder_creates(
    demo_cases: list[dict[str, Any]],
) -> None:
    for case in working_cases(demo_cases):
        complaints = case["mock_extraction"]["presenting_complaints"]
        assert [c["code"] for c in complaints if c["is_primary"]] != []
        for complaint in complaints:
            assert complaint["code"] in SEEDED_COMPLAINT_CODES


def test_a_working_scenario_never_records_other_as_its_primary_complaint(
    demo_cases: list[dict[str, Any]],
) -> None:
    """A primary `OTHER` means manual triage (P05 §5.3 rule 4).

    These three scenarios must reach a category, so none of them may record it.
    """
    for case in working_cases(demo_cases):
        primary = [c for c in case["mock_extraction"]["presenting_complaints"] if c["is_primary"]]
        assert [c["code"] for c in primary] != [OTHER_COMPLAINT[0]]


def test_evidence_spans_are_substrings_of_the_description(
    demo_cases: list[dict[str, Any]],
) -> None:
    """The contract requires an exact substring of the de-identified text.

    The mock de-identifier returns the text unchanged, so the description itself is
    what a span has to be found in. A span that drifted would break the review
    screen's highlighting without any test noticing.
    """
    for case in working_cases(demo_cases):
        description = normalized_description(case)
        spans = case["mock_extraction"]["evidence_spans"]
        assert spans
        for span in spans:
            assert span["text"] in description


def test_every_working_scenario_records_passages_with_a_usable_score(
    demo_cases: list[dict[str, Any]],
) -> None:
    """Above the retrieval floor, so `LOW_RETRIEVAL_SCORE` is not recorded (5.3 rule 3)."""
    for case in working_cases(demo_cases):
        passages = case["mock_passages"]
        assert passages
        assert all(0.30 <= passage["score"] <= 1.0 for passage in passages)
        assert [p["score"] for p in passages] == sorted(
            (p["score"] for p in passages), reverse=True
        )


def test_recorded_passages_name_a_placeholder_source(demo_cases: list[dict[str, Any]]) -> None:
    """No real veterinary publication is cited anywhere in the fixtures (CLAUDE.md §9).

    The knowledge base is written and approved by a veterinarian in P08/M5; until
    then a screenshot must not imply a source that was never consulted.
    """
    for case in working_cases(demo_cases):
        for passage in case["mock_passages"]:
            assert "Placeholder" in passage["source_title"]
            assert passage["source_url"] is None


def test_every_recorded_draft_cites_a_passage_it_recorded(
    demo_cases: list[dict[str, Any]],
) -> None:
    """An invalid citation is dropped by the validator (FR-22), which would then
    report `NO_VALID_CITATION` for a scenario meant to look well supported."""
    for case in working_cases(demo_cases):
        ranks = set(range(1, len(case["mock_passages"]) + 1))
        draft = case["mock_draft"]
        assert draft["cited_ranks"]
        assert set(draft["cited_ranks"]) <= ranks
        VTLCategory(draft["category"])
        ConfidenceLevel(draft["confidence"])
        assert draft["rationale"].strip()


def test_demo_1_records_a_yellow_draft_under_an_orange_floor(
    demo_cases: list[dict[str, Any]],
) -> None:
    """The FR-23 demonstration depends on these two disagreeing.

    If the recorded draft ever matched the floor, the safety validator would stop
    being visible in the walkthrough and the queue would show ORANGE for the wrong
    reason.
    """
    case = next(c for c in demo_cases if c["id"] == "DEMO_1")

    assert [h["min_category"] for h in case["mock_red_flags"]] == [VTLCategory.ORANGE]
    assert case["mock_draft"]["category"] == VTLCategory.YELLOW
    assert case["expected_category"] == VTLCategory.ORANGE


def test_demo_2_records_the_most_urgent_draft(demo_cases: list[dict[str, Any]]) -> None:
    case = next(c for c in demo_cases if c["id"] == "DEMO_2")

    assert case["mock_draft"]["category"] == VTLCategory.RED
    assert {h["min_category"] for h in case["mock_red_flags"]} == {VTLCategory.RED}


def test_demo_3_records_the_least_urgent_draft(demo_cases: list[dict[str, Any]]) -> None:
    case = next(c for c in demo_cases if c["id"] == "DEMO_3")

    assert case["mock_draft"]["category"] == VTLCategory.BLUE
    assert case["mock_red_flags"] == []


def test_demo_4_records_a_forced_failure_and_nothing_after_it(
    demo_cases: list[dict[str, Any]],
) -> None:
    """The failure path needs no `.env` change to demonstrate (FR-15, NFR-09)."""
    case = next(c for c in demo_cases if c["id"] == "DEMO_4")

    assert case["mock_failure"] == "invalid_json"
    assert "mock_extraction" not in case
    assert "mock_passages" not in case
    assert "mock_draft" not in case


# --- The recorded suggested actions (P05b §5b.3, FR-74, ADR-18) ----------


def test_every_scenario_records_suggested_actions(demo_cases: list[dict[str, Any]]) -> None:
    """All four, as P05b §5b.3 asks — see the next test about DEMO_4's."""
    for case in demo_cases:
        assert case.get("mock_actions"), case["id"]


def test_demo_4_records_actions_it_can_never_reach(demo_cases: list[dict[str, Any]]) -> None:
    """Stated so the dead data in the file is deliberate rather than an oversight.

    The actions stage is found by extraction (`find_by_extraction`), and this
    scenario records none because it fails before extraction returns. No
    recommendation is stored either, so no `SUGGEST_ACTIONS` job is ever
    enqueued for it.
    """
    case = next(c for c in demo_cases if c["id"] == "DEMO_4")

    assert case["mock_actions"]
    assert "mock_extraction" not in case
    assert load_fixtures()["DEMO_4"].extraction is None


def test_recorded_actions_are_all_model_produced(demo_cases: list[dict[str, Any]]) -> None:
    """Baseline actions live in the knowledge base, not here (FR-72, ADR-18 §2)."""
    sources = {action.get("source") for case in demo_cases for action in case["mock_actions"]}

    assert sources == {ActionSource.AI.value}


def test_recorded_actions_stay_within_the_word_limit(demo_cases: list[dict[str, Any]]) -> None:
    for case in demo_cases:
        for action in case["mock_actions"]:
            assert len(action["text"].split()) <= MAX_WORDS, (case["id"], action["text"])


def test_recorded_actions_cite_a_passage_the_same_scenario_recorded(
    demo_cases: list[dict[str, Any]],
) -> None:
    """As with the drafts: a citation the retriever never returned is dropped."""
    for case in working_cases(demo_cases):
        ranks = set(range(1, len(case["mock_passages"]) + 1))
        for action in case["mock_actions"]:
            assert action["cited_ranks"], (case["id"], action["text"])
            assert set(action["cited_ranks"]) <= ranks, (case["id"], action["text"])


def test_every_recorded_action_survives_the_validator(
    demo_cases: list[dict[str, Any]],
) -> None:
    """The one invariant that makes the demo show a checklist (FR-74, ADR-18 §4).

    Run through the real validator rather than re-checked by hand, so a block
    list that grows in M6b immediately tells the team which fixture line to
    reword.
    """
    for case in working_cases(demo_cases):
        scenario = load_fixtures()[case["id"]]

        kept, reasons = validate(list(scenario.actions), scenario.passages, max_items=5)

        assert reasons == [], case["id"]
        assert len(kept) == len(scenario.actions), case["id"]


def test_only_the_failure_scenario_forces_a_failure(demo_cases: list[dict[str, Any]]) -> None:
    forced = [case["id"] for case in demo_cases if case.get("mock_failure") is not None]

    assert forced == ["DEMO_4"]
    assert [case["id"] for case in demo_cases if case.get("force_failure")] == forced
