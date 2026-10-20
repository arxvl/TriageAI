"""pgvector KB indexer (M5). Called by the KB_INDEX job when an entry is approved."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.kb.chunking import chunk_text, embedding_text, species_names
from app.models.enums import KBEntryKind
from app.models.knowledge_base import KBChunk, KBEntry


class PgVectorKBIndexer:
    def __init__(self, session_factory, embedder, target_words: int, overlap: int):
        self.sf, self.embedder = session_factory, embedder
        self.target_words, self.overlap = target_words, overlap

    @classmethod
    def from_settings(cls, settings, deps) -> PgVectorKBIndexer:
        if deps.embedder is None:
            raise RuntimeError("KB_INDEXER=pgvector needs EMBEDDING_PROVIDER to be set (M4)")
        return cls(
            deps.session_factory,
            deps.embedder,
            settings.KB_CHUNK_TARGET_WORDS,
            settings.KB_CHUNK_OVERLAP_SENTENCES,
        )

    def index_entry(self, entry_id: uuid.UUID) -> int:
        """Create and embed the entry's chunks. Safe to call twice. Returns the chunk count."""
        with self.sf() as s, s.begin():
            entry = s.get(KBEntry, entry_id)
            if entry is None:
                raise ValueError(f"KB entry {entry_id} not found")
            if entry.kind == KBEntryKind.URGENCY_ACTIONS:
                # Baseline actions are looked up by category, never similarity-searched (ADR-18).
                return 0

            chunks = list(
                s.scalars(
                    select(KBChunk)
                    .where(KBChunk.entry_id == entry_id)
                    .order_by(KBChunk.chunk_index)
                ).all()
            )
            if not chunks:
                pieces = chunk_text(entry.content, self.target_words, self.overlap)
                if not pieces:
                    raise ValueError(f"KB entry {entry_id} has no content to index")
                chunks = [
                    KBChunk(
                        id=uuid.uuid4(),
                        entry_id=entry.id,
                        chunk_index=i,
                        text=piece,
                        word_count=len(piece.split()),
                    )
                    for i, piece in enumerate(pieces)
                ]
                s.add_all(chunks)
                s.flush()

            missing = [c for c in chunks if c.embedding is None]
            if missing:
                species = species_names(entry.species)
                vectors = self.embedder.embed(
                    [embedding_text(entry.title, species, c.text) for c in missing]
                )
                for chunk, vector in zip(missing, vectors, strict=True):
                    chunk.embedding = vector
                    chunk.embedding_model = self.embedder.model_id
            return len(chunks)

    def remove_entry(self, entry_id: uuid.UUID) -> None:
        """Chunks are kept on purpose: stored references point at them, and a retired
        entry simply drops out of newer KB versions (ADR-14)."""
        return None
