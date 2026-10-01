"""The recorded answers the mock stages replay (P05 §5.2, ADR-17).

`tests/fixtures/demo_cases.yaml` holds four hand-written demo scenarios, each
with the red-flag hits, extraction, passages and draft a run over it should
produce. This module loads that file into the pipeline contracts and answers two
questions: *which fixture is this description?* and *which fixture produced this
extraction?*

**There is no NLP here and there must never be.** A description matches a fixture
when the two are equal after whitespace normalisation — `str.split()` and a
rejoin, nothing more. No stemming, no similarity, no phrase lists. Anything the
file does not hold exactly produces no match, and the stage falls back to its
generic answer. The real stages are written manually under M1–M6.

Two lookups, because the stages see different things. `MockRedFlagScreener` and
`MockEntityExtractor` are given the text, so they look up by description.
`MockRetriever` and `MockRecommendationGenerator` are given an `ExtractionOutput`
and never see the text (CLAUDE.md §8.2), and the contract carries no fixture id,
so they look up by exact equality against the extraction the file recorded. That
is the only deterministic link back, and a near-miss degrades to the generic
passages rather than to a wrong fixture.

`species` and `signalment` are not written in the YAML. They are filled from the
case's own `signalment` block, through the same coercion the generic extraction
uses, so the recorded extraction cannot drift from the case it belongs to.

The file lives under `tests/` because that is where P05 §5.2 puts it and where
the test suite already reads it. Application code reading it is deliberate: these
are fixtures in the strict sense — invented data for development (CLAUDE.md §9) —
and a deployment that ships without them simply gets no match and the generic
answers, rather than a failure to start.
"""

import logging
import os
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import MockLLMBehavior
from app.models.enums import Species
from app.pipeline.types import (
    DraftRecommendation,
    ExtractionOutput,
    Passage,
    RedFlagHit,
)

logger = logging.getLogger(__name__)

# backend/app/pipeline/mock_fixtures.py -> backend/
BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE_PATH = BACKEND_ROOT / "tests" / "fixtures" / "demo_cases.yaml"

# Overridable so a test can point at a smaller file, or at none.
FIXTURE_PATH_ENV = "MOCK_FIXTURES_PATH"


def fixture_path() -> Path:
    override = os.environ.get(FIXTURE_PATH_ENV)
    return Path(override) if override else DEFAULT_FIXTURE_PATH


def normalize(text: str) -> str:
    """The matching key: one space between words, nothing at the ends.

    Whitespace only. Case and punctuation are left alone, because P05 §5.2 fixes
    the rule as equality after whitespace normalisation and anything more would
    be the beginning of matching logic this module must not have.
    """
    return " ".join(text.split())


def mock_chunk_id(fixture_id: str, rank: int) -> uuid.UUID:
    """The `chunk_id` a mock passage carries (P05 §5.2).

    Derived, not random: a mock run has no `kb_chunks` rows to point at, and a
    stable id is what lets a test assert on a stored reference.
    """
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{fixture_id}{rank}")


def mock_entry_id(fixture_id: str, entry_title: str) -> uuid.UUID:
    """The `entry_id` a mock passage carries.

    Keyed by the entry title, so two passages quoted from the same placeholder
    entry share one id — the review screen groups citations by entry.
    """
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{fixture_id}:{entry_title}")


def coerce_signalment(signalment: dict | None) -> dict[str, str | None]:
    """Coerce a signalment dict to the `dict[str, str | None]` the contract uses.

    Ages and weights arrive as numbers from the database and from the fixture
    file; the extraction contract stores signalment as text because a real model
    reports it as the owner said it ("about 3 years"), not as a column value.
    """
    return {
        str(key): None if value is None else str(value) for key, value in (signalment or {}).items()
    }


@dataclass(frozen=True)
class MockFixture:
    """One demo scenario's recorded outputs.

    `extraction`, `passages` and `draft` are `None`/empty for a scenario that is
    meant to fail before it reaches that stage (DEMO_4).
    """

    fixture_id: str
    description: str  # whitespace-normalised
    species: Species
    red_flags: list[RedFlagHit]
    extraction: ExtractionOutput | None
    passages: list[Passage]
    draft: DraftRecommendation | None
    failure: MockLLMBehavior | None


def _build_extraction(case: dict[str, Any]) -> ExtractionOutput | None:
    recorded = case.get("mock_extraction")
    if recorded is None:
        return None
    return ExtractionOutput(
        species=Species(case["species"]),
        signalment=coerce_signalment(case.get("signalment")),
        **recorded,
    )


def _build_passages(case: dict[str, Any]) -> list[Passage]:
    fixture_id = case["id"]
    return [
        Passage(
            rank=rank,
            chunk_id=mock_chunk_id(fixture_id, rank),
            entry_id=mock_entry_id(fixture_id, recorded["entry_title"]),
            **recorded,
        )
        for rank, recorded in enumerate(case.get("mock_passages") or [], start=1)
    ]


def _build_fixture(case: dict[str, Any]) -> MockFixture:
    failure = case.get("mock_failure")
    draft = case.get("mock_draft")
    return MockFixture(
        fixture_id=case["id"],
        description=normalize(case["description"]),
        species=Species(case["species"]),
        red_flags=[RedFlagHit(**hit) for hit in case.get("mock_red_flags") or []],
        extraction=_build_extraction(case),
        passages=_build_passages(case),
        draft=None if draft is None else DraftRecommendation(**draft),
        failure=None if failure is None else MockLLMBehavior(failure),
    )


@lru_cache(maxsize=1)
def load_fixtures() -> dict[str, MockFixture]:
    """Every demo scenario, by fixture id. Parsed once per process.

    A missing file is not an error: the mocks then answer generically
    everywhere, which is the behaviour a deployment without `tests/` should have.
    A file that exists but does not parse *is* an error — a typo in a recorded
    red-flag code or category would otherwise surface as a silently wrong demo.
    """
    path = fixture_path()
    if not path.is_file():
        logger.warning("mock fixtures not found at %s; mock stages will answer generically", path)
        return {}

    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    fixtures = [_build_fixture(case) for case in document.get("cases") or []]
    return {fixture.fixture_id: fixture for fixture in fixtures}


def find_by_text(text: str) -> MockFixture | None:
    """The fixture whose description equals `text` after normalisation."""
    key = normalize(text)
    for fixture in load_fixtures().values():
        if fixture.description == key:
            return fixture
    return None


def find_by_extraction(extraction: ExtractionOutput) -> MockFixture | None:
    """The fixture that recorded exactly this extraction.

    Exact equality, so an extraction a stage modified on the way through no
    longer matches and the caller falls back to its generic answer. That is the
    safe direction: a half-matching fixture would attach passages to an
    extraction they do not support.
    """
    for fixture in load_fixtures().values():
        if fixture.extraction is not None and fixture.extraction == extraction:
            return fixture
    return None
