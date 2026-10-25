"""The evaluation harness for the Administrator (P09 §9.2, FR-64..FR-69, BR-05).

Importing a set, starting a run and reading one back. The service holds the rules a
request must not skip — a name means one set, a bad file stores nothing, an
unfinished run cannot be exported — and raises `AppError` subclasses; it knows
nothing about HTTP (CLAUDE.md §7).

Starting a run only *queues* it: the run row and its `EVAL_RUN` job are written in
one transaction and the worker does the rest, so a request never waits on a model
(ADR-08). The run itself is `app.eval.runner`.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.errors import (
    EvaluationNameInUse,
    EvaluationNotFinished,
    EvaluationNotFound,
    InvalidVignetteFile,
)
from app.eval import export
from app.eval.importer import parse_vignette_csv
from app.eval.targets import evaluate_targets
from app.jobs.queue import EVAL_RUN_ID_KEY, JobQueue
from app.models import EvaluationRun, JobStatus, JobType, User
from app.repositories.evaluation_repository import EvaluationRepository, NewVignette
from app.schemas.evaluation import (
    EvaluationRunListOut,
    EvaluationRunOut,
    EvaluationSetListOut,
    EvaluationSetOut,
    RunProgress,
    TargetResultOut,
)
from app.services.audit_service import (
    EVAL_RUN_ENTITY,
    EVAL_SET_ENTITY,
    AuditAction,
    AuditService,
)

Clock = Callable[[], datetime]
ExportFormat = Literal["csv", "json"]

NAME_MAX_LENGTH = 200


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ExportFile:
    content: str
    media_type: str
    filename: str


class EvaluationService:
    def __init__(self, session: Session, *, now: Clock | None = None) -> None:
        self._session = session
        self._repo = EvaluationRepository(session)
        self._audit = AuditService(session)
        self._jobs = JobQueue(session)
        self._now = now or _utc_now

    # --- Sets --------------------------------------------------------------

    def import_set(self, name: str, content: bytes, actor: User) -> EvaluationSetOut:
        """Validate the file and store the set, or store nothing (FR-64, DR-06)."""
        name = name.strip()
        if not name or len(name) > NAME_MAX_LENGTH:
            raise InvalidVignetteFile(
                [
                    {
                        "row": 0,
                        "field": "name",
                        "message": f"Enter a name of 1 to {NAME_MAX_LENGTH} characters.",
                    }
                ],
                "The set needs a name.",
            )

        parsed = parse_vignette_csv(content)
        if parsed.errors:
            raise InvalidVignetteFile([error.as_dict() for error in parsed.errors])
        if self._repo.get_set_by_name(name) is not None:
            raise EvaluationNameInUse()

        wanted = sorted({slug for vignette in parsed.vignettes for slug in vignette.relevant_slugs})
        known = self._repo.entry_ids_by_slug(wanted)
        warnings = [
            f"Unknown knowledge-base entry slug: {slug}" for slug in wanted if slug not in known
        ]

        stored = self._repo.add_set(name=name, imported_by=actor.id, imported_at=self._now())
        self._repo.add_vignettes(
            stored.id,
            [
                NewVignette(
                    external_id=vignette.external_id,
                    species=vignette.species,
                    description=vignette.description,
                    reference_category=vignette.reference_category,
                    relevant_entry_ids=[
                        str(known[slug]) for slug in vignette.relevant_slugs if slug in known
                    ],
                )
                for vignette in parsed.vignettes
            ],
        )
        self._audit.record(
            action=AuditAction.EVAL_SET_IMPORTED,
            entity_type=EVAL_SET_ENTITY,
            entity_id=str(stored.id),
            user_id=actor.id,
            role=actor.role,
            after={
                "name": stored.name,
                "vignette_count": len(parsed.vignettes),
                "unknown_slug_count": len(warnings),
            },
        )
        self._session.commit()
        return EvaluationSetOut(
            id=stored.id,
            name=stored.name,
            vignette_count=len(parsed.vignettes),
            imported_at=stored.imported_at,
            warnings=warnings,
        )

    def list_sets(self) -> EvaluationSetListOut:
        items = [
            EvaluationSetOut(
                id=summary.set.id,
                name=summary.set.name,
                vignette_count=summary.vignette_count,
                imported_at=summary.set.imported_at,
            )
            for summary in self._repo.list_sets()
        ]
        return EvaluationSetListOut(items=items, total=len(items))

    # --- Runs --------------------------------------------------------------

    def start_run(
        self, set_id: uuid.UUID, actor: User, *, enqueue: bool = True
    ) -> EvaluationRunOut:
        """Create a run over a set (FR-65) and, by default, queue it for the worker.

        `enqueue=False` is for the CLI, which runs the run itself in its own
        process: a queued job as well would have the API's worker run it a second
        time.
        """
        if self._repo.get_set(set_id) is None:
            raise EvaluationNotFound("That evaluation set could not be found.")

        run = self._repo.add_run(set_id=set_id, created_by=actor.id)
        if enqueue:
            self._jobs.enqueue(JobType.EVAL_RUN, payload={EVAL_RUN_ID_KEY: str(run.id)})
        self._audit.record(
            action=AuditAction.EVAL_RUN_STARTED,
            entity_type=EVAL_RUN_ENTITY,
            entity_id=str(run.id),
            user_id=actor.id,
            role=actor.role,
            after={"set_id": str(set_id), "vignette_count": self._repo.vignette_count(set_id)},
        )
        self._session.commit()
        return self._run_out(run)

    def list_runs(self) -> EvaluationRunListOut:
        runs = self._repo.list_runs()
        names = self._repo.set_names([run.set_id for run in runs])
        items = [self._run_out(run, names.get(run.set_id)) for run in runs]
        return EvaluationRunListOut(items=items, total=len(items))

    def get_run(self, run_id: uuid.UUID) -> EvaluationRunOut:
        return self._run_out(self._require_run(run_id))

    # --- Export ------------------------------------------------------------

    def export_run(self, run_id: uuid.UUID, file_format: ExportFormat) -> ExportFile:
        """The finished run's per-vignette rows and metrics (FR-69)."""
        run = self._require_run(run_id)
        if run.status not in {JobStatus.DONE, JobStatus.FAILED}:
            raise EvaluationNotFinished()

        rows = export.rows_for_export(self._repo.result_rows(run_id))
        stem = f"evaluation-run-{str(run.id)[:8]}"
        if file_format == "csv":
            return ExportFile(export.to_csv(rows, run.metrics), "text/csv", f"{stem}.csv")
        summary = self._run_out(run).model_dump(
            mode="json", exclude={"metrics", "targets", "progress"}
        )
        return ExportFile(
            export.to_json(summary, rows, run.metrics), "application/json", f"{stem}.json"
        )

    # --- helpers -----------------------------------------------------------

    def _require_run(self, run_id: uuid.UUID) -> EvaluationRun:
        run = self._repo.get_run(run_id)
        if run is None:
            raise EvaluationNotFound("That evaluation run could not be found.")
        return run

    def _run_out(self, run: EvaluationRun, set_name: str | None = None) -> EvaluationRunOut:
        if set_name is None:
            set_name = self._repo.set_names([run.set_id]).get(run.set_id, "")
        config: dict[str, Any] | None = run.config
        return EvaluationRunOut(
            id=run.id,
            set_id=run.set_id,
            set_name=set_name,
            status=run.status,
            progress=RunProgress(
                done=self._repo.result_count(run.id), total=self._repo.vignette_count(run.set_id)
            ),
            kb_version_id=run.kb_version_id,
            fully_mocked=None if config is None else bool(config.get("fully_mocked")),
            config=config,
            metrics=run.metrics,
            targets=[TargetResultOut(**target) for target in evaluate_targets(run.metrics)],
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )
