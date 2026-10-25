"""The evaluation metrics against numbers worked out by hand (P09 §9.2, FR-66..FR-68).

Every expected value below is derived in a comment, not computed by the code under
test: a metrics module that is wrong in the same way as its test proves nothing.
All data is fictitious (CLAUDE.md §9).
"""

import math

import pytest

from app.eval.metrics import VignetteOutcome, compute_metrics
from app.models import VTLCategory

RED, ORANGE, YELLOW, GREEN, BLUE = (
    VTLCategory.RED,
    VTLCategory.ORANGE,
    VTLCategory.YELLOW,
    VTLCategory.GREEN,
    VTLCategory.BLUE,
)
ORDER = (RED, ORANGE, YELLOW, GREEN, BLUE)

# Reference on the rows, prediction on the columns, in VTL order. Every row and every
# column sums to 5, which keeps the hand arithmetic short.
#
#          RED ORG YEL GRN BLU
#   RED  [  4,  1,  0,  0,  0 ]
#   ORG  [  1,  3,  1,  0,  0 ]
#   YEL  [  0,  1,  3,  1,  0 ]
#   GRN  [  0,  0,  1,  3,  1 ]
#   BLU  [  0,  0,  0,  1,  4 ]
MATRIX = [
    [4, 1, 0, 0, 0],
    [1, 3, 1, 0, 0],
    [0, 1, 3, 1, 0],
    [0, 0, 1, 3, 1],
    [0, 0, 0, 1, 4],
]


def outcomes_from(matrix: list[list[int]]) -> list[VignetteOutcome]:
    result: list[VignetteOutcome] = []
    for row, reference in enumerate(ORDER):
        for column, predicted in enumerate(ORDER):
            for copy in range(matrix[row][column]):
                result.append(
                    VignetteOutcome(
                        external_id=f"{reference.value}-{predicted.value}-{copy}",
                        reference=reference,
                        predicted=predicted,
                        primary_complaint="COMPLAINT",
                    )
                )
    return result


@pytest.fixture
def classification() -> dict:
    return compute_metrics(outcomes_from(MATRIX))["classification"]


# --- Classification: the 5x5 case ------------------------------------------


def test_the_confusion_matrix_is_in_vtl_order_with_the_reference_on_the_rows(
    classification: dict,
) -> None:
    assert classification["labels"] == ["RED", "ORANGE", "YELLOW", "GREEN", "BLUE"]
    assert classification["confusion_matrix"] == MATRIX
    assert classification["n"] == 25


def test_accuracy_is_the_diagonal_over_everything(classification: dict) -> None:
    # Diagonal 4 + 3 + 3 + 3 + 4 = 17 of 25.
    assert classification["accuracy"] == pytest.approx(17 / 25)


def test_per_category_precision_recall_and_f1(classification: dict) -> None:
    # Each row and column sums to 5, so precision = recall = diagonal / 5, and F1
    # equals both: 4/5 for RED and BLUE, 3/5 for the three in the middle.
    per_category = classification["per_category"]
    for label, expected in {
        "RED": 0.8,
        "ORANGE": 0.6,
        "YELLOW": 0.6,
        "GREEN": 0.6,
        "BLUE": 0.8,
    }.items():
        assert per_category[label]["precision"] == pytest.approx(expected)
        assert per_category[label]["recall"] == pytest.approx(expected)
        assert per_category[label]["f1"] == pytest.approx(expected)
        assert per_category[label]["support"] == 5


def test_macro_f1_is_the_mean_of_the_five_f1_scores(classification: dict) -> None:
    # (0.8 + 0.6 + 0.6 + 0.6 + 0.8) / 5 = 3.4 / 5 = 0.68
    assert classification["macro_f1"] == pytest.approx(0.68)
    assert classification["macro_f1_labels"] == 5


def test_under_and_over_triage_are_the_two_triangles_of_the_matrix(classification: dict) -> None:
    # Right of the diagonal (predicted less urgent): RED->ORANGE, ORANGE->YELLOW,
    # YELLOW->GREEN, GREEN->BLUE = 4 of 25. Left of it is the mirror image, also 4.
    assert classification["under_triage_count"] == 4
    assert classification["under_triage_rate"] == pytest.approx(0.16)
    assert classification["over_triage_count"] == 4
    assert classification["over_triage_rate"] == pytest.approx(0.16)


def test_red_orange_recall_counts_a_miss_between_the_two_as_caught(classification: dict) -> None:
    # Reference RED or ORANGE: 10 vignettes. Predicted RED or ORANGE: RED row 4 + 1,
    # ORANGE row 1 + 3 = 9. 9 / 10 = 0.9.
    assert classification["red_orange_n"] == 10
    assert classification["red_orange_recall"] == pytest.approx(0.9)


