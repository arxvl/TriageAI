"""Export a finished run: per-vignette rows plus the metrics (P09 §9.2, FR-69).

Two formats from one set of rows. JSON carries the metrics as an object. CSV has the
per-vignette table first, then a blank line and a `metric,value` section, so the
file opens in a spreadsheet as two blocks without a second download.

Vignette descriptions are not exported: the rows identify a vignette by its
`external_id`, which is all the analysis needs (BR-08). Every cell that starts with
a character a spreadsheet would read as a formula is prefixed so it stays text.
"""

import csv
import io
import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.csv_safety import text_cell
from app.core.vtl import URGENCY_ORDER
from app.repositories.evaluation_repository import ResultRow

__all__ = ["flatten_metrics", "rows_for_export", "to_csv", "to_json"]

FIXED_COLUMNS = (
    "external_id",
    "species",
    "reference_category",
    "predicted_category",
    "outcome",
    "confidence",
    "safety_floor_applied",
    "primary_complaint",
    "red_flag_rules",
    "retrieved_entry_ids",
    "relevant_entry_ids",
    "error",
)


def _outcome(row: ResultRow) -> str:
    predicted = row.result.predicted_category
    if predicted is None:
        return "FAILED"
    reference = row.vignette.reference_category
    position = URGENCY_ORDER.index
    if predicted == reference:
        return "CORRECT"
    return "UNDER_TRIAGE" if position(predicted) > position(reference) else "OVER_TRIAGE"


def rows_for_export(rows: Sequence[ResultRow]) -> list[dict[str, Any]]:
    """One plain dict per vignette, with the latencies as `latency_<stage>_ms`."""
    exported: list[dict[str, Any]] = []
    for row in rows:
        payload = row.result.payload or {}
        record: dict[str, Any] = {
            "external_id": row.vignette.external_id,
            "species": row.vignette.species.value,
            "reference_category": row.vignette.reference_category.value,
            "predicted_category": (
                None
                if row.result.predicted_category is None
                else row.result.predicted_category.value
            ),
            "outcome": _outcome(row),
            "confidence": payload.get("confidence"),
            "safety_floor_applied": payload.get("safety_floor_applied"),
            "primary_complaint": payload.get("primary_complaint"),
            "red_flag_rules": [hit["rule_code"] for hit in payload.get("red_flag_hits") or []],
            "retrieved_entry_ids": list(payload.get("retrieved_entry_ids") or []),
            "relevant_entry_ids": list(row.vignette.relevant_entry_ids or []),
            "error": row.result.error,
        }
        for stage, milliseconds in sorted((row.result.stage_latencies or {}).items()):
            record[f"latency_{stage}_ms"] = milliseconds
        exported.append(record)
    return exported


def flatten_metrics(metrics: Mapping[str, Any] | None) -> list[tuple[str, Any]]:
    """The metrics as `(dotted.name, value)` pairs, scalars only.

    The confusion matrix becomes `classification.confusion.<reference>.<predicted>`
    and the under-triaged list is left out: it is the `UNDER_TRIAGE` rows above.
    """
    if not metrics:
        return []
    pairs: list[tuple[str, Any]] = []

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if key in {"under_triaged", "labels"}:
                    continue
                if key == "confusion_matrix":
                    labels = node.get("labels") or []
                    for i, line in enumerate(value):
                        for j, count in enumerate(line):
                            pairs.append((f"{prefix}.confusion.{labels[i]}.{labels[j]}", count))
                    continue
                walk(f"{prefix}.{key}" if prefix else str(key), value)
        elif isinstance(node, list):
            return
        else:
            pairs.append((prefix, node))

    walk("", metrics)
    return pairs


def to_csv(rows: Sequence[dict[str, Any]], metrics: Mapping[str, Any] | None) -> str:
    latency_columns = sorted({key for row in rows for key in row if key.startswith("latency_")})
    columns = [*FIXED_COLUMNS, *latency_columns]

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        cells = []
        for column in columns:
            value = row.get(column)
            if isinstance(value, list):
                value = ";".join(str(item) for item in value)
            cells.append(
                text_cell(value)
                if column in {"external_id", "primary_complaint", "error"}
                else ("" if value is None else value)
            )
        writer.writerow(cells)

    writer.writerow([])
    writer.writerow(["metric", "value"])
    for name, value in flatten_metrics(metrics):
        writer.writerow([name, "" if value is None else value])
    return buffer.getvalue()


def to_json(
    run: Mapping[str, Any], rows: Sequence[dict[str, Any]], metrics: Mapping[str, Any] | None
) -> str:
    return json.dumps(
        {"run": dict(run), "metrics": metrics, "vignettes": list(rows)},
        indent=2,
        ensure_ascii=False,
        default=str,
    )
