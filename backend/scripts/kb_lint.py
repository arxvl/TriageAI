"""Content lint for knowledge_base/entries/*.yaml. Run it BEFORE import_kb.

    python -m scripts.kb_lint                      # every entry
    python -m scripts.kb_lint seizures-dog-cat     # one entry (slug or filename)

Errors block the import. Warnings need a human decision. It checks the mechanical rules only;
whether the content is accurate and in your own words is still a person's job.
"""

from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

import yaml

ENTRIES = Path("/knowledge_base/entries")
SPECIES = {"DOG", "CAT"}
SUFFIX = {("DOG",): "dog", ("CAT",): "cat", ("CAT", "DOG"): "dog-cat"}
DOSE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:mg|mcg|µg|ml|mL|cc|IU)\b|\b(?:mg|ml)/kg\b|\b(?:IV|IM|SC|SQ|PO)\b"
)
DRUGS = re.compile(
    r"\b(?:butorphanol|acepromazine|dexmedetomidine|propofol|alfaxalone|ketamine|diazepam|midazolam|"
    r"methocarbamol|levetiracetam|phenobarbital|furosemide|terbutaline|albuterol|dexamethasone|mannitol|"
    r"dextrose|antibiotics?|steroids?|sedatives?|analgesics?|NSAIDs?)\b",
    re.I,
)
ABBREV = re.compile(r"\b(?:e\.g|i\.e|vs|approx|etc)\.\s+[A-Z]")  # the chunker would split here
CATEGORY = re.compile(r"\b(?:Red|Orange|Yellow|Green|Blue)\b")
PLACEHOLDER = re.compile(r"TODO|\[\[|XXX|PLACEHOLDER")

CATEGORIES = ("RED", "ORANGE", "YELLOW", "GREEN", "BLUE")


def lint_actions(path: Path, d: dict, raw: str) -> tuple[list[str], list[str]]:
    """URGENCY_ACTIONS entries: one action per line.

    Staff see this text verbatim, so it must be clean.
    """
    err: list[str] = []
    warn: list[str] = []
    cat = d.get("urgency_category")
    for k in ("slug", "title", "urgency_category", "species", "content", "source"):
        if not d.get(k):
            err.append(f"missing or empty: {k}")
    src = d.get("source") or {}
    for k in ("title", "publisher", "url", "access_date"):
        if not src.get(k):
            err.append(f"missing source.{k}")
    if PLACEHOLDER.search(raw):
        err.append("a TODO or placeholder is still in the file")
    if cat and cat not in CATEGORIES:
        err.append(f"urgency_category must be one of {', '.join(CATEGORIES)}")
    if d.get("complaint_code"):
        err.append("an URGENCY_ACTIONS entry must not set complaint_code")
    slug = str(d.get("slug") or "")
    if slug and slug != path.stem:
        err.append(f"slug '{slug}' must equal the file name '{path.stem}'")
    if cat in CATEGORIES and slug != f"actions-{cat.lower()}":
        err.append(f"slug should be 'actions-{cat.lower()}'")
    species = d.get("species") or []
    if not isinstance(species, list) or not species or not set(species) <= SPECIES:
        err.append(f"species must be a list drawn from {sorted(SPECIES)}, written in capitals")
    if src.get("url") and not str(src["url"]).startswith("https://"):
        err.append("source.url must start with https://")
    ad = src.get("access_date")
    if ad and (not isinstance(ad, datetime.date) or ad > datetime.date.today()):
        err.append("source.access_date must be a real date no later than today (YYYY-MM-DD)")

    content = str(d.get("content") or "")
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if content and len(content.split()) < 50:
        err.append(f"content is {len(content.split())} words; the importer expects at least 50")
    if lines and not 3 <= len(lines) <= 6:
        warn.append(f"{len(lines)} actions; the guide asks for 3 to 6, one per line")
    for ln in lines:
        if DOSE.search(ln):
            err.append(f"dose or route expression in an action: {DOSE.search(ln).group(0)!r}")
        if DRUGS.search(ln):
            err.append(f"medication term in an action: {DRUGS.search(ln).group(0)!r}")
        if len(ln.split()) > 25:
            err.append(f"action over 25 words (the action validator rejects it): {ln[:40]!r}...")
        elif len(ln.split()) > 20:
            warn.append(f"action over 20 words: {ln[:40]!r}...")
    return err, warn


