"""The deterministic action validator (P05b §5b.2, FR-74, NFR-30, ADR-18 §4).

These are the tests CLAUDE.md §10 calls non-negotiable, and NFR-30 is written in
terms of them: no displayed action may contain a medication name, a dose
expression or a diagnosis. The validator is the only thing that makes that true
of model output, so every blocked pattern is asserted directly — and so is the
other half, that ordinary triage wording still gets through. A validator that
rejects everything would satisfy NFR-30 and make the feature useless.

The pairs are the point. "Prepare oxygen and alert the veterinarian" passes while
"Give butorphanol 0.2 mg/kg IV" does not; "recheck every 15 minutes" passes while
"50 mcg" does not; "watch for signs of obstruction" passes while "the dog has
pneumonia" does not. Each pair is one line of FR-28 drawn in code.

All data here is fictitious, and none of it is clinical advice (CLAUDE.md §9).
"""

import uuid

import pytest

from app.models.enums import ActionSource
from app.pipeline.action_validator import (
    CONTAINS_DIAGNOSIS,
    CONTAINS_DOSE,
    CONTAINS_DRUG,
    DUPLICATE,
    MAX_WORDS,
    NO_VALID_CITATION,
    REJECTION_REASONS,
    TOO_LONG,
    baseline_line_failure,
    validate,
)
from app.pipeline.types import Passage, SuggestedAction

MAX_ITEMS = 5


def make_passage(rank: int) -> Passage:
    return Passage(
        rank=rank,
        chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, f"action-chunk-{rank}"),
        entry_id=uuid.uuid5(uuid.NAMESPACE_URL, "action-entry"),
        entry_title="Breathing difficulty in cats",
        source_title="Placeholder triage reference (invented for tests)",
        source_url=None,
        text="Placeholder passage text for the action validator tests.",
        score=0.80,
    )


def make_passages(count: int = 3) -> list[Passage]:
    return [make_passage(rank) for rank in range(1, count + 1)]


def make_action(text: str, cited_ranks: list[int] | None = None) -> SuggestedAction:
    return SuggestedAction(
        text=text,
        cited_ranks=[1] if cited_ranks is None else cited_ranks,
        source=ActionSource.AI,
    )


def only_reason(text: str, cited_ranks: list[int] | None = None) -> str:
    """Validate one action that is expected to be rejected, and name the reason."""
    kept, reasons = validate([make_action(text, cited_ranks)], make_passages(), MAX_ITEMS)
    assert kept == []
    assert len(reasons) == 1
    return reasons[0]


# --- Actions that must get through ----------------------------------------
# ADR-18 §1 lists the kinds of action that are in scope: escalate, prepare,
# monitor, ask the owner, transport. If one of these starts failing, the feature
# is broken even though NFR-30 still holds.
PASSING = (
    "Prepare oxygen and alert the veterinarian",
    "Monitor respiratory rate every few minutes",
    "Recheck the patient every 15 minutes",
    "Ask the owner whether the cat has eaten any toxin",
    "Watch for signs of obstruction",
    "Rule out obstruction",
    "Check whether the cat has asthma",
    "Transport the cat in a carrier and keep handling to a minimum",
    "Move the patient to the treatment area now",
)


@pytest.mark.parametrize("text", PASSING)
def test_triage_level_action_passes(text: str) -> None:
    kept, reasons = validate([make_action(text)], make_passages(), MAX_ITEMS)

    assert reasons == []
    assert [action.text for action in kept] == [text]
    # Text is never rewritten and the source tag is untouched (IR-23).
    assert kept[0].source is ActionSource.AI


def test_kept_action_keeps_only_retrieved_citations() -> None:
    """A rank the model invented is dropped; the action survives on the rest."""
    kept, reasons = validate(
        [make_action("Prepare oxygen and alert the veterinarian", [2, 99])],
        make_passages(),
        MAX_ITEMS,
    )

    assert reasons == []
    assert kept[0].cited_ranks == [2]


def test_duplicate_citations_collapse() -> None:
    kept, _ = validate(
        [make_action("Alert the veterinarian immediately", [1, 1, 2])],
        make_passages(),
        MAX_ITEMS,
    )

    assert kept[0].cited_ranks == [1, 2]


# --- Rule 1: citations (FR-74) --------------------------------------------


