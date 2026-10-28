"""Check which knowledge-base entries the vignette CSVs rely on.

python -m scripts.vignette_coverage /evaluation/vignettes/set_a.csv [more.csv ...]

ACTIVE slugs come from the database. Prints how many vignettes rely on each ACTIVE clinical
entry, then a table "file slug -> current ACTIVE slug", and flags any vignette slug that is
retired or unknown. Exit 1 if any slug is flagged.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from scripts.kb_probe import base_slug

SLUG_SEPARATOR = ";"

OK, SUCCESSOR, RETIRED, UNKNOWN = "ok", "successor", "RETIRED", "UNKNOWN"


def vignette_slugs(paths: list[Path]) -> tuple[int, Counter[str]]:
    """(vignette count, how many vignettes name each slug) across all the files."""
    count = 0
    named: Counter[str] = Counter()
    for path in paths:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                count += 1
                raw = row.get("relevant_entry_slugs") or ""
                named.update({p.strip() for p in raw.split(SLUG_SEPARATOR) if p.strip()})
    return count, named


def resolve(slug: str, active: list[str], stored: set[str]) -> tuple[str, str | None]:
    """(status, current ACTIVE slug) for one slug written in a vignette file."""
    if slug in active:
        return OK, slug
    successor = next((a for a in active if base_slug(a) == base_slug(slug)), None)
    if successor is not None:
        return SUCCESSOR, successor
    return (RETIRED if slug in stored else UNKNOWN), None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_files", nargs="+", type=Path)
    args = parser.parse_args()

    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.enums import KBEntryKind, KBEntryStatus
    from app.models.knowledge_base import KBEntry

    with SessionLocal() as s:
        active = sorted(
            s.scalars(
                select(KBEntry.slug).where(
                    KBEntry.status == KBEntryStatus.ACTIVE,
                    KBEntry.kind == KBEntryKind.COMPLAINT,
                )
            )
        )
        stored = set(s.scalars(select(KBEntry.slug).where(KBEntry.slug.is_not(None))))

    total, named = vignette_slugs(args.csv_files)
    print(f"{total} vignettes in {len(args.csv_files)} file(s); {len(active)} ACTIVE entries\n")

    covered = Counter(
        {a: sum(n for f, n in named.items() if base_slug(f) == base_slug(a)) for a in active}
    )
    for slug in active:
        print(f"{covered[slug]:3d}  {slug}")
    uncovered = [slug for slug in active if covered[slug] == 0]
    print(f"\nACTIVE entries no vignette relies on: {', '.join(uncovered) or 'none'}")

    print("\nfile slug -> current ACTIVE slug")
    flagged = 0
    for slug in sorted(named):
        status, current = resolve(slug, active, stored)
        flagged += status in (RETIRED, UNKNOWN)
        print(f"  {slug} -> {current or '-'}   [{status}]")
    print(f"\nflagged (retired or unknown): {flagged}")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
