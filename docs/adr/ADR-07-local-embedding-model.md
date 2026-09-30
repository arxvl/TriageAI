# ADR-07: Local sentence-embedding model for retrieval

- **Status:** Accepted (final model recorded below)
- **Requirements:** FR-19, NFR-02, NFR-17, NFR-23, NFR-28, SR-08
- **Open item:** TBD-2 is closed when the comparison table is filled in
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

## Candidates and result (TBD-2)

Both candidates produce 384 dimensions, so the database column is unchanged if
the choice changes. Measured on 15–20 English queries with known target entries
(M5 Step 6):

| Model | Max input (word-pieces) | Chunk target words | Recall@5 | MRR | Chosen |
|---|---|---|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | 256 | 150 | | | |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 128 | 75 | | | |

Input is English only (ADR-16), so the multilingual model is chosen only if it
scores better on English queries.

## Consequences

**Positive**

- No case-derived text leaves the server for retrieval. The only outbound AI
  call is the LLM one (ADR-10).
- No per-query cost, no rate limit, and stable latency (under 200 ms after
  warm-up).
- Embeddings are reproducible for a fixed model, which the evaluation depends on
  (NFR-23).

**Negative**

- The backend image grows by roughly 1–1.5 GB, and the container needs about
  1 GB of RAM for the model.
- First load takes 5–15 s, hence the warm-up call.
- Changing the model invalidates every stored embedding: all chunks must be
  re-embedded (`python -m app.kb.reindex --all`).
- The model's maximum input length caps chunk size (ADR-14); longer text is
  silently truncated, which is why the chunker targets a word count below the
  limit.

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
