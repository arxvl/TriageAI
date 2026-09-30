# M5 — Knowledge Base Authoring, Chunking, and Indexing (Manual)

**Owner:** Lane B, with every member writing entries · **Branch:** `feat/m5-kb-indexing` (+ `content/m5-kb-entries`)
**Do after:** M4, P08 · **Requirements:** FR-49–FR-55, BR-04, NFR-02, NFR-18, DR-05

You will:

- write the curated knowledge-base entries;
- implement the chunker and the `PgVectorKBIndexer`, so that approving an entry in W-08 creates embedded chunks;
- publish the first real KB version, reviewed by the veterinarian.

## Prerequisites

- [ ] M4 done: the vector column, the index, and the embedder work.
- [ ] P08 merged: the workflow, versions, `import_kb`, and W-08 exist, with the mock indexer.
- [ ] The veterinary reviewer session is booked for KB review.

---

## Part A — Write the entries (content work)

### Step A1. Choose the entries

Write the entries in this order:

1. The 4 demo complaints: urinary obstruction (cat), respiratory distress, skin/itching, and a fourth of your choice.
2. The remaining 16 supported complaints.
3. A separate dog and cat version, only where the guidance differs.

### Step A2. Writing rules (legal and quality)

- Write **in your own words** from the cited source. Never copy sentences (SRS §6 legal requirements). Quoting 1–2 short phrases in quotation marks is the maximum.
- Length: 150–400 words, using this structure:
  1. **What it is:** one or two sentences, lay description.
  2. **Warning signs that raise urgency:** these are the discriminators.
  3. **Signs of lower urgency:** when it can usually wait.
  4. **What staff should ask the owner.**
- Do not write treatment advice or doses. TriageAI never recommends treatment.
- Cite the specific page: title, publisher, URL, and access date. Allowed sources are the Merck Veterinary Manual, WSAVA guidelines, and the VTL papers listed in SRS §1.5.
- Link red-flag codes (`red_flag_codes`) only when the entry covers that red flag.

### Step A3. Create the files

Create one YAML file per entry in `knowledge_base/entries/`, using the P08 format. Delete the `SAMPLE` entries once the real ones exist.

**Check A3.** `docker compose exec backend python -m scripts.import_kb --dry-run` reports no errors.

### Step A4. Vet review (BR-04)

1. Export the entries as one PDF or document for the reviewer, together with `red_flags.yaml` and `red_flag_phrases.yaml` from M1.
2. Record each decision in `knowledge_base/APPROVALS.md`:

   | Date | Item | Reviewer | Decision | Comment |
   |---|---|---|---|---|

