"""M4 verification: model, vector column, normalisation, latency, token budget and the HNSW index.

    docker compose exec backend python -m scripts.embedding_check

Exit code 0 only if every check passes.
"""

from __future__ import annotations

import statistics
import sys
import time

import numpy as np
from sqlalchemy import text

from app.core.config import get_settings

SIMILAR_A = "Male cat straining to urinate in the litter box."
SIMILAR_B = "Tomcat cannot pass urine and keeps trying."
UNRELATED = "Dog scratching and licking his paws for two weeks."

PASSAGES = [
    "Male cat straining in the litter box and unable to pass urine.",
    "Dog scratching and licking paws for two weeks with red skin.",
    "Dog breathing rapidly with open mouth and blue gums.",
    "Cat vomiting several times since yesterday and refusing food.",
    "Dog limping on a front leg after jumping from a sofa.",
    "Puppy ate chocolate this morning and is restless.",
]
QUERY = "tomcat keeps going to the litter box but nothing comes out"

PROSE = (
    "The cat has been vomiting several times since yesterday morning and refuses to eat. "
    "The owner reports that the animal is drinking more water than usual and seems lethargic. "
    "There is no blood in the vomit and no diarrhoea has been noticed. The cat is three years old "
    "and fully vaccinated. It lives indoors and has not eaten any plants or toys "
    "that the owner knows of. "
    "The owner would like to know how quickly the cat should be seen by a veterinarian today."
)

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    results.append((ok, label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def get_embedder(settings):
    from app.adapters.embeddings.sentence_transformer import SentenceTransformerEmbedder

    return SentenceTransformerEmbedder.from_settings(settings)


def get_engine():
    from app.db.session import engine

    return engine


def main() -> int:
    s = get_settings()
    if not s.EMBEDDING_PROVIDER:
        print(
            "EMBEDDING_PROVIDER is blank. Set EMBEDDING_PROVIDER=sentence_transformer "
            "in .env, then restart."
        )
        return 1
    emb = get_embedder(s)

    # 1. model loads, and the dimension agrees with the setting
    t0 = time.perf_counter()
    try:
        emb.embed(["warm-up"])
    except Exception as exc:  # noqa: BLE001
        check(False, "model loads", f"{type(exc).__name__}: {str(exc)[:150]}")
        return 1
    check(True, f"model loads: {emb.model_id}", f"first load {time.perf_counter() - t0:.1f} s")
    print(f"      dim={emb.dim}  max input={emb.max_seq_length} word-pieces  device={emb.device}")

    # 2. vectors are unit length
    vecs = np.array(emb.embed([SIMILAR_A, SIMILAR_B, UNRELATED]))
    norms = np.linalg.norm(vecs, axis=1)
    check(
        bool(np.all(np.abs(norms - 1.0) < 1e-3)),
        "vectors are L2-normalised",
        f"norms {np.round(norms, 4).tolist()}",
    )

    # 3. meaning, not spelling: the paraphrase must beat the unrelated sentence by a clear margin
    sim_close, sim_far = float(vecs[0] @ vecs[1]), float(vecs[0] @ vecs[2])
    check(
        sim_close - sim_far >= 0.15,
        "paraphrase is clearly closer than an unrelated sentence",
        f"similar={sim_close:.3f} unrelated={sim_far:.3f}",
    )

    # 4. latency (NFR-02 / NFR-01): query-sized input after warm-up
    singles = []
    for _ in range(20):
        t = time.perf_counter()
        emb.embed([QUERY])
        singles.append((time.perf_counter() - t) * 1000)
    p50, p95 = statistics.median(singles), sorted(singles)[int(0.95 * (len(singles) - 1))]
    check(p50 <= 200, "single query p50 <= 200 ms", f"p50={p50:.0f} ms p95={p95:.0f} ms")
    t = time.perf_counter()
    emb.embed(PASSAGES * 11)
    batch = time.perf_counter() - t
    print(f"      indexing speed: {66 / batch:.0f} passages/s (66 passages in {batch:.2f} s)")

    # 5. how many words fit? Measured on realistic English, not guessed.
    words = len(PROSE.split())
    toks = emb.token_count([PROSE])[0]
    ratio = toks / words
    header_budget = 32  # title + species prefix added to every chunk (M5)
    target = int((emb.max_seq_length - header_budget) * 0.9 / ratio)
    print(f"      {words} words = {toks} word-pieces ({ratio:.2f} per word)")
    check(
        target >= 40,
        f"recommended KB_CHUNK_TARGET_WORDS = {target}",
        f"fits {emb.max_seq_length} word-pieces with a {header_budget}-piece header",
    )

    # 6. the database: column dimension, then a real HNSW index on a scratch table
    try:
        eng = get_engine()
        with eng.connect() as c:
            dim = c.execute(
                text(
                    "select atttypmod from pg_attribute "
                    "where attrelid = 'kb_chunks'::regclass "
                    "and attname = 'embedding' and not attisdropped"
                )
            ).scalar()
            if dim is None:
                check(False, "kb_chunks.embedding exists", "run: alembic upgrade head")
            else:
                check(
                    dim == emb.dim,
                    "kb_chunks.embedding dimension matches the model",
                    f"column={dim} model={emb.dim}",
                )
            idx = c.execute(
                text(
                    "select indexdef from pg_indexes "
                    "where indexname = 'ix_kb_chunks_embedding_hnsw'"
                )
            ).scalar()
            check(
                bool(idx) and "hnsw" in idx and "vector_cosine_ops" in idx,
                "HNSW cosine index exists on kb_chunks",
            )
        with eng.begin() as c:
            c.execute(
                text(
                    "create temp table vec_check "
                    f"(id serial primary key, t text, embedding vector({emb.dim})) "
                    "on commit drop"
                )
            )
            for passage, v in zip(PASSAGES, emb.embed(PASSAGES), strict=True):
                c.execute(
                    text("insert into vec_check (t, embedding) values (:t, CAST(:v AS vector))"),
                    {"t": passage, "v": str(v)},
                )
            c.execute(
                text(
                    "create index vec_check_hnsw on vec_check "
                    "using hnsw (embedding vector_cosine_ops)"
                )
            )
            c.execute(
                text("set local enable_seqscan = off")
            )  # tiny table: force the planner to prove the index works
            qv = str(emb.embed([QUERY])[0])
            plan = "\n".join(
                r[0]
                for r in c.execute(
                    text(
                        "explain select t from vec_check "
                        "order by embedding <=> CAST(:q AS vector) limit 1"
                    ),
                    {"q": qv},
                )
            )
            check(
                "vec_check_hnsw" in plan,
                "planner uses the HNSW index for a nearest-neighbour query",
                plan.splitlines()[1].strip()[:70] if len(plan.splitlines()) > 1 else plan[:70],
            )
            best = c.execute(
                text(
                    "select t, 1 - (embedding <=> CAST(:q AS vector)) from vec_check "
                    "order by embedding <=> CAST(:q AS vector) limit 1"
                ),
                {"q": qv},
            ).one()
            check(
                best[0] == PASSAGES[0],
                "nearest neighbour of the test query is the urinary passage",
                f"score={float(best[1]):.3f}",
            )
    except Exception as exc:  # noqa: BLE001
        check(False, "database checks ran", f"{type(exc).__name__}: {str(exc)[:200]}")

    failed = [label for ok, label in results if not ok]
    print(
        f"\n{len(results) - len(failed)}/{len(results)} checks passed"
        + (f"; FAILED: {failed}" if failed else "")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
