"""Request and response bodies for `/eval` (P09 §9.2, FR-64..FR-69).

`metrics` and `config` are returned as the JSON the runner stored: their shape is
defined by `app.eval.metrics` and `app.eval.runner.config_snapshot`, and the run
endpoints add nothing to them. `targets` is the SRS target list with each measured
value and a PASS / FAIL / n/a status, computed from `metrics` so a client never
restates a threshold.

Vignette text is never part of a response: a set reports how many vignettes it has,
not what they say.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import JobStatus


class EvaluationSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    vignette_count: int
    imported_at: datetime
    # Slugs in `relevant_entry_slugs` that name no knowledge-base entry. The import
    # still succeeds; those judgements are left out (P09 §9.2 task 1).
    warnings: list[str] = Field(default_factory=list)


class EvaluationSetListOut(BaseModel):
    items: list[EvaluationSetOut]
    total: int


class EvaluationRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_id: uuid.UUID


class RunProgress(BaseModel):
    done: int
    total: int


class TargetResultOut(BaseModel):
    key: str
    label: str
    requirement: str
    comparison: str
    threshold: float
    unit: str
    value: float | None
    status: str


class EvaluationRunOut(BaseModel):
    id: uuid.UUID
    set_id: uuid.UUID
    set_name: str
    status: JobStatus
    progress: RunProgress
    kb_version_id: uuid.UUID | None
    # True when every stage was a mock: the numbers are then not model results
    # (ADR-17). None until the run has started and a snapshot exists.
    fully_mocked: bool | None
    config: dict[str, Any] | None
    metrics: dict[str, Any] | None
    targets: list[TargetResultOut]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class EvaluationRunListOut(BaseModel):
    items: list[EvaluationRunOut]
    total: int
