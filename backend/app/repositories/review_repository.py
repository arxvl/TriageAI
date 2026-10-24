"""Database access for the Case Review screen and the decisions made on it.

No business rules here (CLAUDE.md §7). This is a separate class from
`CaseRepository` on purpose: that module is about one query — the FR-29 queue
with its lateral joins — and these are a dozen small per-case reads plus the
writes that record a human decision. Putting them together would bury both.

Two things are worth reading before changing anything here.

**"Latest" always means the highest version, with the id as a tie-break.**
Extractions and recommendations are versioned and never updated (ADR-14), so the
newest row is the current one. Decisions are ordered by `decided_at` and then by
id, because two decisions recorded in the same millisecond must still have a
single definite latest.

**Nothing in this module reads `owner_references`** (DR-04), and no read selects
`red_flag_alerts.matched_text`: it is a substring of the owner's description and
the review response carries the rule's label instead (CLAUDE.md §9).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Row, func, select, update
from sqlalchemy.orm import Session

from app.models import (
    ActionSource,
    ActionStatus,
    ActionSuggestion,
    AdjustReason,
    AuditEntry,
    Case,
    CaseStatus,
    ClinicalNote,
    DecisionDirection,
    DecisionType,
    ExtractionResult,
    FinalAction,
    KBVersion,
    OwnerDescription,
    PresentingComplaint,
    Recommendation,
    RedFlagAlert,
    RedFlagRule,
    RetrievedReference,
    Signalment,
    StaffDecision,
    User,
    VTLCategory,
    extraction_complaints,
)


@dataclass(frozen=True)
class FinalActionValues:
    """One `final_actions` row to write, already ordered by the service."""

    text: str
    source: ActionSource
    status: ActionStatus
    suggestion_id: uuid.UUID | None = None


@dataclass(frozen=True)
class TimingMarks:
    """The three instants the FR-46 intervals are measured between.

    The **first** recommendation and the **first** decision, not the latest: the
    metric is how long the system took to answer and how long the reviewer took
    to decide, and a later regeneration or amendment does not change either.
    """

    submitted_at: datetime | None
    first_recommendation_at: datetime | None
    first_decision_at: datetime | None


class ReviewRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- Reads: the case header -------------------------------------------

    def header_row(self, case_id: uuid.UUID) -> Row | None:
        """The patient, the arrival, and who recorded it (W-04 header).

        The fields `CaseRepository.detail_row` does not carry: the full
        signalment, the intake channel, the name of the staff member who entered
        the case, and `closed_at`.
        """
        statement = (
            select(
                Case.case_no,
                Case.species,
                Case.intake_channel,
                Case.created_at,
                Case.closed_at,
                Signalment.pet_name,
                Signalment.age_value,
                Signalment.age_unit,
                Signalment.sex,
                Signalment.neutered,
                Signalment.breed,
                Signalment.weight_kg,
                User.full_name.label("created_by_name"),
            )
            .select_from(Case)
            .outerjoin(Signalment, Signalment.case_id == Case.id)
            .outerjoin(User, User.id == Case.created_by)
            .where(Case.id == case_id)
        )
        return self._session.execute(statement).one_or_none()

    def status_of(self, case_id: uuid.UUID) -> CaseStatus | None:
        """Just the status, for the guards on the write endpoints."""
        return self._session.scalars(select(Case.status).where(Case.id == case_id)).one_or_none()

    def description(self, case_id: uuid.UUID) -> str | None:
        """The owner's verbatim description (FR-05)."""
        return self._session.scalars(
            select(OwnerDescription.text).where(OwnerDescription.case_id == case_id)
        ).one_or_none()

    # --- Reads: the AI output ---------------------------------------------

    def latest_extraction(self, case_id: uuid.UUID) -> Row | None:
        """The newest extraction for a case, with the text it was produced from."""
        statement = (
            select(
                ExtractionResult.id,
                ExtractionResult.version,
                ExtractionResult.is_corrected,
                ExtractionResult.input_text,
                ExtractionResult.entities,
                ExtractionResult.red_flags,
                ExtractionResult.missing_information,
                ExtractionResult.model_id,
                ExtractionResult.prompt_version,
                ExtractionResult.created_at,
                User.full_name.label("corrected_by_name"),
            )
            .select_from(ExtractionResult)
            .outerjoin(User, User.id == ExtractionResult.corrected_by)
            .where(ExtractionResult.case_id == case_id)
            .order_by(ExtractionResult.version.desc(), ExtractionResult.id.desc())
            .limit(1)
        )
        return self._session.execute(statement).one_or_none()

    def extraction_complaints(self, extraction_id: uuid.UUID) -> list[Row]:
        """The complaints an extraction mapped, primary first then by sort order.

        Joined to `presenting_complaints` for the display name, so the review
        screen and the queue name a complaint the same way. An outer join: a
        code the extraction invented would have been dropped before it got here,
        but a name is still allowed to be missing rather than losing the row.
        """
        statement = (
            select(
                extraction_complaints.c.complaint_code.label("code"),
                extraction_complaints.c.is_primary,
                PresentingComplaint.name,
            )
            .select_from(extraction_complaints)
            .outerjoin(
                PresentingComplaint,
                PresentingComplaint.code == extraction_complaints.c.complaint_code,
            )
            .where(extraction_complaints.c.extraction_id == extraction_id)
            .order_by(
                extraction_complaints.c.is_primary.desc(),
                PresentingComplaint.sort_order.asc().nulls_last(),
                extraction_complaints.c.complaint_code.asc(),
            )
        )
        return list(self._session.execute(statement).all())

    def latest_recommendation(self, case_id: uuid.UUID) -> Row | None:
        """The newest recommendation, with its knowledge-base version number.

        `kb_versions.version_no` rather than the id: the footnote under panel 3
        says "KB version 7", and the id means nothing to a reviewer (FR-26).
        """
        statement = (
            self._recommendation_statement(case_id)
            .order_by(Recommendation.version.desc(), Recommendation.id.desc())
            .limit(1)
        )
        return self._session.execute(statement).one_or_none()

    def recommendation_by_version(self, case_id: uuid.UUID, version: int) -> Row | None:
        """One stored recommendation version, for the read-only switcher (FR-27)."""
        statement = (
            self._recommendation_statement(case_id)
            .where(Recommendation.version == version)
            .order_by(Recommendation.id.desc())
            .limit(1)
        )
        return self._session.execute(statement).one_or_none()

    def recommendation_versions(self, case_id: uuid.UUID) -> list[Row]:
        """Every recommendation version for a case, oldest first (FR-27)."""
        statement = (
            select(
                Recommendation.version,
                Recommendation.category,
                Recommendation.created_at,
            )
            .where(Recommendation.case_id == case_id)
            .order_by(Recommendation.version.asc(), Recommendation.id.asc())
        )
        return list(self._session.execute(statement).all())

    @staticmethod
    def _recommendation_statement(case_id: uuid.UUID):
        """The columns every recommendation read returns, unordered."""
        return (
            select(
                Recommendation.id,
                Recommendation.version,
                Recommendation.category,
                # Selected as well as the version number: the baseline action
                # lookup is pinned to the version the run used (FR-54).
                Recommendation.kb_version_id,
                Recommendation.rationale,
                Recommendation.confidence,
                Recommendation.safety_floor_applied,
                Recommendation.safety_floor_rule_codes,
                Recommendation.low_confidence_reasons,
                Recommendation.model_id,
                Recommendation.prompt_version,
                Recommendation.latency_ms,
                Recommendation.created_at,
                Recommendation.extraction_id,
                KBVersion.version_no.label("kb_version_no"),
                ExtractionResult.version.label("extraction_version"),
            )
            .select_from(Recommendation)
            .outerjoin(KBVersion, KBVersion.id == Recommendation.kb_version_id)
            .outerjoin(ExtractionResult, ExtractionResult.id == Recommendation.extraction_id)
            .where(Recommendation.case_id == case_id)
        )

    def references(self, recommendation_id: uuid.UUID) -> list[Row]:
        """One recommendation's retrieved passages, in rank order (FR-31)."""
        statement = (
            select(
                RetrievedReference.rank,
                RetrievedReference.entry_title,
                RetrievedReference.source_title,
                RetrievedReference.source_url,
                RetrievedReference.passage_text,
                RetrievedReference.score,
                RetrievedReference.is_cited,
            )
            .where(RetrievedReference.recommendation_id == recommendation_id)
            .order_by(RetrievedReference.rank)
        )
        return list(self._session.execute(statement).all())

    def rule_labels(self, codes: list[str]) -> dict[str, str]:
        """The clinic's label for each red-flag rule code (IR-03).

        Used for the safety-floor notice, which names the rule in words rather
        than showing `MALE_CAT_NO_URINE`. A code with no rule row — one whose
        rule was removed after the recommendation was made — is simply absent
        from the mapping and the response reports a null label.
        """
        if not codes:
            return {}
        rows = self._session.execute(
            select(RedFlagRule.code, RedFlagRule.label).where(RedFlagRule.code.in_(codes))
        ).all()
        return {row.code: row.label for row in rows}

    # --- Reads: alerts, decisions, notes ----------------------------------

    def alerts(self, case_id: uuid.UUID) -> list[Row]:
        """Every red-flag alert on a case, most urgent first (FR-12).

        `matched_text` is deliberately not selected; see the module docstring.
        """
        statement = (
            select(
                RedFlagAlert.rule_code,
                RedFlagAlert.min_category,
                RedFlagAlert.created_at,
                RedFlagAlert.acknowledged_at,
                RedFlagRule.label.label("rule_label"),
            )
            .select_from(RedFlagAlert)
            .outerjoin(RedFlagRule, RedFlagRule.code == RedFlagAlert.rule_code)
            .where(RedFlagAlert.case_id == case_id)
            .order_by(RedFlagAlert.created_at.asc(), RedFlagAlert.id.asc())
        )
        return list(self._session.execute(statement).all())

    def latest_decision(self, case_id: uuid.UUID) -> Row | None:
        """The newest decision on a case, with the name of who made it."""
        statement = (
            select(
                StaffDecision.id,
                StaffDecision.type,
                StaffDecision.final_category,
                StaffDecision.reason_code,
                StaffDecision.reason_text,
                StaffDecision.direction,
                StaffDecision.decided_at,
                StaffDecision.amends_id,
                User.full_name.label("decided_by_name"),
            )
            .select_from(StaffDecision)
            .outerjoin(User, User.id == StaffDecision.decided_by)
            .where(StaffDecision.case_id == case_id)
            .order_by(StaffDecision.decided_at.desc(), StaffDecision.id.desc())
            .limit(1)
        )
        return self._session.execute(statement).one_or_none()

    def decision_exists(self, case_id: uuid.UUID, decision_id: uuid.UUID) -> bool:
        """Whether this decision belongs to this case.

        Checked before an amendment is accepted, so `amends_id` cannot be made
        to point at another patient's decision.
        """
        return (
            self._session.scalars(
                select(StaffDecision.id).where(
                    StaffDecision.id == decision_id, StaffDecision.case_id == case_id
                )
            ).first()
            is not None
        )

    def notes(self, case_id: uuid.UUID) -> list[Row]:
        """A case's clinical notes, oldest first, with their authors (FR-37).

        Chronological by `created_at`, with the id as a tie-break so the order
        is total and a page of them is stable. Two notes written in the *same*
        transaction share a timestamp and so have no meaningful order between
        them; each note added through the API is its own transaction, so that
        only arises in a fixture.
        """
        statement = (
            select(
                ClinicalNote.id,
                ClinicalNote.text,
                ClinicalNote.created_at,
                User.full_name.label("author_name"),
            )
            .select_from(ClinicalNote)
            .outerjoin(User, User.id == ClinicalNote.author_id)
            .where(ClinicalNote.case_id == case_id)
            .order_by(ClinicalNote.created_at.asc(), ClinicalNote.id.asc())
        )
        return list(self._session.execute(statement).all())

    def tailored_suggestions(self, recommendation_id: uuid.UUID) -> list[Row]:
        """The stored non-baseline suggestions, in display order (FR-76).

        Read when a reviewer finalizes without touching the checklist, so the
        list they are recorded as having accepted is the one they were shown.
        """
        statement = (
            select(ActionSuggestion.id, ActionSuggestion.text, ActionSuggestion.source)
            .where(
                ActionSuggestion.recommendation_id == recommendation_id,
                ActionSuggestion.source != ActionSource.BASELINE,
            )
            .order_by(ActionSuggestion.rank)
        )
        return list(self._session.execute(statement).all())

    # --- Reads: the audit timeline (FR-45, FR-46) --------------------------

    def audit_entries(self, case_id: uuid.UUID) -> list[Row]:
        """Every audit entry about this case, oldest first.

        Ordered by `(ts, id)`: the id is a monotonic bigint, so two entries
        written in the same transaction still have a definite order. The query
        matches `ix_audit_log_entity_type_entity_id_ts` exactly.

        The actor's name is joined from `users`; `audit_log` stores only the id
        and a snapshot of the role, which is correct — the role a person held at
        the time is part of the record, their current name is not.
        """
        statement = (
            select(
                AuditEntry.id,
                AuditEntry.ts,
                AuditEntry.action,
                AuditEntry.before,
                AuditEntry.after,
                AuditEntry.role,
                User.full_name.label("actor_name"),
            )
            .select_from(AuditEntry)
            .outerjoin(User, User.id == AuditEntry.user_id)
            .where(AuditEntry.entity_type == "case", AuditEntry.entity_id == str(case_id))
            .order_by(AuditEntry.ts.asc(), AuditEntry.id.asc())
        )
        return list(self._session.execute(statement).all())

    def latest_audit_entry(self, case_id: uuid.UUID, action: str) -> Row | None:
        """The newest audit entry of one kind about this case, or None.

        `action` is passed in as a plain string rather than read from
        `AuditAction`: that enum belongs to `AuditService`, and a repository that
        imported a service would invert the layering (CLAUDE.md §7). The column
        is `String(100)`, so the value the service hands over is the value stored.

        Ordered by `(ts, id)` descending, for the same reason `audit_entries`
        orders ascending by both: two entries written in one transaction share a
        timestamp, and the monotonic id is what breaks the tie. Uses the same
        `ix_audit_log_entity_type_entity_id_ts` index.
        """
        statement = (
            select(AuditEntry.ts, AuditEntry.after)
            .where(
                AuditEntry.entity_type == "case",
                AuditEntry.entity_id == str(case_id),
                AuditEntry.action == action,
            )
            .order_by(AuditEntry.ts.desc(), AuditEntry.id.desc())
            .limit(1)
        )
        return self._session.execute(statement).first()

    def extraction_marks(self, case_id: uuid.UUID) -> list[Row]:
        """Every extraction version for a case, oldest first.

        The timeline shows "Extraction v1 stored" (W-07), and storing an
        extraction writes no audit entry of its own — the pipeline audits the
        start of the run and the recommendation it ends with. So these items
        come from the table instead, which is what P06 §6.1 means by building
        the timeline from `audit_log` *and the related tables*.
        """
        statement = (
            select(
                ExtractionResult.version,
                ExtractionResult.prompt_version,
                ExtractionResult.is_corrected,
                ExtractionResult.created_at,
            )
            .where(ExtractionResult.case_id == case_id)
            .order_by(ExtractionResult.created_at.asc(), ExtractionResult.version.asc())
        )
        return list(self._session.execute(statement).all())

    def decisions(self, case_id: uuid.UUID) -> list[Row]:
        """Every decision on a case, oldest first, for the timeline details.

        The reason text the timeline prints comes from here and never from
        `audit_log`, which records categories and statuses only (ADR-12).
        """
        statement = (
            select(
                StaffDecision.id,
                StaffDecision.type,
                StaffDecision.final_category,
                StaffDecision.reason_code,
                StaffDecision.reason_text,
                StaffDecision.direction,
                StaffDecision.decided_at,
                StaffDecision.amends_id,
            )
            .where(StaffDecision.case_id == case_id)
            .order_by(StaffDecision.decided_at.asc(), StaffDecision.id.asc())
        )
        return list(self._session.execute(statement).all())

    def reference_counts(self, case_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """How many passages each of a case's recommendations retrieved.

        For the timeline line "Recommendation v1: YELLOW · 2 references" (W-07).
        """
        rows = self._session.execute(
            select(
                RetrievedReference.recommendation_id,
                func.count().label("reference_count"),
            )
            .join(Recommendation, Recommendation.id == RetrievedReference.recommendation_id)
            .where(Recommendation.case_id == case_id)
            .group_by(RetrievedReference.recommendation_id)
        ).all()
        return {row.recommendation_id: row.reference_count for row in rows}

    def timing_marks(self, case_id: uuid.UUID) -> TimingMarks:
        """The three instants the FR-46 intervals are measured between.

        One query with three scalar subqueries rather than three round trips:
        the three values are read together and shown together, and a case being
        decided between two of the reads would produce an interval measured
        against a case state that never existed.
        """
        first_recommendation = (
            select(func.min(Recommendation.created_at))
            .where(Recommendation.case_id == case_id)
            .scalar_subquery()
        )
        # The first decision, not the first amendment: an amendment has
        # `amends_id` set and is a correction of a decision already counted.
        first_decision = (
            select(func.min(StaffDecision.decided_at))
            .where(StaffDecision.case_id == case_id, StaffDecision.amends_id.is_(None))
            .scalar_subquery()
        )
        submitted = (
            select(OwnerDescription.submitted_at)
            .where(OwnerDescription.case_id == case_id)
            .scalar_subquery()
        )
        row = self._session.execute(
            select(
                submitted.label("submitted_at"),
                first_recommendation.label("first_recommendation_at"),
                first_decision.label("first_decision_at"),
            )
        ).one()
        return TimingMarks(
            submitted_at=row.submitted_at,
            first_recommendation_at=row.first_recommendation_at,
            first_decision_at=row.first_decision_at,
        )

    # --- Writes ------------------------------------------------------------

    def acknowledge_alerts(self, case_id: uuid.UUID, at: datetime) -> int:
        """Stamp a case's unacknowledged alerts and return how many. Flushes.

        Only the unacknowledged ones, so re-opening a case does not move a
        timestamp that already records when the alert was first seen — the
        acknowledgement is a fact about the first reviewer to look, not about
        the most recent page load (FR-12, NFR-05).
        """
        alerts = list(
            self._session.scalars(
                select(RedFlagAlert).where(
                    RedFlagAlert.case_id == case_id,
                    RedFlagAlert.acknowledged_at.is_(None),
                )
            )
        )
        for alert in alerts:
            alert.acknowledged_at = at
        if alerts:
            self._session.flush()
        return len(alerts)

    def insert_decision(
        self,
        *,
        case_id: uuid.UUID,
        decision_type: DecisionType,
        final_category: VTLCategory,
        reason_code: AdjustReason | None,
        reason_text: str | None,
        direction: DecisionDirection,
        decided_by: uuid.UUID,
        decided_at: datetime,
        amends_id: uuid.UUID | None,
    ) -> StaffDecision:
        """Insert one decision. Flushes, never commits.

        Always an insert. A correction is a new row carrying `amends_id`; the
        row it amends is never touched (FR-48, ADR-12).
        """
        decision = StaffDecision(
            case_id=case_id,
            type=decision_type,
            final_category=final_category,
            reason_code=reason_code,
            reason_text=reason_text,
            direction=direction,
            decided_by=decided_by,
            decided_at=decided_at,
            amends_id=amends_id,
        )
        self._session.add(decision)
        self._session.flush()
        return decision

    def insert_final_actions(
        self,
        *,
        case_id: uuid.UUID,
        decision_id: uuid.UUID,
        finalized_by: uuid.UUID,
        finalized_at: datetime,
        rows: list[FinalActionValues],
    ) -> list[FinalAction]:
        """Write the finalized action list. Flushes, never commits.

        Append-only in the database, by both a REVOKE on `triageai_app` and a
        trigger (DR-09, ADR-12), so this can only ever add rows. `rank` is the
        caller's order, 1-based, because the order a checklist is worked through
        is part of what was decided.

        `action_suggestions` is not touched: the suggestion stays as it was
        produced, which is what makes the reviewer's keep, edit and remove rates
        measurable (FR-76).
        """
        actions = [
            FinalAction(
                case_id=case_id,
                decision_id=decision_id,
                rank=rank,
                text=values.text,
                source=values.source,
                status=values.status,
                suggestion_id=values.suggestion_id,
                finalized_by=finalized_by,
                finalized_at=finalized_at,
            )
            for rank, values in enumerate(rows, start=1)
        ]
        if actions:
            self._session.add_all(actions)
            self._session.flush()
        return actions

    def insert_note(self, *, case_id: uuid.UUID, author_id: uuid.UUID, text: str) -> ClinicalNote:
        """Insert a clinical note. Flushes, never commits (FR-37)."""
        note = ClinicalNote(case_id=case_id, author_id=author_id, text=text)
        self._session.add(note)
        self._session.flush()
        return note

    def set_status(self, case_id: uuid.UUID, status: CaseStatus) -> None:
        """Set a case's status. Flushes, never commits.

        Unguarded, like `PipelineRepository.set_status`: whether the move is
        allowed is `case_transitions`' question, and the service asks it before
        calling this.
        """
        case = self._session.get(Case, case_id)
        if case is not None:
            case.status = status
            self._session.flush()

    def reopen_for_retry(self, case_id: uuid.UUID) -> bool:
        """Move `MANUAL_TRIAGE_REQUIRED` back to `SUBMITTED`; True if this call did.

        A compare-and-set in one statement rather than a read and a write: two
        reviewers pressing Retry at once must produce one job, and only one of
        them may see `True` (P07 §7.1 task 3). Flushes, never commits.
        """
        result = self._session.execute(
            update(Case)
            .where(Case.id == case_id, Case.status == CaseStatus.MANUAL_TRIAGE_REQUIRED)
            .values(status=CaseStatus.SUBMITTED)
        )
        self._session.flush()
        return result.rowcount == 1

    def begin_regeneration(self, case_id: uuid.UUID) -> bool:
        """Move `AWAITING_REVIEW` to `PROCESSING`; True if this call did.

        A compare-and-set in one statement, like `reopen_for_retry`: two presses
        of "Save and regenerate" must produce one job, and a decision recorded in
        between must win. While the case is `PROCESSING` no decision can be made
        on the recommendation that is about to be superseded (FR-27, NFR-11).
        Flushes, never commits.
        """
        result = self._session.execute(
            update(Case)
            .where(Case.id == case_id, Case.status == CaseStatus.AWAITING_REVIEW)
            .values(status=CaseStatus.PROCESSING)
        )
        self._session.flush()
        return result.rowcount == 1

    def close_case(self, case_id: uuid.UUID, at: datetime) -> Case | None:
        """Mark a case closed and stamp `closed_at`. Flushes, never commits."""
        case = self._session.get(Case, case_id)
        if case is None:
            return None
        case.status = CaseStatus.CLOSED
        case.closed_at = at
        self._session.flush()
        return case
