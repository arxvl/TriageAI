"""Case intake and the Triage Queue (FR-01..FR-07, FR-29, FR-30, FR-36, FR-39).

The service owns the rules a caller must not be able to skip: the dog-and-cat
restriction, the single transaction that keeps a case and its description
together, the audit entry, and the waiting-time arithmetic the queue is judged
on. It raises `AppError` subclasses and knows nothing about HTTP (CLAUDE.md §7).

`now` is injectable so the waiting-time and overdue tests can place a case at an
exact age instead of sleeping. One `now` is used for every row in a response and
for `generated_at`, so a queue is a consistent snapshot rather than a set of rows
measured a few milliseconds apart.

Nothing here starts the pipeline. A new case stays in `SUBMITTED`; P05 adds the
job (FR-06).
"""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Row
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import CaseNotFound, SpeciesOutOfScope
from app.core.vtl import is_overdue, target_minutes
from app.models import (
    CaseStatus,
    IntakeChannel,
    Sex,
    Species,
    User,
    VTLCategory,
)
from app.repositories.case_repository import (
    CaseRepository,
    OwnerReferenceValues,
    SignalmentValues,
)
from app.schemas.case import (
    CaseCreate,
    CaseCreated,
    CaseListResponse,
    CaseQueueCounts,
    CaseQueueFilters,
    CaseQueueItem,
    CaseStatusOut,
    QueueCategoryFilter,
    SpeciesInput,
)
from app.services.audit_service import CASE_ENTITY, AuditAction, AuditService

Clock = Callable[[], datetime]

