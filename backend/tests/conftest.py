"""Shared test fixtures.

The database tests run against a real PostgreSQL instance — the protections in
migration 0002 are role grants and triggers, so nothing else can prove them.
`triageai_test` is created if missing and migrated once per session as the
owner; the tests themselves connect as the restricted `triageai_app` role, the
same way the application does (ADR-12).

All data here is fictitious (CLAUDE.md §9).
"""

import uuid
from collections.abc import Generator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
import yaml
from alembic import command
from alembic.config import Config
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Connection, Engine, create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.cookies import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from app.api.deps import ROLE_GUARD_ATTR
from app.core.config import AppEnv, Settings, get_settings
from app.core.security import hash_password
from app.db.session import get_db
from app.main import create_app
from app.models import (
    AgeUnit,
    AuditEntry,
    Case,
    CaseStatus,
    ConfidenceLevel,
    DecisionDirection,
    DecisionType,
    ExtractionResult,
    IntakeChannel,
    Job,
    JobStatus,
    JobType,
    KBVersion,
    OwnerDescription,
    OwnerReference,
    Recommendation,
    RedFlagAlert,
    RedFlagRule,
    Sex,
    Signalment,
    Species,
    StaffDecision,
    User,
    UserRole,
    VTLCategory,
)
from app.pipeline.registry import build_pipeline
from app.repositories.case_repository import (
    CaseRepository,
    OwnerReferenceValues,
    SignalmentValues,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# The demo scenarios the mock stages replay (P05 §5.2). Read here as well as by
# `app.pipeline.mock_fixtures` so a test can build the *case* a scenario describes,
# which the loader's `MockFixture` deliberately does not carry.
DEMO_CASES_PATH = BACKEND_ROOT / "tests" / "fixtures" / "demo_cases.yaml"

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


def rolled_back_connection(engine: Engine) -> Generator[Connection, None, None]:
    """Yield a connection inside a transaction that is always rolled back."""
    connection: Connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


def session_on(connection: Connection) -> Session:
    """A session nested in `connection`'s transaction.

    `create_savepoint` is what makes two things possible at once: a deliberately
    failing statement does not poison the outer transaction, so a test can assert
    on a rejection and still clean up — and a session that *commits* (which the
    pipeline does, several times per run) only releases its savepoint, so the
    outer rollback still removes everything.
    """
    return Session(bind=connection, join_transaction_mode="create_savepoint")


def rolled_back_session(engine: Engine) -> Generator[Session, None, None]:
    """Yield a session whose work is always rolled back."""
    for connection in rolled_back_connection(engine):
        session = session_on(connection)
        try:
            yield session
        finally:
            session.close()


@pytest.fixture
def db_connection(app_engine: Engine) -> Generator[Connection, None, None]:
    """One rolled-back transaction, shared by the test and the code under test."""
    yield from rolled_back_connection(app_engine)


@pytest.fixture
def db_session(db_connection: Connection) -> Generator[Session, None, None]:
    session = session_on(db_connection)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def app_session_factory(db_connection: Connection) -> sessionmaker:
    """A `sessionmaker` the pipeline and the worker can open sessions from.

    Bound to the same connection as `db_session`, so a row the orchestrator
    commits is visible to the test that asserts on it and still vanishes when the
    outer transaction rolls back. This is the whole reason `build_pipeline` takes
    a `session_factory` override: without it a run would have to touch the
    development database.
    """
    return sessionmaker(bind=db_connection, join_transaction_mode="create_savepoint")


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
    full_name: str = "Test Staff",
    password: str | None = None,
    is_active: bool = True,
    must_change_password: bool = False,
    failed_login_count: int = 0,
    locked_until: datetime | None = None,
) -> User:
    """Insert a fictitious user and return it.

    Pass `password` to store a real Argon2id hash the auth tests can sign in
    with; without it the row carries an unusable placeholder, which is cheaper
    and is all the schema tests need.
    """
    user = User(
        full_name=full_name,
        email=email or f"staff-{uuid.uuid4().hex[:8]}@triageai.invalid",
        password_hash=hash_password(password) if password else "not-a-real-hash",
        role=role,
        can_approve_kb=can_approve_kb,
        is_active=is_active,
        must_change_password=must_change_password,
        failed_login_count=failed_login_count,
        locked_until=locked_until,
    )
    session.add(user)
    session.flush()
    return user


