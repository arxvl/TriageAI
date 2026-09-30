"""`--reset` truncates every table, including the append-only audit log.

It is therefore allowed only in development (FR-43, ADR-12). These tests use
no database: the point is that the guard trips before anything connects.
"""

import pytest

from app.core.config import AppEnv, Settings
from scripts import seed as seed_module
from scripts.seed import main, reset


@pytest.fixture
def settings() -> Settings:
    return Settings(
        db_password="x",
        db_app_password="x",
        database_url="postgresql+psycopg://app:x@db:5432/nowhere",
        migration_database_url="postgresql+psycopg://owner:x@db:5432/nowhere",
        test_database_url="postgresql+psycopg://app:x@db:5432/nowhere_test",
        secret_key="x",
    )


@pytest.fixture
def forbid_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn any attempt to open a connection into a test failure."""

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("--reset must refuse before connecting to the database")

    monkeypatch.setattr(seed_module, "create_engine", explode)
    monkeypatch.setattr(seed_module, "SessionLocal", explode)


@pytest.mark.parametrize("app_env", [AppEnv.PROD, AppEnv.TEST])
def test_reset_refuses_outside_dev(
    settings: Settings, app_env: AppEnv, forbid_connections: None
) -> None:
    with pytest.raises(RuntimeError, match="development-only"):
        reset(settings.model_copy(update={"app_env": app_env}))


def test_main_reset_exits_nonzero_outside_dev(
    settings: Settings, capsys: pytest.CaptureFixture[str], forbid_connections: None
) -> None:
    exit_code = main(["--reset"], settings=settings.model_copy(update={"app_env": AppEnv.PROD}))

    assert exit_code == 2
    assert "development-only" in capsys.readouterr().err


def test_reset_is_allowed_in_dev(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard lets dev through — proved without touching a real database."""
    statements: list[str] = []

    class FakeConnection:
        def execute(self, statement: object) -> None:
            statements.append(str(statement))

    class FakeEngine:
        def begin(self) -> "FakeEngine":
            return self

        def __enter__(self) -> FakeConnection:
            return FakeConnection()

        def __exit__(self, *exc: object) -> None:
            return None

        def dispose(self) -> None:
            return None

    monkeypatch.setattr(seed_module, "create_engine", lambda url: FakeEngine())

    reset(settings.model_copy(update={"app_env": AppEnv.DEV}))

    assert any(statement.startswith("TRUNCATE TABLE") for statement in statements)
    # alembic_version is not in Base.metadata, so it is never truncated.
    assert not any("alembic_version" in statement for statement in statements)
    assert any("case_no_seq" in statement for statement in statements)


def test_reset_connects_as_the_owner(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """The app role has no TRUNCATE privilege, so the owner URL is required."""
    urls: list[str] = []

    class FakeEngine:
        def begin(self) -> "FakeEngine":
            return self

        def __enter__(self) -> object:
            class Connection:
                def execute(self, statement: object) -> None:
                    return None

            return Connection()

        def __exit__(self, *exc: object) -> None:
            return None

        def dispose(self) -> None:
            return None

    def record(url: str) -> FakeEngine:
        urls.append(url)
        return FakeEngine()

    monkeypatch.setattr(seed_module, "create_engine", record)

    dev_settings = settings.model_copy(update={"app_env": AppEnv.DEV})
    reset(dev_settings)

    assert urls == [dev_settings.migration_database_url]
