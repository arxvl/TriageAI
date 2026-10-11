"""p05b suggested actions

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-11

Storage for suggested actions per urgency level (DR-09, FR-71..FR-79, ADR-18).

Four things, in the order `upgrade()` does them:

1. `kb_entries` learns the difference between retrievable clinical content and a
   baseline action set. `complaint_code` becomes nullable, because an
   `URGENCY_ACTIONS` entry belongs to a VTL category rather than to a presenting
   complaint; two check constraints keep the two kinds exclusive.
2. `recommendations` gains the three columns the review screen polls while the
   actions job runs. They sit on the recommendation rather than in a side table
   so one query returns both (P05b §5b.1).
3. `action_suggestions` holds what the pipeline produced, with provenance;
   `final_actions` holds what the reviewer decided, append-only.
4. `job_type` gains `SUGGEST_ACTIONS`.

`job_type` is a native PostgreSQL enum (migration 0001), so adding a member is
`ALTER TYPE ... ADD VALUE`, not a column change. PostgreSQL 16 permits that
inside a transaction as long as the new value is not *used* in the same
transaction, which this migration never does. It appends the value after
`KB_INDEX` rather than at the position `JobType` lists it; nothing orders by the
column, so the sort order of the type is immaterial.

An enum value cannot be removed, so the downgrade rebuilds the type instead and
drops any `SUGGEST_ACTIONS` jobs first — a job for a feature that is being
removed has nothing left to do.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "triageai_app"

# Types this migration owns. As in 0001, create_type=False: they are created and
# dropped explicitly here, never implicitly by op.create_table().
kb_entry_kind = postgresql.ENUM(
    "COMPLAINT", "URGENCY_ACTIONS", name="kb_entry_kind", create_type=False
)
action_source = postgresql.ENUM(
    "BASELINE", "AI", "REVIEWER", name="action_source", create_type=False
)
action_status = postgresql.ENUM(
    "SUGGESTED", "KEPT", "EDITED", "REMOVED", "ADDED", name="action_status", create_type=False
)
actions_status = postgresql.ENUM(
    "PENDING", "READY", "FAILED", "NOT_APPLICABLE", name="actions_status", create_type=False
)

ENUM_TYPES = (kb_entry_kind, action_source, action_status, actions_status)

# Reused from 0001 rather than redeclared, so no duplicate CREATE TYPE is
# emitted for a type those tables share.
vtl_category = postgresql.ENUM(
    "RED", "ORANGE", "YELLOW", "GREEN", "BLUE", name="vtl_category", create_type=False
)

JOB_TYPES_BEFORE = ("PIPELINE_RUN", "REGENERATE", "EVAL_RUN", "KB_INDEX")
NEW_JOB_TYPE = "SUGGEST_ACTIONS"


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in ENUM_TYPES:
        enum_type.create(bind, checkfirst=True)

    # --- 1. kb_entries: COMPLAINT or URGENCY_ACTIONS (ADR-18 §2) -----------
    op.add_column(
        "kb_entries",
        sa.Column("kind", kb_entry_kind, nullable=False, server_default="COMPLAINT"),
    )
    op.add_column("kb_entries", sa.Column("urgency_category", vtl_category, nullable=True))
    # Every existing entry is clinical content and keeps its complaint code;
    # only an URGENCY_ACTIONS entry may have none.
    op.alter_column("kb_entries", "complaint_code", existing_type=sa.String(64), nullable=True)
    op.create_check_constraint(
        "ck_kb_entries_urgency_category_iff_urgency_actions",
        "kb_entries",
        "(urgency_category IS NOT NULL) = (kind = 'URGENCY_ACTIONS')",
    )
    op.create_check_constraint(
        "ck_kb_entries_complaint_code_iff_complaint",
        "kb_entries",
        "(complaint_code IS NOT NULL) = (kind = 'COMPLAINT')",
    )
    # At most one ACTIVE baseline set per category, so the lookup by category
    # can never be ambiguous (FR-72). Partial, so superseded DRAFT or RETIRED
    # revisions of the same set still coexist.
    op.create_index(
        "uq_kb_entries_active_urgency_actions",
        "kb_entries",
        ["urgency_category"],
        unique=True,
        postgresql_where=sa.text("kind = 'URGENCY_ACTIONS' AND status = 'ACTIVE'"),
    )

    # --- 2. recommendations: the field the UI polls (NFR-29, FR-77) --------
    op.add_column(
        "recommendations",
        sa.Column("actions_status", actions_status, nullable=False, server_default="PENDING"),
    )
    # A reason code such as ACTIONS_TIMEOUT, never a model message: that could
    # carry action text (SR-17).
    op.add_column("recommendations", sa.Column("actions_error", sa.String(100), nullable=True))
    op.add_column(
        "recommendations",
        sa.Column("actions_rejected_count", sa.Integer(), nullable=False, server_default="0"),
    )

    # --- 3. the two action tables (DR-09) ----------------------------------
    op.create_table(
        "action_suggestions",
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("vignette_id", sa.UUID(), nullable=True),
        sa.Column("recommendation_id", sa.UUID(), nullable=False),
        sa.Column("generated_for_category", vtl_category, nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", action_source, nullable=False),
        sa.Column("cited_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("kb_version_id", sa.UUID(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(case_id IS NULL) <> (vignette_id IS NULL)",
            name="ck_action_suggestions_case_xor_vignette",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["kb_version_id"], ["kb_versions.id"]),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendations.id"]),
        sa.ForeignKeyConstraint(["vignette_id"], ["vignettes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Not unique: the actions job may be retried, and a retry replaces the
    # previous rows rather than being rejected by a constraint.
    op.create_index(
        "ix_action_suggestions_recommendation_id_rank",
        "action_suggestions",
        ["recommendation_id", "rank"],
        unique=False,
    )
    op.create_table(
        "final_actions",
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("decision_id", sa.UUID(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", action_source, nullable=False),
        sa.Column("status", action_status, nullable=False),
        sa.Column("suggestion_id", sa.UUID(), nullable=True),
        sa.Column("finalized_by", sa.UUID(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["decision_id"], ["staff_decisions.id"]),
        sa.ForeignKeyConstraint(["finalized_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["suggestion_id"], ["action_suggestions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_final_actions_case_id_rank", "final_actions", ["case_id", "rank"])

    # Migration 0002's ALTER DEFAULT PRIVILEGES already covers tables added
    # here; the explicit grants restate the intent next to the REVOKE so the
    # privileges of these two tables can be read in one place.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON action_suggestions TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON final_actions TO {APP_ROLE}")
    # A finalized action list is a record of a clinical decision: a correction
    # is a new decision with new rows, never an edit (DR-09, ADR-12).
    op.execute(f"REVOKE UPDATE, DELETE ON final_actions FROM {APP_ROLE}")
    # Second layer, which binds the database owner too. prevent_modify() is
    # created by migration 0002.
    op.execute(
        "CREATE TRIGGER trg_final_actions_prevent_modify "
        "BEFORE UPDATE OR DELETE ON final_actions "
        "FOR EACH STATEMENT EXECUTE FUNCTION prevent_modify()"
    )

    # --- 4. the new job type (ADR-08) --------------------------------------
    op.execute(f"ALTER TYPE job_type ADD VALUE IF NOT EXISTS '{NEW_JOB_TYPE}'")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_final_actions_prevent_modify ON final_actions")
    op.drop_index("ix_final_actions_case_id_rank", table_name="final_actions")
    op.drop_table("final_actions")
    op.drop_index("ix_action_suggestions_recommendation_id_rank", table_name="action_suggestions")
    op.drop_table("action_suggestions")

    op.drop_column("recommendations", "actions_rejected_count")
    op.drop_column("recommendations", "actions_error")
    op.drop_column("recommendations", "actions_status")

    # `complaint_code` goes back to NOT NULL, so the entries that have none
    # cannot stay. They are seed or curated baseline sets, re-created by
    # `scripts.seed` or the approval workflow on the next upgrade.
    op.execute(
        "DELETE FROM kb_version_entries WHERE entry_id IN "
        "(SELECT id FROM kb_entries WHERE kind = 'URGENCY_ACTIONS')"
    )
    op.execute("DELETE FROM kb_entries WHERE kind = 'URGENCY_ACTIONS'")
    op.drop_index("uq_kb_entries_active_urgency_actions", table_name="kb_entries")
    op.drop_constraint("ck_kb_entries_complaint_code_iff_complaint", "kb_entries", type_="check")
    op.drop_constraint(
        "ck_kb_entries_urgency_category_iff_urgency_actions", "kb_entries", type_="check"
    )
    op.alter_column("kb_entries", "complaint_code", existing_type=sa.String(64), nullable=False)
    op.drop_column("kb_entries", "urgency_category")
    op.drop_column("kb_entries", "kind")

    # PostgreSQL cannot drop an enum value, so the type is rebuilt without it.
    # S608: a module constant, not a value from any caller.
    op.execute(f"DELETE FROM jobs WHERE type = '{NEW_JOB_TYPE}'")  # noqa: S608
    op.execute("ALTER TYPE job_type RENAME TO job_type_old")
    values = ", ".join(f"'{value}'" for value in JOB_TYPES_BEFORE)
    op.execute(f"CREATE TYPE job_type AS ENUM ({values})")
    op.execute("ALTER TABLE jobs ALTER COLUMN type TYPE job_type USING type::text::job_type")
    op.execute("DROP TYPE job_type_old")

    bind = op.get_bind()
    for enum_type in reversed(ENUM_TYPES):
        enum_type.drop(bind, checkfirst=True)
