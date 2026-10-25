"""p09 2 evaluation harness

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-25

What the evaluation harness needs that migration 0001 did not give the tables
(P09 §9.2, FR-64..FR-69, NFR-23, DR-06).

`evaluation_results.payload` holds what a run found out about one vignette that
has no column of its own: the red-flag hits, the entry ids the retriever returned
in rank order (the retrieval metrics read them), the primary complaint and the
safety-floor flag.

`evaluation_runs.created_at` and `created_by` exist because `started_at` is NULL
while a run is queued, and the run list needs an order and an author.

Three unique constraints:
- `evaluation_sets.name`, because the CLI resolves a set by its name.
- `vignettes (set_id, external_id)`, so an id means one vignette within a set.
- `evaluation_results (run_id, vignette_id)`, so a run that is picked up again
  after a crash skips what it already did instead of scoring a vignette twice.

No new table, so no new grants: the four evaluation tables are already writable
by the application role (migration 0002).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_results",
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "evaluation_runs",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column("evaluation_runs", sa.Column("created_by", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_evaluation_runs_created_by_users", "evaluation_runs", "users", ["created_by"], ["id"]
    )
    op.create_unique_constraint("uq_evaluation_sets_name", "evaluation_sets", ["name"])
    op.create_unique_constraint(
        "uq_vignettes_set_id_external_id", "vignettes", ["set_id", "external_id"]
    )
    op.create_unique_constraint(
        "uq_evaluation_results_run_id_vignette_id", "evaluation_results", ["run_id", "vignette_id"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_evaluation_results_run_id_vignette_id", "evaluation_results", type_="unique"
    )
    op.drop_constraint("uq_vignettes_set_id_external_id", "vignettes", type_="unique")
    op.drop_constraint("uq_evaluation_sets_name", "evaluation_sets", type_="unique")
    op.drop_constraint("fk_evaluation_runs_created_by_users", "evaluation_runs", type_="foreignkey")
    op.drop_column("evaluation_runs", "created_by")
    op.drop_column("evaluation_runs", "created_at")
    op.drop_column("evaluation_results", "payload")
