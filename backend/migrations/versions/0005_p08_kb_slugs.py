"""p08 kb slugs

Revision ID: 0005
Revises: c2b9970f3c53
Create Date: 2026-10-19

What the knowledge-base workflow needs from the schema (P08 §8.1 task 1,
FR-51, FR-54, FR-56, NFR-08, ADR-14).

Four columns and one index, and none of them is nullable-by-accident:

1. `kb_entries.slug` — the stable name a file in `knowledge_base/entries/`
   carries, so re-importing the same file updates the row it created rather than
   inserting a second one (FR-56). Unique, and **nullable**: the five
   urgency-action entries `scripts/seed.py` wrote have no file behind them, and
   PostgreSQL treats NULLs in a unique index as distinct, so they coexist.

2. `kb_entries.revises_entry_id` — the ACTIVE entry a draft supersedes. An
   ACTIVE entry is never edited in place; a changed file becomes a new DRAFT
   revision pointing back at it (ADR-14). Added here rather than in 8.2 because
   a subphase gets one migration (CLAUDE.md §11) and the importer is told to
   rely on this column.

3. `red_flag_rules.phrases_ref` — the key in `knowledge_base/red_flag_phrases.yaml`
   holding this rule's phrases. The phrases themselves are maintained by hand
   (M1) and deliberately do not live in the database: the categories do, and
   duplicating the phrase lists into rows would give the safety floor two
   sources of truth.

4. `red_flag_rules.retired_at` — a retired rule never fires again
   (`get_active_rules`). Retiring rather than deleting, because a recommendation
   whose safety floor cited the rule must still be explainable (FR-23, ADR-14).

`ix_kb_entries_status_kind` serves W-08's four status tabs and the kind filter.

No new tables, so no new grants and no new `prevent_modify` trigger: migration
0002 already granted the application role default privileges on tables added
later, and `kb_version_entries` is already append-only (DR-05).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "c2b9970f3c53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("kb_entries", sa.Column("slug", sa.String(length=120), nullable=True))
    op.create_index("uq_kb_entries_slug", "kb_entries", ["slug"], unique=True)

    op.add_column("kb_entries", sa.Column("revises_entry_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_kb_entries_revises_entry_id",
        "kb_entries",
        "kb_entries",
        ["revises_entry_id"],
        ["id"],
    )

    op.add_column("red_flag_rules", sa.Column("phrases_ref", sa.Text(), nullable=True))
    op.add_column(
        "red_flag_rules", sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_index("ix_kb_entries_status_kind", "kb_entries", ["status", "kind"])


def downgrade() -> None:
    op.drop_index("ix_kb_entries_status_kind", table_name="kb_entries")

    op.drop_column("red_flag_rules", "retired_at")
    op.drop_column("red_flag_rules", "phrases_ref")

    op.drop_constraint("fk_kb_entries_revises_entry_id", "kb_entries", type_="foreignkey")
    op.drop_column("kb_entries", "revises_entry_id")

    op.drop_index("uq_kb_entries_slug", table_name="kb_entries")
    op.drop_column("kb_entries", "slug")
