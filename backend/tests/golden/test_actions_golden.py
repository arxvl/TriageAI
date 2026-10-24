"""Golden tests for LLMActionSuggester (M6b Step 4). Calls the REAL model: marked
@pytest.mark.llm and excluded by default (pyproject.toml: addopts = "-m 'not llm'").

    docker compose exec backend pytest -m llm tests/golden/test_actions_golden.py -q -s

Follows the same shape as test_extraction_golden.py: stages are chained directly in
memory (de-identify -> extract -> retrieve -> suggest -> validate), with no Case or
Recommendation rows created and no job queue involved. The urgency category each case
is tested against comes straight from actions_golden_cases.yaml's expected_category,
not from running the real generator and safety validator -- that correctness is
already covered by test_generation_golden.py. This test is only about the actions
stage: given a genuine extraction and genuine retrieved passages for a known
category, are the suggested actions safe, cited, and worth showing?

validate() from action_validator.py (P05b) is called here too, exactly as the
orchestrator calls it in production, so "kept" actions in this test are the same
ones that would reach the UI -- this test is not only checking suggest() in
isolation.

A run is OK when validate() rejects nothing unsafe and leaves at least one action
for the run. A case passes when at least 2 of its 3 runs are OK (same threshold as
extraction). The suite passes when every case passes, and separately, no RED or
ORANGE case may come back empty in every single run (NFR-30, FR-71).

Costs real quota: up to 5 cases x 3 runs x 2 calls (extract, suggest) = 30 calls.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from sqlalchemy import text as sql_text

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.enums import Species, VTLCategory
from app.pipeline.action_validator import validate as validate_actions
from app.pipeline.actions_llm import LLMActionSuggester
from app.pipeline.deidentify_rules import RuleBasedDeidentifier
from app.pipeline.errors import (
    ActionsFailed,
    ExtractionFailed,
    LLMTimeout,
    LLMUnavailable,
    RetrievalFailed,
)
from app.pipeline.extraction_llm import LLMEntityExtractor
from app.pipeline.registry import PipelineDeps
from app.pipeline.retrieval_pgvector import PgVectorRetriever
from scripts._llm import provider_from_settings

CASES_PATH = Path(__file__).parent / "actions_golden_cases.yaml"
RUNS_PER_CASE = 3
PASS_THRESHOLD = 2  # OK runs needed, out of RUNS_PER_CASE -- same as extraction
PROVIDER_ERRORS = (ActionsFailed, ExtractionFailed, RetrievalFailed, LLMTimeout, LLMUnavailable)

# Defence-in-depth re-check only (never the source of truth -- that is action_validator.py).
# Deliberately does not import private names from that module, so this test cannot drift
# out of sync with however you named your internal regex or constants there.
_DOSE_HINT = re.compile(r"\b\d+(\.\d+)?\s?(mg|mcg|ml|iu|cc)\b|q\d+h|\b(iv|im|sc|sq|po)\b", re.I)


def load_cases() -> list[dict]:
    cases = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    for c in cases:
        if (
            str(c.get("text", "")).strip().upper().startswith("TODO")
            or str(c.get("species", "")).strip() == "TODO"
        ):
            pytest.skip(f"{CASES_PATH.name} still has a TODO entry ({c.get('id')}). Fill it in.")
    return cases


# ------------------------------------------------------------------ fixtures
# Same minimal-stand-in pattern as test_extraction_golden.py's `extractor` fixture:
# a SimpleNamespace for config, since every real stage only reads timeout_s and
# max_retries off it, and a PipelineDeps with embedder populated this time, since
# retrieval needs one.


@pytest.fixture(scope="module")
def deps():
    settings = get_settings()
    from app.adapters.embeddings.sentence_transformer import SentenceTransformerEmbedder

    config = SimpleNamespace(
        timeout_s=settings.pipeline_timeout_s,
        max_retries=settings.pipeline_max_retries,
    )
    return PipelineDeps(
        config=config,
        session_factory=SessionLocal,
        llm=provider_from_settings(settings),
        embedder=SentenceTransformerEmbedder.from_settings(settings),
        rules_provider=lambda: [],
    )


@pytest.fixture(scope="module")
def deidentifier():
    return RuleBasedDeidentifier()


@pytest.fixture(scope="module")
def extractor(deps):
    return LLMEntityExtractor.from_settings(get_settings(), deps)


@pytest.fixture(scope="module")
def retriever(deps):
    return PgVectorRetriever.from_settings(get_settings(), deps)


@pytest.fixture(scope="module")
def suggester(deps):
    return LLMActionSuggester.from_settings(get_settings(), deps)


@pytest.fixture(scope="module")
def kb_version_id():
    with SessionLocal() as s:
        row = s.execute(
            sql_text("select id from kb_versions order by version_no desc limit 1")
        ).first()
    if row is None:
        pytest.skip(
            "No published KB version found -- publish one (M5 Part C/D) before running this."
        )
    return row[0]


# ------------------------------------------------------------------ one run of one case
def run_once(case, deidentifier, extractor, retriever, suggester, kb_version_id):
    """Chains the real stages for one case and returns (raw_actions, kept, rejection_reasons).
    `kept` is what validate() would actually let reach the UI -- the same function the
    orchestrator calls in production (P05b, subphase 5b.3)."""
    settings = get_settings()
    species = Species[case["species"]]
    clean = deidentifier.deidentify(case["text"].strip(), owner_name=None, owner_contact=None)
    extraction = extractor.extract(clean, species)
    passages = retriever.retrieve(extraction, kb_version_id, 5)
    try:
        category = VTLCategory[case["expected_category"]]
    except KeyError:
        valid = [c.name for c in VTLCategory]
        pytest.fail(
            f"{case['id']}: expected_category {case['expected_category']!r} in "
            f"{CASES_PATH.name} is not a valid VTLCategory member. Valid values: {valid}. "
            f"Common mistake: writing the display label (e.g. 'Standard', 'Urgent') "
            f"instead of the enum name (e.g. 'GREEN', 'YELLOW')."
        )
    raw_actions = suggester.suggest(extraction, category, passages, settings.actions_max_items)
    kept, rejection_reasons = validate_actions(raw_actions, passages, settings.actions_max_items)
    return raw_actions, kept, rejection_reasons


def check_run(kept) -> list[str]:
    """Problems in what validate() decided to keep. An empty list means the run is OK.
    A validator that is working should never let any of these through -- if this test
    ever finds one, that is a bug in action_validator.py, not in this test."""
    problems = []
    for a in kept:
        if _DOSE_HINT.search(a.text):
            problems.append(f"UNSAFE CONTENT SURVIVED VALIDATION: {a.text!r}")
        if not a.cited_ranks:
            problems.append(f"validator kept an action with no citation: {a.text!r}")
    return problems


def evaluate_case(case, deidentifier, extractor, retriever, suggester, kb_version_id):
    """Run one case RUNS_PER_CASE times.
    Returns (passed, ok_runs, errored_runs, any_run_had_kept_actions, raw_total, kept_total, notes).
    """
    ok_runs = errored = 0
    any_kept = False
    raw_total = kept_total = 0
    notes: list[str] = []
    for i in range(1, RUNS_PER_CASE + 1):
        try:
            raw_actions, kept, rejection_reasons = run_once(
                case, deidentifier, extractor, retriever, suggester, kb_version_id
            )
        except PROVIDER_ERRORS as exc:
            errored += 1
            notes.append(f"run {i}: {type(exc).__name__}")
            continue
        problems = check_run(kept)
        raw_total += len(raw_actions)
        kept_total += len(kept)
        any_kept = any_kept or bool(kept)
        ok_runs += 0 if problems else 1
        notes.extend(f"run {i}: {p}" for p in problems)
        notes.append(
            f"run {i}: {len(raw_actions)} suggested, {len(kept)} kept"
            + (f", rejected: {rejection_reasons}" if rejection_reasons else "")
        )
    return ok_runs >= PASS_THRESHOLD, ok_runs, errored, any_kept, raw_total, kept_total, notes


# ------------------------------------------------------------------ the tests
@pytest.mark.llm
def test_actions_golden(deidentifier, extractor, retriever, suggester, kb_version_id):
    cases = load_cases()
    lines, passed_cases, total_errors = [], 0, 0
    raw_all = kept_all = 0
    red_orange_always_empty = []

    for case in cases:
        passed, ok_runs, errored, any_kept, raw_total, kept_total, notes = evaluate_case(
            case, deidentifier, extractor, retriever, suggester, kb_version_id
        )
        passed_cases += passed
        total_errors += errored
        raw_all += raw_total
        kept_all += kept_total
        if case["expected_category"] in ("RED", "ORANGE") and not any_kept:
            red_orange_always_empty.append(case["id"])
        lines.append(
            f"{case['id']} ({case['expected_category']}): {'PASS' if passed else 'FAIL'} "
            f"({ok_runs}/{RUNS_PER_CASE} ok)"
        )
        lines.extend(f"    {n}" for n in notes)

    calls = len(cases) * RUNS_PER_CASE
    rejection_rate = 0.0 if raw_all == 0 else (raw_all - kept_all) / raw_all
    report = "\n".join(
        [
            f"{passed_cases}/{len(cases)} cases passed",
            f"rejection rate across all runs: {rejection_rate:.0%} (target: <= 20%)",
            *lines,
        ]
    )
    print("\n" + report)

    if total_errors > calls / 2:
        pytest.fail(
            f"{total_errors}/{calls} calls failed (quota, network or provider). "
            f"This is not an accuracy result.\n{report}"
        )
    assert not red_orange_always_empty, (
        f"RED/ORANGE case(s) with zero kept actions in every run: {red_orange_always_empty}. "
        f"Baseline actions still cover these (FR-71), but tailored suggestions are not "
        f"adding anything for them.\n{report}"
    )
    assert passed_cases == len(cases), report


@pytest.mark.llm
def test_citations_always_point_at_a_real_passage(
    deidentifier, extractor, retriever, suggester, kb_version_id
):
    """One extra run per case, checking that every kept citation rank is actually in
    range for the passages that were retrieved -- a cheap, sharp check on top of the
    broader test above."""
    for case in load_cases():
        try:
            _raw, kept, _rejected = run_once(
                case, deidentifier, extractor, retriever, suggester, kb_version_id
            )
        except PROVIDER_ERRORS as exc:
            pytest.skip(f"{case['id']}: provider error on this extra check ({type(exc).__name__})")
            continue
        species = Species[case["species"]]
        clean = deidentifier.deidentify(case["text"].strip(), owner_name=None, owner_contact=None)
        extraction = extractor.extract(clean, species)
        passages = retriever.retrieve(extraction, kb_version_id, 5)
        valid_ranks = {p.rank for p in passages}
        for a in kept:
            assert set(a.cited_ranks) <= valid_ranks, (
                f"{case['id']}: kept action cites rank(s) outside {valid_ranks}: {a.cited_ranks} "
                f"(action: {a.text!r})"
            )
