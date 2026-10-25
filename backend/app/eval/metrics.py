"""Evaluation metrics, as a pure function of the stored results (P09 §9.2, FR-66..FR-68).

Nothing here touches the database, a model or a clock: `compute_metrics` takes plain
`VignetteOutcome` values and returns a JSON-ready dict. That is what lets the runner
store the metrics, the CLI recompute them for a report, and the tests check them
against numbers worked out by hand.

Conventions, each of which changes a reported number if it is changed:

**Failed vignettes** — those with no predicted category — are counted and left out of
every other metric (classification, retrieval and latency). A pipeline failure is a
fact about reliability, reported as `counts.failed`, not a wrong answer to be
averaged in.

**Categories** are always in VTL order, RED to BLUE. The confusion matrix has the
reference on the rows and the prediction on the columns, so a cell to the right of
the diagonal is an under-triage.

**Undefined is `None`.** A ratio with an empty denominator is `None`, never `0.0`,
`NaN` or an exception: "no BLUE vignettes, so no BLUE recall" is not the same
statement as "BLUE recall was zero".

**Macro-F1** averages over the categories that occur — those with a reference
vignette or a prediction — and `macro_f1_labels` says how many. A 20-30 vignette
set may hold no BLUE case at all, and counting that as F1 = 0 would cap the figure
for a reason that has nothing to do with the system. Within an occurring category an
undefined precision or recall counts as 0 in its F1.

**Kappa** is quadratic-weighted over all five categories (FR-66): the disagreement
weight is the squared distance between categories, scaled to 0..1.

**Retrieval** is judged on unique `entry_id`s in rank order, truncated to `k`.
Precision@k divides by `k`, Recall@k by the number of relevant entries, MRR uses the
first relevant entry, and nDCG@k uses binary gain with a log2 discount. Only
vignettes with at least one relevance judgement count, and `retrieval.n` says how
many did.

**Latency** percentiles use numpy's default linear interpolation, in milliseconds.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.vtl import URGENCY_ORDER
from app.models.enums import VTLCategory

__all__ = ["DEFAULT_K", "VignetteOutcome", "compute_metrics"]

DEFAULT_K = 5

# Reference categories whose misses matter most (NFR-16).
_CRITICAL = (VTLCategory.RED, VTLCategory.ORANGE)

# The key `total` in a vignette's latencies is the whole run; the others are stages.
_TOTAL = "total"


@dataclass(frozen=True)
class VignetteOutcome:
    """What one vignette scored, reduced to what the metrics read.

    `predicted` is None when the pipeline failed on it.
    """

    external_id: str
    reference: VTLCategory
    predicted: VTLCategory | None
    relevant_entry_ids: Sequence[str] = ()
    retrieved_entry_ids: Sequence[str] = ()
    latencies_ms: Mapping[str, int | float] = field(default_factory=dict)
    primary_complaint: str | None = None

    @property
    def failed(self) -> bool:
        return self.predicted is None


def _rate(numerator: int | float, denominator: int | float) -> float | None:
    return None if denominator == 0 else float(numerator) / float(denominator)


def _f1(precision: float | None, recall: float | None) -> float:
    p, r = precision or 0.0, recall or 0.0
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


def _confusion(scored: Sequence[VignetteOutcome]) -> np.ndarray:
    size = len(URGENCY_ORDER)
    matrix = np.zeros((size, size), dtype=int)
    for outcome in scored:
        if outcome.predicted is None:  # callers pass scored vignettes only
            continue
        matrix[URGENCY_ORDER.index(outcome.reference), URGENCY_ORDER.index(outcome.predicted)] += 1
    return matrix


def _weighted_kappa(matrix: np.ndarray) -> float | None:
    """Quadratic-weighted Cohen's kappa; None when chance agreement is total."""
    total = matrix.sum()
    if total == 0:
        return None
    size = matrix.shape[0]
    distance = np.abs(np.subtract.outer(np.arange(size), np.arange(size)))
    weights = (distance / (size - 1)) ** 2
    expected = np.outer(matrix.sum(axis=1), matrix.sum(axis=0)) / total
    denominator = float((weights * expected).sum())
    if denominator == 0:
        return None
    return 1.0 - float((weights * matrix).sum()) / denominator


