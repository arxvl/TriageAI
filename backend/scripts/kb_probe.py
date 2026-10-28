"""Probe retrieval with the hand-written cases in evaluation/probes/kb_probes.yaml.

python -m scripts.kb_probe
python -m scripts.kb_probe --probes /evaluation/probes/kb_probes.yaml

Reports top1, top3, MRR and every MISS (expected entry not in the top 5). Slugs are compared
without a trailing "-rev<N>", so an approved revision counts as the entry it replaces.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from app.kb.retrieval_metrics import reciprocal_rank

DEFAULT_PROBES = "/evaluation/probes/kb_probes.yaml"
TOP_K = 5
# Over-fetch, because an original and its revision can both be ACTIVE for a while and collapse
# into one slug once the suffix is removed.
FETCH_K = 8


def base_slug(slug: str) -> str:
    return re.sub(r"-rev\d+$", "", slug)


def base_ranking(slugs: list[str]) -> list[str]:
    """Slugs without their revision suffix, best first, each once."""
    return list(dict.fromkeys(base_slug(slug) for slug in slugs))


def query_text(probe: dict) -> str:
    parts = [f"My {probe['species'].lower()}: " + ", ".join(probe["signs"])]
    parts.extend(probe.get("red_flags") or [])
    parts.append(probe["duration"])
    return "; ".join(parts) + "."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probes", default=DEFAULT_PROBES)
    args = parser.parse_args()

    probes = yaml.safe_load(Path(args.probes).read_text(encoding="utf-8"))

    from app.db.session import SessionLocal
    from scripts._kb import build_embedder, nearest_entries

    embedder = build_embedder()
    top1 = top3 = 0
    reciprocal_ranks: list[float] = []
    misses: list[str] = []
    with SessionLocal() as s:
        for probe in probes:
            vector = embedder.embed([query_text(probe)])[0]
            ranked = base_ranking(
                [slug for slug, _, _ in nearest_entries(s, vector, probe["species"], k=FETCH_K)]
            )[:TOP_K]
            expected = base_slug(probe["expect"])
            rank = ranked.index(expected) + 1 if expected in ranked else None
            top1 += rank == 1
            top3 += rank is not None and rank <= 3
            reciprocal_ranks.append(reciprocal_rank(ranked, [expected]))
            if rank is None:
                misses.append(f"{probe['id']} expected {expected}, got {', '.join(ranked)}")
            outcome = f"hit @{rank}" if rank else "MISS"
            print(f"{probe['id']:5s} {outcome:8s} top-5: {', '.join(ranked)}")

    n = len(probes)
    print(
        f"\nmodel={embedder.model_id}  probes={n}  top1={top1 / n:.2f}  "
        f"top3={top3 / n:.2f}  MRR={sum(reciprocal_ranks) / n:.2f}"
    )
    print(f"MISS: {len(misses)}")
    for line in misses:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