def test_quadratic_weighted_kappa(classification: dict) -> None:
    # Weight (i - j)^2 / 16. Observed: eight cells one step off the diagonal, each
    # weight 1/16, so 8/16 = 0.5. Expected: every margin is 5 and n is 25, so every
    # cell expects 1; sum of (i - j)^2 over the 5x5 grid = 8*1 + 6*4 + 4*9 + 2*16 =
    # 100, so 100/16 = 6.25. kappa = 1 - 0.5 / 6.25 = 0.92.
    assert classification["weighted_kappa"] == pytest.approx(0.92)


def test_the_under_triaged_vignettes_are_listed_with_their_complaint(
    classification: dict,
) -> None:
    listed = classification["under_triaged"]

    assert len(listed) == 4
    assert {(item["reference"], item["predicted"]) for item in listed} == {
        ("RED", "ORANGE"),
        ("ORANGE", "YELLOW"),
        ("YELLOW", "GREEN"),
        ("GREEN", "BLUE"),
    }
    assert all(item["primary_complaint"] == "COMPLAINT" for item in listed)


# --- Classification: edges --------------------------------------------------


def test_macro_f1_averages_over_the_categories_that_occur() -> None:
    # Two RED predictions are right, one ORANGE vignette is called RED.
    #   RED: precision 2/3, recall 2/2 -> F1 = 2 * (2/3) * 1 / (2/3 + 1) = 0.8
    #   ORANGE: nothing predicted ORANGE (precision undefined, counts as 0), recall
    #   0/1 = 0 -> F1 = 0
    # GREEN, YELLOW and BLUE occur nowhere, so they are not averaged: (0.8 + 0) / 2.
    outcomes = [
        VignetteOutcome("a", RED, RED),
        VignetteOutcome("b", RED, RED),
        VignetteOutcome("c", ORANGE, RED),
    ]

    classification = compute_metrics(outcomes)["classification"]

    assert classification["macro_f1_labels"] == 2
    assert classification["macro_f1"] == pytest.approx(0.4)
    assert classification["per_category"]["ORANGE"]["precision"] is None
    assert classification["per_category"]["BLUE"]["f1"] is None


def test_an_empty_run_has_undefined_metrics_not_errors() -> None:
    metrics = compute_metrics([])

    assert metrics["counts"] == {"total": 0, "failed": 0, "scored": 0}
    classification = metrics["classification"]
    for key in (
        "accuracy",
        "macro_f1",
        "weighted_kappa",
        "under_triage_rate",
        "over_triage_rate",
        "red_orange_recall",
    ):
        assert classification[key] is None
    assert metrics["retrieval"]["mrr"] is None
    assert metrics["latency_ms"]["total"]["p50"] is None


def test_a_run_of_one_category_has_no_kappa_but_a_perfect_score() -> None:
    outcomes = [VignetteOutcome(f"v{i}", GREEN, GREEN) for i in range(3)]

    classification = compute_metrics(outcomes)["classification"]

    assert classification["accuracy"] == 1.0
    assert classification["macro_f1"] == 1.0
    assert classification["weighted_kappa"] is None
    assert classification["red_orange_recall"] is None


# --- Failed vignettes -------------------------------------------------------


def test_failed_vignettes_are_counted_and_left_out_of_every_metric() -> None:
    outcomes = [
        VignetteOutcome("ok-1", RED, RED, latencies_ms={"total": 1000, "extract": 400}),
        VignetteOutcome("ok-2", BLUE, BLUE, latencies_ms={"total": 3000, "extract": 600}),
        # A failure would be an under-triage and a 90-second outlier if it counted.
        VignetteOutcome(
            "failed",
            RED,
            None,
            relevant_entry_ids=["e1"],
            retrieved_entry_ids=[],
            latencies_ms={"total": 90000, "extract": 90000},
        ),
    ]

    metrics = compute_metrics(outcomes)

    assert metrics["counts"] == {"total": 3, "failed": 1, "scored": 2}
    classification = metrics["classification"]
    assert classification["n"] == 2
    assert classification["accuracy"] == 1.0
    assert classification["under_triage_count"] == 0
    assert classification["red_orange_n"] == 1
    assert metrics["retrieval"]["n"] == 0
    assert metrics["latency_ms"]["total"] == {"p50": 2000.0, "p95": 2900.0, "n": 2}


# --- Retrieval --------------------------------------------------------------