def _classification(scored: Sequence[VignetteOutcome]) -> dict[str, Any]:
    labels = [category.value for category in URGENCY_ORDER]
    matrix = _confusion(scored)
    n = int(matrix.sum())
    diagonal = int(np.trace(matrix))

    per_category: dict[str, dict[str, Any]] = {}
    f1_of_occurring: list[float] = []
    for index, label in enumerate(labels):
        true_positive = int(matrix[index, index])
        support = int(matrix[index, :].sum())
        predicted_count = int(matrix[:, index].sum())
        precision = _rate(true_positive, predicted_count)
        recall = _rate(true_positive, support)
        f1 = _f1(precision, recall) if (support or predicted_count) else None
        if f1 is not None:
            f1_of_occurring.append(f1)
        per_category[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
            "predicted": predicted_count,
        }

    order = {category: position for position, category in enumerate(URGENCY_ORDER)}
    under = [o for o in scored if order[o.predicted] > order[o.reference]]  # type: ignore[index]
    over = [o for o in scored if order[o.predicted] < order[o.reference]]  # type: ignore[index]
    critical = [o for o in scored if o.reference in _CRITICAL]
    critical_caught = [o for o in critical if o.predicted in _CRITICAL]

    return {
        "labels": labels,
        "n": n,
        "accuracy": _rate(diagonal, n),
        "per_category": per_category,
        "macro_f1": _rate(sum(f1_of_occurring), len(f1_of_occurring)),
        "macro_f1_labels": len(f1_of_occurring),
        "confusion_matrix": matrix.tolist(),
        "weighted_kappa": _weighted_kappa(matrix),
        "under_triage_rate": _rate(len(under), n),
        "under_triage_count": len(under),
        "over_triage_rate": _rate(len(over), n),
        "over_triage_count": len(over),
        "red_orange_recall": _rate(len(critical_caught), len(critical)),
        "red_orange_n": len(critical),
        "under_triaged": [
            {
                "external_id": o.external_id,
                "reference": o.reference.value,
                "predicted": o.predicted.value,  # type: ignore[union-attr]
                "primary_complaint": o.primary_complaint,
            }
            for o in under
        ],
    }


def _unique_in_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _retrieval(scored: Sequence[VignetteOutcome], k: int) -> dict[str, Any]:
    judged = [o for o in scored if o.relevant_entry_ids]
    precision: list[float] = []
    recall: list[float] = []
    reciprocal_rank: list[float] = []
    ndcg: list[float] = []

    for outcome in judged:
        relevant = set(outcome.relevant_entry_ids)
        retrieved = _unique_in_order(outcome.retrieved_entry_ids)[:k]
        hits = [entry in relevant for entry in retrieved]

        precision.append(sum(hits) / k)
        recall.append(sum(hits) / len(relevant))
        first = next((rank for rank, hit in enumerate(hits, start=1) if hit), None)
        reciprocal_rank.append(0.0 if first is None else 1.0 / first)

        dcg = sum(1.0 / math.log2(rank + 1) for rank, hit in enumerate(hits, start=1) if hit)
        ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
        ndcg.append(dcg / ideal)

    n = len(judged)
    return {
        "k": k,
        "n": n,
        "precision_at_k": _rate(sum(precision), n),
        "recall_at_k": _rate(sum(recall), n),
        "mrr": _rate(sum(reciprocal_rank), n),
        "ndcg_at_k": _rate(sum(ndcg), n),
    }


def _percentiles(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"p50": None, "p95": None, "n": 0}
    p50, p95 = np.percentile(np.asarray(values, dtype=float), [50, 95])
    return {"p50": float(p50), "p95": float(p95), "n": len(values)}


def _latency(scored: Sequence[VignetteOutcome]) -> dict[str, Any]:
    stage_names = sorted({name for o in scored for name in o.latencies_ms if name != _TOTAL})
    return {
        "total": _percentiles([o.latencies_ms[_TOTAL] for o in scored if _TOTAL in o.latencies_ms]),
        "stages": {
            name: _percentiles([o.latencies_ms[name] for o in scored if name in o.latencies_ms])
            for name in stage_names
        },
    }


def compute_metrics(outcomes: Sequence[VignetteOutcome], k: int = DEFAULT_K) -> dict[str, Any]:
    """All the metrics for one run. See the module docstring for every convention."""
    scored = [outcome for outcome in outcomes if not outcome.failed]
    return {
        "counts": {
            "total": len(outcomes),
            "failed": len(outcomes) - len(scored),
            "scored": len(scored),
        },
        "classification": _classification(scored),
        "retrieval": _retrieval(scored, k),
        "latency_ms": _latency(scored),
    }
