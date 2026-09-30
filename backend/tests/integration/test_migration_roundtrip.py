"""`alembic upgrade head` and `alembic downgrade base` both work, repeatedly.

Runs against a throwaway database so the session's `triageai_test` is left
alone. A broken downgrade is otherwise invisible until someone needs it.
"""

from collections.abc import Generator

import pytest
from sqlalchemy import Engine, create_engine, text

from tests.conftest import (
    MAINTENANCE_DATABASE,
    alembic_downgrade,
    alembic_upgrade,
    create_database_if_missing,
    with_database,
)

ROUNDTRIP_DATABASE = "triageai_migration_check"

# A representative slice of the schema: one table per aggregate the SRS's
# integrity rules touch.
EXPECTED_TABLES = ("users", "cases", "owner_descriptions", "audit_log", "kb_version_entries")


def table_names(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).scalars()
        return set(rows)


def enum_type_names(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT t.typname FROM pg_type t "
                "JOIN pg_namespace n ON n.oid = t.typnamespace "
                "WHERE t.typtype = 'e' AND n.nspname = 'public'"
            )
        ).scalars()
        return set(rows)


@pytest.fixture
def roundtrip_database_url(owner_database_url: str) -> Generator[str, None, None]:
    url = with_database(owner_database_url, ROUNDTRIP_DATABASE)
    drop_database(owner_database_url, ROUNDTRIP_DATABASE)
    create_database_if_missing(owner_database_url, ROUNDTRIP_DATABASE)
    yield url
    drop_database(owner_database_url, ROUNDTRIP_DATABASE)


def drop_database(owner_url: str, name: str) -> None:
    engine = create_engine(
        with_database(owner_url, MAINTENANCE_DATABASE), isolation_level="AUTOCOMMIT"
    )
    try:
        with engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_on_an_empty_database(roundtrip_database_url: str) -> None:
    engine = create_engine(roundtrip_database_url)
    try:
        alembic_upgrade(roundtrip_database_url)
        after_first_upgrade = table_names(engine)
        assert set(EXPECTED_TABLES) <= after_first_upgrade
        assert enum_type_names(engine)

        alembic_downgrade(roundtrip_database_url)
        # alembic_version survives a downgrade to base; nothing else should.
        assert table_names(engine) == {"alembic_version"}
        assert enum_type_names(engine) == set()

        alembic_upgrade(roundtrip_database_url)
        assert table_names(engine) == after_first_upgrade
    finally:
        engine.dispose()


def test_protections_are_reapplied_by_the_second_upgrade(roundtrip_database_url: str) -> None:
    """The triggers and revokes must come back, not just the tables."""
    alembic_upgrade(roundtrip_database_url)
    alembic_downgrade(roundtrip_database_url)
    alembic_upgrade(roundtrip_database_url)

    engine = create_engine(roundtrip_database_url)
    try:
        with engine.connect() as connection:
            triggers = set(
                connection.execute(
                    text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
                ).scalars()
            )
            assert triggers == {
                "trg_audit_log_prevent_modify",
                "trg_owner_descriptions_prevent_modify",
                "trg_kb_version_entries_prevent_modify",
            }

            audit_update = connection.execute(
                text("SELECT has_table_privilege('triageai_app', 'audit_log', 'UPDATE')")
            ).scalar_one()
            audit_insert = connection.execute(
                text("SELECT has_table_privilege('triageai_app', 'audit_log', 'INSERT')")
            ).scalar_one()
            assert audit_update is False
            assert audit_insert is True
    finally:
        engine.dispose()
