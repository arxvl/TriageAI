"""The SRS targets an evaluation run is held against (NFR-01, NFR-16, NFR-17).

Data, not logic: the CLI report, the run endpoints and (in 9.3) the W-10 cards read
the same list, so a target is written down once. `path` says where the measured
value lives in the metrics dict; `unit_scale` converts it to the unit the target is
stated in (latency is stored in milliseconds, NFR-01 is in seconds).

A missed target is a valid result (NFR-16, M7 Step 4), so nothing here decides
anything beyond pass or fail for a value that exists.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Comparison(StrEnum):
    AT_LEAST = "at_least"
    AT_MOST = "at_most"


class TargetStatus(StrEnum):
    PASS = "PASS"  # noqa: S105 - a result label, not a credential
    FAIL = "FAIL"
    # The metric could not be computed (an empty set, no relevance judgements).
    NOT_AVAILABLE = "n/a"


@dataclass(frozen=True)
class Target:
    key: str
    label: str
    requirement: str
    path: tuple[str, ...]
    comparison: Comparison
    threshold: float
    unit: str = ""
    unit_scale: float = 1.0

    def measured(self, metrics: Mapping[str, Any]) -> float | None:
        """The metric's value in the target's unit, or None if it is not there."""
        node: Any = metrics
        for part in self.path:
            if not isinstance(node, Mapping) or part not in node:
                return None
            node = node[part]
        if node is None:
            return None
        return float(node) * self.unit_scale

    def status(self, metrics: Mapping[str, Any]) -> TargetStatus:
        value = self.measured(metrics)
        if value is None:
            return TargetStatus.NOT_AVAILABLE
        met = (
            value >= self.threshold
            if self.comparison is Comparison.AT_LEAST
            else (value <= self.threshold)
        )
        return TargetStatus.PASS if met else TargetStatus.FAIL

    def describe(self) -> dict[str, Any]:
        """The target as the API reports it."""
        return {
            "key": self.key,
            "label": self.label,
            "requirement": self.requirement,
            "comparison": self.comparison.value,
            "threshold": self.threshold,
            "unit": self.unit,
        }


TARGETS: tuple[Target, ...] = (
    Target(
        "macro_f1",
        "Macro-F1",
        "NFR-16",
        ("classification", "macro_f1"),
        Comparison.AT_LEAST,
        0.70,
    ),
    Target(
        "red_orange_recall",
        "Red+Orange recall",
        "NFR-16",
        ("classification", "red_orange_recall"),
        Comparison.AT_LEAST,
        0.90,
    ),
    Target(
        "under_triage_rate",
        "Under-triage rate",
        "NFR-16",
        ("classification", "under_triage_rate"),
        Comparison.AT_MOST,
        0.10,
    ),
    Target(
        "recall_at_k",
        "Recall@5",
        "NFR-17",
        ("retrieval", "recall_at_k"),
        Comparison.AT_LEAST,
        0.80,
    ),
    Target("mrr", "MRR", "NFR-17", ("retrieval", "mrr"), Comparison.AT_LEAST, 0.70),
    Target(
        "latency_p50",
        "Latency p50",
        "NFR-01",
        ("latency_ms", "total", "p50"),
        Comparison.AT_MOST,
        10.0,
        unit="s",
        unit_scale=0.001,
    ),
    Target(
        "latency_p95",
        "Latency p95",
        "NFR-01",
        ("latency_ms", "total", "p95"),
        Comparison.AT_MOST,
        20.0,
        unit="s",
        unit_scale=0.001,
    ),
)


def describe_targets() -> list[dict[str, Any]]:
    return [target.describe() for target in TARGETS]


def evaluate_targets(metrics: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Every target with its measured value and PASS / FAIL / n/a status.

    With no metrics (a run that has not finished) every status is `n/a`.
    """
    measured = metrics or {}
    return [
        {
            **target.describe(),
            "value": target.measured(measured),
            "status": target.status(measured).value,
        }
        for target in TARGETS
    ]
