"""Deterministic stand-ins for every AI stage (CLAUDE.md §8, ADR-17).

These exist so the whole application — intake, queue, review, decisions, audit,
evaluation — runs end to end before any AI component is written, and so the test
suite and CI need no API key, no model download and no network (ADR-17).

**There is no NLP here and there must never be.** A mock either returns a
recorded fixture or a fixed generic answer. Matching is string equality after
whitespace normalisation, not similarity. The real stages are written manually
under M1–M6.

Subphase 5.1 ships the skeletons: the correct signatures, the provenance
attributes the orchestrator reads, and the "no fixture match" answers that P05
§5.2 specifies. Subphase 5.2 adds the `tests/fixtures/demo_cases.yaml` lookup and
the `MOCK_LLM_BEHAVIOR` failure modes — see each `TODO(P05.2)`.

A mock reports `model_id="mock"` and `prompt_version="mock-0"` rather than
omitting them, so the provenance columns are filled the same way on a mock run
and a real one and nothing downstream branches (FR-26, NFR-23, ADR-14). The
evaluation screen tells the two apart by those values, which is why a mock-mode
run is labelled rather than silently reported as a result.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import TYPE_CHECKING

from app.core.config import MockLLMBehavior, Settings
from app.models.enums import ConfidenceLevel, Species, VTLCategory
from app.pipeline.config import PipelineConfig
from app.pipeline.types import (
    DraftRecommendation,
    ExtractedComplaint,
    ExtractionOutput,
    Passage,
    RedFlagHit,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.pipeline.registry import PipelineDeps

MOCK_MODEL_ID = "mock"
MOCK_PROMPT_VERSION = "mock-0"

# The complaint code for anything outside the supported set. A primary `OTHER`
# is what makes the safety validator recommend manual triage (P05 §5.3 rule 4).
OTHER_COMPLAINT = "OTHER"

# What a generic extraction admits it does not know. Fixed wording, because the
# review screen's "missing information" list is asserted on in tests and shown in
# the PD8 walkthrough (P05 §5.2).
GENERIC_MISSING_INFORMATION = ["duration", "appetite", "water intake"]

# Deterministic ids for generic passages. `uuid5` of a stable seed, so the same
# description produces the same `chunk_id` on every run and in every environment
# (P05 §5.2).
GENERIC_FIXTURE_ID = "GENERIC"
GENERIC_PASSAGE_COUNT = 2
GENERIC_PASSAGE_SCORE = 0.20


def mock_chunk_id(fixture_id: str, rank: int) -> uuid.UUID:
    """The `chunk_id` a mock passage carries (P05 §5.2).

    Derived, not random: a mock run has no `kb_chunks` rows to point at, and a
    stable id is what lets a test assert on a stored reference.
    """
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{fixture_id}{rank}")


class _MockStage:
    """Shared provenance and timing for the mocks (CLAUDE.md §8.2).

    Not a stage. It holds the three attributes the orchestrator reads off every
    stage, so each mock below is only its own `from_settings` and its one method.
    """

    model_id: str = MOCK_MODEL_ID
    prompt_version: str = MOCK_PROMPT_VERSION

    def __init__(self, config: PipelineConfig, behavior: MockLLMBehavior) -> None:
        self.config = config
        self.behavior = behavior
        self.last_latency_ms = 0

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
    """Replays a fixture's recorded hits; no phrase matching (M1 writes the real one)."""

    def screen(self, text: str, species: Species, sex: str | None) -> list[RedFlagHit]:
        with self._measured():
            # TODO(P05.2): look `text` up in demo_cases.yaml and return its
            # `mock_red_flags`. No fixture match means no hit.
            return []


class MockEntityExtractor(_MockStage):
    """Replays a fixture's recorded extraction (M3 writes the real one)."""

    def extract(
        self, text: str, species: Species, signalment: dict | None = None
    ) -> ExtractionOutput:
        with self._measured():
            # TODO(P05.2): look `text` up in demo_cases.yaml and return its
            # `mock_extraction`; honour MOCK_LLM_BEHAVIOR (invalid_json, timeout,
            # flaky, slow) so the orchestrator's retry and failure paths are
            # exercised without a network call.
            return generic_extraction(species, signalment)


class MockRetriever(_MockStage):
    """Replays a fixture's recorded passages; no vector search (M6 writes the real one)."""

    def retrieve(
        self, extraction: ExtractionOutput, kb_version_id: uuid.UUID, k: int
    ) -> list[Passage]:
        with self._measured():
            # TODO(P05.2): look the extraction's source description up in
            # demo_cases.yaml and return its `mock_passages`.
            return generic_passages(k)


class MockRecommendationGenerator(_MockStage):
    """Replays a fixture's recorded draft (M6 writes the real one)."""

    def generate(
        self, extraction: ExtractionOutput, passages: list[Passage]
    ) -> DraftRecommendation:
        with self._measured():
            # TODO(P05.2): look the extraction up in demo_cases.yaml and return
            # its `mock_draft`; honour MOCK_LLM_BEHAVIOR as above.
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


def _as_signalment(signalment: dict | None) -> dict[str, str | None]:
    """Coerce a signalment dict to the `dict[str, str | None]` the contract uses.

    Ages and weights arrive as numbers from the database; the extraction contract
    stores signalment as text because a real model reports it as the owner said
    it ("about 3 years"), not as a column value.
    """
    return {
        str(key): None if value is None else str(value) for key, value in (signalment or {}).items()
    }


def generic_extraction(species: Species, signalment: dict | None = None) -> ExtractionOutput:
    """What the extractor returns for a description no fixture matches.

    A primary complaint of `OTHER` and nothing else claimed. That is the honest
    answer from a mock, and it drives the case toward manual triage rather than
    toward a fabricated category (P05 §5.3 rule 4).
    """
    return ExtractionOutput(
        species=species,
        signalment=_as_signalment(signalment),
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