3. Apply the requested changes, then import (`python -m scripts.import_kb`). Entries arrive as drafts. The administrator submits them in W-08. The **approver account of the licensed veterinarian** (or a team member acting on the vet's written approval, as stated in APPROVALS.md) approves them. **This happens after Part B**, so approval triggers real indexing.

---

## Part B — Chunker and indexer (code)

### Step B1. Chunk-size rule

Chunks must fit the embedding model's max input (M4 Step 2). About 0.7 words fit per word-piece:

| Model | Max word-pieces | Target words per chunk | Overlap |
|---|---|---|---|
| `all-MiniLM-L6-v2` | 256 | about 150 | 1 sentence |
| `paraphrase-multilingual-MiniLM-L12-v2` | 128 | about 75 | 1 sentence |

Prefix every chunk with the entry title and species. This gives each chunk context and improves retrieval.

### Step B2. Create `backend/app/kb/chunking.py`

```python
"""Sentence-packing chunker (M5)."""
from __future__ import annotations

import re

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def split_sentences(text: str) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    for p in paras:
        out.extend(s.strip() for s in SENT_SPLIT.split(p) if s.strip())
    return out


def chunk_text(text: str, target_words: int, overlap_sentences: int = 1) -> list[str]:
    sents = split_sentences(text)
    chunks, cur, cur_words = [], [], 0
    for s in sents:
        w = len(s.split())
        if cur and cur_words + w > target_words:
            chunks.append(" ".join(cur))
            cur = cur[-overlap_sentences:] if overlap_sentences else []
            cur_words = sum(len(x.split()) for x in cur)
        cur.append(s)
        cur_words += w
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def with_header(title: str, species: list[str], chunk: str) -> str:
    return f"{title} ({', '.join(species)}). {chunk}"
```

Add `KB_CHUNK_TARGET_WORDS=150` and `KB_CHUNK_OVERLAP_SENTENCES=1` to the settings.

### Step B3. Create `backend/app/kb/indexer_pgvector.py`

This design decision matters: **chunks are never deleted.** Retrieved references point at chunks, and approved entries are immutable; a changed entry becomes a new revision (P08). A retired entry simply drops out of newer KB versions.

```python
"""pgvector KB indexer (M5)."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.kb.chunking import chunk_text, with_header
from app.models.knowledge_base import KBChunk, KBEntry


class PgVectorKBIndexer:
    def __init__(self, session_factory, embedder, target_words: int, overlap: int):
        self.sf, self.embedder = session_factory, embedder
        self.target_words, self.overlap = target_words, overlap

    @classmethod
    def from_settings(cls, settings, deps) -> "PgVectorKBIndexer":
        if deps.embedder is None:
            raise RuntimeError("KB_INDEXER=pgvector requires EMBEDDING_PROVIDER to be set (M4)")
        return cls(deps.session_factory, deps.embedder,
                   settings.KB_CHUNK_TARGET_WORDS, settings.KB_CHUNK_OVERLAP_SENTENCES)

    def index_entry(self, entry_id: uuid.UUID) -> int:
        with self.sf() as s, s.begin():
            existing = s.scalar(select(func.count()).select_from(KBChunk).where(KBChunk.entry_id == entry_id))
            if existing:
                missing = s.scalars(select(KBChunk).where(KBChunk.entry_id == entry_id,
                                                          KBChunk.embedding.is_(None))).all()
                self._embed_rows(missing)
                return existing
            entry = s.get(KBEntry, entry_id)
            species = [getattr(x, "value", x) for x in entry.species]
            pieces = chunk_text(entry.content, self.target_words, self.overlap)
            rows = [KBChunk(id=uuid.uuid4(), entry_id=entry.id, chunk_index=i,
                            text=with_header(entry.title, species, p), word_count=len(p.split()))
                    for i, p in enumerate(pieces)]
            s.add_all(rows)
            s.flush()
            self._embed_rows(rows)
            return len(rows)

    def _embed_rows(self, rows) -> None:
        if not rows:
            return
        vecs = self.embedder.embed([r.text for r in rows])
        for r, v in zip(rows, vecs, strict=True):
            r.embedding = v
            r.embedding_model = self.embedder.model_id

    def remove_entry(self, entry_id: uuid.UUID) -> None:
        return None  # retired entries are excluded by KB versions; chunks are kept for audit
```

### Step B4. Re-embed CLI — `backend/app/kb/reindex.py`

`python -m app.kb.reindex --missing` embeds every chunk whose `embedding IS NULL`. `--all` re-embeds every chunk; use it after changing to another 384-dimension model in M4. Print the counts. The CLI is a loop over `_embed_rows` in batches of 64.

### Step B5. Unit tests

- `tests/unit/kb/test_chunking.py`:
  - no chunk exceeds `target_words` plus one sentence
  - the overlap sentence repeats at the start of the next chunk
  - paragraphs are respected
  - short text produces 1 chunk
- `tests/unit/kb/test_indexer.py`, with a fake embedder returning fixed vectors:
  - creates the expected number of rows, with the model recorded
  - is idempotent: a second call creates no duplicates
  - fills missing embeddings

---

## Part C — Switch on and publish the real KB

1. In `.env`, set `KB_INDEXER=pgvector` (keep `EMBEDDING_PROVIDER=sentence_transformer`), then restart the backend.
2. In W-08, as administrator, submit the imported entries.
3. As approver, approve them one by one. Each approval runs a `KB_INDEX` job and publishes a new version.
4. Check the database:

   ```sql
   -- every active entry has chunks, all embedded
   select e.slug, count(c.id) as chunks, count(c.embedding) as embedded
   from kb_entries e left join kb_chunks c on c.entry_id = e.id
   where e.status = 'ACTIVE' group by e.slug order by e.slug;

   -- latest version contains all active entries
   select v.version_no, count(ve.entry_id) from kb_versions v
   join kb_version_entries ve on ve.version_id = v.id
   group by v.version_no order by v.version_no desc limit 1;
   ```

   **Check C4.** `chunks = embedded > 0` for every active entry. The latest version count equals the number of active entries.
5. Nearest-neighbour check for each demo case:

   ```bash
   docker compose exec backend python - <<'PY'
   from sqlalchemy import select
   from app.db.session import SessionLocal
   from app.models.knowledge_base import KBChunk, KBEntry
   from app.adapters.embeddings.sentence_transformer import SentenceTransformerEmbedder as E
   from app.core.config import get_settings
   e = E.from_settings(get_settings())
   q = e.embed(["Cat. Straining or inability to urinate. Signs: crying. Red flags: nothing comes out."])[0]
   with SessionLocal() as s:
       d = KBChunk.embedding.cosine_distance(q)
       for c, title, dist in s.execute(select(KBChunk, KBEntry.title, d).join(KBEntry).order_by(d).limit(5)):
           print(round(1 - dist, 3), title)
   PY
   ```

   **Check C5.** The correct entry is ranked first, or at least in the top 3, for each demo case.

## Step 6. Compare the embedding models (closes TBD-2)

1. Write 15–20 short queries in the format produced by the M6 query builder, each with its expected entry slug. Write them in English (FR-18), and include 3–5 that use lay wording rather than clinical terms.
2. For each candidate model:
   1. Set `EMBEDDING_MODEL`.
   2. Rebuild the image.
   3. Run `python -m app.kb.reindex --all`.
   4. Compute Recall@5 and MRR over the queries, using a small script and the query code from C5.
3. Choose the model with the higher Recall@5, and record it in ADR-07 with the numbers. If you switch to the multilingual model, set `KB_CHUNK_TARGET_WORDS=75` and re-create the chunks.
   - Chunks are never deleted, so re-chunking means publishing new revisions of the entries. Alternatively, run this comparison **before** approving the entries for the first time. That order is simpler.

## Done when

- [ ] All demo entries, and as many of the others as possible, are vet-approved and Active. `APPROVALS.md` is filled in.
- [ ] Checks C4 and C5 pass, and the chunking and indexer tests pass.
- [ ] ADR-07 is updated with the final model and its Recall@5.
- [ ] `KB_INDEXER=pgvector` is committed in `.env.example` as the documented real value.
