"""Deterministic stand-ins for every AI stage (CLAUDE.md §8, ADR-17).

These exist so the whole application — intake, queue, review, decisions, audit,
evaluation — runs end to end before any AI component is written, and so the test
suite and CI need no API key, no model download and no network (ADR-17).

**There is no NLP here and there must never be.** A mock either replays a
recorded fixture from `tests/fixtures/demo_cases.yaml` or returns a fixed generic
answer. Matching is string equality after whitespace normalisation, not
similarity; it lives in `app.pipeline.mock_fixtures`. The real stages are written
manually under M1–M6.

Three things the mocks have to get right, because the orchestrator and the safety
validator are built against them:

**The demo scenarios.** `DEMO_1` replays a YELLOW draft together with a
`MALE_CAT_NO_URINE` hit at ORANGE, so the deterministic validator visibly raises
the category and FR-23 can be demonstrated on screen. `DEMO_2` replays RED,
`DEMO_3` BLUE.

**The failure paths.** `MOCK_LLM_BEHAVIOR` turns the two model stages into a
timeout, an unusable answer, a one-off flake or a slow answer, so the retry and
failure-path logic in P05 §5.4 is exercised with no network call. A fixture may
also force a failure for one scenario alone — `DEMO_4` does, which is how the
walkthrough reaches `MANUAL_TRIAGE_REQUIRED` without editing `.env`.

**Provenance.** A mock reports `model_id="mock"` and `prompt_version="mock-0"`
rather than omitting them, so the provenance columns are filled the same way on a
mock run and a real one and nothing downstream branches (FR-26, NFR-23, ADR-14).
The evaluation screen tells the two apart by those values, which is why a
mock-mode run is labelled rather than silently reported as a result.
"""

import hashlib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter, sleep
from typing import TYPE_CHECKING