def ranked(external_id: str, relevant: list[str], retrieved: list[str]) -> VignetteOutcome:
    return VignetteOutcome(
        external_id,
        YELLOW,
        YELLOW,
        relevant_entry_ids=relevant,
        retrieved_entry_ids=retrieved,
    )


def test_retrieval_metrics_against_a_worked_example() -> None:
    # k = 5, three judged vignettes.
    #
    # A: relevant {a, b}; retrieved [x, a, y, b, z] -> hits at ranks 2 and 4.
    #    P@5 = 2/5 = 0.4        R@5 = 2/2 = 1       RR = 1/2 = 0.5
    #    DCG = 1/log2(3) + 1/log2(5); ideal = 1/log2(2) + 1/log2(3)
    # B: relevant {c}; retrieved [c, d, e, f, g] -> hit at rank 1.
    #    P@5 = 1/5 = 0.2        R@5 = 1             RR = 1             nDCG = 1
    # C: relevant {h, i, j}; nothing relevant retrieved -> all four are 0.
    # D: relevant {} -> not judged, so not counted.
    ndcg_a = (1 / math.log2(3) + 1 / math.log2(5)) / (1 / math.log2(2) + 1 / math.log2(3))
    outcomes = [
        ranked("A", ["a", "b"], ["x", "a", "y", "b", "z"]),
        ranked("B", ["c"], ["c", "d", "e", "f", "g"]),
        ranked("C", ["h", "i", "j"], ["p", "q", "r", "s", "t"]),
        ranked("D", [], ["a", "b"]),
    ]

    retrieval = compute_metrics(outcomes, k=5)["retrieval"]

    assert retrieval["k"] == 5
    assert retrieval["n"] == 3
    assert retrieval["precision_at_k"] == pytest.approx((0.4 + 0.2 + 0.0) / 3)
    assert retrieval["recall_at_k"] == pytest.approx((1 + 1 + 0) / 3)
    assert retrieval["mrr"] == pytest.approx((0.5 + 1 + 0) / 3)
    assert retrieval["ndcg_at_k"] == pytest.approx((ndcg_a + 1 + 0) / 3)
    # Spelled out for A: DCG 1.06161 / ideal 1.63093.
    assert ndcg_a == pytest.approx(0.65093, abs=1e-5)


def test_a_repeated_entry_counts_once_at_its_first_rank() -> None:
    # Retrieved [x, x, a, a, y] is the unique list [x, a, y]: a is at rank 2, so
    # P@5 = 1/5, recall 1, RR = 1/2, nDCG = (1/log2(3)) / 1.
    outcome = ranked("A", ["a"], ["x", "x", "a", "a", "y"])

    retrieval = compute_metrics([outcome], k=5)["retrieval"]

    assert retrieval["precision_at_k"] == pytest.approx(0.2)
    assert retrieval["recall_at_k"] == pytest.approx(1.0)
    assert retrieval["mrr"] == pytest.approx(0.5)
    assert retrieval["ndcg_at_k"] == pytest.approx(1 / math.log2(3))


def test_only_the_top_k_entries_are_judged() -> None:
    # The relevant entry is at rank 4; with k = 3 it is not retrieved at all.
    outcome = ranked("A", ["a"], ["x", "y", "z", "a"])

    retrieval = compute_metrics([outcome], k=3)["retrieval"]

    assert retrieval["recall_at_k"] == 0.0
    assert retrieval["mrr"] == 0.0


def test_retrieval_with_no_relevance_judgements_is_undefined() -> None:
    retrieval = compute_metrics([ranked("A", [], ["a"])])["retrieval"]

    assert retrieval["n"] == 0
    assert retrieval["precision_at_k"] is None
    assert retrieval["ndcg_at_k"] is None


# --- Latency ----------------------------------------------------------------


def test_latency_percentiles_use_linear_interpolation_per_stage() -> None:
    # total 1000..5000 ms: p50 = 3000; p95 sits at index 0.95 * 4 = 3.8, so
    # 4000 + 0.8 * 1000 = 4800. extract is the same series divided by ten.
    outcomes = [
        VignetteOutcome(
            f"v{n}", YELLOW, YELLOW, latencies_ms={"total": n * 1000, "extract": n * 100}
        )
        for n in range(1, 6)
    ]

    latency = compute_metrics(outcomes)["latency_ms"]

    assert latency["total"] == {"p50": 3000.0, "p95": 4800.0, "n": 5}
    assert latency["stages"]["extract"] == {"p50": 300.0, "p95": 480.0, "n": 5}
    assert set(latency["stages"]) == {"extract"}
