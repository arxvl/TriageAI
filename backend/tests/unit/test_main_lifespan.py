"""The embedding warm-up in the lifespan (M4 Step 7, NFR-01).

The real adapter is never built here: `from_settings` is replaced by a spy, so
nothing imports `sentence_transformers` or `torch` and no model is loaded. What
is under test is the lifespan's decision — when it warms up, when it does not,
and that a failure is left to propagate.

`test_settings` pins `embedding_provider` to `None`, so `build_pipeline` builds
no embedder of its own and the warm-up is the only thing that can reach the
adapter. `EMBEDDING_PROVIDER` — the field the warm-up reads — is set per test.
"""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.adapters.embeddings.sentence_transformer import SentenceTransformerEmbedder
from app.core.config import Settings
from app.main import create_app
from tests.conftest import test_settings as app_settings

WARMED = [["warm-up"]]


class _SpyEmbedder:
    """Stands in for the adapter, and records what the lifespan asked of it."""

    def __init__(self) -> None:
        self.built: list[Settings] = []
        self.embedded: list[list[str]] = []
        self.error: Exception | None = None

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def from_settings(settings: Settings, deps: object = None) -> "_SpyEmbedder":
            self.built.append(settings)
            return self

        monkeypatch.setattr(SentenceTransformerEmbedder, "from_settings", from_settings)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embedded.append(texts)
        if self.error is not None:
            raise self.error
        return [[0.0] * 3 for _ in texts]


@pytest.fixture
def embedder_spy(monkeypatch: pytest.MonkeyPatch) -> _SpyEmbedder:
    spy = _SpyEmbedder()
    spy.install(monkeypatch)
    return spy


@pytest.fixture
def stub_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the worker branch without a database sweep or a background thread."""

    class _StubWorker:
        def __init__(self, *args: object, **kwargs: object) -> None: ...

        def start(self) -> None: ...

        def stop(self, *args: object, **kwargs: object) -> None: ...

    monkeypatch.setattr(main, "recover_stale_jobs", lambda *a, **k: None)
    monkeypatch.setattr(main, "JobWorker", _StubWorker)


def _settings(**overrides: object) -> Settings:
    """Mock-pipeline settings, worker off unless the test turns it on."""
    return app_settings(**{"job_worker_enabled": False, **overrides})


def _start(settings: Settings) -> None:
    """Run the lifespan start-to-finish."""
    with TestClient(create_app(settings)):
        pass


def test_warm_up_embeds_once_when_a_provider_is_configured(
    embedder_spy: _SpyEmbedder, stub_worker: None
) -> None:
    _start(
        _settings(
            EMBEDDING_PROVIDER="sentence_transformer",
            EMBEDDING_WARMUP=True,
            job_worker_enabled=True,
        )
    )

    assert embedder_spy.embedded == WARMED


def test_no_warm_up_when_no_embedding_provider_is_configured(
    embedder_spy: _SpyEmbedder,
) -> None:
    """The default configuration: mock stages need no embeddings at all."""
    _start(_settings(EMBEDDING_PROVIDER="", EMBEDDING_WARMUP=True))

    assert embedder_spy.built == []


def test_no_warm_up_when_it_is_switched_off(embedder_spy: _SpyEmbedder) -> None:
    """`EMBEDDING_WARMUP=false` is how a short startup is bought back."""
    _start(_settings(EMBEDDING_PROVIDER="sentence_transformer", EMBEDDING_WARMUP=False))

    assert embedder_spy.built == []


def test_warm_up_runs_with_the_job_worker_disabled(embedder_spy: _SpyEmbedder) -> None:
    """It is not the worker's warm-up: the KB import and the retriever need it too."""
    _start(
        _settings(
            EMBEDDING_PROVIDER="sentence_transformer",
            EMBEDDING_WARMUP=True,
            job_worker_enabled=False,
        )
    )

    assert embedder_spy.embedded == WARMED


def test_a_failing_warm_up_fails_startup(embedder_spy: _SpyEmbedder) -> None:
    """A dimension mismatch is a startup failure, not a case that fails later."""
    embedder_spy.error = RuntimeError("EMBEDDING_DIM=384 but the model produces 768")

    with pytest.raises(RuntimeError, match="EMBEDDING_DIM=384"):
        _start(_settings(EMBEDDING_PROVIDER="sentence_transformer", EMBEDDING_WARMUP=True))
