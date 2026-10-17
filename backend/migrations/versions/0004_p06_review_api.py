"""p06 review api

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17

What the Case Review screen and the human-in-the-loop decision need from the
schema (P06 §6.1, FR-13, FR-33, FR-45, ADR-10, ADR-12).

Three things, in the order `upgrade()` does them:

1. `extraction_results.input_text` — the **de-identified** description a run was
   actually given. ADR-10 specifies this column and the pipeline has been
   computing the string since P05 without storing it. Evidence spans are exact
   substrings of it (`pipeline/types.py`), so the review screen cannot position
   a highlight without it (FR-13).

   Nullable, and it has to be: an extraction written before this migration has
   no stored de-identified text and it cannot be reconstructed — the raw
   description is immutable but the de-identifier's output is not derivable from
   it once the owner reference has changed. Those rows report every span as
   `found: false` rather than guessing.

   The column holds clinical free text, so it is subject to the same rule as
   `owner_descriptions.text`: never an audit payload, never a log record
   (CLAUDE.md §9, SR-17).

2. `staff_decisions.reason_code` becomes the native enum `adjust_reason`
   (P06 §6.1 task 4). It was `String(100)` because P02 had no list to constrain
   it to. Every other enum column in this schema is a native PostgreSQL type,
   and a reason code is the data behind the disagreement analysis — a typo in it
   is a lost data point, so the database rejects one. The cast is safe: nothing
   has ever written a `staff_decisions` row outside the test fixtures.

   The existing `ck_staff_decisions_reason_code_required_for_adjust` already
   makes a code mandatory for ADJUST, so no new constraint is needed.

3. Indexes for the reads P06 adds. `audit_log` already has
   `ix_audit_log_entity_type_entity_id_ts`, which is exactly the timeline query;
   the per-case decision, note and reference reads had no index at all.

No new tables, so no new grants and no new `prevent_modify` trigger.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# As in 0001 and 0003, create_type=False: the type is created and dropped
# explicitly here, never implicitly by a column operation.
adjust_reason = postgresql.ENUM(
    "CONDITION_DIFFERS_ON_ARRIVAL",
    "SIGN_NOT_CAPTURED",
    "RECOMMENDATION_TOO_LOW",
    "RECOMMENDATION_TOO_HIGH",
    "OTHER",
    name="adjust_reason",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    adjust_reason.create(bind, checkfirst=True)

    # --- 1. the de-identified text a run was given (ADR-10, FR-13) ---------
    op.add_column("extraction_results", sa.Column("input_text", sa.Text(), nullable=True))

    # --- 2. reason codes become a constrained set (FR-33, BR-03) -----------
    # Any value already stored would have to be one of the five codes for this
    # to succeed. Nothing writes decisions yet, so the table is empty outside
    # the test fixtures, which this migration's companion change updates.
    op.alter_column(
        "staff_decisions",
        "reason_code",
        existing_type=sa.String(length=100),
        type_=adjust_reason,
        existing_nullable=True,
        postgresql_using="reason_code::adjust_reason",
    )

    # --- 3. indexes for the per-case review reads --------------------------
    op.create_index("ix_staff_decisions_case_id", "staff_decisions", ["case_id"])
    op.create_index("ix_clinical_notes_case_id", "clinical_notes", ["case_id"])
    op.create_index(
        "ix_retrieved_references_recommendation_id_rank",
        "retrieved_references",
        ["recommendation_id", "rank"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_retrieved_references_recommendation_id_rank", table_name="retrieved_references"
    )
    op.drop_index("ix_clinical_notes_case_id", table_name="clinical_notes")
    op.drop_index("ix_staff_decisions_case_id", table_name="staff_decisions")

    op.alter_column(
        "staff_decisions",
        "reason_code",
        existing_type=adjust_reason,
        type_=sa.String(length=100),
        existing_nullable=True,
        postgresql_using="reason_code::text",
    )

    op.drop_column("extraction_results", "input_text")

    adjust_reason.drop(op.get_bind(), checkfirst=True)
