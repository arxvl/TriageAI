"""Suggested and finalized actions (DR-09, ADR-18).

Two tables, deliberately separate:

* `action_suggestions` is what the pipeline produced — baseline rows copied from
  the `URGENCY_ACTIONS` entry and tailored rows that survived the deterministic
  action validator (FR-74). It carries the provenance DR-09 asks for, so a
  suggestion can be read back later with the model, prompt version, knowledge
  base version and cited chunks that produced it (FR-26, ADR-14).
* `final_actions` is what a Veterinary Reviewer decided, written once with the
  decision and never edited (FR-76, ADR-12). Keeping the reviewer's outcome
  apart from the suggestion is what makes keep/edit/remove rates measurable
  without the original ever being overwritten.

Action text is untrusted model output: it is length-limited and screened before
it ever reaches a row here, and it is never written to a log (SR-17).
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin
from app.models.enums import ActionSource, ActionStatus, VTLCategory, pg_enum


class ActionSuggestion(Base, UUIDPKMixin, CreatedAtMixin):
    """One suggested action, as produced for a recommendation.

    `generated_for_category` is recorded rather than inferred: if a reviewer
    later changes the category, the stored rows are what lets the UI say the
    tailored actions are outdated instead of quietly showing them against the
    wrong urgency (FR-78).
    """

    __tablename__ = "action_suggestions"

    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id"))
    vignette_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vignettes.id"))
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recommendations.id"), nullable=False
    )
    generated_for_category: Mapped[VTLCategory] = mapped_column(
        pg_enum(VTLCategory, "vtl_category"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[ActionSource] = mapped_column(
        pg_enum(ActionSource, "action_source"), nullable=False
    )
    cited_chunk_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    kb_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kb_versions.id"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        # The same rule as `recommendations`: a suggestion belongs to a case or
        # to an evaluation vignette, never both and never neither.
        CheckConstraint(
            "(case_id IS NULL) <> (vignette_id IS NULL)",
            name="ck_action_suggestions_case_xor_vignette",
        ),
        # Not unique: the actions job may be retried, and a retry replaces the
        # previous rows rather than being rejected by a constraint.
        Index("ix_action_suggestions_recommendation_id_rank", "recommendation_id", "rank"),
    )


class FinalAction(Base, UUIDPKMixin):
    """One row of the action list a reviewer finalized with their decision.

    Append-only in the database, by both a REVOKE on `triageai_app` and the
    `prevent_modify()` trigger (DR-09, ADR-12). A later correction is a new
    decision with new rows, never an edit of these.

    `suggestion_id` is null for an action the reviewer wrote themselves
    (`source = REVIEWER`).
    """

    __tablename__ = "final_actions"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), nullable=False)
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff_decisions.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[ActionSource] = mapped_column(
        pg_enum(ActionSource, "action_source"), nullable=False
    )
    status: Mapped[ActionStatus] = mapped_column(
        pg_enum(ActionStatus, "action_status"), nullable=False
    )
    suggestion_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("action_suggestions.id"))
    finalized_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_final_actions_case_id_rank", "case_id", "rank"),)
