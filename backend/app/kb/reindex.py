"""Re-embed knowledge-base chunks.

python -m app.kb.reindex --missing     # only chunks with no embedding
python -m app.kb.reindex --all         # every chunk (after changing EMBEDDING_MODEL)
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.kb.chunking import embedding_text, species_names
from app.models.knowledge_base import KBChunk, KBEntry

BATCH = 64


def reindex(session_factory, embedder, *, only_missing: bool, batch: int = BATCH) -> int:
    """Walk the chunks in id order, one batch per transaction. Returns how many were updated."""
    updated, last_id = 0, None
    while True:
        with session_factory() as s, s.begin():
            query = (
                select(KBChunk, KBEntry)
                .join(KBEntry, KBEntry.id == KBChunk.entry_id)
                .order_by(KBChunk.id)
                .limit(batch)
            )
            if only_missing:
                query = query.where(KBChunk.embedding.is_(None))
            if last_id is not None:
                query = query.where(KBChunk.id > last_id)
            rows = s.execute(query).all()
            if not rows:
                return updated
            texts = [
                embedding_text(entry.title, species_names(entry.species), chunk.text)
                for chunk, entry in rows
            ]
            for (chunk, _), vector in zip(rows, embedder.embed(texts), strict=True):
                chunk.embedding = vector
                chunk.embedding_model = embedder.model_id
            updated += len(rows)
            last_id = rows[-1][0].id


def main() -> None:
    from app.adapters.embeddings.sentence_transformer import SentenceTransformerEmbedder
    from app.core.config import get_settings
    from app.db.session import SessionLocal

    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--missing", action="store_true")
    mode.add_argument("--all", action="store_true")
    args = parser.parse_args()

    embedder = SentenceTransformerEmbedder.from_settings(get_settings())
    count = reindex(SessionLocal, embedder, only_missing=args.missing)
    print(f"re-embedded {count} chunk(s) with {embedder.model_id}")


if __name__ == "__main__":
    main()