from app.core.config import MOCK_SLOW_DELAY_S, MockLLMBehavior, Settings
from app.models.enums import ConfidenceLevel, Species, VTLCategory
from app.pipeline.config import PipelineConfig
from app.pipeline.errors import LLMInvalidOutput, LLMTimeout
from app.pipeline.mock_fixtures import (
    coerce_signalment,
    find_by_extraction,
    find_by_text,
    mock_chunk_id,
    mock_entry_id,
    normalize,
)
from app.pipeline.types import (
    DraftRecommendation,
    ExtractedComplaint,
    ExtractionOutput,
    Passage,
    RedFlagHit,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.pipeline.registry import PipelineDeps

__all__ = [
    "GENERIC_MISSING_INFORMATION",
    "GENERIC_PASSAGE_SCORE",
    "MOCK_MODEL_ID",
    "MOCK_PROMPT_VERSION",
    "OTHER_COMPLAINT",
    "MockDeidentifier",
    "MockEntityExtractor",
    "MockKBIndexer",
    "MockRecommendationGenerator",
    "MockRedFlagScreener",
    "MockRetriever",
    "generic_draft",
    "generic_extraction",
    "generic_passages",
    "mock_chunk_id",
    "mock_entry_id",
]

MOCK_MODEL_ID = "mock"
MOCK_PROMPT_VERSION = "mock-0"

# The complaint code for anything outside the supported set. A primary `OTHER`
# is what makes the safety validator recommend manual triage (P05 §5.3 rule 4).
OTHER_COMPLAINT = "OTHER"

# What a generic extraction admits it does not know. Fixed wording, because the
# review screen's "missing information" list is asserted on in tests and shown in
# the PD8 walkthrough (P05 §5.2).
GENERIC_MISSING_INFORMATION = ["duration", "appetite", "water intake"]

GENERIC_FIXTURE_ID = "GENERIC"
GENERIC_PASSAGE_COUNT = 2
GENERIC_PASSAGE_SCORE = 0.20


class _MockStage:
    """Shared provenance, timing and failure simulation (CLAUDE.md §8.2).

    Not a stage. It holds the three attributes the orchestrator reads off every
    stage, so each mock below is only its own `from_settings` and its one method.
    """

    model_id: str = MOCK_MODEL_ID
    prompt_version: str = MOCK_PROMPT_VERSION

    def __init__(self, config: PipelineConfig, behavior: MockLLMBehavior) -> None:
        self.config = config
        self.behavior = behavior
        self.last_latency_ms = 0
        # Attempt counts, so `flaky` can fail the first attempt at a given call
        # and succeed on the retry. Keyed and counted only under `flaky`; see
        # `_simulate`.
        self._attempts: dict[str, int] = {}

    @classmethod
    def from_settings(cls, settings: Settings, deps: "PipelineDeps") -> "_MockStage":
        return cls(config=deps.config, behavior=settings.mock_llm_behavior)

    @contextmanager
    def _measured(self) -> Iterator[None]:
        """Record the wall time of one call in `last_latency_ms`.

        Measured even on the failure paths — a timed-out attempt still took time,
        and the orchestrator stores what the stage reports.
        """
        started = perf_counter()
        try:
            yield
        finally:
            self.last_latency_ms = int((perf_counter() - started) * 1000)

    def _simulate(self, key: str, behavior: MockLLMBehavior | None = None) -> None:
        """Apply `MOCK_LLM_BEHAVIOR` before the stage answers (P05 §5.2).

        `behavior` overrides the configured one, which is how a fixture forces a
        failure for one scenario alone.

        `key` identifies the call, not the caller: `flaky` must fail the first
        attempt at *each* case and succeed on its retry. Counting per stage
        instance would not do — the registry builds each stage once at startup
        and shares it, so only the first case the process ever saw would flake.
        The key is a digest, never the text itself, so no owner description is
        retained here (CLAUDE.md §9).

        Messages name the simulated behaviour and nothing else: they end up in
        the job's `last_error` and in the log.
        """
        behavior = behavior or self.behavior

        if behavior is MockLLMBehavior.TIMEOUT:
            raise LLMTimeout(f"mock stage simulating a timeout (MOCK_LLM_BEHAVIOR={behavior})")

        if behavior is MockLLMBehavior.INVALID_JSON:
            raise LLMInvalidOutput(
                f"mock stage simulating unusable output (MOCK_LLM_BEHAVIOR={behavior})"
            )

        if behavior is MockLLMBehavior.FLAKY:
            attempt = self._attempts[key] = self._attempts.get(key, 0) + 1
            if attempt == 1:
                raise LLMInvalidOutput(
                    f"mock stage simulating a first-attempt failure "
                    f"(MOCK_LLM_BEHAVIOR={behavior}); the retry succeeds"
                )

        if behavior is MockLLMBehavior.SLOW:
            sleep(min(MOCK_SLOW_DELAY_S, self.config.timeout_s))

    def reset_attempts(self) -> None:
        """Forget the `flaky` attempt counts. For tests, and for a worker restart."""
        self._attempts.clear()


def _call_key(value: str) -> str:
    """A stable, non-reversible key for one call's input.

    Hashed rather than kept: the extractor's input is the owner's description,
    and nothing outside the de-identifier should hold on to it (CLAUDE.md §9).
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class MockDeidentifier(_MockStage):
    """Returns the text **unchanged**. It removes nothing.

    This is a placeholder, not a de-identifier. The real one is written manually
    in M1 as `app.pipeline.deidentify_rules:RuleBasedDeidentifier`.

    Because it removes nothing, the registry refuses to start a non-mock
    `LLM_PROVIDER` while this stage is selected: raw text must never leave the
    server (IR-20, ADR-10).
    """

    def deidentify(self, text: str, owner_name: str | None, owner_contact: str | None) -> str:
        with self._measured():
            return text


class MockRedFlagScreener(_MockStage):
    """Replays a fixture's recorded hits; no phrase matching (M1 writes the real one).

    It does not honour `MOCK_LLM_BEHAVIOR`. Screening is not a model call, and an
    alert has to reach the queue within about two seconds even when the model
    path is failing (NFR-05, FR-12) — making this stage fail with the others
    would hide exactly the behaviour P05 §5.4 has to prove.
    """

    def screen(self, text: str, species: Species, sex: str | None) -> list[RedFlagHit]:
        with self._measured():
            fixture = find_by_text(text)
            return list(fixture.red_flags) if fixture is not None else []


class MockEntityExtractor(_MockStage):
    """Replays a fixture's recorded extraction (M3 writes the real one).

    A fixture's own `mock_failure` takes precedence over `MOCK_LLM_BEHAVIOR`, so
    `DEMO_4` fails on every run and the other scenarios still succeed. That is
    what lets the walkthrough show the failure path (FR-15, NFR-09) beside three
    working cases, in one pass, with no configuration change.
    """

    def extract(
        self, text: str, species: Species, signalment: dict | None = None
    ) -> ExtractionOutput:
        with self._measured():
            fixture = find_by_text(text)
            self._simulate(
                key=_call_key(normalize(text)),
                behavior=fixture.failure if fixture is not None else None,
            )
            if fixture is not None and fixture.extraction is not None:
                return fixture.extraction
            return generic_extraction(species, signalment)


class MockRetriever(_MockStage):
    """Replays a fixture's recorded passages; no vector search (M6 writes the real one).

    The stage is handed an `ExtractionOutput` and never the description
    (CLAUDE.md §8.2), so the fixture is found by exact equality against the
    extraction the file recorded. It does not honour `MOCK_LLM_BEHAVIOR`:
    retrieval is a database query in the real stage, not a model call.
    """

    def retrieve(
        self, extraction: ExtractionOutput, kb_version_id: uuid.UUID, k: int
    ) -> list[Passage]:
        with self._measured():
            fixture = find_by_extraction(extraction)
            if fixture is not None and fixture.passages:
                return list(fixture.passages[:k])
            return generic_passages(k)


class MockRecommendationGenerator(_MockStage):
    """Replays a fixture's recorded draft (M6 writes the real one).

    Found by the same reverse lookup as the retriever. The draft is a *draft*:
    `DEMO_1`'s is YELLOW on purpose, and the safety validator is what turns it
    into the ORANGE a reviewer sees (FR-23, ADR-09).
    """

    def generate(
        self, extraction: ExtractionOutput, passages: list[Passage]
    ) -> DraftRecommendation:
        with self._measured():
            fixture = find_by_extraction(extraction)
            self._simulate(
                key=fixture.fixture_id
                if fixture is not None
                else _call_key(extraction.model_dump_json())
            )
            if fixture is not None and fixture.draft is not None:
                return fixture.draft
            return generic_draft()


class MockKBIndexer(_MockStage):
    """Indexes nothing and reports nothing indexed.

    The knowledge-base approval workflow (P08) calls this so the approval itself
    can be built and tested before chunking and embedding exist. The real indexer
    is written manually in M5 as `app.kb.indexer_pgvector:PgVectorKBIndexer`.
    """

    def index_entry(self, entry_id: uuid.UUID) -> int:
        with self._measured():
            return 0

    def remove_entry(self, entry_id: uuid.UUID) -> None:
        with self._measured():
            return None


# --- The "no fixture match" answers (P05 §5.2) ----------------------------
#
# Module-level functions rather than methods: the orchestrator tests and the
# subphase 5.3 validator tests both need these exact shapes, and neither should
# have to build a stage to get one.


def generic_extraction(species: Species, signalment: dict | None = None) -> ExtractionOutput:
    """What the extractor returns for a description no fixture matches.

    A primary complaint of `OTHER` and nothing else claimed. That is the honest
    answer from a mock, and it drives the case toward manual triage rather than
    toward a fabricated category (P05 §5.3 rule 4).
    """
    return ExtractionOutput(
        species=species,
        signalment=coerce_signalment(signalment),
        presenting_complaints=[ExtractedComplaint(code=OTHER_COMPLAINT, is_primary=True)],
        onset_duration=None,
        frequency_severity=None,
        associated_signs=[],
        negated_findings=[],
        exposure_history=None,
        relevant_history=None,
        red_flags=[],
        missing_information=list(GENERIC_MISSING_INFORMATION),
        evidence_spans=[],
    )


def generic_passages(k: int) -> list[Passage]:
    """Two placeholder passages, scored below `retrieval_min_score`.

    0.20 is deliberately under the 0.30 floor: a description no fixture matches
    has no real supporting evidence, so the validator must record
    `LOW_RETRIEVAL_SCORE` and cap confidence (P05 §5.3 rule 3).
    """
    count = min(GENERIC_PASSAGE_COUNT, k)
    return [
        Passage(
            rank=rank,
            chunk_id=mock_chunk_id(GENERIC_FIXTURE_ID, rank),
            entry_id=mock_chunk_id(GENERIC_FIXTURE_ID, 0),
            entry_title="Placeholder knowledge base entry",
            source_title="Placeholder source (mock pipeline)",
            source_url=None,
            text=(
                "Placeholder passage returned by the mock retriever. No knowledge "
                "base search was performed."
            ),
            score=GENERIC_PASSAGE_SCORE,
        )
        for rank in range(1, count + 1)
    ]


def generic_draft() -> DraftRecommendation:
    """What the generator returns for an extraction no fixture matches.

    YELLOW at MEDIUM confidence: a middling category a reviewer must look at,
    rather than a reassuring one. The rationale says plainly that no model ran,
    so a screenshot of a mock run can never be mistaken for a real result.
    """
    return DraftRecommendation(
        category=VTLCategory.YELLOW,
        rationale=(
            "Placeholder recommendation from the mock pipeline. No model was "
            "called and no knowledge base was searched. A veterinary reviewer "
            "must triage this case."
        ),
        cited_ranks=[1],
        confidence=ConfidenceLevel.MEDIUM,
    )
