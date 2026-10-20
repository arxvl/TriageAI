"""M5 Step 11: Recall@5 and MRR over your labelled queries (NFR-17: 0.80 and 0.70).

python -m scripts.kb_recall
python -m scripts.kb_recall --queries /evaluation/retrieval/queries.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from app.kb.retrieval_metrics import summarize

DEFAULT_QUERIES = "/evaluation/retrieval/queries.yaml"
TARGET_RECALL, TARGET_MRR = 0.80, 0.70


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", default=DEFAULT_QUERIES)
    parser.add_argument("--min-queries", type=int, default=15)
    args = parser.parse_args()

    queries = [q for q in yaml.safe_load(Path(args.queries).read_text(encoding="utf-8"))]
    if any(str(q.get("query", "")).strip().upper().startswith("TODO") for q in queries):
        print("queries.yaml still has TODO entries. Write them first.")
        return 1
    if len(queries) < args.min_queries:
        print(
            f"queries.yaml has {len(queries)} queries; write at least {args.min_queries} "
            "(or pass --min-queries to override)."
        )
        return 1

    from app.core.config import get_settings
    from app.db.session import SessionLocal
    from scripts._kb import build_embedder, nearest_entries

    embedder = build_embedder()
    pairs: list[tuple[list[str], list[str]]] = []
    with SessionLocal() as s:
        for q in queries:
            ranked = [
                slug
                for slug, _, _ in nearest_entries(
                    s, embedder.embed([q["query"]])[0], q.get("species"), k=5
                )
            ]
            pairs.append((ranked, q["expected"]))
            rank = next((i for i, slug in enumerate(ranked, 1) if slug in q["expected"]), None)
            status = f"hit @{rank}" if rank else "MISS"
            print(f"{q['id']:5s} {status}   top-5: {', '.join(ranked)}")

    out = summarize(pairs, k=5)
    model = get_settings().EMBEDDING_MODEL
    print(
        f"\nmodel={model}  queries={out['queries']}  "
        f"Recall@5={out['recall@5']:.2f}  "
        f"MRR={out['mrr']:.2f}"
    )
    print(f"targets: Recall@5 >= {TARGET_RECALL}, MRR >= {TARGET_MRR}")
    print(f"\n| {model} | {out['queries']} | {out['recall@5']:.2f} | {out['mrr']:.2f} |")
    return 0 if out["recall@5"] >= TARGET_RECALL and out["mrr"] >= TARGET_MRR else 2


if __name__ == "__main__":
    sys.exit(main())