def make_case(
    session: Session,
    *,
    created_by: User | None = None,
    case_no: str | None = None,
    species: Species = Species.DOG,
    intake_channel: IntakeChannel = IntakeChannel.WALK_IN,
    status: CaseStatus = CaseStatus.SUBMITTED,
    created_at: datetime | None = None,
    closed_at: datetime | None = None,
    pet_name: str | None = None,
) -> Case:
    """Insert a fictitious case and return it.

    `created_at` has a server default, so it is set explicitly only when a test
    needs a case of a particular age — which the queue tests do, since waiting
    time and the overdue flag are measured from it.
    """
    author = created_by or make_user(session)
    case = Case(
        case_no=case_no or f"C-{uuid.uuid4().int % 10000:04d}",
        species=species,
        intake_channel=intake_channel,
        status=status,
        created_by=author.id,
        closed_at=closed_at,
    )
    if created_at is not None:
        case.created_at = created_at
    session.add(case)
    session.flush()

    if pet_name is not None:
        session.add(Signalment(case_id=case.id, pet_name=pet_name))
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


def make_recommendation(
    session: Session,
    *,
    case: Case,
    category: VTLCategory,
    version: int = 1,
    created_at: datetime | None = None,
) -> Recommendation:
    """Insert an AI recommendation for a case, with the extraction it came from.

    `recommendations.extraction_id` is not nullable, so a recommendation cannot
    exist on its own. Creating the pair here keeps that out of the queue tests,
    which care only about the category.

    The pipeline does not run until P05; these rows stand in for its output so
    that the FR-29 ordering can be proved now.
    """
    extraction = ExtractionResult(
        case_id=case.id,
        version=version,
        entities={},
        red_flags=[],
        missing_information=[],
        is_corrected=False,
        model_id="mock",
        prompt_version="mock-0",
    )
    session.add(extraction)
    session.flush()

    recommendation = Recommendation(
        case_id=case.id,
        extraction_id=extraction.id,
        version=version,
        category=category,
        rationale="Fixture recommendation.",
        confidence=ConfidenceLevel.MEDIUM,
        safety_floor_applied=False,
        safety_floor_rule_codes=[],
        low_confidence_reasons=[],
        model_id="mock",
        prompt_version="mock-0",
    )
    if created_at is not None:
        recommendation.created_at = created_at
    session.add(recommendation)
    session.flush()
    return recommendation


def make_staff_decision(
    session: Session,
    *,
    case: Case,
    final_category: VTLCategory,
    decision_type: DecisionType = DecisionType.CONFIRM,
    direction: DecisionDirection = DecisionDirection.SAME,
    decided_by: User | None = None,
    decided_at: datetime | None = None,
) -> StaffDecision:
    """Insert a reviewer's decision, which outranks the AI category (FR-29)."""
    reviewer = decided_by or make_user(session, role=UserRole.VETERINARY_REVIEWER)
    decision = StaffDecision(
        case_id=case.id,
        type=decision_type,
        final_category=final_category,
        # Required whenever the type is ADJUST (ck_staff_decisions_...).
        reason_code="FIXTURE" if decision_type is DecisionType.ADJUST else None,
        direction=direction,
        decided_by=reviewer.id,
        decided_at=decided_at or datetime.now(UTC),
    )
    session.add(decision)
    session.flush()
    return decision


def make_red_flag_rule(
    session: Session,
    *,
    code: str,
    min_category: VTLCategory = VTLCategory.RED,
    species: tuple[Species, ...] = (Species.DOG, Species.CAT),
) -> RedFlagRule:
    """Get or create a placeholder red-flag rule.

    Nothing here has been seen by a veterinarian, so `is_placeholder` is True —
    the same contract the seed script uses (P08 replaces both).
    """
    existing = session.query(RedFlagRule).filter_by(code=code).one_or_none()
    if existing is not None:
        return existing
    rule = RedFlagRule(
        code=code,
        label=f"Fixture rule {code}",
        min_category=min_category,
        species=list(species),
        is_placeholder=True,
    )
    session.add(rule)
    session.flush()
    return rule


def make_red_flag_alert(
    session: Session,
    *,
    case: Case,
    rule_code: str = "FIXTURE_RED_FLAG",
    min_category: VTLCategory = VTLCategory.RED,
) -> RedFlagAlert:
    """Insert a red-flag alert, creating its rule if the test has not already."""
    make_red_flag_rule(session, code=rule_code, min_category=min_category)
    alert = RedFlagAlert(
        case_id=case.id,
        rule_code=rule_code,
        matched_text="fixture match",
        min_category=min_category,
    )
    session.add(alert)
    session.flush()
    return alert


