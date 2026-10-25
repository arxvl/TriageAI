"""Database access for evaluation sets, vignettes, runs and results (P09 §9.2).

No business rules (CLAUDE.md §7). Everything here is addressed by vignette, set or
run — never by case: evaluation data lives apart from clinical data, and nothing in
this module can reach a `cases` table (DR-06).

`outcomes` is the one place stored rows become the plain values the metrics read,
so a run's metrics are always a function of what is on disk and the runner, the
export and the CLI report cannot disagree about them.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.eval.metrics import VignetteOutcome
from app.models import (
    EvaluationResult,
    EvaluationRun,
    EvaluationSet,
    JobStatus,
    KBEntry,
    Species,
    Vignette,
    VTLCategory,
)

__all__ = ["EvaluationRepository", "NewVignette", "ResultRow", "SetSummary"]


@dataclass(frozen=True)
class NewVignette:
    external_id: str
    species: Species
    description: str
    reference_category: VTLCategory
    relevant_entry_ids: list[str]


@dataclass(frozen=True)
class SetSummary:
    set: EvaluationSet
    vignette_count: int


@dataclass(frozen=True)
class ResultRow:
    """One stored result beside the vignette it is about."""

    result: EvaluationResult
    vignette: Vignette


class EvaluationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- Sets and vignettes -----------------------------------------------

    def get_set(self, set_id: uuid.UUID) -> EvaluationSet | None:
        return self._session.get(EvaluationSet, set_id)

    def get_set_by_name(self, name: str) -> EvaluationSet | None:
        return self._session.scalars(
            select(EvaluationSet).where(EvaluationSet.name == name)
        ).one_or_none()

    def add_set(self, *, name: str, imported_by: uuid.UUID, imported_at: datetime) -> EvaluationSet:
        row = EvaluationSet(name=name, imported_by=imported_by, imported_at=imported_at)
        self._session.add(row)
        self._session.flush()
        return row

    def add_vignettes(self, set_id: uuid.UUID, vignettes: list[NewVignette]) -> None:
        self._session.add_all(
            Vignette(
                set_id=set_id,
                external_id=vignette.external_id,
                species=vignette.species,
                description=vignette.description,
                reference_category=vignette.reference_category,
                relevant_entry_ids=vignette.relevant_entry_ids,
            )
            for vignette in vignettes
        )
        self._session.flush()

    def list_sets(self) -> list[SetSummary]:
        rows = self._session.execute(
            select(EvaluationSet, func.count(Vignette.id))
            .outerjoin(Vignette, Vignette.set_id == EvaluationSet.id)
            .group_by(EvaluationSet.id)
            .order_by(EvaluationSet.imported_at.desc(), EvaluationSet.name)
        ).all()
        return [SetSummary(set=row[0], vignette_count=row[1]) for row in rows]

    def vignette_count(self, set_id: uuid.UUID) -> int:
        return (
            self._session.scalar(select(func.count(Vignette.id)).where(Vignette.set_id == set_id))
            or 0
        )

    def vignettes_for_set(self, set_id: uuid.UUID) -> list[Vignette]:
        """The set's vignettes in a stable order, so a resumed run takes them as before."""
        return list(
            self._session.scalars(
                select(Vignette).where(Vignette.set_id == set_id).order_by(Vignette.external_id)
            )
        )

    def entry_ids_by_slug(self, slugs: list[str]) -> dict[str, uuid.UUID]:
        """Which of `slugs` name a knowledge-base entry, and its id.

        Any status: a slug identifies the entry, and whether it is retrievable is a
        property of the knowledge base the run is pinned to, not of the label.
        """
        if not slugs:
            return {}
        rows = self._session.execute(
            select(KBEntry.slug, KBEntry.id).where(KBEntry.slug.in_(slugs))
        ).all()
        return {slug: entry_id for slug, entry_id in rows}

    # --- Runs --------------------------------------------------------------

    def add_run(self, *, set_id: uuid.UUID, created_by: uuid.UUID | None) -> EvaluationRun:
        run = EvaluationRun(set_id=set_id, created_by=created_by, status=JobStatus.QUEUED)
        self._session.add(run)
        self._session.flush()
        return run

    def get_run(self, run_id: uuid.UUID) -> EvaluationRun | None:
        return self._session.get(EvaluationRun, run_id)

    def list_runs(self, limit: int = 100) -> list[EvaluationRun]:
        return list(
            self._session.scalars(
                select(EvaluationRun)
                .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id)
                .limit(limit)
            )
        )

    def set_names(self, set_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not set_ids:
            return {}
        rows = self._session.execute(
            select(EvaluationSet.id, EvaluationSet.name).where(EvaluationSet.id.in_(set_ids))
        ).all()
        return {set_id: name for set_id, name in rows}

    # --- Results -----------------------------------------------------------

    def completed_vignette_ids(self, run_id: uuid.UUID) -> set[uuid.UUID]:
        return set(
            self._session.scalars(
                select(EvaluationResult.vignette_id).where(EvaluationResult.run_id == run_id)
            )
        )

    def result_count(self, run_id: uuid.UUID) -> int:
        return (
            self._session.scalar(
                select(func.count(EvaluationResult.id)).where(EvaluationResult.run_id == run_id)
            )
            or 0
        )

    def add_result(
        self,
        *,
        run_id: uuid.UUID,
        vignette_id: uuid.UUID,
        recommendation_id: uuid.UUID | None,
        extraction_id: uuid.UUID | None,
        predicted_category: VTLCategory | None,
        stage_latencies: dict[str, int],
        error: str | None,
        payload: dict,
    ) -> EvaluationResult:
        row = EvaluationResult(
            run_id=run_id,
            vignette_id=vignette_id,
            recommendation_id=recommendation_id,
            extraction_id=extraction_id,
            predicted_category=predicted_category,
            stage_latencies=stage_latencies,
            error=error,
            payload=payload,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def result_rows(self, run_id: uuid.UUID) -> list[ResultRow]:
        rows = self._session.execute(
            select(EvaluationResult, Vignette)
            .join(Vignette, Vignette.id == EvaluationResult.vignette_id)
            .where(EvaluationResult.run_id == run_id)
            .order_by(Vignette.external_id)
        ).all()
        return [ResultRow(result=row[0], vignette=row[1]) for row in rows]

    def outcomes(self, run_id: uuid.UUID) -> list[VignetteOutcome]:
        """The run's stored results as the values `compute_metrics` takes."""
        return [outcome_of(row) for row in self.result_rows(run_id)]


def outcome_of(row: ResultRow) -> VignetteOutcome:
    payload = row.result.payload or {}
    return VignetteOutcome(
        external_id=row.vignette.external_id,
        reference=row.vignette.reference_category,
        predicted=row.result.predicted_category,
        relevant_entry_ids=[str(entry) for entry in row.vignette.relevant_entry_ids or []],
        retrieved_entry_ids=[str(entry) for entry in payload.get("retrieved_entry_ids") or []],
        latencies_ms=dict(row.result.stage_latencies or {}),
        primary_complaint=payload.get("primary_complaint"),
    )
