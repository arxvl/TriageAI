"""Entry-level retrieval metrics used by the M5 measurement (NFR-17).

`ranked` is a list of DISTINCT entry slugs, best first. `expected` is the set of slugs
that count as a correct answer for the query.
"""

from __future__ import annotations


def recall_at_k(ranked: list[str], expected: list[str], k: int) -> float:
    wanted = set(expected)
    if not wanted:
        raise ValueError("a query needs at least one expected slug")
    return len(set(ranked[:k]) & wanted) / len(wanted)


def reciprocal_rank(ranked: list[str], expected: list[str]) -> float:
    wanted = set(expected)
    for position, slug in enumerate(ranked, start=1):
        if slug in wanted:
            return 1.0 / position
    return 0.0


def summarize(results: list[tuple[list[str], list[str]]], k: int = 5) -> dict:
    """results: one (ranked, expected) pair per query."""
    n = len(results)
    if n == 0:
        raise ValueError("no queries")
    return {
        "queries": n,
        f"recall@{k}": sum(recall_at_k(r, e, k) for r, e in results) / n,
        "mrr": sum(reciprocal_rank(r, e) for r, e in results) / n,
    }
