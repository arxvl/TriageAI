# M4 — pgvector Column, Vector Index, and Embedding Model (Manual)

**Owner:** Lane B · **Branch:** `feat/m4-pgvector-embeddings`
**Do after:** P02 (the schema exists) · **Closes:** TBD-2 · **Updates:** ADR-04, ADR-07
**Requirements:** FR-19, NFR-02, NFR-23, NFR-28

You will add the vector column and the HNSW index to `kb_chunks`, install a local sentence-embedding model, and implement `SentenceTransformerEmbedder` behind the `EmbeddingProvider` interface.

## Prerequisites

- [ ] P02 migrations are applied. `kb_chunks` exists **without** an `embedding` column.
- [ ] `db/init/01-extensions.sql` created the `vector` extension.
- [ ] Your laptop has at least 8 GB RAM, with Docker allowed to use at least 4 GB.

---

## Step 1. Confirm pgvector is available

```bash
docker compose exec db psql -U triageai -d triageai -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker compose exec db psql -U triageai -d triageai -c "SELECT extversion FROM pg_extension WHERE extname='vector';"
```

**Check 1.** A version is printed. HNSW indexes need pgvector 0.5.0 or later; the `pgvector/pgvector:pg16` image satisfies this.

## Step 2. Choose the embedding model

| Candidate | Dimensions | Max input | Notes |
|---|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | 384 | 256 word-pieces | Small and fast; English-focused |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 384 | 128 word-pieces | Multilingual. Input is English only (FR-18), so pick this **only** if it scores better on the English queries in M5 Step 6 |

Both use 384 dimensions, so the column stays the same if you switch models later. The **max input** limits the chunk size in M5: text beyond it is silently cut off.

Start with `all-MiniLM-L6-v2`: input is English only (FR-18), and its longer input limit allows larger chunks. The comparison by Recall@5 happens in M5 Step 6, after real entries exist. Record the choice in `docs/adr/ADR-07.md` as "provisional".

## Step 3. Add the dependencies

In `backend/pyproject.toml`, add `pgvector` and `sentence-transformers` to the runtime dependencies.

In `backend/Dockerfile`, install the **CPU-only** PyTorch *before* the project, so the image doesn't download a multi-gigabyte GPU build. Then pre-download the model at build time:

```dockerfile
ENV HF_HOME=/opt/hf
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
# ... existing project install ...
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('${EMBEDDING_MODEL}')"
```

Add these settings to `config.py` and `.env.example`:

```dotenv
EMBEDDING_PROVIDER=sentence_transformer
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIM=384
EMBEDDING_DEVICE=cpu
EMBEDDING_BATCH_SIZE=32
```

Model weights live in the image cache under `/opt/hf`. **Never commit them.** `models/` is in `.gitignore`.

**Check 3.** Run `docker compose build backend`, then check the image size with `docker images`. An increase of about 1–1.5 GB is expected.

## Step 4. Migration — vector column and HNSW index

Create the revision:

```bash
docker compose exec backend alembic revision -m "m4 kb_chunks embedding vector and hnsw index"
```

Edit the generated file:

```python
def upgrade() -> None:
    op.execute("ALTER TABLE kb_chunks ADD COLUMN embedding vector(384)")
    op.execute("ALTER TABLE kb_chunks ADD COLUMN embedding_model text")
    op.execute(
        "CREATE INDEX ix_kb_chunks_embedding_hnsw ON kb_chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_kb_chunks_embedding_hnsw")
    op.execute("ALTER TABLE kb_chunks DROP COLUMN IF EXISTS embedding_model")
    op.execute("ALTER TABLE kb_chunks DROP COLUMN IF EXISTS embedding")
```

Update the model in `backend/app/models/knowledge_base.py`:

```python
from pgvector.sqlalchemy import Vector

class KBChunk(Base):
    ...
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(nullable=True)
```

About the choices:

- `vector_cosine_ops` matches the `<=>` cosine-distance operator used in M6.
- `m = 16` and `ef_construction = 64` are pgvector's defaults, and are fine for fewer than 5,000 chunks.
- The application role must be able to use the new column. Re-run the grants from P02's `0002` migration, or add `GRANT SELECT, INSERT, UPDATE ON kb_chunks TO triageai_app;` to this migration.

Apply the migration:

```bash
docker compose exec backend alembic upgrade head
docker compose exec db psql -U triageai -d triageai -c "\d kb_chunks"
```

**Check 4.** `\d kb_chunks` shows `embedding | vector(384)` and the index `ix_kb_chunks_embedding_hnsw ... hnsw (embedding vector_cosine_ops)`. Also check that downgrade followed by upgrade works.

## Step 5. Implement `backend/app/adapters/embeddings/sentence_transformer.py`

