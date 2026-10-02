"""Database access for one triage run (P05 §5.4). No business rules (CLAUDE.md §7).

The orchestrator decides what happens; this decides how it is written down. Five
things here are not obvious from the table definitions.

**The owner reference has its own method, and its name says why.** `owner_name`
and `contact_number` are read by exactly one caller — the de-identifier, which
needs those strings in order to remove them. DR-04 says no other pipeline code
reads them, and a method called
`owner_reference_for_deidentification` is harder to call by accident than a field
on the case object would be. `CaseRunInput` deliberately does not carry them.

**Outputs are versioned, never updated.** `next_extraction_version` and
`next_recommendation_version` return previous + 1, so a re-run after a crash
(ADR-08) or a regeneration (P07) adds a row and leaves the earlier one as the
record of what a reviewer was shown (ADR-14).

**Three foreign keys are filtered before use.** A red-flag `rule_code` must exist
in `red_flag_rules`, a complaint code in `presenting_complaints`, and a passage's
`chunk_id` in `kb_chunks`. While the stages are mocked none of the chunk ids exist
— the mock passages carry derived uuid5 values — so `chunk_id` is stored as NULL
and the passage's text and source are kept on the row instead. That is the same
copy-on-write the real pipeline does for ADR-14, so nothing changes when M5 and M6
land.

**`entities` holds the whole extraction.** `red_flags` and `missing_information`
also have their own columns, which are the queryable projection the review screen
and the evaluation harness filter on; `entities` is the verbatim contract object,
so an old case can be re-read exactly as it was produced (FR-26, NFR-23).
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Case,
    CaseStatus,
    ConfidenceLevel,
    ExtractionResult,
    KBChunk,
    KBVersion,
    OwnerDescription,
    OwnerReference,
    PresentingComplaint,
    Recommendation,
    RedFlagAlert,
    RedFlagRule,
    RetrievedReference,
    Signalment,
    Species,
    VTLCategory,
    extraction_complaints,
)
from app.pipeline.types import OTHER_COMPLAINT, ExtractionOutput, Passage, RedFlagHit

__all__ = ["CaseRunInput", "PipelineRepository"]

# The signalment fields handed to the extraction stage, in the order a clinician
# would say them. Values are stringified because the extraction contract stores
# signalment as text: a real model reports what the owner said ("about 3 years"),
# not a column value (CLAUDE.md §8.1).
_SIGNALMENT_FIELDS = (
    "pet_name",
    "age_value",
    "age_unit",
    "sex",
    "neutered",
    "breed",
    "weight_kg",
)


@dataclass(frozen=True)
class CaseRunInput:
    """Everything a run needs about a case, except the owner reference.

    `description` is the verbatim text from `owner_descriptions` and is the only
    free text here. It goes straight to the de-identifier and is never logged or
    audited (CLAUDE.md §9).
    """

    case_id: uuid.UUID
    status: CaseStatus
    species: Species
    sex: str | None
    signalment: dict[str, str | None]
    description: str


def _as_text(value: object) -> str | None:
    """Stringify a signalment value for the extraction contract."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        # 3.00 -> "3"; a trailing zero is an artefact of NUMERIC, not something
        # the owner said.
        return format(value.normalize(), "f")
    return str(value)


class PipelineRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- Reads -------------------------------------------------------------

    def case_for_run(self, case_id: uuid.UUID) -> CaseRunInput | None:
        """The case, its signalment and its description, or None if there is no
        such case or it has no description."""
        row = self._session.execute(
            select(Case, Signalment, OwnerDescription.text)
            .select_from(Case)
            .outerjoin(Signalment, Signalment.case_id == Case.id)
            .join(OwnerDescription, OwnerDescription.case_id == Case.id)
            .where(Case.id == case_id)
        ).one_or_none()
        if row is None:
            return None

        case, signalment, description = row
        return CaseRunInput(
            case_id=case.id,
            status=case.status,
            species=case.species,
            sex=None if signalment is None else str(signalment.sex),
            signalment={
                field: _as_text(getattr(signalment, field, None)) for field in _SIGNALMENT_FIELDS
            },
            description=description,
        )

    def case_exists(self, case_id: uuid.UUID) -> bool:
        return self._session.get(Case, case_id) is not None

    def owner_reference_for_deidentification(
        self, case_id: uuid.UUID
    ) -> tuple[str | None, str | None]:
        """The owner's name and contact number, for the de-identifier **only**.

        The single legitimate read of `owner_references` inside a pipeline run
        (DR-04, ADR-10): the stage is given these strings so it can remove them
        from the text. Nothing else may call this, and the return value must not
        outlive the `deidentify` call.
        """
        row = self._session.execute(
            select(OwnerReference.owner_name, OwnerReference.contact_number).where(
                OwnerReference.case_id == case_id
            )
        ).one_or_none()
        if row is None:
            return None, None
        return row.owner_name, row.contact_number

    def latest_kb_version_id(self) -> uuid.UUID | None:
        """The newest knowledge-base version, which a run is pinned to (FR-54).

        Ordered by `version_no`, not by `published_at`: the seed version 0 has no
        publication date, and an unpublished draft version must still be the one a
        mock run points at.
        """
        return self._session.scalars(
            select(KBVersion.id).order_by(KBVersion.version_no.desc()).limit(1)
        ).first()

    def next_extraction_version(self, case_id: uuid.UUID) -> int:
        return self._next_version(ExtractionResult, case_id)

    def next_recommendation_version(self, case_id: uuid.UUID) -> int:
        return self._next_version(Recommendation, case_id)

    def _next_version(self, model: type, case_id: uuid.UUID) -> int:
        current = self._session.scalars(
            select(func.max(model.version)).where(model.case_id == case_id)
        ).one()
        return (current or 0) + 1

    def known_rule_codes(self, codes: list[str]) -> set[str]:
        """Which of `codes` exist in `red_flag_rules`.

        A screener that reports a rule the clinic has not defined cannot have an
        alert row written for it — `red_flag_alerts.rule_code` is a foreign key.
        The orchestrator skips those rather than failing the run, because losing
        one alert is better than losing the case (NFR-09).
        """
        if not codes:
            return set()
        return set(
            self._session.scalars(select(RedFlagRule.code).where(RedFlagRule.code.in_(codes)))
        )

    def known_complaint_codes(self, codes: list[str]) -> set[str]:
        """Which of `codes` exist in `presenting_complaints` (FR-10)."""
        if not codes:
            return set()
        return set(
            self._session.scalars(
                select(PresentingComplaint.code).where(PresentingComplaint.code.in_(codes))
            )
        )

    def known_chunk_ids(self, chunk_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        """Which of `chunk_ids` exist in `kb_chunks`. See the module docstring."""
        if not chunk_ids:
            return set()
        return set(self._session.scalars(select(KBChunk.id).where(KBChunk.id.in_(chunk_ids))))

    # --- Writes ------------------------------------------------------------

    def set_status(self, case_id: uuid.UUID, status: CaseStatus) -> None:
        case = self._session.get(Case, case_id)
        if case is not None:
            case.status = status

    def insert_red_flag_alert(self, case_id: uuid.UUID, hit: RedFlagHit) -> RedFlagAlert:
        """Record one pre-screen hit. Flushes; the caller commits immediately
        (NFR-05)."""
        alert = RedFlagAlert(
            case_id=case_id,
            rule_code=hit.rule_code,
            matched_text=hit.matched_text,
            min_category=hit.min_category,
        )
        self._session.add(alert)
        self._session.flush()
        return alert

    def insert_extraction(
        self,
        *,
        case_id: uuid.UUID,
        version: int,
        extraction: ExtractionOutput,
        model_id: str,
        prompt_version: str,
        latency_ms: int | None,
        complaint_codes: list[tuple[str, bool]],
    ) -> ExtractionResult:
        """Store an extraction and its complaint junction rows. Flushes.

        `complaint_codes` is `(code, is_primary)` already mapped to codes that
        exist, so the FK cannot be violated by a stage that invented one.
        """
        row = ExtractionResult(
            case_id=case_id,
            version=version,
            entities=extraction.model_dump(mode="json"),
            red_flags=list(extraction.red_flags),
            missing_information=list(extraction.missing_information),
            is_corrected=False,
            model_id=model_id,
            prompt_version=prompt_version,
            latency_ms=latency_ms,
        )
        self._session.add(row)
        self._session.flush()

        if complaint_codes:
            self._session.execute(
                extraction_complaints.insert(),
                [
                    {"extraction_id": row.id, "complaint_code": code, "is_primary": is_primary}
                    for code, is_primary in complaint_codes
                ],
            )
        return row

    def insert_recommendation(
        self,
        *,
        case_id: uuid.UUID,
        extraction_id: uuid.UUID,
        kb_version_id: uuid.UUID | None,
        version: int,
        category: VTLCategory,
        rationale: str,
        confidence: ConfidenceLevel,
        safety_floor_applied: bool,
        safety_floor_rule_codes: list[str],
        low_confidence_reasons: list[str],
        model_id: str,
        prompt_version: str,
        params: dict,
        latency_ms: int | None,
    ) -> Recommendation:
        """Store the final recommendation. Flushes."""
        row = Recommendation(
            case_id=case_id,
            extraction_id=extraction_id,
            kb_version_id=kb_version_id,
            version=version,
            category=category,
            rationale=rationale,
            confidence=confidence,
            safety_floor_applied=safety_floor_applied,
            safety_floor_rule_codes=list(safety_floor_rule_codes),
            low_confidence_reasons=list(low_confidence_reasons),
            model_id=model_id,
            prompt_version=prompt_version,
            params=params,
            latency_ms=latency_ms,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def insert_retrieved_references(
        self,
        *,
        recommendation_id: uuid.UUID,
        passages: list[Passage],
        cited: dict[int, bool],
        storable_chunk_ids: set[uuid.UUID],
    ) -> list[RetrievedReference]:
        """Store the passages a recommendation was made from (FR-26, ADR-14).

        The text, the entry title and the source are copied rather than joined, so
        the recommendation keeps the passage as it read at the time even if the
        entry is later edited or retired.
        """
        rows = [
            RetrievedReference(
                recommendation_id=recommendation_id,
                rank=passage.rank,
                chunk_id=passage.chunk_id if passage.chunk_id in storable_chunk_ids else None,
                score=passage.score,
                is_cited=cited.get(passage.rank, False),
                entry_title=passage.entry_title,
                source_title=passage.source_title,
                source_url=passage.source_url,
                passage_text=passage.text,
            )
            for passage in passages
        ]
        self._session.add_all(rows)
        self._session.flush()
        return rows

    @staticmethod
    def mapped_complaints(extraction: ExtractionOutput, known: set[str]) -> list[tuple[str, bool]]:
        """Complaint codes for the junction rows, de-duplicated (FR-10).

        A code outside the supported list becomes `OTHER` rather than being
        dropped: the safety validator treats a primary `OTHER` as a reason to
        recommend manual triage, so losing it would make a case look better
        supported than it is (P05 §5.3 rule 4).

        First mention of a code wins, because the junction's primary key is
        `(extraction_id, complaint_code)` and two mentions would collide.

        `known` must contain `OTHER` for the fallback to be storable. On a
        database that has not been seeded it does not, and the junction rows are
        then dropped rather than failing the run: the extraction itself still
        carries the complaints in `entities`.
        """
        mapped: dict[str, bool] = {}
        for complaint in extraction.presenting_complaints:
            code = complaint.code if complaint.code in known else OTHER_COMPLAINT
            mapped[code] = mapped.get(code, False) or complaint.is_primary
        return [(code, is_primary) for code, is_primary in mapped.items() if code in known]
