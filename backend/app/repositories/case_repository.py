"""Database access for cases and the Triage Queue. No business rules here
(CLAUDE.md §7).

The queue query is the interesting part. FR-29 orders open cases by the category
that is *displayed*, which is the confirmed one if a reviewer has decided and the
AI's recommendation otherwise, and that category also decides the target waiting
time the row is measured against. Both live in other tables, one row per version,
so each case needs its latest decision and its latest recommendation.

That is done with LATERAL joins rather than a scalar subquery per column. A
lateral gives the whole latest row at once, so the category and the decision type
a row reports provably come from the *same* decision — two independently ordered
subqueries could, with equal timestamps, disagree.

Every join is an OUTER join. Through P04 none of these tables has any rows at
all: a case is created and left in SUBMITTED, so every category comes back NULL
and the queue shows "—". The query is written now because it is exactly what P05
and P06 switch on.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, Row, Select, Sequence, exists, func, or_, select, true
from sqlalchemy import case as sql_case
from sqlalchemy.orm import Session

from app.core.vtl import QUEUE_RANK, UNRANKED
from app.models import (
    AgeUnit,
    Case,
    CaseStatus,
    ExtractionResult,
    IntakeChannel,
    OwnerDescription,
    OwnerReference,
    PresentingComplaint,
    Recommendation,
    RedFlagAlert,
    Sex,
    Signalment,
    Species,
    StaffDecision,
    VTLCategory,
    extraction_complaints,
)

CASE_NO_PREFIX = "C-"
CASE_NO_DIGITS = 4

# Created in migration 0001 and owned by no column, so it is declared here rather
# than on the `cases` table. Not attached to `Base.metadata`: Alembic must not
# think it is a schema object this module is responsible for.
CASE_NO_SEQUENCE = Sequence("case_no_seq")


@dataclass(frozen=True)
class SignalmentValues:
    """The optional patient details from the intake form (FR-01).

    `sex` is not optional in the table — it defaults to UNKNOWN — so the service
    settles that before this gets here.
    """

    pet_name: str | None = None
    age_value: Decimal | None = None
    age_unit: AgeUnit | None = None
    sex: Sex = Sex.UNKNOWN
    neutered: bool | None = None
    breed: str | None = None
    weight_kg: Decimal | None = None


@dataclass(frozen=True)
class OwnerReferenceValues:
    """Owner identifiers, kept in their own table and never read by the pipeline
    (FR-07, DR-04)."""

    owner_name: str | None = None
    contact_number: str | None = None


class CaseRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- Writes -----------------------------------------------------------

    def next_case_no(self) -> str:
        """The next case number, as `C-0001` (FR-03).

        A sequence rather than `max(case_no) + 1`: two intake staff submitting at
        the same moment must not be able to claim the same number, and a sequence
        is the only way to get that without locking the table. It is created in
        migration 0001 and never rolls back, so a failed submission leaves a gap
        — which is correct, a case number is an identifier and not a count.
        """
        value = self._session.execute(select(CASE_NO_SEQUENCE.next_value())).scalar_one()
        return f"{CASE_NO_PREFIX}{value:0{CASE_NO_DIGITS}d}"

    def insert_case(
        self,
        *,
        case_no: str,
        species: Species,
        intake_channel: IntakeChannel,
        status: CaseStatus,
        created_by: uuid.UUID,
        arrived_at: datetime,
        description: str,
        signalment: SignalmentValues,
        owner_reference: OwnerReferenceValues | None,
    ) -> Case:
        """Insert a case and its three satellite rows. Flushes, never commits.

        `arrived_at` becomes both `cases.created_at` and the description's
        `submitted_at`. They are the same event — a case arriving — and the queue
        measures waiting time against one of them while FR-46 will measure
        processing time from the other, so they must not be two slightly different
        instants. `cases.created_at` has a server default for every other writer;
        this is the one place that overrides it.

        `description` is written exactly as given and is never updated again
        (FR-05, enforced by a trigger from migration 0002). The owner reference
        row is created only when there is something to put in it.
        """
        new_case = Case(
            case_no=case_no,
            species=species,
            intake_channel=intake_channel,
            status=status,
            created_by=created_by,
            created_at=arrived_at,
        )
        self._session.add(new_case)
        self._session.flush()

        self._session.add(
            Signalment(
                case_id=new_case.id,
                pet_name=signalment.pet_name,
                age_value=signalment.age_value,
                age_unit=signalment.age_unit,
                sex=signalment.sex,
                neutered=signalment.neutered,
                breed=signalment.breed,
                weight_kg=signalment.weight_kg,
            )
        )
        self._session.add(
            OwnerDescription(
                case_id=new_case.id,
                text=description,
                char_count=len(description),
                submitted_at=arrived_at,
            )
        )
        if owner_reference is not None:
            self._session.add(
                OwnerReference(
                    case_id=new_case.id,
                    owner_name=owner_reference.owner_name,
                    contact_number=owner_reference.contact_number,
                )
            )

        self._session.flush()
        return new_case

    # --- Reads ------------------------------------------------------------

    def queue_rows(
        self,
        *,
        species: Species | None = None,
        category: VTLCategory | None = None,
        manual_only: bool = False,
        status: CaseStatus | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        search: str | None = None,
        limit: int,
        offset: int,
    ) -> list[Row]:
        """Open cases in FR-29 order, one row per case.

        `created_from` and `created_to` are UTC instants; the service converts the
        clinic's calendar dates into them (DR-03).
        """
        parts = _QueueParts()
        statement = (
            select(
                Case.id,
                Case.case_no,
                Case.status,
                Case.created_at,
                Case.species,
                Signalment.pet_name,
                Signalment.age_value,
                Signalment.age_unit,
                Signalment.breed,
                parts.complaint.c.code.label("primary_complaint_code"),
                parts.complaint.c.name.label("primary_complaint_name"),
                parts.recommendation.c.category.label("recommended_category"),
                parts.decision.c.final_category.label("confirmed_category"),
                parts.decision.c.type.label("decision_type"),
                parts.effective_category.label("category"),
                parts.has_red_flag.label("has_red_flag"),
            )
            .select_from(Case)
            .outerjoin(Signalment, Signalment.case_id == Case.id)
        )
        statement = parts.join_onto(statement)
        statement = statement.where(Case.status != CaseStatus.CLOSED)

        if species is not None:
            statement = statement.where(Case.species == species)
        if status is not None:
            statement = statement.where(Case.status == status)
        if manual_only:
            statement = statement.where(Case.status == CaseStatus.MANUAL_TRIAGE_REQUIRED)
        elif category is not None:
            statement = statement.where(parts.effective_category == category)
        if created_from is not None:
            statement = statement.where(Case.created_at >= created_from)
        if created_to is not None:
            statement = statement.where(Case.created_at < created_to)
        if search:
            pattern = f"%{_escape_like(search)}%"
            statement = statement.where(
                or_(
                    Case.case_no.ilike(pattern, escape="\\"),
                    Signalment.pet_name.ilike(pattern, escape="\\"),
                    parts.complaint.c.name.ilike(pattern, escape="\\"),
                )
            )

        # `case_no` breaks a tie between two cases created in the same
        # millisecond, so the order is total and a page boundary is stable.
        statement = statement.order_by(
            parts.rank_expression(), Case.created_at.asc(), Case.case_no.asc()
        )
        return list(self._session.execute(statement.limit(limit).offset(offset)).all())

    def queue_counts(self) -> list[Row]:
        """One row per (displayed category, status) over the whole open queue.

        Deliberately unfiltered: the W-02 counters are the state of the queue, not
        a summary of the rows on screen, so they do not move when a filter is
        applied. Grouping by both columns answers all seven counters — the five
        category tiles, MANUAL and "awaiting review" — from one pass.
        """
        parts = _QueueParts()
        statement = select(
            parts.effective_category.label("category"),
            Case.status,
            func.count().label("case_count"),
        ).select_from(Case)
        statement = parts.join_onto(statement, with_complaint=False)
        statement = statement.where(Case.status != CaseStatus.CLOSED).group_by(
            parts.effective_category, Case.status
        )
        return list(self._session.execute(statement).all())

    def status_row(self, case_id: uuid.UUID) -> Row | None:
        """The polling payload for one case, or None when there is no such case.

        `updated_at` is derived rather than stored: the case row itself does not
        change when a recommendation or a decision lands, so a column on `cases`
        would have to be touched by every later phase to stay honest. PostgreSQL's
        GREATEST ignores NULLs, so the three absent timestamps simply drop out and
        a brand-new case reports its creation time.
        """
        parts = _QueueParts()
        statement = select(
            Case.status,
            parts.effective_category.label("category"),
            parts.has_red_flag.label("has_red_flag"),
            func.greatest(
                Case.created_at,
                Case.closed_at,
                parts.recommendation.c.created_at,
                parts.decision.c.decided_at,
            ).label("updated_at"),
        ).select_from(Case)
        statement = parts.join_onto(statement, with_complaint=False)
        statement = statement.where(Case.id == case_id)
        return self._session.execute(statement).one_or_none()


class _QueueParts:
    """The lateral joins and derived expressions the three queue reads share.

    One instance per statement: the laterals carry aliases, so reusing them
    across two statements would be a name collision waiting to happen.
    """

    def __init__(self) -> None:
        # The latest decision. `id` breaks a tie between two decisions recorded
        # with the same timestamp, so "latest" is a single definite row.
        self.decision = (
            select(StaffDecision.final_category, StaffDecision.type, StaffDecision.decided_at)
            .where(StaffDecision.case_id == Case.id)
            .order_by(StaffDecision.decided_at.desc(), StaffDecision.id.desc())
            .limit(1)
            .lateral("latest_decision")
        )
        # The latest recommendation. Versions are per case and monotonic (P07
        # regeneration adds versions), so the highest version is the current one.
        self.recommendation = (
            select(Recommendation.category, Recommendation.created_at)
            .where(Recommendation.case_id == Case.id)
            .order_by(Recommendation.version.desc(), Recommendation.id.desc())
            .limit(1)
            .lateral("latest_recommendation")
        )
        self.extraction = (
            select(ExtractionResult.id)
            .where(ExtractionResult.case_id == Case.id)
            .order_by(ExtractionResult.version.desc(), ExtractionResult.id.desc())
            .limit(1)
            .lateral("latest_extraction")
        )
        # The complaint the extraction marked primary, resolved to its display
        # name so the queue and the search both read the same text.
        self.complaint = (
            select(PresentingComplaint.code, PresentingComplaint.name)
            .join(
                extraction_complaints,
                extraction_complaints.c.complaint_code == PresentingComplaint.code,
            )
            .where(
                extraction_complaints.c.extraction_id == self.extraction.c.id,
                extraction_complaints.c.is_primary.is_(true()),
            )
            .limit(1)
            .lateral("primary_complaint")
        )

        # FR-29: the confirmed category wins over the recommended one.
        self.effective_category = func.coalesce(
            self.decision.c.final_category, self.recommendation.c.category
        )
        # FR-12: whether the pre-screen raised anything for this case. Each caller
        # labels it, so it is left unlabelled here.
        self.has_red_flag = exists(select(RedFlagAlert.id).where(RedFlagAlert.case_id == Case.id))

    def join_onto(self, statement: Select, *, with_complaint: bool = True) -> Select:
        """Add the lateral joins. `extraction` must precede `complaint`, which
        references it."""
        statement = statement.outerjoin(self.decision, true()).outerjoin(
            self.recommendation, true()
        )
        if with_complaint:
            statement = statement.outerjoin(self.extraction, true()).outerjoin(
                self.complaint, true()
            )
        return statement

    def rank_expression(self) -> ColumnElement[int]:
        """The FR-29 urgency rank as SQL, built from the one Python table.

        RED first, then cases with no category at all, then ORANGE down to BLUE.
        An unclassified case sits second because it might be the most urgent one
        in the room — nobody has looked at it yet.
        """
        branches = [
            (self.effective_category == category, rank)
            for category, rank in QUEUE_RANK.items()
            if category is not None
        ]
        branches.append((self.effective_category.is_(None), QUEUE_RANK[None]))
        return sql_case(*branches, else_=UNRANKED)


def _escape_like(value: str) -> str:
    """Make `%` and `_` literal, so searching for "C-01_" finds that case only."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
