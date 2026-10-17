"""The human-in-the-loop decision, and the record it leaves (P06 §6.1).

This service owns the rules that make a TriageAI decision trustworthy, and none
of them may be reachable around:

* **A category is never final without a person.** Every status in
  `DECIDED_STATUSES` is reached only through `record_decision`, which requires a
  Veterinary Reviewer and writes a `StaffDecision` row. No background process
  sets one (BR-01, NFR-07, NFR-11).
* **A recorded decision is never edited.** A change is a new row carrying
  `amends_id`; the original stays exactly as it was written (FR-48, ADR-12).
* **Disagreement is cheap but never silent.** Adjusting requires a different
  category and a reason code from a fixed list, and the direction is computed
  and stored, because the reasons and the directions are the data behind the
  disagreement analysis (BR-03, FR-42).
* **What the reviewer accepted is recorded even when they accept everything.**
  Finalizing with no `final_actions` key is not "no actions"; it is the list
  they were shown, stored as `KEPT` (FR-76).

The audit payloads here carry identifiers, categories, statuses and counts.
Never the owner's description, never a reviewer's reason text, never an action's
text — the log cannot be corrected, and action text is untrusted model output
(CLAUDE.md §9, SR-17, FR-43).

`now` is injectable so a test can place a decision at an exact instant instead of
sleeping. The service raises `AppError` subclasses and knows nothing about HTTP
(CLAUDE.md §7).
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Row
from sqlalchemy.orm import Session

from app.core.errors import CaseNotFound, InvalidDecision
from app.core.vtl import TARGET_MINUTES
from app.models import (
    ActionSource,
    ActionStatus,
    AdjustReason,
    CaseStatus,
    DecisionType,
    User,
    VTLCategory,
)
from app.repositories.case_repository import CaseRepository
from app.repositories.review_repository import FinalActionValues, ReviewRepository
from app.schemas.review import (
    AuditTimeline,
    CaseClosed,
    DecisionCreate,
    DecisionOut,
    FinalActionInput,
    NoteCreate,
    NoteOut,
)
from app.services.audit_service import CASE_ENTITY, AuditAction, AuditService
from app.services.case_transitions import (
    direction as compute_direction,
)
from app.services.case_transitions import (
    require_closable,
    require_decision_allowed,
)
from app.services.timeline import build_timeline

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ReviewService:
    def __init__(self, session: Session, *, now: Clock | None = None) -> None:
        self._session = session
        self._reviews = ReviewRepository(session)
        self._cases = CaseRepository(session)
        self._audit = AuditService(session)
        self._now = now or _utc_now

    # --- Decisions (FR-32..FR-35) -----------------------------------------

    def record_decision(
        self, case_id: uuid.UUID, payload: DecisionCreate, user: User
    ) -> DecisionOut:
        """Record one decision and move the case. One transaction.

        The order matters. The transition is checked before anything is written,
        so a request that is not allowed leaves no trace of having been tried;
        and the decision row is inserted before the status is changed, so a
        failure between the two cannot produce a case that claims to be decided
        with nothing behind the claim (BR-01).
        """
        status = self._reviews.status_of(case_id)
        if status is None:
            raise CaseNotFound()

        recommendation = self._reviews.latest_recommendation(case_id)
        recommended = None if recommendation is None else VTLCategory(recommendation.category)
        previous = self._reviews.latest_decision(case_id)

        amends_id = self._resolve_amendment(case_id, payload)
        next_status = require_decision_allowed(
            status, payload.type, is_amendment=amends_id is not None
        )
        final_category = self._resolve_category(payload, recommended)
        self._require_reason(payload)

        decided_at = self._now()
        decision = self._reviews.insert_decision(
            case_id=case_id,
            decision_type=payload.type,
            final_category=final_category,
            reason_code=payload.reason_code,
            reason_text=payload.reason_text,
            direction=compute_direction(recommended, final_category),
            decided_by=user.id,
            decided_at=decided_at,
            amends_id=amends_id,
        )
        self._reviews.set_status(case_id, next_status)

        # Categories and statuses only. The reason text stays on the decision
        # row, which is readable beside the case and correctable by amendment.
        self._audit.record(
            action=AuditAction.DECISION_RECORDED,
            entity_type=CASE_ENTITY,
            entity_id=str(case_id),
            user_id=user.id,
            role=user.role,
            before={
                "status": status.value,
                "category": None if recommended is None else recommended.value,
                "previous_decision_id": None if previous is None else str(previous.id),
            },
            after={
                "status": next_status.value,
                "category": final_category.value,
                "decision_id": str(decision.id),
                "decision_type": payload.type.value,
                "reason_code": None if payload.reason_code is None else payload.reason_code.value,
                "direction": decision.direction.value,
                "amends_id": None if amends_id is None else str(amends_id),
            },
        )

        self._finalize_actions(
            case_id=case_id,
            decision_id=decision.id,
            final_category=final_category,
            recommendation=recommendation,
            payload=payload,
            user=user,
            finalized_at=decided_at,
        )

        # FR-34 requires a note with a manual triage, and a reviewer may attach
        # one to any decision. It is a note like any other, so it appears on the
        # timeline through the same path.
        if payload.note is not None:
            self._reviews.insert_note(case_id=case_id, author_id=user.id, text=payload.note)
            self._audit.record(
                action=AuditAction.NOTE_ADDED,
                entity_type=CASE_ENTITY,
                entity_id=str(case_id),
                user_id=user.id,
                role=user.role,
                after={"with_decision": True, "char_count": len(payload.note)},
            )

        self._session.commit()
        return DecisionOut(
            id=decision.id,
            type=payload.type,
            final_category=final_category,
            target_minutes=TARGET_MINUTES[final_category],
            reason_code=payload.reason_code,
            reason_text=payload.reason_text,
            direction=decision.direction,
            decided_by_name=user.full_name,
            decided_at=decided_at,
            amends_id=amends_id,
            status=next_status,
        )

    def _resolve_amendment(self, case_id: uuid.UUID, payload: DecisionCreate) -> uuid.UUID | None:
        """Validate `amends_id` and return it, or None for a first decision.

        An amendment must name a decision on *this* case, so a reviewer cannot
        be made to amend another patient's record by a malformed request, and it
        must carry a reason: the point of an amendment is that the record says
        why the earlier decision was superseded (FR-48, BR-03).
        """
        if payload.amends_id is None:
            return None
        if not self._reviews.decision_exists(case_id, payload.amends_id):
            raise InvalidDecision("That decision does not belong to this case.", field="amends_id")
        if payload.reason_code is None:
            raise InvalidDecision(
                "Choose a reason for amending the decision that was already recorded.",
                field="reason_code",
            )
        return payload.amends_id

    def _resolve_category(
        self, payload: DecisionCreate, recommended: VTLCategory | None
    ) -> VTLCategory:
        """The category this decision settles on (FR-32, FR-33, FR-34).

        CONFIRM takes the recommendation's category rather than the client's.
        That is the whole meaning of confirming, and accepting a category here
        would allow a "confirmation" that quietly disagreed with the thing it
        claims to confirm.

        ADJUST and MANUAL require an explicit category, and ADJUST requires a
        *different* one — adjusting to the same category is not a disagreement
        and would pollute the direction statistics with meaningless rows.
        """
        if payload.type is DecisionType.CONFIRM:
            if recommended is None:
                raise InvalidDecision(
                    "There is no AI recommendation to confirm. Use manual triage instead.",
                    field="type",
                )
            return recommended

        if payload.final_category is None:
            raise InvalidDecision(
                "Choose one of the five urgency categories.", field="final_category"
            )

        if payload.type is DecisionType.ADJUST and payload.final_category is recommended:
            raise InvalidDecision(
                "That is already the recommended category. Confirm it instead, or "
                "choose a different one.",
                field="final_category",
            )

        if payload.type is DecisionType.MANUAL and payload.note is None:
            raise InvalidDecision("Enter a note explaining the manual triage.", field="note")

        return payload.final_category

    def _require_reason(self, payload: DecisionCreate) -> None:
        """An ADJUST needs a reason code, and `OTHER` needs the detail (BR-03).

        The database's check constraint enforces the first of these too. It is
        checked here as well so the answer is a 422 naming the field rather than
        an integrity error, which no form can display.
        """
        if payload.type is DecisionType.ADJUST and payload.reason_code is None:
            raise InvalidDecision(
                "Choose a reason for the change from the list.", field="reason_code"
            )
        if payload.reason_code is AdjustReason.OTHER and payload.reason_text is None:
            raise InvalidDecision("Describe the reason for the change.", field="reason_text")

    # --- Finalized actions (FR-76, DR-09) ---------------------------------

    def _finalize_actions(
        self,
        *,
        case_id: uuid.UUID,
        decision_id: uuid.UUID,
        final_category: VTLCategory,
        recommendation: Row | None,
        payload: DecisionCreate,
        user: User,
        finalized_at: datetime,
    ) -> None:
        """Write the action list this decision settles, and audit the counts.

        `action_suggestions` is never touched. The suggestion is the record of
        what was proposed; `final_actions` is the record of what was decided, and
        keeping them apart is what makes the keep/edit/remove rates measurable
        without the original ever being overwritten (DR-09, ADR-18 §6).
        """
        rows = (
            self._explicit_actions(payload.final_actions)
            if payload.final_actions is not None
            else self._accepted_actions(final_category, recommendation)
        )
        self._reviews.insert_final_actions(
            case_id=case_id,
            decision_id=decision_id,
            finalized_by=user.id,
            finalized_at=finalized_at,
            rows=rows,
        )

        # Counts per status and nothing else: an action's text is untrusted
        # model output and the log is permanent (SR-17).
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.status.value] = counts.get(row.status.value, 0) + 1
        self._audit.record(
            action=AuditAction.ACTIONS_FINALIZED,
            entity_type=CASE_ENTITY,
            entity_id=str(case_id),
            user_id=user.id,
            role=user.role,
            after={
                "decision_id": str(decision_id),
                "category": final_category.value,
                "total": len(rows),
                "counts_by_status": counts,
                "was_edited_by_reviewer": payload.final_actions is not None,
            },
        )

    def _explicit_actions(self, actions: list[FinalActionInput]) -> list[FinalActionValues]:
        """The list the reviewer sent, in the order they sent it."""
        return [
            FinalActionValues(
                text=action.text,
                source=action.source,
                status=action.status,
                suggestion_id=action.suggestion_id,
            )
            for action in actions
        ]

    def _accepted_actions(
        self, final_category: VTLCategory, recommendation: Row | None
    ) -> list[FinalActionValues]:
        """What a reviewer who did not touch the checklist therefore accepted.

        The baseline set for the category they settled on — read live, so it
        follows a reviewer who changed the category (ADR-18 §6) — plus the
        tailored suggestions they were shown. All `KEPT`: they decided on this
        list by not changing it, and a decision with no action record at all
        would lose that (FR-76).

        **The tailored actions are dropped when the category moved.** They were
        generated for the recommendation's category, and FR-78 says a changed
        category makes them outdated. A reviewer who adjusts ORANGE to RED and
        does not open the checklist has approved nothing case-specific, so
        recording ORANGE's suggestions as actions they kept would put approval
        in the permanent record that they never gave. They stay in
        `action_suggestions`, where the screen can still show them flagged as
        outdated (P07 §7.2b).
        """
        rows = [
            FinalActionValues(text=text, source=ActionSource.BASELINE, status=ActionStatus.KEPT)
            for text in self._baseline(final_category, recommendation)
        ]
        if recommendation is None:
            return rows
        if VTLCategory(recommendation.category) is not final_category:
            return rows
        rows += [
            FinalActionValues(
                text=suggestion.text,
                source=ActionSource(suggestion.source),
                status=ActionStatus.KEPT,
                suggestion_id=suggestion.id,
            )
            for suggestion in self._reviews.tailored_suggestions(recommendation.id)
        ]
        return rows

    def _baseline(self, category: VTLCategory, recommendation: Row | None) -> list[str]:
        """The baseline actions for one category (FR-71, FR-72).

        Imported here rather than at module scope so this service does not pull
        the pipeline package in at import time; `CaseService` does the same read
        for the review response.
        """
        from app.pipeline.action_validator import baseline_actions

        kb_version_id = None if recommendation is None else recommendation.kb_version_id
        if kb_version_id is None:
            kb_version_id = self._cases.latest_kb_version_id()
        if kb_version_id is None:
            return []
        return baseline_actions(self._session, category, kb_version_id)

    # --- Notes and close (FR-37, FR-38) -----------------------------------

    def add_note(self, case_id: uuid.UUID, payload: NoteCreate, user: User) -> NoteOut:
        """Attach a clinical note to a case (FR-37).

        Allowed at any status, including a closed case: a note is a record of
        something a clinician observed, and the time to write one down is when
        it is known rather than when the workflow permits it. It appears on the
        timeline, so adding one to a closed case is visible rather than quiet.
        """
        status = self._reviews.status_of(case_id)
        if status is None:
            raise CaseNotFound()

        note = self._reviews.insert_note(case_id=case_id, author_id=user.id, text=payload.text)
        # The note's text is not audited, only that one was added: it is
        # clinical content, and the log cannot be corrected (FR-43).
        self._audit.record(
            action=AuditAction.NOTE_ADDED,
            entity_type=CASE_ENTITY,
            entity_id=str(case_id),
            user_id=user.id,
            role=user.role,
            after={
                "note_id": str(note.id),
                "with_decision": False,
                "char_count": len(payload.text),
            },
        )
        self._session.commit()
        return NoteOut(
            id=note.id,
            text=payload.text,
            author_name=user.full_name,
            created_at=note.created_at,
        )

    def close_case(self, case_id: uuid.UUID, user: User) -> CaseClosed:
        """Close a case, removing it from the active queue (FR-38).

        Only after a decision. Closing an undecided case would drop a patient
        off the working list with no recorded urgency, which is the single
        outcome the queue exists to prevent.
        """
        status = self._reviews.status_of(case_id)
        if status is None:
            raise CaseNotFound()
        require_closable(status)

        closed_at = self._now()
        case = self._reviews.close_case(case_id, closed_at)
        if case is None:
            raise CaseNotFound()

        self._audit.record(
            action=AuditAction.CASE_CLOSED,
            entity_type=CASE_ENTITY,
            entity_id=str(case_id),
            user_id=user.id,
            role=user.role,
            before={"status": status.value},
            after={"status": CaseStatus.CLOSED.value, "closed_at": closed_at.isoformat()},
        )
        closed = CaseClosed(
            id=case.id,
            case_no=case.case_no,
            status=CaseStatus.CLOSED,
            closed_at=closed_at,
        )
        self._session.commit()
        return closed

    # --- The audit timeline (FR-45, FR-46) --------------------------------

    def get_timeline(self, case_id: uuid.UUID) -> AuditTimeline:
        """The chronological record of one case, with its timing intervals.

        Built from `audit_log` — the only append-only, provably complete record
        of what happened (FR-43, ADR-12) — joined with the related tables for the
        details the log must not hold: a reviewer's reason text, the extraction
        versions, and how many passages each recommendation retrieved.
        """
        if self._reviews.status_of(case_id) is None:
            raise CaseNotFound()

        return build_timeline(
            entries=self._reviews.audit_entries(case_id),
            extractions=self._reviews.extraction_marks(case_id),
            decisions=self._reviews.decisions(case_id),
            reference_counts=self._reviews.reference_counts(case_id),
            marks=self._reviews.timing_marks(case_id),
        )
