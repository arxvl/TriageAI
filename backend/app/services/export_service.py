"""De-identified exports for the Administrator (P09 §9.4, FR-47, BR-05, BR-08, SR-12).

Reads the rows, formats them (`export_format` decides what may leave) and records
a `DATA_EXPORTED` audit entry. The entry and the read share one transaction, and
the file is returned only after the entry is committed: an export that could not
be audited is not handed over.

The entry holds the date range, the format and the row count, never a row. It is
written after the rows are read, so an export's own entry is not in the file it
produced.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import InvalidExportRange
from app.models import User
from app.repositories.export_repository import ExportRepository
from app.services import export_format
from app.services.audit_service import EXPORT_ENTITY, AuditAction, AuditService

CASES_EXPORT = "cases"
AUDIT_EXPORT = "audit"
CSV_FORMAT = "csv"


@dataclass(frozen=True)
class ExportFile:
    content: str
    media_type: str
    filename: str


class ExportService:
    def __init__(self, session: Session, *, settings: Settings | None = None) -> None:
        self._session = session
        self._repo = ExportRepository(session)
        self._audit = AuditService(session)
        self._display_timezone = ZoneInfo((settings or get_settings()).tz_display)

    def export_cases(self, date_from: date | None, date_to: date | None, actor: User) -> ExportFile:
        """One row per case created in the range (FR-47)."""
        start, end = self._utc_bounds(date_from, date_to)
        rows = self._repo.case_rows(start, end)
        content = export_format.cases_to_csv(row._mapping for row in rows)
        return self._deliver(CASES_EXPORT, content, len(rows), date_from, date_to, actor)

    def export_audit(self, date_from: date | None, date_to: date | None, actor: User) -> ExportFile:
        """The audit entries stamped in the range, people replaced by pseudonyms."""
        start, end = self._utc_bounds(date_from, date_to)
        rows = self._repo.audit_rows(start, end)
        content = export_format.audit_to_csv(
            (row._mapping for row in rows), self._repo.user_roles()
        )
        return self._deliver(AUDIT_EXPORT, content, len(rows), date_from, date_to, actor)

    # --- helpers -----------------------------------------------------------

    def _deliver(
        self,
        kind: str,
        content: str,
        row_count: int,
        date_from: date | None,
        date_to: date | None,
        actor: User,
    ) -> ExportFile:
        self._audit.record(
            action=AuditAction.DATA_EXPORTED,
            entity_type=EXPORT_ENTITY,
            entity_id=kind,
            user_id=actor.id,
            role=actor.role,
            after={
                "from": None if date_from is None else date_from.isoformat(),
                "to": None if date_to is None else date_to.isoformat(),
                "format": CSV_FORMAT,
                "row_count": row_count,
            },
        )
        self._session.commit()
        return ExportFile(content, "text/csv; charset=utf-8", _file_name(kind, date_from, date_to))

    def _utc_bounds(
        self, date_from: date | None, date_to: date | None
    ) -> tuple[datetime | None, datetime | None]:
        """The clinic's calendar days as UTC instants, `date_to` inclusive.

        Days are Asia/Manila days because that is what the screens show; the upper
        bound is midnight after `date_to` and the repository compares it with `<`.
        """
        if date_from is not None and date_to is not None and date_from > date_to:
            raise InvalidExportRange()
        start = end = None
        if date_from is not None:
            start = datetime.combine(date_from, time.min, tzinfo=self._display_timezone)
        if date_to is not None:
            end = datetime.combine(
                date_to + timedelta(days=1), time.min, tzinfo=self._display_timezone
            )
        return start, end


def _file_name(kind: str, date_from: date | None, date_to: date | None) -> str:
    stem = f"triageai-{kind}-export"
    if date_from is not None or date_to is not None:
        stem += f"-{date_from or 'start'}_{date_to or 'end'}"
    return f"{stem}.csv"
