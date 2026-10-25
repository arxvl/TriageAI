"""Evaluation harness endpoints (P09 §9.2, FR-64..FR-69, BR-05, SR-05).

Administrator only, on every route: running an evaluation and reading its results
is the Administrator's work (BR-05), and a reviewer or intake account gets 403. The
router holds no business logic (CLAUDE.md §7); `EvaluationService` does.

Answers: 202 when a run is queued, 422 naming the rows of a bad vignette file, 409
for a duplicate set name or an export before the run has finished, 404 for an
unknown id.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status

from app.api.deps import DbSession, require_role
from app.core.errors import InvalidVignetteFile
from app.eval.importer import MAX_FILE_BYTES
from app.models import User, UserRole
from app.schemas.evaluation import (
    EvaluationRunCreate,
    EvaluationRunListOut,
    EvaluationRunOut,
    EvaluationSetListOut,
    EvaluationSetOut,
)
from app.services.evaluation_service import EvaluationService

router = APIRouter(prefix="/eval", tags=["evaluation"])

AdminUser = Annotated[User, Depends(require_role(UserRole.ADMINISTRATOR))]


@router.post("/sets", status_code=status.HTTP_201_CREATED)
def import_set(
    db: DbSession,
    admin: AdminUser,
    name: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> EvaluationSetOut:
    """Import a vignette CSV as a new evaluation set."""
    # One byte over the limit is enough to know the file is too large, without
    # reading all of an upload that is.
    content = file.file.read(MAX_FILE_BYTES + 1)
    if not content:
        raise InvalidVignetteFile(
            [{"row": 0, "field": "file", "message": "The file is empty."}],
            "The vignette file is empty.",
        )
    return EvaluationService(db).import_set(name, content, admin)


@router.get("/sets")
def list_sets(db: DbSession, admin: AdminUser) -> EvaluationSetListOut:
    return EvaluationService(db).list_sets()


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
def start_run(payload: EvaluationRunCreate, db: DbSession, admin: AdminUser) -> EvaluationRunOut:
    """Queue an evaluation run over a set. Poll the run for progress."""
    return EvaluationService(db).start_run(payload.set_id, admin)


@router.get("/runs")
def list_runs(db: DbSession, admin: AdminUser) -> EvaluationRunListOut:
    return EvaluationService(db).list_runs()


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, db: DbSession, admin: AdminUser) -> EvaluationRunOut:
    return EvaluationService(db).get_run(run_id)


@router.get("/runs/{run_id}/export")
def export_run(
    run_id: uuid.UUID,
    db: DbSession,
    admin: AdminUser,
    format: Annotated[Literal["csv", "json"], Query()] = "csv",
) -> Response:
    """Per-vignette rows and the metrics, as a download."""
    exported = EvaluationService(db).export_run(run_id, format)
    return Response(
        content=exported.content,
        media_type=exported.media_type,
        headers={"Content-Disposition": f'attachment; filename="{exported.filename}"'},
    )
