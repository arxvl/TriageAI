"""De-identified export endpoints (P09 §9.4, FR-47, BR-05, BR-08, SR-05).

Administrator only, on both routes. The router holds no business logic
(CLAUDE.md §7); `ExportService` decides what leaves and audits it. Answers 422
for a malformed date or a start after the end, and 403 for any other role.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import DbSession, require_role
from app.models import User, UserRole
from app.services.export_service import ExportFile, ExportService

router = APIRouter(prefix="/exports", tags=["exports"])

AdminUser = Annotated[User, Depends(require_role(UserRole.ADMINISTRATOR))]
DateFrom = Annotated[date | None, Query(alias="from")]
DateTo = Annotated[date | None, Query(alias="to")]


def _attachment(exported: ExportFile) -> Response:
    return Response(
        content=exported.content,
        media_type=exported.media_type,
        headers={"Content-Disposition": f'attachment; filename="{exported.filename}"'},
    )


@router.get("/cases")
def export_cases(
    db: DbSession,
    admin: AdminUser,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    format: Annotated[Literal["csv"], Query()] = "csv",
) -> Response:
    """One row per case: categories, decision, intervals and action counts."""
    return _attachment(ExportService(db).export_cases(date_from, date_to, admin))


@router.get("/audit")
def export_audit(
    db: DbSession,
    admin: AdminUser,
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> Response:
    """The audit log with people replaced by role and pseudonym."""
    return _attachment(ExportService(db).export_audit(date_from, date_to, admin))
