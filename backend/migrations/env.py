"""Alembic environment for TriageAI.

Migrations run as the database owner (`MIGRATION_DATABASE_URL`), never as the
restricted application role the app itself uses (ADR-12). Tests override the
target database with `-x db_url=...`.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importing the models package registers every table on Base.metadata.
import app.models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Resolve the database URL for this migration run.

    Overrides come first so a caller can target another database without
    touching `.env`: `-x db_url=...` on the command line, or
    `config.set_main_option("sqlalchemy.url", ...)` when Alembic is driven
    programmatically (the test fixtures migrate `triageai_test` that way).
    Otherwise the owner account from settings is used.
    """
    override = context.get_x_argument(as_dictionary=True).get("db_url")
    if override:
        return override
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    return get_settings().migration_database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