```python
"""Local sentence-embedding provider (M4). CPU, normalized vectors (cosine)."""
from __future__ import annotations

import threading


class SentenceTransformerEmbedder:
    _lock = threading.Lock()
    _model = None

    def __init__(self, model_id: str, dim: int, device: str = "cpu", batch_size: int = 32):
        self.model_id, self.dim, self.device, self.batch_size = model_id, dim, device, batch_size

    @classmethod
    def from_settings(cls, settings, deps=None) -> "SentenceTransformerEmbedder":
        return cls(settings.EMBEDDING_MODEL, settings.EMBEDDING_DIM,
                   settings.EMBEDDING_DEVICE, settings.EMBEDDING_BATCH_SIZE)

    def _load(self):
        with self._lock:
            if SentenceTransformerEmbedder._model is None:
                from sentence_transformers import SentenceTransformer  # lazy import (slow)
                model = SentenceTransformer(self.model_id, device=self.device)
                actual = model.get_sentence_embedding_dimension()
                if actual != self.dim:
                    raise RuntimeError(f"EMBEDDING_DIM={self.dim} but model produces {actual}")
                SentenceTransformerEmbedder._model = model
        return SentenceTransformerEmbedder._model

    @property
    def max_seq_length(self) -> int:
        return self._load().max_seq_length

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = self._load().encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                   convert_to_numpy=True, show_progress_bar=False)
        return vecs.tolist()
```

**Load it at startup.** In the FastAPI lifespan, call `embedder.embed(["warm-up"])` when `EMBEDDING_PROVIDER` is set, so the first real query doesn't pay the 5–15 s model load. Ask Claude Code to add this lifespan hook as a one-line change. It is wiring, not AI logic.

## Step 6. Verify the embedder

```bash
docker compose exec backend python - <<'PY'
from app.core.config import get_settings
from app.adapters.embeddings.sentence_transformer import SentenceTransformerEmbedder as E
import numpy as np, time
e = E.from_settings(get_settings())
a, b, c = e.embed(["male cat straining in the litter box, no urine",
                   "tomcat cannot pass urine and keeps trying",
                   "dog itching and licking paws for two weeks"])
print("dim", len(a), "max_seq_length", e.max_seq_length)
print("similar pair", round(float(np.dot(a, b)), 3), "unrelated pair", round(float(np.dot(a, c)), 3))
t = time.perf_counter(); e.embed(["query"]); print("query ms", round((time.perf_counter()-t)*1000))
PY
```

**Check 6.**

- `dim 384`.
- The similar pair scores clearly higher than the unrelated pair. Expect roughly 0.6 or more versus 0.2 or less; exact values vary.
- The query takes under 200 ms after warm-up.

## Step 7. Verify vector SQL end to end (temporary rows)

```bash
docker compose exec backend python - <<'PY'
import uuid
from sqlalchemy import text
from app.db.session import SessionLocal
from app.adapters.embeddings.sentence_transformer import SentenceTransformerEmbedder as E
from app.core.config import get_settings
e = E.from_settings(get_settings())
with SessionLocal() as s:
    entry = s.execute(text("select id from kb_entries limit 1")).scalar()
    if entry is None:
        raise SystemExit("Import at least one sample entry first (P08 import_kb)")
    ids = []
    for i, t in enumerate(["cat cannot urinate", "dog skin itching", "dog breathing hard"]):
        cid = uuid.uuid4(); ids.append(cid)
        s.execute(text("insert into kb_chunks (id, entry_id, chunk_index, text, word_count, embedding, created_at) "
                       "values (:id, :e, :i, :t, 3, :v, now())"),
                  {"id": cid, "e": entry, "i": 900 + i, "t": t, "v": str(e.embed([t])[0])})
    q = str(e.embed(["male cat straining, nothing comes out"])[0])
    rows = s.execute(text("select text, 1 - (embedding <=> :q) as score from kb_chunks "
                          "where id = any(:ids) order by embedding <=> :q"), {"q": q, "ids": ids}).all()
    print(rows)
    s.rollback()   # temporary rows, nothing kept
PY
```

**Check 7.** The first row is `cat cannot urinate`, with the highest score. Everything is rolled back.

With very few rows, PostgreSQL may not use the index at all. That is normal; the results are still correct.

## Done when

- [ ] The migration is applied, `\d kb_chunks` shows the vector column and the HNSW index, and downgrade/upgrade works.
- [ ] Checks 6 and 7 pass.
- [ ] ADR-07 is updated with the provisional model, dimension, and max input.
- [ ] Committed, with a PR into `develop`. `KB_INDEXER` and `PIPELINE_RETRIEVER` stay `mock` until M5 and M6.