# Intake channel is optional on the form (FR-01) but not null in the table. A
# case entered on the intake screen is someone standing at the counter unless
# they say otherwise.
DEFAULT_INTAKE_CHANNEL = IntakeChannel.WALK_IN


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CaseService:
    def __init__(
        self,
        session: Session,
        *,
        now: Clock | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._cases = CaseRepository(session)
        self._audit = AuditService(session)
        self._now = now or _utc_now
        self._display_timezone = ZoneInfo((settings or get_settings()).tz_display)

    # --- Intake -----------------------------------------------------------

    def create_case(self, payload: CaseCreate, user: User) -> CaseCreated:
        """Create a case in `SUBMITTED` and return its number (FR-01, FR-03).

        Dogs and cats only (FR-02, BR-06). The check comes first, so an
        out-of-scope case leaves nothing behind at all — no row, no case number,
        no audit entry. Those cases are triaged on paper by clinic procedure, and
        a half-created record of one would be worse than none.

        The case, its signalment, its description and its owner reference are one
        transaction. A case without its description would be unrecoverable:
        `owner_descriptions.text` cannot be inserted later by an update (FR-05).
        """
        if payload.species is SpeciesInput.OTHER:
            raise SpeciesOutOfScope()

        species = Species(payload.species.value)
        intake_channel = payload.intake_channel or DEFAULT_INTAKE_CHANNEL
        arrived_at = self._now()

        new_case = self._cases.insert_case(
            case_no=self._cases.next_case_no(),
            species=species,
            intake_channel=intake_channel,
            status=CaseStatus.SUBMITTED,
            created_by=user.id,
            arrived_at=arrived_at,
            description=payload.description,
            signalment=SignalmentValues(
                pet_name=payload.pet_name,
                age_value=payload.age_value,
                age_unit=payload.age_unit,
                # Not null in the table; "not stated" is itself a finding.
                sex=payload.sex or Sex.UNKNOWN,
                neutered=payload.neutered,
                breed=payload.breed,
                weight_kg=payload.weight_kg,
            ),
            owner_reference=(
                OwnerReferenceValues(
                    owner_name=payload.owner_name,
                    contact_number=payload.contact_number,
                )
                if payload.has_owner_reference
                else None
            ),
        )

        # Read before the commit expires the instance, and so the response
        # reports what was actually written.
        created = CaseCreated(id=new_case.id, case_no=new_case.case_no, status=new_case.status)

        # Identifiers, codes and a character count only. The description itself,
        # the owner name and the contact number never reach the audit log, which
        # cannot be corrected afterwards (FR-43, CLAUDE.md §9).
        self._audit.record(
            action=AuditAction.CASE_CREATED,
            entity_type=CASE_ENTITY,
            entity_id=str(created.id),
            user_id=user.id,
            role=user.role,
            after={
                "case_no": created.case_no,
                "species": species.value,
                "intake_channel": intake_channel.value,
                "status": created.status.value,
                "description_char_count": len(payload.description),
                "has_owner_reference": payload.has_owner_reference,
            },
        )

        self._session.commit()
        return created

    # --- Triage Queue -----------------------------------------------------

    def list_queue(self, filters: CaseQueueFilters) -> CaseListResponse:
        """Open cases in FR-29 order, with the W-02 counters (FR-39).

        Waiting times are computed here rather than in SQL so that every row in
        one response is measured against the same instant, and so a test can
        place a case at an exact age.
        """
        now = self._now()
        created_from, created_to = self._utc_bounds(filters.date_from, filters.date_to)
        # MANUAL is a status, not a VTL category, so the two go to separate
        # arguments and only one of them is ever set.
        manual_only = filters.category is QueueCategoryFilter.MANUAL
        category = None if manual_only else _as_category(filters.category)

        rows = self._cases.queue_rows(
            species=filters.species,
            category=category,
            manual_only=manual_only,
            status=filters.status,
            created_from=created_from,
            created_to=created_to,
            search=filters.q,
            limit=filters.limit,
            offset=filters.offset,
        )

        return CaseListResponse(
            items=[self._to_queue_item(row, now) for row in rows],
            counts=self._queue_counts(),
            generated_at=now,
        )

    def get_status(self, case_id: uuid.UUID) -> CaseStatusOut:
        """What a case looks like right now, for the polling clients (IR-22)."""
        row = self._cases.status_row(case_id)
        if row is None:
            raise CaseNotFound()
        return CaseStatusOut(
            status=CaseStatus(row.status),
            category=_as_category(row.category),
            has_red_flag=row.has_red_flag,
            updated_at=row.updated_at,
        )

    # --- Internals --------------------------------------------------------

    def _to_queue_item(self, row: Row, now: datetime) -> CaseQueueItem:
        category = _as_category(row.category)
        waiting_minutes = _minutes_between(row.created_at, now)
        return CaseQueueItem(
            id=row.id,
            case_no=row.case_no,
            status=CaseStatus(row.status),
            created_at=row.created_at,
            species=Species(row.species),
            pet_name=row.pet_name,
            age_value=float(row.age_value) if row.age_value is not None else None,
            age_unit=row.age_unit,
            breed=row.breed,
            primary_complaint_code=row.primary_complaint_code,
            primary_complaint_name=row.primary_complaint_name,
            category=category,
            recommended_category=_as_category(row.recommended_category),
            confirmed_category=_as_category(row.confirmed_category),
            decision_type=row.decision_type,
            waiting_minutes=waiting_minutes,
            target_minutes=target_minutes(category),
            is_overdue=is_overdue(category, waiting_minutes),
            has_red_flag=row.has_red_flag,
        )

    def _queue_counts(self) -> CaseQueueCounts:
        """Fold the grouped counts into the seven numbers W-02 shows.

        A case with no category is counted in `total` and, when it is there for a
        reviewer to triage by hand, in `manual_count` — but in none of the five
        category tiles, because it has no category to be counted under.
        """
        by_category = dict.fromkeys(VTLCategory, 0)
        manual_count = 0
        awaiting_review_count = 0
        total = 0

        for row in self._cases.queue_counts():
            count = row.case_count
            total += count
            category = _as_category(row.category)
            if category is not None:
                by_category[category] += count
            status = CaseStatus(row.status)
            if status is CaseStatus.MANUAL_TRIAGE_REQUIRED:
                manual_count += count
            elif status is CaseStatus.AWAITING_REVIEW:
                awaiting_review_count += count

        return CaseQueueCounts(
            by_category=by_category,
            manual_count=manual_count,
            awaiting_review_count=awaiting_review_count,
            total=total,
        )

    def _utc_bounds(
        self, date_from: date | None, date_to: date | None
    ) -> tuple[datetime | None, datetime | None]:
        """Turn the clinic's calendar dates into the UTC instants to compare.

        The filter bar says "Today", and the clinic's today starts at midnight in
        Asia/Manila, not at midnight UTC — which is 8 a.m. locally and would cut
        the morning's cases off the list. Timestamps are stored in UTC (DR-03),
        so the conversion happens here.

        `date_to` is inclusive, so the upper bound is midnight on the day after;
        the repository compares it with `<`.
        """
        start = None
        end = None
        if date_from is not None:
            start = datetime.combine(date_from, time.min, tzinfo=self._display_timezone)
        if date_to is not None:
            end = datetime.combine(
                date_to + timedelta(days=1), time.min, tzinfo=self._display_timezone
            )
        return start, end


def _as_category(value: object) -> VTLCategory | None:
    """Normalise a category into a `VTLCategory`, or None.

    Two callers need this. `coalesce` over two enum columns can hand back the raw
    label rather than the enum member, and `TARGET_MINUTES` is keyed by the
    member. The queue's category filter is a separate enum that shares the five
    VTL labels, so the same conversion turns one into the other.
    """
    if value is None:
        return None
    return VTLCategory(value)


def _minutes_between(started_at: datetime, now: datetime) -> int:
    """Whole minutes waited, never negative.

    A case cannot have waited a negative time; a clock adjustment between the
    insert and the read should show 0, not -1.
    """
    return max(0, int((now - started_at).total_seconds() // 60))
