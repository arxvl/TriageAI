"""p07 2b action sets

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-24

Suggested actions can be regenerated for a changed category without losing the
set they replace (P07 §7.2b, FR-78, ADR-18 §6).

`action_suggestions.generation` numbers the sets of one recommendation. Every
existing row is generation 1, which is what the column default gives them. A
regeneration is a later generation, and the actions job replaces only its own
generation, so a retry of the same job never duplicates a set and never touches
an earlier one.

The ranking index gains `generation` in front of `rank`, because the review
screen reads one generation of one recommendation in rank order.

No new table, so no new grants: `action_suggestions` is already writable by the
application role (migration 0003).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "action_suggestions",
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
    )
    op.drop_index("ix_action_suggestions_recommendation_id_rank", table_name="action_suggestions")
    op.create_index(
        "ix_action_suggestions_recommendation_id_generation_rank",
        "action_suggestions",
        ["recommendation_id", "generation", "rank"],
    )


def downgrade() -> None:
    # Earlier sets cannot be told apart once the column is gone, and the
    # two-set rows would overlap in rank. Keep the newest set of each
    # recommendation, which is the one the screen was showing.
    op.execute(
        "DELETE FROM action_suggestions a USING ("
        "SELECT recommendation_id, max(generation) AS latest "
        "FROM action_suggestions GROUP BY recommendation_id"
        ") newest "
        "WHERE a.recommendation_id = newest.recommendation_id AND a.generation < newest.latest"
    )
    op.drop_index(
        "ix_action_suggestions_recommendation_id_generation_rank",
        table_name="action_suggestions",
    )
    op.create_index(
        "ix_action_suggestions_recommendation_id_rank",
        "action_suggestions",
        ["recommendation_id", "rank"],
    )
    op.drop_column("action_suggestions", "generation")