def make_owner_reference(
    session: Session,
    *,
    case: Case,
    owner_name: str | None = "Owner Placeholder",
    contact_number: str | None = "0999-000-0000",
) -> OwnerReference:
    """Insert a fictitious owner reference (FR-07, DR-04).

    Only the de-identifier may read these columns, so the tests that create one
    are the de-identification tests and the pipeline tests that prove nothing else
    does (CLAUDE.md §9).
    """
    reference = OwnerReference(
        case_id=case.id, owner_name=owner_name, contact_number=contact_number
    )
    session.add(reference)
    session.flush()
    return reference


def make_kb_version(session: Session, *, version_no: int = 0) -> KBVersion:
    """Get or create a knowledge-base version for a run to be pinned to (FR-54).

    A run with no version at all takes the failure path, which is its own test; the
    rest need one to exist, exactly as `scripts/seed.py` creates version 0.
    """
    existing = session.query(KBVersion).filter_by(version_no=version_no).one_or_none()
    if existing is not None:
        return existing
    version = KBVersion(version_no=version_no, note="Fixture – no entries")
    session.add(version)
    session.flush()
    return version


def make_job(
    session: Session,
    *,
    case: Case | None = None,
    job_type: JobType = JobType.PIPELINE_RUN,
    status: JobStatus = JobStatus.QUEUED,
    attempts: int = 0,
    payload: dict | None = None,
    run_after: datetime | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Job:
    """Insert a job row directly.

    `updated_at` is settable because the recovery sweep measures staleness from it
    and a test must be able to place a job two minutes in the past without
    sleeping.
    """
    job = Job(
        type=job_type,
        case_id=None if case is None else case.id,
        payload=payload,
        status=status,
        attempts=attempts,
        run_after=run_after,
    )
    if created_at is not None:
        job.created_at = created_at
    if updated_at is not None:
        job.updated_at = updated_at
    session.add(job)
    session.flush()
    return job


@lru_cache(maxsize=1)
def demo_cases() -> dict[str, dict[str, Any]]:
    """The demo scenarios by fixture id, straight from the YAML."""
    document = yaml.safe_load(DEMO_CASES_PATH.read_text(encoding="utf-8")) or {}
    return {case["id"]: case for case in document.get("cases") or []}


def make_demo_case(
    session: Session,
    fixture_id: str,
    *,
    created_by: User | None = None,
    owner_name: str | None = None,
    contact_number: str | None = None,
    created_at: datetime | None = None,
) -> Case:
    """Insert the case one demo scenario describes, through the real write path.

    `CaseRepository.insert_case` rather than hand-built rows, so the description
    and the signalment a run reads are written exactly as intake writes them — the
    mock stages match a fixture by the description, and a test that stored it
    differently would silently fall through to the generic answers.
    """
    spec = demo_cases()[fixture_id]
    signalment = spec.get("signalment") or {}
    arrived_at = created_at or datetime.now(UTC)
    repository = CaseRepository(session)

    return repository.insert_case(
        case_no=repository.next_case_no(),
        species=Species(spec["species"]),
        intake_channel=IntakeChannel(spec.get("intake_channel", "WALK_IN")),
        status=CaseStatus.SUBMITTED,
        created_by=(created_by or make_user(session)).id,
        arrived_at=arrived_at,
        description=spec["description"],
        signalment=SignalmentValues(
            pet_name=signalment.get("pet_name"),
            age_value=(
                None
                if signalment.get("age_value") is None
                else Decimal(str(signalment["age_value"]))
            ),
            age_unit=(
                None if signalment.get("age_unit") is None else AgeUnit(signalment["age_unit"])
            ),
            sex=Sex(signalment.get("sex", "UNKNOWN")),
            neutered=signalment.get("neutered"),
            breed=signalment.get("breed"),
            weight_kg=(
                None
                if signalment.get("weight_kg") is None
                else Decimal(str(signalment["weight_kg"]))
            ),
        ),
        owner_reference=(
            OwnerReferenceValues(owner_name=owner_name, contact_number=contact_number)
            if owner_name is not None or contact_number is not None
            else None
        ),
    )


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


# --- HTTP client (P03) ----------------------------------------------------


# --- The pipeline, on the test transaction (P05) ---------------------------


def test_settings(**overrides: object) -> Settings:
    """The application settings with fields replaced, for one test.

    `model_copy` rather than `Settings(...)`: the cached settings already carry the
    passwords and URLs from `.env`, and a test that wants a different
    `MOCK_LLM_BEHAVIOR` should not have to restate them.
    """
    return get_settings().model_copy(update=overrides)


@pytest.fixture
def pipeline_factory(app_session_factory: sessionmaker):
    """Build a fully mocked `TriagePipeline` that runs on the test transaction.

    One per call, not one per session: the mock stages keep the attempt counts the
    `flaky` behaviour needs, so a test that wants a first-attempt failure must
    start from a pipeline that has not seen that case yet.
    """

    def build(**overrides: object):
        return build_pipeline(test_settings(**overrides), session_factory=app_session_factory)

    return build


@pytest.fixture
def pipeline(pipeline_factory):
    """The default pipeline: every stage mocked, `MOCK_LLM_BEHAVIOR=ok`."""
    return pipeline_factory()


@pytest.fixture
def api_client(db_session: Session) -> Generator[TestClient, None, None]:
    """A client whose requests run inside the test's rolled-back transaction.

    `get_db` is overridden with the very session the test asserts on, so a row
    an endpoint commits is visible to the test and still disappears afterwards.

    The app is built per test rather than imported, because
    `dependency_overrides` is app-wide state.

    The job worker is off (ADR-08). It would run on `SessionLocal`, which points at
    the *development* database — nothing in a test should start a thread that
    processes real cases — and the tests drive the queue with
    `run_pending_jobs_once` so a run is finished when the assertion reads it.
    """
    settings = get_settings()
    assert settings.app_env is AppEnv.DEV, (
        "the API tests need APP_ENV=dev: the RBAC demo routes are mounted only in "
        f"development and cookies are Secure outside it (got {settings.app_env.value})"
    )

    app = create_app(test_settings(job_worker_enabled=False))
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def sign_in(client: TestClient, email: str, password: str) -> Response:
    """Log in and leave the session and CSRF cookies on `client`."""
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def csrf_headers(client: TestClient) -> dict[str, str]:
    """The double-submit header the SPA sends, read from the readable cookie."""
    return {CSRF_HEADER_NAME: client.cookies[CSRF_COOKIE_NAME]}


def set_session_cookie_value(client: TestClient, token: str) -> None:
    """Plant a session cookie, as a browser holding an old token would.

    Any existing one is removed first: httpx files a cookie it was handed
    without a domain under a different host than one parsed from a response, so
    setting over the top would leave the jar holding two of the same name.
    """
    client.cookies.delete(SESSION_COOKIE_NAME)
    client.cookies.set(SESSION_COOKIE_NAME, token)


def session_token_from(response: Response) -> str | None:
    """The session token in this response's `Set-Cookie`, if it set one.

    Read from the headers rather than the client's jar so a test can tell
    "the server re-issued the cookie" from "the jar still has the old one".
    """
    for key, value in response.headers.multi_items():
        if key.lower() == "set-cookie" and value.startswith(f"{SESSION_COOKIE_NAME}="):
            return value.split("=", 1)[1].split(";", 1)[0]
    return None


def iter_api_routes(router: object, prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    """Yield `(full path, route)` for every API route reachable from `router`.

    FastAPI 0.142 stores an included router lazily instead of copying its routes
    onto the parent, so the walk has to follow `original_router`. Handling the
    flattened shape too keeps this working on either side of that change.
    """
    for route in getattr(router, "routes", ()):
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
            continue
        included = getattr(route, "original_router", None)
        if included is not None:
            context = getattr(route, "include_context", None)
            yield from iter_api_routes(included, prefix + getattr(context, "prefix", ""))


def has_role_guard(dependant: Dependant) -> bool:
    """True when `require_role` appears anywhere in this route's dependencies."""
    if getattr(dependant.call, ROLE_GUARD_ATTR, False):
        return True
    return any(has_role_guard(sub_dependant) for sub_dependant in dependant.dependencies)


def audit_actions(session: Session, user_id: uuid.UUID | None = None) -> list[str]:
    """Audit actions written so far, oldest first, optionally for one user."""
    statement = select(AuditEntry.action).order_by(AuditEntry.id)
    if user_id is not None:
        statement = statement.where(AuditEntry.user_id == user_id)
    return list(session.execute(statement).scalars())
