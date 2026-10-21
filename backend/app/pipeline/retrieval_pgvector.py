"""pgvector retriever (M6): cosine top-k over the active KB version, species-filtered.

Only entries of kind COMPLAINT are retrievable. URGENCY_ACTIONS entries (the
baseline suggested-action text written in M5 Part D) are excluded from similarity
search -- they are looked up directly by category in the SUGGEST_ACTIONS stage
(P05b, M6b), never surfaced here (ADR-18).
"""

from __future__ import annotations

import time

from sqlalchemy import select, text

from app.models.enums import KBEntryKind
from app.models.knowledge_base import KBChunk, KBEntry, PresentingComplaint, kb_version_entries
from app.pipeline.errors import RetrievalFailed
from app.pipeline.types import Passage


class PgVectorRetriever:
    MAX_CHUNKS_PER_ENTRY = 2
    prompt_version = "retrieval-v1"  # stage attribute (CLAUDE.md section 8.2)

    def __init__(self, session_factory, embedder, ef_search: int = 40):
        self.sf, self.embedder, self.ef_search = session_factory, embedder, ef_search
        self.last_latency_ms = 0

    @classmethod
    def from_settings(cls, settings, deps) -> PgVectorRetriever:
        if deps.embedder is None:
            raise RuntimeError("PIPELINE_RETRIEVER=pgvector requires EMBEDDING_PROVIDER (M4)")
        return cls(deps.session_factory, deps.embedder, settings.HNSW_EF_SEARCH)

    @property
    def model_id(self) -> str:
        return self.embedder.model_id

    def build_query(self, extraction, names: dict[str, str]) -> str:
        primary = next((c for c in extraction.presenting_complaints if c.is_primary), None)
        others = [
            names.get(c.code, c.code) for c in extraction.presenting_complaints if not c.is_primary
        ]
        parts = [
            f"{extraction.species.value.title()}.",
            f"{names.get(primary.code, primary.code)}." if primary else "",
            f"Other complaints: {', '.join(others)}." if others else "",
            f"Signs: {', '.join(extraction.associated_signs)}."
            if extraction.associated_signs
            else "",
            f"Red flags: {', '.join(extraction.red_flags)}." if extraction.red_flags else "",
            f"Duration: {extraction.onset_duration}." if extraction.onset_duration else "",
        ]
        return " ".join(p for p in parts if p)

    def retrieve(self, extraction, kb_version_id, k: int) -> list[Passage]:
        start = time.perf_counter()
        try:
            with self.sf() as s:
                names = {c.code: c.name for c in s.scalars(select(PresentingComplaint))}
                q = self.embedder.embed([self.build_query(extraction, names)])[0]
                # Postgres does not accept bind parameters in SET commands at all (not a
                # psycopg limitation -- the server rejects it outright), so the value is
                # validated as an int and interpolated directly. It is never user input.
                s.execute(text(f"SET LOCAL hnsw.ef_search = {int(self.ef_search)}"))
                dist = KBChunk.embedding.cosine_distance(q).label("dist")
                stmt = (
                    select(KBChunk, KBEntry, dist)
                    .join(KBEntry, KBEntry.id == KBChunk.entry_id)
                    .join(kb_version_entries, kb_version_entries.c.entry_id == KBEntry.id)
                    .where(kb_version_entries.c.kb_version_id == kb_version_id)
                    .where(KBEntry.kind == KBEntryKind.COMPLAINT)
                    .where(KBEntry.species.any(extraction.species))
                    .where(KBChunk.embedding.is_not(None))
                    .order_by(dist)
                    .limit(k * 4)
                )
                rows = s.execute(stmt).all()
        except Exception as exc:
            raise RetrievalFailed("vector search failed") from exc

        per_entry: dict = {}
        passages: list[Passage] = []
        for chunk, entry, d in rows:
            if per_entry.get(entry.id, 0) >= self.MAX_CHUNKS_PER_ENTRY:
                continue
            per_entry[entry.id] = per_entry.get(entry.id, 0) + 1
            passages.append(
                Passage(
                    rank=len(passages) + 1,
                    chunk_id=chunk.id,
                    entry_id=entry.id,
                    entry_title=entry.title,
                    source_title=entry.source_title,
                    source_url=entry.source_url,
                    text=chunk.text,
                    score=max(0.0, 1.0 - float(d)),
                )
            )
            if len(passages) == k:
                break
        self.last_latency_ms = int((time.perf_counter() - start) * 1000)
        return passages
