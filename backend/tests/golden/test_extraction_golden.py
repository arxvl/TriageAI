"""Golden tests for LLMEntityExtractor (M3 Step 5). Calls the REAL model: marked
@pytest.mark.llm and excluded by default (pyproject.toml: addopts = "-m 'not llm'").

    docker compose exec backend pytest -m llm tests/golden -q -s

A run is OK when ALL of its expectations hold (primary complaint, expected negated phrases,
red-flag presence). A case passes when at least 2 of its 3 runs are OK. The suite passes when
at least 90% of the cases pass. Provider errors (quota, timeout) are reported separately from
accuracy so a rate limit cannot masquerade as a bad prompt.

Costs real quota: 10 cases x 3 runs = 30 calls, plus 3 for the vague-case test.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.enums import Species
from app.models.knowledge_base import PresentingComplaint
from app.pipeline.deidentify_rules import RuleBasedDeidentifier
from app.pipeline.errors import ExtractionFailed, LLMTimeout, LLMUnavailable
from app.pipeline.extraction_llm import LLMEntityExtractor
from app.pipeline.registry import PipelineDeps
from scripts._llm import provider_from_settings

CASES_PATH = Path(__file__).parent / "extraction_cases.yaml"
RUNS_PER_CASE = 3
PASS_THRESHOLD = 2  # OK runs needed, out of RUNS_PER_CASE
VAGUE_CASE_ID = "S05"  # the id of your vague case in extraction_cases.yaml
PROVIDER_ERRORS = (ExtractionFailed, LLMTimeout, LLMUnavailable)


def load_cases() -> list[dict]:
    cases = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    for c in cases:
        if str(c.get("text", "")).strip().upper().startswith("TODO"):
            pytest.skip(f"{CASES_PATH.name} still has a TODO entry ({c.get('id')}). Fill it in.")
    return cases


def check_run(case: dict, out) -> list[str]:
    """Return the problems found in one extraction (an empty list means the run is OK)."""
    problems = []
    primary = next((c.code for c in out.presenting_complaints if c.is_primary), None)
    if primary != case["expected_primary"]:
        problems.append(f"primary {primary!r}, expected {case['expected_primary']!r}")
    negated = " ".join(out.negated_findings).lower()
    for phrase in case.get("expected_negated", []):
        if phrase.lower() not in negated:
            problems.append(f"{phrase!r} not in negated_findings {out.negated_findings!r}")
    if bool(out.red_flags) != bool(case["expected_red_flag"]):
        wanted = "some" if case["expected_red_flag"] else "none"
        problems.append(f"red_flags {out.red_flags!r}, expected {wanted}")
    return problems


def evaluate_case(case: dict, run_once) -> tuple[bool, int, int, list[str]]:
    """Run one case RUNS_PER_CASE times. Returns (passed, ok_runs, errored_runs, notes)."""
    ok_runs = errored = 0
    notes: list[str] = []
    for i in range(1, RUNS_PER_CASE + 1):
        try:
            out = run_once()
        except PROVIDER_ERRORS as exc:
            errored += 1
            notes.append(f"run {i}: {type(exc).__name__}")
            continue
        problems = check_run(case, out)
        ok_runs += 0 if problems else 1
        notes.extend(f"run {i}: {p}" for p in problems)
    return ok_runs >= PASS_THRESHOLD, ok_runs, errored, notes


@pytest.fixture(scope="module")
def extractor():
    settings = get_settings()
    # The extractor only reads timeout_s and max_retries from deps.config, so a small
    # stand-in is enough and does not depend on how PipelineConfig is constructed.
    config = SimpleNamespace(
        timeout_s=settings.pipeline_timeout_s,
        max_retries=settings.pipeline_max_retries,
    )
    deps = PipelineDeps(
        config=config,
        session_factory=SessionLocal,
        llm=provider_from_settings(settings),
        embedder=None,
        rules_provider=lambda: [],
    )
    return LLMEntityExtractor.from_settings(settings, deps)


@pytest.fixture(scope="module")
def deidentifier():
    return RuleBasedDeidentifier()


@pytest.mark.llm
def test_extraction_golden(extractor, deidentifier):
    cases = load_cases()
    lines, passed_cases, total_errors = [], 0, 0
    for case in cases:
        text = deidentifier.deidentify(case["text"].strip(), owner_name=None, owner_contact=None)
        run_once = partial(extractor.extract, text, Species[case["species"]])
        passed, ok_runs, errored, notes = evaluate_case(case, run_once)
        passed_cases += passed
        total_errors += errored
        lines.append(f"{case['id']}: {'PASS' if passed else 'FAIL'} ({ok_runs}/{RUNS_PER_CASE} ok)")
        lines.extend(f"    {n}" for n in notes)

    required = (9 * len(cases) + 9) // 10  # 90%, rounded up: 9 of 10
    calls = len(cases) * RUNS_PER_CASE
    report = "\n".join([f"{passed_cases}/{len(cases)} cases passed (need {required})", *lines])
    print("\n" + report)

    if total_errors > calls / 2:
        pytest.fail(
            f"{total_errors}/{calls} calls failed (quota, network or provider). "
            f"This is not an accuracy result.\n{report}"
        )
    assert passed_cases >= required, report


@pytest.mark.llm
def test_complaint_codes_are_valid():
    """Every expected_primary in the YAML must exist in the database (catches typos)."""
    with SessionLocal() as s:
        valid = {c.code for c in s.scalars(select(PresentingComplaint))}
    for case in load_cases():
        code = case["expected_primary"]
        assert code in valid, f"{case['id']}: unknown complaint code {code!r}"


@pytest.mark.llm
def test_vague_case_lists_missing_information(extractor, deidentifier):
    case = next((c for c in load_cases() if c["id"] == VAGUE_CASE_ID), None)
    if case is None:
        pytest.skip(f"No case {VAGUE_CASE_ID} in {CASES_PATH.name}; set VAGUE_CASE_ID.")
    text = deidentifier.deidentify(case["text"].strip(), owner_name=None, owner_contact=None)
    species = Species[case["species"]]
    hits = 0
    for _ in range(RUNS_PER_CASE):
        try:
            hits += 1 if extractor.extract(text, species).missing_information else 0
        except PROVIDER_ERRORS:
            continue
    assert hits >= PASS_THRESHOLD, "a vague case should list what staff still need to ask"


@pytest.mark.llm
def test_negation_case(extractor, deidentifier):
    case = next(c for c in load_cases() if c["id"] == "S04")
    species = Species[case["species"]]
    clean = deidentifier.deidentify(case["text"].strip(), owner_name=None, owner_contact=None)
    out = extractor.extract(clean, species)
    negated = " ".join(out.negated_findings).lower()
    signs = " ".join(out.associated_signs).lower()
    for phrase in case["expected_negated"]:
        assert phrase.lower() in negated, (
            f"{phrase!r} missing from negated_findings: {out.negated_findings!r}"
        )
        assert phrase.lower() not in signs, f"{phrase!r} wrongly listed as an associated sign"
