"""Database reads for the de-identified exports (P09 §9.4, FR-47, BR-08).

Reads only, and only the columns an export may carry: the case query never
selects the description, the owner reference, the pet name, a note, a rationale,
a reason text or an action's text — they are not in the `select`, so no later
formatting mistake can leak them. "Latest" means what the queue and Case History
mean by it: the highest recommendation version and the most recent decision
(FR-44).
"""

import uuid
from datetime import datetime

from sqlalchemy import Row, func, select, true
from sqlalchemy.orm import Session, aliased

from app.models import (
    ActionSource,
    ActionStatus,
    ActionSuggestion,
    AuditEntry,
    Case,
    FinalAction,
    Recommendation,
    StaffDecision,
    User,
    UserRole,
)


class ExportRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def case_rows(self, start: datetime | None, end: datetime | None) -> list[Row]:
        """One row per case created in `[start, end)`, oldest first.

        `start` and `end` are UTC instants; either may be open.
        """
        recommendation = (
            select(
                Recommendation.id,
                Recommendation.category,
                Recommendation.confidence,
                Recommendation.safety_floor_applied,
                Recommendation.created_at,
                Recommendation.actions_rejected_count,
            )
            .where(Recommendation.case_id == Case.id)
            .order_by(Recommendation.version.desc(), Recommendation.id.desc())
            .correlate(Case)
            .limit(1)
            .lateral("latest_recommendation")
        )
        decision = (
            select(
                StaffDecision.id,
                StaffDecision.type,
                StaffDecision.final_category,
                StaffDecision.reason_code,
                StaffDecision.direction,
                StaffDecision.decided_at,
            )
            .where(StaffDecision.case_id == Case.id)
            .order_by(StaffDecision.decided_at.desc(), StaffDecision.id.desc())
            .correlate(Case)
            .limit(1)
            .lateral("latest_decision")
        )

        # The newest set of suggestions for that recommendation: a regeneration
        # adds a set and keeps the earlier one (FR-78), and only the set the
        # reviewer was shown counts as "shown".
        newest = aliased(ActionSuggestion)
        suggested = (
            select(
                func.count()
                .filter(ActionSuggestion.source == ActionSource.BASELINE)
                .label("baseline"),
                func.count().filter(ActionSuggestion.source == ActionSource.AI).label("tailored"),
            )
            .where(
                ActionSuggestion.recommendation_id == recommendation.c.id,
                ActionSuggestion.generation
                == select(func.max(newest.generation))
                .where(newest.recommendation_id == recommendation.c.id)
                .correlate(recommendation)
                .scalar_subquery(),
            )
            .correlate(recommendation)
            .lateral("suggested_counts")
        )

        finalized = (
            select(
                *[
                    func.count().filter(FinalAction.status == status).label(status.value.lower())
                    for status in (
                        ActionStatus.KEPT,
                        ActionStatus.EDITED,
                        ActionStatus.REMOVED,
                        ActionStatus.ADDED,
                    )
                ]
            )
            .where(FinalAction.decision_id == decision.c.id)
            .correlate(decision)
            .lateral("final_counts")
        )

        statement = (
            select(
                Case.case_no,
                Case.species,
                Case.created_at,
                Case.status,
                recommendation.c.id.label("recommendation_id"),
                recommendation.c.category.label("ai_category"),
                recommendation.c.confidence.label("ai_confidence"),
                recommendation.c.safety_floor_applied,
                recommendation.c.created_at.label("recommendation_at"),
                decision.c.id.label("decision_id"),
                decision.c.final_category,
                decision.c.type.label("decision_type"),
                decision.c.reason_code,
                decision.c.direction,
                decision.c.decided_at,
                suggested.c.baseline.label("baseline_shown"),
                suggested.c.tailored.label("tailored_suggested"),
                recommendation.c.actions_rejected_count.label("tailored_rejected"),
                finalized.c.kept.label("final_kept"),
                finalized.c.edited.label("final_edited"),
                finalized.c.removed.label("final_removed"),
                finalized.c.added.label("final_added"),
            )
            .select_from(Case)
            .outerjoin(recommendation, true())
            .outerjoin(decision, true())
            .outerjoin(suggested, true())
            .outerjoin(finalized, true())
            .order_by(Case.created_at, Case.id)
        )
        if start is not None:
            statement = statement.where(Case.created_at >= start)
        if end is not None:
            statement = statement.where(Case.created_at < end)
        return list(self._session.execute(statement).all())

    def audit_rows(self, start: datetime | None, end: datetime | None) -> list[Row]:
        """Audit entries stamped in `[start, end)`, in the order they were written."""
        statement = select(
            AuditEntry.id,
            AuditEntry.ts,
            AuditEntry.user_id,
            AuditEntry.role,
            AuditEntry.action,
            AuditEntry.entity_type,
            AuditEntry.entity_id,
            AuditEntry.before,
            AuditEntry.after,
        ).order_by(AuditEntry.ts, AuditEntry.id)
        if start is not None:
            statement = statement.where(AuditEntry.ts >= start)
        if end is not None:
            statement = statement.where(AuditEntry.ts < end)
        return list(self._session.execute(statement).all())

    def user_roles(self) -> dict[uuid.UUID, UserRole]:
        """Every account's id and role — nothing else about them is read."""
        rows = self._session.execute(select(User.id, User.role)).all()
        return {row.id: row.role for row in rows}