def test_action_with_no_valid_citation_is_rejected() -> None:
    """Stricter than FR-22: an uncited action is dropped, not labelled."""
    assert only_reason("Prepare oxygen and alert the veterinarian", [99]) == NO_VALID_CITATION


def test_action_with_empty_citations_is_rejected() -> None:
    assert only_reason("Prepare oxygen and alert the veterinarian", []) == NO_VALID_CITATION


def test_action_is_rejected_when_nothing_was_retrieved() -> None:
    kept, reasons = validate([make_action("Alert the veterinarian")], [], MAX_ITEMS)

    assert kept == []
    assert reasons == [NO_VALID_CITATION]


# --- Rule 2: length -------------------------------------------------------


def test_action_of_exactly_the_word_limit_passes() -> None:
    kept, reasons = validate(
        [make_action(" ".join(["monitor"] * MAX_WORDS))], make_passages(), MAX_ITEMS
    )

    assert reasons == []
    assert len(kept) == 1


def test_action_over_the_word_limit_is_rejected() -> None:
    assert only_reason(" ".join(["monitor"] * (MAX_WORDS + 1))) == TOO_LONG


# --- Rule 3: dose expressions ---------------------------------------------
DOSE_TEXTS = (
    "Give butorphanol 0.2 mg/kg IV",
    "Administer 2 mL of dextrose",
    "Prepare 50 mcg of the infusion",
    "Prepare 50 µg of the infusion",
    "Prepare 50 μg of the infusion",
    "Give 2 SC now",
    "Repeat the dose q8h",
    "Give the medication BID",
    "Prepare 500 IU before the veterinarian arrives",
    "Set the rate to 10 ml/kg",
    # Spelled out is still a dose: NFR-30 is about what a staff member reads.
    "Give 1 litre of fluids",
    "Prepare 2 grams of the powder",
)


@pytest.mark.parametrize("text", DOSE_TEXTS)
def test_dose_expression_is_rejected(text: str) -> None:
    assert only_reason(text) == CONTAINS_DOSE


def test_drug_with_a_dose_reports_the_dose_rule() -> None:
    """Rule order is fixed, so the stored code is the same every time.

    "Give butorphanol 0.2 mg/kg IV" breaks both rule 3 and rule 4. Rule 3 runs
    first, so it is the reason recorded — the action is rejected either way.
    """
    assert only_reason("Give butorphanol 0.2 mg/kg IV") == CONTAINS_DOSE
    assert only_reason("Give butorphanol before transport") == CONTAINS_DRUG


# --- Rule 4: medication names ---------------------------------------------
DRUG_TEXTS = (
    "Start antibiotics",
    "Give a sedative before transport",
    "Prepare dextrose for the veterinarian",
    "Prepare calcium gluconate",
    "Prepare hypertonic saline",
    "Ask the veterinarian about an NSAID",
    "Apply a steroid",
)


@pytest.mark.parametrize("text", DRUG_TEXTS)
def test_medication_name_is_rejected(text: str) -> None:
    assert only_reason(text) == CONTAINS_DRUG


# --- Rule 5: diagnosis assertions -----------------------------------------
DIAGNOSIS_TEXTS = (
    "The dog has pneumonia",
    "This is a pleural effusion",
    "The cat is in heart failure from cardiomyopathy",
    "Treat the bloat before the veterinarian arrives",
    # The hedge is there, but nine words away from the term: too far to be a
    # question about it.
    "Check the owner, the carrier and the waiting room before moving the dog with obstruction",
)


@pytest.mark.parametrize("text", DIAGNOSIS_TEXTS)
def test_asserted_diagnosis_is_rejected(text: str) -> None:
    assert only_reason(text) == CONTAINS_DIAGNOSIS


def test_hedged_diagnosis_passes_either_side_of_the_term() -> None:
    kept, reasons = validate(
        [
            make_action("Watch for signs of obstruction"),
            make_action("Report a possible pneumothorax to the veterinarian"),
            make_action("Note that obstruction is suspected and tell the veterinarian"),
        ],
        make_passages(),
        MAX_ITEMS,
    )

    assert reasons == []
    assert len(kept) == 3


# --- Rule 6: duplicates and the cap ---------------------------------------


def test_duplicates_collapse_to_one() -> None:
    kept, reasons = validate(
        [
            make_action("Alert the veterinarian immediately"),
            make_action("alert the veterinarian immediately."),
            make_action("Alert  the   veterinarian immediately"),
        ],
        make_passages(),
        MAX_ITEMS,
    )

    assert [action.text for action in kept] == ["Alert the veterinarian immediately"]
    assert reasons == [DUPLICATE, DUPLICATE]


