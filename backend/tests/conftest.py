"""Shared test fixtures.

The database tests run against a real PostgreSQL instance — the protections in
migration 0002 are role grants and triggers, so nothing else can prove them.
`triageai_test` is created if missing and migrated once per session as the
owner; the tests themselves connect as the restricted `triageai_app` role, the
same way the application does (ADR-12).

All data here is fictitious (CLAUDE.md §9).
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Case, CaseStatus, IntakeChannel, OwnerDescription, Species, User, UserRole

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Used to create the test database itself; always present in a PostgreSQL
# cluster, so it is safe to connect to while `triageai_test` does not exist.
MAINTENANCE_DATABASE = "postgres"


# --- URL helpers ----------------------------------------------------------


def with_database(url: str, database: str) -> str:
    """Return `url` pointing at a different database on the same server."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{database}"))


def database_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


# --- Alembic --------------------------------------------------------------


def alembic_config(database_url: str) -> Config:
    """An Alembic config pointed at `database_url` instead of the .env value."""
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    # Leave pytest's logging alone; see migrations/env.py.
    config.attributes["configure_logger"] = False
    return config


def alembic_upgrade(database_url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def alembic_downgrade(database_url: str, revision: str = "base") -> None:
    command.downgrade(alembic_config(database_url), revision)


# --- Database setup -------------------------------------------------------


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Application-role URL for the test database (the restricted role)."""
    return get_settings().test_database_url


@pytest.fixture(scope="session")
def owner_database_url(test_database_url: str) -> str:
    """Owner-role URL for the same database.

    Derived from MIGRATION_DATABASE_URL so no extra environment variable is
    needed: same server and owner credentials, test database name.
    """
    return with_database(get_settings().migration_database_url, database_name(test_database_url))


def create_database_if_missing(owner_url: str, name: str) -> None:
    engine = create_engine(
        with_database(owner_url, MAINTENANCE_DATABASE), isolation_level="AUTOCOMMIT"
    )
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            ).first()
            if exists is None:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def migrated_database(owner_database_url: str) -> str:
    """Create `triageai_test` if missing and bring it to head, once per session."""
    create_database_if_missing(owner_database_url, database_name(owner_database_url))
    alembic_upgrade(owner_database_url)
    return owner_database_url


@pytest.fixture(scope="session")
def app_engine(test_database_url: str, migrated_database: str) -> Generator[Engine, None, None]:
    """Engine connected as `triageai_app` — the role the application uses."""
    engine = create_engine(test_database_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def owner_engine(migrated_database: str) -> Generator[Engine, None, None]:
    """Engine connected as the database owner.

    Used to prove the triggers stop even a connection the grants do not
    restrict.
    """
    engine = create_engine(migrated_database, pool_pre_ping=True)
    yield engine
    engine.dispose()


def rolled_back_session(engine: Engine) -> Generator[Session, None, None]:
    """Yield a session whose work is always rolled back.

    `create_savepoint` keeps a deliberately failing statement from poisoning
    the outer transaction, so a test can assert on a rejection and still clean
    up.
    """
    connection: Connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def db_session(app_engine: Engine) -> Generator[Session, None, None]:
    yield from rolled_back_session(app_engine)


@pytest.fixture
def owner_session(owner_engine: Engine) -> Generator[Session, None, None]:
    yield from rolled_back_session(owner_engine)


# --- Fictitious row builders (CLAUDE.md §9) -------------------------------


def make_user(
    session: Session,
    *,
    role: UserRole = UserRole.INTAKE_STAFF,
    can_approve_kb: bool = False,
    email: str | None = None,
) -> User:
    """Insert a fictitious user and return it."""
    user = User(
        full_name="Test Staff",
        email=email or f"staff-{uuid.uuid4().hex[:8]}@triageai.invalid",
        password_hash="not-a-real-hash",
        role=role,
        can_approve_kb=can_approve_kb,
        is_active=True,
        must_change_password=False,
        failed_login_count=0,
    )
    session.add(user)
    session.flush()
    return user


def make_case(session: Session, *, created_by: User | None = None) -> Case:
    """Insert a fictitious case and return it."""
    author = created_by or make_user(session)
    case = Case(
        case_no=f"C-{uuid.uuid4().int % 10000:04d}",
        species=Species.DOG,
        intake_channel=IntakeChannel.WALK_IN,
        status=CaseStatus.SUBMITTED,
        created_by=author.id,
    )
    session.add(case)
    session.flush()
    return case


def make_owner_description(session: Session, *, case: Case | None = None) -> OwnerDescription:
    """Insert a fictitious owner description and return it."""
    subject = case or make_case(session)
    text_value = "Dog has been limping on the right front leg since this morning."
    description = OwnerDescription(
        case_id=subject.id,
        text=text_value,
        char_count=len(text_value),
        submitted_at=datetime.now(UTC),
    )
    session.add(description)
    session.flush()
    return description


def insert_audit_entry(session: Session, *, action: str = "CASE_CREATED") -> int:
    """Insert an audit row through raw SQL and return its id.

    Raw SQL rather than the model: the point of these tests is what the
    database permits, not what the ORM does.
    """
    return session.execute(
        text(
            "INSERT INTO audit_log (action, entity_type, entity_id) "
            "VALUES (:action, 'case', :entity_id) RETURNING id"
        ),
        {"action": action, "entity_id": str(uuid.uuid4())},
    ).scalar_one()
