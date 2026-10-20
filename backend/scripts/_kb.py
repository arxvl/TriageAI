"""Shared helpers for the M5 verification scripts. The application never imports this."""

from __future__ import annotations

from sqlalchemy import select

from app.adapters.embeddings.sentence_transformer import SentenceTransformerEmbedder
from app.core.config import get_settings
from app.models.enums import KBEntryKind, KBEntryStatus, Species
from app.models.knowledge_base import KBChunk, KBEntry


def build_embedder() -> SentenceTransformerEmbedder:
    return SentenceTransformerEmbedder.from_settings(get_settings())


def nearest_entries(session, vector, species: str | None, k: int = 5, overfetch: int = 4):
    """The k best DISTINCT clinical entries for a query vector, as (slug, title, score).

    Same rules the M6 retriever will use: ACTIVE entries only, clinical entries only,
    optionally filtered by species, ranked by cosine similarity of their best chunk."""
    distance = KBChunk.embedding.cosine_distance(vector).label("distance")
    statement = (
        select(KBEntry.slug, KBEntry.title, distance)
        .select_from(KBChunk)
        .join(KBEntry, KBEntry.id == KBChunk.entry_id)
        .where(
            KBEntry.status == KBEntryStatus.ACTIVE,
            KBEntry.kind == KBEntryKind.COMPLAINT,
            KBChunk.embedding.is_not(None),
        )
    )
    if species:
        statement = statement.where(KBEntry.species.any(Species(species)))
    seen: set[str] = set()
    ranked: list[tuple[str, str, float]] = []
    for slug, title, d in session.execute(statement.order_by(distance).limit(k * overfetch)):
        if slug not in seen:
            seen.add(slug)
            ranked.append((slug, title, 1.0 - float(d)))
        if len(ranked) == k:
            break
    return ranked
