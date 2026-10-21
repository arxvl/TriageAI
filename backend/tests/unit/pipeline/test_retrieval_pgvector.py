"""Unit tests for PgVectorRetriever (M6 Step A3).

These run against the real test database, because pgvector's SQL cannot be
meaningfully faked. `db_session` and `app_session_factory` share one rolled-back
connection (see `tests/conftest.py`), so the retriever sees the rows seeded here
without anything being committed. A fake embedder returns a fixed vector: the SQL
under test, not the embedding model, is what these tests exercise.

All data is fictitious (CLAUDE.md §9).
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models import KBChunk, KBEntry, KBEntryKind, KBEntryStatus, UserRole, VTLCategory
from app.models.enums import Species
from app.pipeline.errors import RetrievalFailed
from app.pipeline.retrieval_pgvector import PgVectorRetriever
from app.pipeline.types import ExtractedComplaint, ExtractionOutput
from tests.conftest import make_kb_entry, make_kb_version, make_user

DIM = 384


def unit(axis: int) -> list[float]:
    """A one-hot vector: cosine distance 0 to itself and 1 to any other axis."""
    vector = [0.0] * DIM
    vector[axis] = 1.0
    return vector


class FakeEmbedder:
    model_id = "fake-embedder"

    def __init__(self, vector: list[float]) -> None:
        self.vector = vector

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vector for _ in texts]


class BrokenEmbedder:
    model_id = "broken-embedder"

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("model not loaded")


def make_extraction(species: Species, **overrides: object) -> ExtractionOutput:
    values: dict = {
        "species": species,
        "signalment": {},
        "presenting_complaints": [ExtractedComplaint(code="LETHARGY", is_primary=True)],
        "onset_duration": None,
        "frequency_severity": None,
        "associated_signs": [],
        "negated_findings": [],
        "exposure_history": None,
        "relevant_history": None,
        "red_flags": [],
        "missing_information": [],
        "evidence_spans": [],
    }
    values.update(overrides)
    return ExtractionOutput(**values)


def add_entry(
    session: Session,
    *,
    title: str,
    species: list[Species],
    version,
    axes: list[int],
    kind: KBEntryKind = KBEntryKind.COMPLAINT,
    urgency_category: VTLCategory | None = None,
    author=None,
) -> KBEntry:
    """An ACTIVE entry linked into `version`, with one chunk per axis in `axes`."""
    is_complaint = kind is KBEntryKind.COMPLAINT
    entry = make_kb_entry(
        session,
        kind=kind,
        complaint_code="LETHARGY" if is_complaint else None,
        urgency_category=urgency_category,
        status=KBEntryStatus.ACTIVE,
        title=title,
        created_by=author,
        kb_version=version,
        with_source=True,
    )
    entry.species = species
    for index, axis in enumerate(axes):
        session.add(
            KBChunk(
                entry_id=entry.id,
                chunk_index=index,
                text=f"{title} chunk {index}",
                word_count=4,
                embedding=unit(axis),
                embedding_model="fake-embedder",
            )
        )
    session.flush()
    return entry


@pytest.fixture
def seeded(db_session: Session) -> dict:
    """Version 1: 2 cat + 1 dog COMPLAINT entries and one URGENCY_ACTIONS entry.

    The URGENCY_ACTIONS chunk sits at distance 0 from the query, closer than any
    COMPLAINT chunk, so it proves the kind filter and not just the ranking keeps
    it out. Version 2 holds one more cat entry, to prove version isolation.
    """
    author = make_user(db_session, role=UserRole.VETERINARY_REVIEWER)
    v1 = make_kb_version(db_session, version_no=9001)
    v2 = make_kb_version(db_session, version_no=9002)
    cat, dog = [Species.CAT], [Species.DOG]
    # Three chunks, all at distance 0: the per-entry cap has to drop one.
    add_entry(
        db_session,
        title="Urinary straining",
        species=cat,
        version=v1,
        axes=[0, 0, 0],
        author=author,
    )
    add_entry(db_session, title="Vomiting", species=cat, version=v1, axes=[1], author=author)
    add_entry(db_session, title="Itching", species=dog, version=v1, axes=[2], author=author)
    add_entry(
        db_session,
        title="Suggested actions - Red",
        species=[Species.DOG, Species.CAT],
        version=v1,
        axes=[0],
        kind=KBEntryKind.URGENCY_ACTIONS,
        urgency_category=VTLCategory.RED,
        author=author,
    )
    add_entry(db_session, title="Vomiting v2", species=cat, version=v2, axes=[0], author=author)
    return {"v1": v1.id, "v2": v2.id}


@pytest.fixture
def retriever(app_session_factory) -> PgVectorRetriever:
    return PgVectorRetriever(app_session_factory, FakeEmbedder(unit(0)), ef_search=40)


def titles(passages) -> list[str]:
    return [passage.entry_title for passage in passages]


def test_only_the_requested_version_is_searched(retriever, seeded) -> None:
    result = retriever.retrieve(make_extraction(Species.CAT), seeded["v1"], k=5)

    assert "Vomiting v2" not in titles(result)
    assert titles(result)  # and the version is not simply empty


def test_the_other_version_is_searched_on_its_own(retriever, seeded) -> None:
    result = retriever.retrieve(make_extraction(Species.CAT), seeded["v2"], k=5)

    assert titles(result) == ["Vomiting v2"]


def test_urgency_actions_entry_is_never_returned(retriever, seeded) -> None:
    """ADR-18: baseline action text is looked up by category, never retrieved."""
    result = retriever.retrieve(make_extraction(Species.CAT), seeded["v1"], k=10)

    assert "Suggested actions - Red" not in titles(result)


def test_dog_only_entry_never_appears_for_a_cat(retriever, seeded) -> None:
    result = retriever.retrieve(make_extraction(Species.CAT), seeded["v1"], k=10)

    assert "Itching" not in titles(result)


def test_cat_only_entries_never_appear_for_a_dog(retriever, seeded) -> None:
    result = retriever.retrieve(make_extraction(Species.DOG), seeded["v1"], k=10)

    assert titles(result) == ["Itching"]


def test_at_most_two_chunks_per_entry(retriever, seeded) -> None:
    result = retriever.retrieve(make_extraction(Species.CAT), seeded["v1"], k=10)

    assert titles(result).count("Urinary straining") == PgVectorRetriever.MAX_CHUNKS_PER_ENTRY


def test_ranks_are_consecutive_from_one_in_score_order(retriever, seeded) -> None:
    result = retriever.retrieve(make_extraction(Species.CAT), seeded["v1"], k=10)

    assert [passage.rank for passage in result] == list(range(1, len(result) + 1))
    scores = [passage.score for passage in result]
    assert scores == sorted(scores, reverse=True)
    assert result[0].score == pytest.approx(1.0)
    assert result[0].entry_title == "Urinary straining"


def test_k_limits_the_result(retriever, seeded) -> None:
    result = retriever.retrieve(make_extraction(Species.CAT), seeded["v1"], k=1)

    assert len(result) == 1
    assert result[0].rank == 1


def test_a_chunk_without_an_embedding_is_skipped(db_session, retriever, seeded) -> None:
    for chunk in db_session.query(KBChunk).all():
        chunk.embedding = None
    db_session.flush()

    assert retriever.retrieve(make_extraction(Species.CAT), seeded["v1"], k=5) == []


def test_latency_is_recorded(retriever, seeded) -> None:
    retriever.retrieve(make_extraction(Species.CAT), seeded["v1"], k=5)

    assert retriever.last_latency_ms >= 0


def test_a_failing_search_surfaces_as_retrieval_failed(app_session_factory, seeded) -> None:
    broken = PgVectorRetriever(app_session_factory, BrokenEmbedder())

    with pytest.raises(RetrievalFailed):
        broken.retrieve(make_extraction(Species.CAT), seeded["v1"], k=5)


def test_stage_attributes_follow_the_stage_contract() -> None:
    retriever = PgVectorRetriever(None, FakeEmbedder(unit(0)))

    assert retriever.model_id == "fake-embedder"
    assert retriever.prompt_version == "retrieval-v1"


def test_query_leaves_out_empty_parts() -> None:
    retriever = PgVectorRetriever(None, FakeEmbedder(unit(0)))
    extraction = make_extraction(Species.DOG)

    assert retriever.build_query(extraction, {"LETHARGY": "Lethargy"}) == "Dog. Lethargy."


def test_query_names_every_part_when_present() -> None:
    retriever = PgVectorRetriever(None, FakeEmbedder(unit(0)))
    extraction = make_extraction(
        Species.CAT,
        presenting_complaints=[
            ExtractedComplaint(code="VOMITING", is_primary=False),
            ExtractedComplaint(code="LETHARGY", is_primary=True),
        ],
        associated_signs=["hiding"],
        red_flags=["straining"],
        onset_duration="two days",
    )

    query = retriever.build_query(extraction, {"VOMITING": "Vomiting", "LETHARGY": "Lethargy"})

    assert query == (
        "Cat. Lethargy. Other complaints: Vomiting. Signs: hiding. "
        "Red flags: straining. Duration: two days."
    )
