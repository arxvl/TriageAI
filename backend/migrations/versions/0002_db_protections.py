"""db protections

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30

Database-level enforcement of the append-only guarantees (FR-05, FR-43,
ADR-12). Two independent layers, because application discipline is not a
guarantee:

1. The application connects as the restricted role `triageai_app`, which has
   no UPDATE or DELETE on `audit_log` and no UPDATE on `owner_descriptions`.
   Migrations keep using the owner account (MIGRATION_DATABASE_URL).
2. A `prevent_modify()` trigger raises on any attempt to modify `audit_log`,
   `owner_descriptions` or `kb_version_entries` — including attempts by the
   owner, which the grants above cannot stop.

Corrections are new rows, never edits: a new ExtractionResult version, a new
StaffDecision with `amends_id`, a new KB version.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.config import get_settings

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "triageai_app"

# BEFORE UPDATE on these tables; audit_log additionally BEFORE DELETE.
PROTECTED_TABLES = ("audit_log", "owner_descriptions", "kb_version_entries")


def _role_exists(bind: sa.engine.Connection) -> bool:
    return (
        bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": APP_ROLE}
        ).first()
        is not None
    )


def upgrade() -> None:
    bind = op.get_bind()

    password = get_settings().db_app_password
    if not password:
        raise RuntimeError(
            "DB_APP_PASSWORD is not set. It is the password for the restricted "
            f"{APP_ROLE} role the application connects as; see .env.example."
        )

    # Let PostgreSQL quote the password rather than formatting it into SQL
    # ourselves. CREATE/ALTER ROLE cannot take a bound parameter.
    quoted_password = bind.execute(
        sa.text("SELECT quote_literal(:password)"), {"password": password}
    ).scalar_one()

    verb = "ALTER" if _role_exists(bind) else "CREATE"
    bind.execute(sa.text(f"{verb} ROLE {APP_ROLE} WITH LOGIN PASSWORD {quoted_password}"))

    # --- Normal privileges -------------------------------------------------
    op.execute(
        f"DO $$ BEGIN EXECUTE format("
        f"'GRANT CONNECT ON DATABASE %I TO {APP_ROLE}', current_database()); END $$"
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")

    # Tables and sequences added by later migrations (the M4 embedding work,
    # P08) are covered without repeating the block above. A future append-only
    # table must add its own REVOKE.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )

    # --- Revokes (FR-05, FR-43, ADR-12) ------------------------------------
    op.execute(f"REVOKE UPDATE, DELETE ON audit_log FROM {APP_ROLE}")
    op.execute(f"REVOKE UPDATE ON owner_descriptions FROM {APP_ROLE}")
    # Schema history is Alembic's, and Alembic runs as the owner.
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {APP_ROLE}")

    # --- Trigger layer -----------------------------------------------------
    # Statement-level, not row-level: the statement is rejected even when it
    # would match no rows, so the guarantee does not depend on table contents.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_modify() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION
                'Table % is append-only: % is not permitted (FR-05, FR-43, ADR-12)',
                TG_TABLE_NAME, TG_OP;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_audit_log_prevent_modify "
        "BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION prevent_modify()"
    )
    op.execute(
        "CREATE TRIGGER trg_owner_descriptions_prevent_modify "
        "BEFORE UPDATE ON owner_descriptions "
        "FOR EACH STATEMENT EXECUTE FUNCTION prevent_modify()"
    )
    op.execute(
        "CREATE TRIGGER trg_kb_version_entries_prevent_modify "
        "BEFORE UPDATE ON kb_version_entries "
        "FOR EACH STATEMENT EXECUTE FUNCTION prevent_modify()"
    )


def downgrade() -> None:
    bind = op.get_bind()

    for table in PROTECTED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_prevent_modify ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_modify()")

    # The role itself is left in place. A role is cluster-scoped and shared by
    # the dev and test databases, so DROP ROLE would fail on the privileges it
    # still holds in the other database.
    if not _role_exists(bind):
        return

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE}"
    )
    op.execute(
        # S608: DDL on a module constant, not a query built from input.
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "  # noqa: S608
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {APP_ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    op.execute(
        f"DO $$ BEGIN EXECUTE format("
        f"'REVOKE CONNECT ON DATABASE %I FROM {APP_ROLE}', current_database()); END $$"
    )
