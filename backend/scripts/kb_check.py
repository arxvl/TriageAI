"""M5 acceptance checks.

    python -m scripts.kb_check                                   # database checks
    python -m scripts.kb_check --queries /evaluation/retrieval/queries.yaml
    # + nearest-neighbour check

Exit code 0 means every check passed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from sqlalchemy import select, text

CATEGORIES = ["RED", "ORANGE", "YELLOW", "GREEN", "BLUE"]
Result = tuple[str, bool, str]  # (check name, passed, detail)


def check_chunks(s) -> list[Result]:
    """Clinical entries must be chunked and fully embedded. Action entries must have no chunks."""
    rows = s.execute(
        text("""
        select e.slug, e.kind, count(c.id) as chunks, count(c.embedding) as embedded
        from kb_entries e left join kb_chunks c on c.entry_id = e.id
        where e.status = 'ACTIVE'
        group by e.slug, e.kind order by e.kind, e.slug""")
    ).all()
    if not rows:
        return [("active entries exist", False, "no ACTIVE entries yet: approve some in W-08")]
    results: list[Result] = []
    for slug, kind, chunks, embedded in rows:
        if str(kind) == "URGENCY_ACTIONS":
            results.append((f"{slug}: not indexed", chunks == 0, f"{chunks} chunks (expected 0)"))
        else:
            ok = chunks > 0 and chunks == embedded
            results.append(
                (f"{slug}: chunked and embedded", ok, f"{chunks} chunks, {embedded} embedded")
            )
    return results


def check_actions(s) -> list[Result]:
    """Exactly one ACTIVE baseline-action entry per urgency category."""
    found = dict(
        s.execute(
            text("""
        select urgency_category, count(*) from kb_entries
        where kind = 'URGENCY_ACTIONS' and status = 'ACTIVE' group by urgency_category""")
        ).all()
    )
    results: list[Result] = []
    for category in CATEGORIES:
        n = found.get(category, 0)
        detail = "ok" if n == 1 else ("missing" if n == 0 else f"{n} active entries, expected 1")
        results.append((f"baseline actions: {category}", n == 1, detail))
    return results


def check_version(s) -> list[Result]:
    """The newest published KB version must contain every ACTIVE entry."""
    active = s.execute(text("select count(*) from kb_entries where status = 'ACTIVE'")).scalar()
    latest = s.execute(
        text("""
        select v.version_no, count(ve.entry_id) from kb_versions v
        left join kb_version_entries ve on ve.version_id = v.id
        group by v.version_no order by v.version_no desc limit 1""")
    ).first()
    if latest is None:
        return [("a KB version is published", False, "no rows in kb_versions")]
    version_no, in_version = latest
    return [
        (
            f"latest KB version v{version_no} lists every active entry",
            in_version == active,
            f"{in_version} in the version, {active} active",
        )
    ]


def check_truncation(s, count_tokens, max_len: int) -> list[Result]:
    """No chunk may be longer than the embedding model can read, or its tail is silently ignored."""
    from app.kb.chunking import embedding_text, species_names
    from app.models.enums import KBEntryKind, KBEntryStatus
    from app.models.knowledge_base import KBChunk, KBEntry

    rows = s.execute(
        select(KBEntry, KBChunk)
        .join(KBChunk, KBChunk.entry_id == KBEntry.id)
        .where(KBEntry.status == KBEntryStatus.ACTIVE, KBEntry.kind == KBEntryKind.COMPLAINT)
    ).all()
    too_long = []
    for entry, chunk in rows:
        tokens = count_tokens(embedding_text(entry.title, species_names(entry.species), chunk.text))
        if tokens > max_len:
            too_long.append(f"{entry.slug}#{chunk.chunk_index} ({tokens} tokens)")
    detail = (
        "all chunks fit"
        if not too_long
        else (
            "over the limit: "
            + ", ".join(too_long[:5])
            + ". Lower KB_CHUNK_TARGET_WORDS, e.g. to 120, and re-chunk."
        )
    )
    return [(f"no chunk exceeds {max_len} tokens", not too_long, detail)]


def check_neighbours(s, embedder, queries: list[dict], k: int = 3) -> list[Result]:
    from scripts._kb import nearest_entries

    results: list[Result] = []
    for q in queries:
        ranked = [
            slug
            for slug, _, _ in nearest_entries(
                s, embedder.embed([q["query"]])[0], q.get("species"), k=k
            )
        ]
        hit = any(slug in ranked for slug in q["expected"])
        results.append(
            (f"{q['id']}: expected entry in the top {k}", hit, "top: " + ", ".join(ranked))
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--queries", help="YAML file of labelled queries (enables the neighbour check)"
    )
    parser.add_argument(
        "--skip-truncation", action="store_true", help="skip loading the embedding model"
    )
    args = parser.parse_args()

    from app.db.session import SessionLocal

    results: list[Result] = []
    with SessionLocal() as s:
        results += check_chunks(s) + check_actions(s) + check_version(s)
        embedder = None
        if not args.skip_truncation or args.queries:
            from scripts._kb import build_embedder

            embedder = build_embedder()
        if not args.skip_truncation:
            model = embedder._load()  # the loaded SentenceTransformer
            tokenizer = model.tokenizer
            results += check_truncation(
                s,
                lambda t: len(tokenizer(t, add_special_tokens=True)["input_ids"]),
                model.max_seq_length,
            )
        if args.queries:
            queries = yaml.safe_load(Path(args.queries).read_text(encoding="utf-8"))
            results += check_neighbours(s, embedder, queries)

    failed = 0
    for name, ok, detail in results:
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:62s} {detail}")
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