def test_max_items_truncates_without_counting_a_rejection() -> None:
    """A cap is not a rejection: `rejected_count` stays a safety signal."""
    actions = [make_action(f"Recheck the patient during step number {index}") for index in range(8)]

    kept, reasons = validate(actions, make_passages(), MAX_ITEMS)

    assert len(kept) == MAX_ITEMS
    assert reasons == []


def test_max_items_of_zero_keeps_nothing() -> None:
    kept, reasons = validate([make_action("Alert the veterinarian")], make_passages(), 0)

    assert kept == []
    assert reasons == []


# --- Shape of the result --------------------------------------------------


def test_empty_input_returns_empty() -> None:
    assert validate([], make_passages(), MAX_ITEMS) == ([], [])


def test_empty_input_and_no_passages_returns_empty() -> None:
    assert validate([], [], MAX_ITEMS) == ([], [])


def test_one_reason_per_dropped_action() -> None:
    """`len(reasons)` is the `rejected_count` subphase 5b.3 stores."""
    actions = [
        make_action("Prepare oxygen and alert the veterinarian"),
        make_action("Give butorphanol 0.2 mg/kg IV"),
        make_action("Start antibiotics"),
        make_action("The dog has pneumonia"),
        make_action("Alert the veterinarian", [99]),
        make_action(" ".join(["monitor"] * (MAX_WORDS + 1))),
    ]

    kept, reasons = validate(actions, make_passages(), MAX_ITEMS)

    assert len(kept) == 1
    assert reasons == [
        CONTAINS_DOSE,
        CONTAINS_DRUG,
        CONTAINS_DIAGNOSIS,
        NO_VALID_CITATION,
        TOO_LONG,
    ]
    assert all(reason in REJECTION_REASONS for reason in reasons)


def test_inputs_are_not_mutated() -> None:
    """The caller's objects are also the provenance record (FR-26, ADR-14)."""
    actions = [make_action("Prepare oxygen and alert the veterinarian", [1, 99])]
    passages = make_passages()

    validate(actions, passages, MAX_ITEMS)

    assert actions[0].cited_ranks == [1, 99]
    assert [passage.rank for passage in passages] == [1, 2, 3]


# --- Baseline action lines (P08 §8.2b, FR-28, FR-72) ----------------------
# The lines of an `URGENCY_ACTIONS` entry are shown to staff verbatim and never
# pass `validate`, so the knowledge-base workflow screens them with the same
# four content rules before the entry can be imported or submitted.


@pytest.mark.parametrize(
    "text",
    [
        "Move the patient to the treatment area now",
        "Alert the veterinarian immediately",
        "Prepare oxygen and monitoring equipment",
        "Recheck breathing effort and alertness every 15 minutes",
        "Ask the owner whether the patient has passed any urine",
        "Carry the patient in; do not let it walk",
    ],
)
def test_a_triage_level_baseline_line_passes(text: str) -> None:
    """The other half of FR-28: ordinary baseline wording must get through."""
    assert baseline_line_failure(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Give butorphanol for pain", CONTAINS_DRUG),
        ("Give 0.2 mg/kg of the usual analgesic", CONTAINS_DOSE),
        ("Start antibiotics before the consultation", CONTAINS_DRUG),
        ("The cat has a urethral obstruction", CONTAINS_DIAGNOSIS),
    ],
)
def test_a_baseline_line_past_the_fr28_boundary_is_refused(text: str, expected: str) -> None:
    assert baseline_line_failure(text) == expected


def test_a_baseline_line_is_held_to_the_same_word_limit() -> None:
    assert baseline_line_failure(" ".join(["monitor"] * MAX_WORDS)) is None
    assert baseline_line_failure(" ".join(["monitor"] * (MAX_WORDS + 1))) == TOO_LONG


def test_a_baseline_line_needs_no_citation() -> None:
    """An approved `URGENCY_ACTIONS` entry is its own provenance (ADR-18 §2).

    `validate` drops an uncited action; a baseline line has nothing to cite and
    must not be refused for it (FR-74 against FR-72).
    """
    assert baseline_line_failure("Prepare oxygen and monitoring equipment") is None
    assert only_reason("Prepare oxygen and monitoring equipment", []) == NO_VALID_CITATION
