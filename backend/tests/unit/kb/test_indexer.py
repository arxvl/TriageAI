"""Indexer tests with a fake session: no database needed, and no guessing about which
columns kb_entries requires. The real database behaviour is checked by scripts.kb_check."""

import uuid
from types import SimpleNamespace

import pytest

from app.kb.indexer_pgvector import PgVectorKBIndexer
from app.models.enums import KBEntryKind


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeSession:
    """Just enough of a SQLAlchemy Session for index_entry()."""

    def __init__(self, entry, chunks=None):
        self.entry, self.chunks, self.flushed = entry, chunks or [], 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def begin(self):
        return self

    def get(self, model, key):
        return self.entry

    def scalars(self, statement):
        return _Rows(sorted(self.chunks, key=lambda c: c.chunk_index))

    def add_all(self, rows):
        self.chunks.extend(rows)

    def flush(self):
        self.flushed += 1


class FakeEmbedder:
    model_id = "fake-model"

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[float(len(t))] * 4 for t in texts]


def make_entry(kind=KBEntryKind.COMPLAINT, content=None, species=("CAT",)):
    body = (
        content
        if content is not None
        else " ".join(
            f"This is sentence number {i} of the entry and it has a few words in it."
            for i in range(1, 41)
        )
    )
    return SimpleNamespace(
        id=uuid.uuid4(), kind=kind, title="Entry title", content=body, species=list(species)
    )


def make_indexer(session):
    return PgVectorKBIndexer(lambda: session, FakeEmbedder(), target_words=60, overlap=1)


def test_creates_chunks_and_embeds_all_of_them():
    session = FakeSession(make_entry())
    indexer = make_indexer(session)
    count = indexer.index_entry(session.entry.id)
    assert count == len(session.chunks) > 1
    assert all(
        c.embedding is not None and c.embedding_model == "fake-model" for c in session.chunks
    )
    assert [c.chunk_index for c in session.chunks] == list(range(count))


def test_stored_text_is_clean_but_the_embedded_text_has_the_header():
    session = FakeSession(make_entry())
    indexer = make_indexer(session)
    indexer.index_entry(session.entry.id)
    assert not session.chunks[0].text.startswith("Entry title")
    assert indexer.embedder.calls[0][0].startswith("Entry title (CAT). ")


def test_calling_twice_creates_no_duplicates_and_re_embeds_nothing():
    session = FakeSession(make_entry())
    indexer = make_indexer(session)
    first = indexer.index_entry(session.entry.id)
    second = indexer.index_entry(session.entry.id)
    assert first == second == len(session.chunks)
    assert len(indexer.embedder.calls) == 1


def test_fills_in_missing_embeddings_without_recreating_chunks():
    session = FakeSession(make_entry())
    indexer = make_indexer(session)
    indexer.index_entry(session.entry.id)
    session.chunks[1].embedding = None  # simulate an interrupted run
    before = [c.id for c in session.chunks]
    indexer.index_entry(session.entry.id)
    assert [c.id for c in session.chunks] == before
    assert session.chunks[1].embedding is not None
    assert len(indexer.embedder.calls[-1]) == 1


def test_urgency_action_entries_are_never_chunked_or_embedded():
    session = FakeSession(make_entry(kind=KBEntryKind.URGENCY_ACTIONS))
    indexer = make_indexer(session)
    assert indexer.index_entry(session.entry.id) == 0
    assert session.chunks == [] and indexer.embedder.calls == []


def test_an_entry_with_no_content_is_an_error_not_a_silent_success():
    session = FakeSession(make_entry(content="   "))
    with pytest.raises(ValueError, match="no content"):
        make_indexer(session).index_entry(session.entry.id)


def test_a_missing_entry_is_an_error():
    session = FakeSession(None)
    with pytest.raises(ValueError, match="not found"):
        make_indexer(session).index_entry(uuid.uuid4())


def test_from_settings_refuses_to_start_without_an_embedder():
    settings = SimpleNamespace(KB_CHUNK_TARGET_WORDS=150, KB_CHUNK_OVERLAP_SENTENCES=1)
    deps = SimpleNamespace(embedder=None, session_factory=None)
    with pytest.raises(RuntimeError, match="EMBEDDING_PROVIDER"):
        PgVectorKBIndexer.from_settings(settings, deps)


def test_remove_entry_keeps_the_chunks():
    session = FakeSession(make_entry())
    indexer = make_indexer(session)
    indexer.index_entry(session.entry.id)
    indexer.remove_entry(session.entry.id)
    assert session.chunks
