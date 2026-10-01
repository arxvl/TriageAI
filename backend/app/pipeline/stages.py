"""The six pipeline stage ports (CLAUDE.md §8.2, ADR-17).

One Protocol per stage, each with a mock implementation written here and a real
one written manually later (M1–M6). The orchestrator depends on these names only,
so turning a component on is a `.env` change and no application code moves.

Signatures follow CLAUDE.md §8.2 exactly.

Order in a run, and why the seam is where it is:

1. `Deidentifier` — the only stage that ever sees the owner's name and contact
   details. Everything after it receives de-identified text, which is what makes
   it safe for a real `LLMProvider` to exist at all (IR-20, ADR-10).
2. `RedFlagScreener` — runs before extraction so an alert reaches the queue in
   about two seconds even if the model is slow or down (NFR-05, FR-12).
3. `EntityExtractor` → 4. `Retriever` → 5. `RecommendationGenerator`.

`KBIndexer` is not part of a triage run. It belongs to the knowledge-base
approval workflow (P08) and is here because it is selected by the same registry.

Every stage also carries provenance, which is what `PipelineStage` below
describes. Mocks report `model_id="mock"` and `prompt_version="mock-0"` so the
storage code has no special case (FR-26, NFR-23, ADR-14).
"""

import uuid
from typing import Protocol, runtime_checkable

from app.models.enums import Species
from app.pipeline.types import (
    DraftRecommendation,
    ExtractionOutput,
    Passage,
    RedFlagHit,
)


@runtime_checkable
class PipelineStage(Protocol):
    """What every stage exposes for storage and reproducibility.

    Not a stage in itself — the orchestrator reads these three attributes off
    whichever stage just ran and writes them to the row it produced, identically
    for mocks and real stages (CLAUDE.md §8.2, ADR-14).

    `last_latency_ms` is set by the stage after each call. A non-model stage
    still reports one; it is the measured wall time, and it is what fills
    `recommendations.params.stage_ms` (P05 §5.4).
    """

    model_id: str
    prompt_version: str
    last_latency_ms: int


@runtime_checkable
class Deidentifier(Protocol):
    def deidentify(self, text: str, owner_name: str | None, owner_contact: str | None) -> str:
        """Return the text with identifying details removed (FR-10, ADR-10).

        `owner_name` and `owner_contact` come from `owner_references`, which no
        other pipeline code may read (DR-04). They are passed here so the stage
        can remove those exact strings, and they are never stored with any
        output.
        """
        ...


@runtime_checkable
class RedFlagScreener(Protocol):
    def screen(self, text: str, species: Species, sex: str | None) -> list[RedFlagHit]:
        """Return every red-flag rule the text triggers (FR-12).

        `sex` is `MALE`, `FEMALE`, `UNKNOWN` or `None` — some rules are
        sex-specific, such as urinary obstruction in a male cat.

        An empty list means no rule fired, not that screening failed; this stage
        does not raise.
        """
        ...


@runtime_checkable
class EntityExtractor(Protocol):
    def extract(
        self, text: str, species: Species, signalment: dict | None = None
    ) -> ExtractionOutput:
        """Extract the clinical details from a de-identified description (FR-11).

        Raises:
            ExtractionFailed: no usable output after the stage's own retries.
        """
        ...


@runtime_checkable
class Retriever(Protocol):
    def retrieve(
        self, extraction: ExtractionOutput, kb_version_id: uuid.UUID, k: int
    ) -> list[Passage]:
        """Return up to `k` passages, ranked 1..k, most similar first (FR-19).

        `kb_version_id` pins the search to one published knowledge-base version,
        so a recommendation can be reproduced later (ADR-14).

        Raises:
            RetrievalFailed: the search could not be performed.
        """
        ...


@runtime_checkable
class RecommendationGenerator(Protocol):
    def generate(
        self, extraction: ExtractionOutput, passages: list[Passage]
    ) -> DraftRecommendation:
        """Propose a category, rationale and citations (FR-21).

        The result is a *draft*. It is never stored or displayed as the
        recommendation: the deterministic validator produces the final one
        (FR-22, FR-23, ADR-09).

        Raises:
            GenerationFailed: no usable output after the stage's own retries.
        """
        ...


@runtime_checkable
class KBIndexer(Protocol):
    """Used by the knowledge-base approval workflow (P08), not by a triage run."""

    def index_entry(self, entry_id: uuid.UUID) -> int:
        """Chunk and index an approved entry; returns the chunk count."""
        ...

    def remove_entry(self, entry_id: uuid.UUID) -> None:
        """Drop a retired entry's chunks so retrieval can no longer return them."""
        ...
