# ADR-07: Local sentence-embedding model for retrieval

- **Requirements:** FR-19, NFR-02, NFR-17, NFR-23, NFR-28, SR-08
- **Open item:** TBD-2 stays open until the Recall@5 comparison in M5 Step 6; the model below is provisional.
- **Related:** ADR-04, ADR-05, ADR-10, ADR-14

## Context

Retrieval needs vector representations for knowledge-base chunks and for each
case's query text. Embeddings are needed twice per case-related workflow: once
when an entry is approved and indexed, once per triage run.

Using a hosted embedding API would mean sending case-derived text to a second
external service, doubling the privacy surface and adding a second dependency
that can rate-limit or fail mid-demonstration.

## Decision

Run the embedding model **locally, inside the backend container**, through the
`EmbeddingProvider` port:

```python
class EmbeddingProvider(Protocol):
    model_id: str
    dim: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

- Implementation: `app.adapters.embeddings.sentence_transformer:SentenceTransformerEmbedder`
  using `sentence-transformers` on **CPU** (`torch` CPU wheel).
- Vectors are **normalised** at encode time, so cosine similarity is a dot
  product and `score = 1 - (embedding <=> query)`.
- The model is downloaded at **image build time** into `HF_HOME=/opt/hf`, so
  containers start without network access and the demo does not depend on a
  model download.
- The model is loaded once per process and warmed up in the FastAPI lifespan.
- `EMBEDDING_DIM` is validated against the loaded model at startup; a mismatch
  with the `vector(384)` column is a startup error, not a silent bug.
- The embedding stage is **off by default**: `EMBEDDING_PROVIDER` is blank in
  `.env.example`, so a fresh clone and CI never load PyTorch. A developer enables
  it in their own `.env`.
- `sentence-transformers` is declared as an optional dependency extra
  (`embeddings`) in `pyproject.toml`, so CI and a plain project install never
  download it. The backend image installs it explicitly in the Dockerfile, after
  the CPU-only PyTorch wheel. The adapter imports it lazily, so unit tests run
  without it using a fake module.
- The loaded model is cached per process, keyed by model and device, so the
  lifespan warm-up and the pipeline's embedder share one copy.
- The image sets `HF_HUB_OFFLINE=1` at runtime, and the model name is passed to
  the image build from `EMBEDDING_MODEL`, so the baked model and the setting
  cannot disagree.
- The schema is added by a migration that also runs
  `CREATE EXTENSION IF NOT EXISTS vector`, because the init script enables the
  extension only in the first database and the test database is created later.
  `kb_chunks.embedding` is `vector(384)` with an HNSW index (`vector_cosine_ops`,
  `m = 16`, `ef_construction = 64`). Rows whose embedding is still NULL are not
  indexed.
- The adapter also exposes `max_seq_length` and `token_count()`. They are not
  part of the `EmbeddingProvider` port. They exist so the M5 chunker can check
  chunk sizes against the model's input limit.

## Candidates and result (TBD-2)

Both candidates produce 384 dimensions, so the database column is unchanged if
the choice changes. Measured on 15–20 English queries with known target entries
(M5 Step 6):

| Model | Max input (word-pieces) | Chunk target words | Recall@5 | MRR | Chosen |
|---|---|---|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | 256 | 150 | | | Provisional default |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 128 | not measured | | | |

Chunk target: 167 was measured on lay prose (1.20 word-pieces per word). 150 is
used until it is re-measured on real knowledge-base entries in M5, because
clinical terms split into more word-pieces.

Input is English only (ADR-16), so the multilingual model is chosen only if it
scores better on English queries.

## Measured in M4

| Item | Value |
|---|---|
| Model | `sentence-transformers/all-MiniLM-L6-v2`, https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2, licence: Apache-2.0 |
| Dimension, max input, device | 384, 256 word-pieces, cpu |
| First load | 3.9 s (weights already in the image) |
| Query embedding latency | p50 7 ms, p95 10 ms |
| Indexing speed | 538 passages/s |
| Word-pieces per word, lay prose | 1.20 (84 words = 101 word-pieces) |
| Paraphrase check | similar 0.447, unrelated 0.271 |
| Nearest-neighbour check | correct passage, score 0.463 |
| Image size increase | about 1.45 GB (torch 904 MB, sentence-transformers 456 MB, model 93 MB; image total 1.71 GB) |
| Resident memory with model loaded | about 506 MB (whole backend container) |

## Consequences

**Positive**

- No case-derived text leaves the server for retrieval. The only outbound AI
  call is the LLM one (ADR-10).
- No per-query cost or rate limit, and low latency: query embedding p50 7 ms,
  p95 10 ms after warm-up (measured in M4).
- Embeddings are reproducible for a fixed model, which the evaluation depends on
  (NFR-23).

**Negative**

- The backend image grew by about 1.45 GB (1.71 GB in total), and the backend
  container uses about 506 MB with the model loaded (measured in M4).
- First load takes about 4 s with the weights baked into the image, hence the
  warm-up call.
- Changing the model invalidates every stored embedding: all chunks must be
  re-embedded (`python -m app.kb.reindex --all`).
- The model's maximum input length caps chunk size (ADR-14); longer text is
  silently truncated, which is why the chunker targets a word count below the
  limit.
- Cosine scores are compressed on short, same-domain text: in the M4 check a true
  paraphrase scored 0.447 and an unrelated pet sentence 0.271. The default
  `retrieval_min_score` of 0.30 sits close to the unrelated level and is
  calibrated on real entries in M5, not changed here.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Hosted embedding API | Second external dependency and second privacy surface for no accuracy need at this scale |
| Full-text search (`tsvector`) only | Misses paraphrase and lay-term matching, which is the point of semantic retrieval |
| Larger local embedding model | Slower on CPU; the retrieval targets are met by a small model at this KB size |

## Implementation notes

- After changing `EMBEDDING_MODEL`, rebuild the image and run
  `python -m app.kb.reindex --all`, then re-check Recall@5.
- `embedding_model` is stored on every chunk row so a mixed-model state is
  detectable.
- Changing `EMBEDDING_DIM` also needs a new migration that alters the column and
  rebuilds the index. Never edit the existing revision.
- `scripts/embedding_check.py` is the verification for this ADR; rerun it after
  any change to the model, the image or the migration.
