"""The evaluation report the CLI prints (P09 §9.2 task 5).

Markdown for pasting into the PD8 document, or the same data as JSON. Built from the
run as the API reports it (`EvaluationRunOut`), so the report, the endpoints and the
W-10 cards are three views of one set of stored numbers.

A missed target is a valid result (NFR-16, M7 Step 4), so the report says FAIL
plainly and then lists what failed. Counts are printed beside percentages, because
with 20-70 vignettes one case moves a rate by several points.
"""

import json
from typing import Any

from app.schemas.evaluation import EvaluationRunOut, TargetResultOut

__all__ = ["render_json", "render_markdown"]

MOCK_NOTICE = "**MOCK MODE – results are not model results.** Every stage ran on its mock (ADR-17)."


def _number(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _measured(target: TargetResultOut, metrics: dict[str, Any]) -> str:
    """The measured value as the target is stated, with the count behind a rate."""
    value = target.value
    if value is None:
        return "n/a"
    classification = metrics.get("classification") or {}
    retrieval = metrics.get("retrieval") or {}
    if target.key == "under_triage_rate":
        return (
            f"{_percent(value)} ({classification.get('under_triage_count')} of "
            f"{classification.get('n')})"
        )
    if target.key == "red_orange_recall":
        return f"{_number(value)} (of {classification.get('red_orange_n')} RED/ORANGE)"
    if target.key in {"recall_at_k", "mrr"}:
        return f"{_number(value)} (n={retrieval.get('n')})"
    if target.unit == "s":
        return f"{value:.1f} s"
    return _number(value)


def _threshold(target: TargetResultOut) -> str:
    sign = "≥" if target.comparison == "at_least" else "≤"
    if target.key == "under_triage_rate":
        return f"{sign} {target.threshold * 100:.0f}%"
    unit = f" {target.unit}" if target.unit else ""
    return f"{sign} {target.threshold:g}{unit}"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    return [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
        *("| " + " | ".join(row) + " |" for row in rows),
    ]


def render_markdown(run: EvaluationRunOut) -> str:
    metrics = run.metrics or {}
    counts = metrics.get("counts") or {}
    classification = metrics.get("classification") or {}
    retrieval = metrics.get("retrieval") or {}
    latency = metrics.get("latency_ms") or {}
    config = run.config or {}

    lines = [f"# Evaluation report – run {str(run.id)[:8]}", ""]
    if run.fully_mocked:
        lines += [f"> {MOCK_NOTICE}", ""]

    lines += [
        f"- **Set:** {run.set_name} ({run.progress.total} vignettes)",
        f"- **Status:** {run.status.value} ({run.progress.done} of {run.progress.total} done)",
        f"- **Started:** {run.started_at or 'n/a'} · **Finished:** {run.finished_at or 'n/a'}",
        f"- **Knowledge base version:** {run.kb_version_id or 'n/a'}",
        f"- **Model / prompt:** {config.get('model_id', 'n/a')} / "
        f"{config.get('prompt_version', 'n/a')} · top-k {config.get('top_k', 'n/a')} · "
        f"temperature {config.get('temperature', 'n/a')}",
        f"- **Scored:** {counts.get('scored', 0)} · **Failed (excluded from the metrics):** "
        f"{counts.get('failed', 0)}",
        "",
    ]

    if not metrics:
        lines += ["No metrics yet: the run has not finished.", ""]
        return "\n".join(lines)

    lines += ["## Targets (NFR-01, NFR-16, NFR-17)", ""]
    lines += _table(
        ["Metric", "Measured", "Target", "Requirement", "Result"],
        [
            [
                target.label,
                _measured(target, metrics),
                _threshold(target),
                target.requirement,
                target.status,
            ]
            for target in run.targets
        ],
    )
    missed = [target.label for target in run.targets if target.status == "FAIL"]
    lines += ["", f"Missed: {', '.join(missed)}." if missed else "No target missed.", ""]

    lines += ["## Classification", ""]
    lines += _table(
        ["Metric", "Value"],
        [
            ["Accuracy", _percent(classification.get("accuracy"))],
            ["Weighted kappa (quadratic)", _number(classification.get("weighted_kappa"))],
            [
                f"Macro-F1 (over {classification.get('macro_f1_labels', 0)} categories)",
                _number(classification.get("macro_f1")),
            ],
            [
                "Over-triage rate",
                f"{_percent(classification.get('over_triage_rate'))} "
                f"({classification.get('over_triage_count')} of {classification.get('n')})",
            ],
        ],
    )
    lines += [""]
    per_category = classification.get("per_category") or {}
    lines += _table(
        ["Category", "Precision", "Recall", "F1", "Support"],
        [
            [
                label,
                _number(values["precision"]),
                _number(values["recall"]),
                _number(values["f1"]),
                str(values["support"]),
            ]
            for label, values in per_category.items()
        ],
    )

    labels = classification.get("labels") or []
    lines += ["", "## Confusion matrix (rows: reference, columns: predicted)", ""]
    lines += _table(
        ["", *labels],
        [
            [label, *(str(count) for count in row)]
            for label, row in zip(
                labels, classification.get("confusion_matrix") or [], strict=False
            )
        ],
    )
    lines += ["", "Cells to the right of the diagonal are under-triaged.", ""]

    lines += [
        f"## Retrieval (k={retrieval.get('k')}, {retrieval.get('n', 0)} vignettes judged)",
        "",
    ]
    lines += _table(
        ["Metric", "Value"],
        [
            [f"Precision@{retrieval.get('k')}", _number(retrieval.get("precision_at_k"))],
            [f"Recall@{retrieval.get('k')}", _number(retrieval.get("recall_at_k"))],
            ["MRR", _number(retrieval.get("mrr"))],
            [f"nDCG@{retrieval.get('k')}", _number(retrieval.get("ndcg_at_k"))],
        ],
    )

    lines += ["", "## Latency (milliseconds)", ""]
    stages = {"whole pipeline": latency.get("total") or {}, **(latency.get("stages") or {})}
    lines += _table(
        ["Stage", "p50", "p95", "n"],
        [
            [
                name,
                _number(values.get("p50"), 0),
                _number(values.get("p95"), 0),
                str(values.get("n", 0)),
            ]
            for name, values in stages.items()
        ],
    )

    under = classification.get("under_triaged") or []
    lines += ["", "## Under-triaged vignettes – for veterinary review (NFR-14)", ""]
    if under:
        lines += _table(
            ["Vignette", "Reference", "Predicted", "Primary complaint"],
            [
                [
                    item["external_id"],
                    item["reference"],
                    item["predicted"],
                    item.get("primary_complaint") or "n/a",
                ]
                for item in under
            ],
        )
    else:
        lines += ["None."]
    lines += [""]
    return "\n".join(lines)


def render_json(run: EvaluationRunOut) -> str:
    return json.dumps(run.model_dump(mode="json"), indent=2, ensure_ascii=False)