def lint(path: Path, codes: set[str], rules: set[str]) -> tuple[list[str], list[str]]:
    err: list[str] = []
    warn: list[str] = []
    raw = path.read_text(encoding="utf-8")
    try:
        d = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return [f"YAML does not parse: {str(exc).splitlines()[0]}"], []
    if not isinstance(d, dict):
        return ["the file is not a YAML mapping"], []

    for k in ("slug", "title", "complaint_code", "species", "content", "source"):
        if not d.get(k):
            err.append(f"missing or empty: {k}")
    src = d.get("source") or {}
    for k in ("title", "publisher", "url", "access_date"):
        if not src.get(k):
            err.append(f"missing source.{k}")
    if PLACEHOLDER.search(raw):
        err.append("a TODO or placeholder is still in the file")

    species = d.get("species") or []
    if not isinstance(species, list) or not species or not set(species) <= SPECIES:
        err.append(f"species must be a list drawn from {sorted(SPECIES)}, written in capitals")
    if d.get("kind") == "URGENCY_ACTIONS":
        return lint_actions(path, d, raw)
    slug = str(d.get("slug") or "")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        err.append("slug must be lower-case words joined by hyphens")
    if slug and slug != path.stem:
        err.append(f"slug '{slug}' must equal the file name '{path.stem}'")
    want = SUFFIX.get(tuple(sorted(species))) if isinstance(species, list) else None
    if want and not slug.endswith("-" + want):
        err.append(f"slug should end with '-{want}' to match species")
    if d.get("complaint_code") and d["complaint_code"] not in codes:
        err.append(f"complaint_code {d['complaint_code']} is not in presenting_complaints")
    for c in d.get("red_flag_codes") or []:
        if c not in rules:
            err.append(f"red_flag_codes: {c} is not a rule in red_flag_rules")

    if src.get("url") and not str(src["url"]).startswith("https://"):
        err.append("source.url must start with https://")
    ad = src.get("access_date")
    if ad and (not isinstance(ad, datetime.date) or ad > datetime.date.today()):
        err.append("source.access_date must be a real date no later than today (YYYY-MM-DD)")

    content = str(d.get("content") or "")
    words = len(content.split())
    if content and (words < 50 or words > 1500):
        err.append(f"content is {words} words; the importer accepts 50 to 1,500")
    elif content and not 150 <= words <= 400:
        warn.append(f"content is {words} words; the target is 150 to 400")
    if DOSE.search(content):
        err.append(f"dose or route expression: {DOSE.search(content).group(0)!r}")
    if DRUGS.search(content):
        err.append(f"medication term: {DRUGS.search(content).group(0)!r}")
    if ABBREV.search(content):
        warn.append(
            f"abbreviation before a capital splits a sentence: {ABBREV.search(content).group(0)!r}"
        )
    if not CATEGORY.search(content):
        warn.append(
            "never names a VTL category (Red, Orange, Yellow, Green, Blue); "
            "the generator needs that cue"
        )
    if len([p for p in re.split(r"\n\s*\n", content.strip()) if p.strip()]) < 3:
        warn.append("fewer than 3 paragraphs; use the four-part structure")
    for sent in re.split(r"(?<=[.!?])\s+", content):
        if len(sent.split()) > 45:
            warn.append(f"sentence of {len(sent.split())} words: {sent[:50]!r}...")
            break
    return err, warn


def main(argv: list[str]) -> int:
    from sqlalchemy import text

    from app.db.session import SessionLocal

    with SessionLocal() as s:
        codes = {r[0] for r in s.execute(text("select code from presenting_complaints"))}
        rules = {r[0] for r in s.execute(text("select code from red_flag_rules"))}
    files = sorted(ENTRIES.glob("*.yaml"))
    if argv:
        want = {a.removesuffix(".yaml") for a in argv}
        files = [f for f in files if f.stem in want]
    seen: dict[tuple, str] = {}
    bad = 0
    for f in files:
        err, warn = lint(f, codes, rules)
        d = yaml.safe_load(f.read_text(encoding="utf-8")) if not err else None
        if isinstance(d, dict) and d.get("complaint_code") and isinstance(d.get("species"), list):
            key = (d["complaint_code"], tuple(sorted(d["species"])))
            if key in seen:
                warn.append(f"same complaint and species as {seen[key]}: is this a duplicate?")
            seen[key] = f.stem
        status = "ERROR" if err else ("warn " if warn else "ok   ")
        print(f"{status} {f.stem}")
        for m in err:
            print(f"        error: {m}")
        for m in warn:
            print(f"        warn:  {m}")
        bad += bool(err)
    print(f"\n{len(files)} files, {bad} with errors")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
