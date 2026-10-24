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

**The actions job reads its inputs back rather than being handed them.**
`actions_run_input` reconstructs the stage inputs — the extraction and the
passages — from the rows the triage run committed, because the actions job is a
separate job that may run after a restart (ADR-18 §3). Retrieval is never run
again: the recommendation must keep the passages it was actually made from
(ADR-14).

**`entities` holds the whole extraction.** `red_flags` and `missing_information`
also have their own columns, which are the queryable projection the review screen
and the evaluation harness filter on; `entities` is the verbatim contract object,
so an old case can be re-read exactly as it was produced (FR-26, NFR-23).
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models import (
    ActionSource,
    ActionsStatus,
    ActionSuggestion,
    Case,
    CaseStatus,
    ConfidenceLevel,
    ExtractionResult,
    KBChunk,
    KBEntry,
    KBEntryKind,
    KBEntryStatus,
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
    kb_version_entries,
)
from app.pipeline.types import OTHER_COMPLAINT, ExtractionOutput, Passage, RedFlagHit

__all__ = [
    "FIRST_ACTION_GENERATION",
    "ActionSuggestionValues",
    "ActionsRunInput",
    "CaseRunInput",
    "PipelineRepository",
]

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


# The set the first actions run stores. A regeneration is a later number.
FIRST_ACTION_GENERATION = 1


@dataclass(frozen=True)
class ActionsRunInput:
    """Everything the `SUGGEST_ACTIONS` job needs, read back from storage.

    Read rather than recomputed: the actions job runs after its own commit and
    possibly after a restart, so it reconstructs the stage inputs from the rows
    the triage run left behind. Retrieval is **not** run again — that would
    search a knowledge base that may have moved on and produce actions citing
    passages the recommendation was never made from (ADR-14, ADR-18 §3).

    `extraction_entities` is the raw JSONB. It is validated into an
    `ExtractionOutput` by the caller, so an unreadable old row becomes a reason
    code on the actions status rather than an exception out of a repository.

    `chunk_ids_by_rank` carries the *real* `kb_chunks` ids, which are NULL while
    the stages are mocked (see the module docstring). `passages` is the
    reconstructed contract object, whose `chunk_id` is a stable placeholder when
    the stored one is NULL — the two are deliberately separate, so a placeholder
    can never be written back as a citation.
    """

    recommendation_id: uuid.UUID
    case_id: uuid.UUID | None
    vignette_id: uuid.UUID | None
    category: VTLCategory
    kb_version_id: uuid.UUID | None
    extraction_entities: dict
    passages: list[Passage]
    chunk_ids_by_rank: dict[int, uuid.UUID | None]


@dataclass(frozen=True)
class ActionSuggestionValues:
    """One `action_suggestions` row, as the orchestrator decided it.

    `cited_chunk_ids` is built by `PipelineRepository.cited_chunk_ids`; see that
    method for why it holds objects rather than bare ids.
    """

    rank: int
    text: str
    source: ActionSource
    cited_chunk_ids: list[dict]
    model_id: str
    prompt_version: str
    latency_ms: int | None


def _as_text(value: object) -> str | None:
    """Stringify a signalment value for the extraction contract."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        # 3.00 -> "3"; a trailing zero is an artefact of NUMERIC, not something
        # the owner said.
        return format(value.normalize(), "f")
    return str(value)


def _placeholder_id(recommendation_id: uuid.UUID, kind: str, key: object) -> uuid.UUID:
    """A stable id for a passage field a mock run did not store.

    uuid5, so the same recommendation rebuilds the same ids on every retry and in
    every process. Scoped by the recommendation, so two recommendations never
    collide, and namespaced by `kind`, so a chunk placeholder and an entry
    placeholder for the same rank differ. These values are handed to the stages
    and are never written to a row (see `ActionsRunInput`).
    """
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{recommendation_id}:{kind}:{key}")


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
        """The knowledge-base version this run is pinned to (FR-54, IR-14).

        Prefers the newest **published** version — one an approval or a
        retirement produced (FR-54, P08 §8.1 task 6) — and falls back to the
        newest version of any kind. The fallback is what the seeded version 0 is
        for: before the first entry has been approved it is the only version
        there is, and a clean checkout has to keep triaging and keep showing
        baseline actions rather than fail every case for want of a version.
        """
        published = self._session.scalars(
            select(KBVersion.id)
            .where(KBVersion.published_at.is_not(None))
            .order_by(KBVersion.version_no.desc())
            .limit(1)
        ).first()
        if published is not None:
            return published
        return self._session.scalars(
            select(KBVersion.id).order_by(KBVersion.version_no.desc()).limit(1)
        ).first()

    def active_urgency_actions_content(
        self, category: VTLCategory, kb_version_id: uuid.UUID
    ) -> str | None:
        """The ACTIVE baseline action entry for one category, or None (FR-72).

        Pinned to a knowledge-base version like every other read a run makes, so
        reopening an old case shows the baseline set as it was then (FR-54,
        ADR-14). `uq_kb_entries_active_urgency_actions` is what makes the row
        unambiguous: at most one ACTIVE entry exists per category, so a second
        one cannot quietly shadow the first.

        Returns the entry content; splitting it into actions belongs to
        `app.pipeline.action_validator.baseline_actions`.
        """
        return self._session.execute(
            select(KBEntry.content)
            .join(kb_version_entries, kb_version_entries.c.entry_id == KBEntry.id)
            .where(
                kb_version_entries.c.kb_version_id == kb_version_id,
                KBEntry.kind == KBEntryKind.URGENCY_ACTIONS,
                KBEntry.status == KBEntryStatus.ACTIVE,
                KBEntry.urgency_category == category,
            )
        ).scalar_one_or_none()

    def actions_run_input(self, recommendation_id: uuid.UUID) -> ActionsRunInput | None:
        """The stored inputs for one actions run, or None if the row is gone.

        Two queries, not one: the references are a list and joining them onto the
        recommendation would multiply the extraction JSON by the number of
        passages for nothing.
        """
        row = self._session.execute(
            select(
                Recommendation.id,
                Recommendation.case_id,
                Recommendation.vignette_id,
                Recommendation.category,
                Recommendation.kb_version_id,
                ExtractionResult.entities,
            )
            .join(ExtractionResult, ExtractionResult.id == Recommendation.extraction_id)
            .where(Recommendation.id == recommendation_id)
        ).one_or_none()
        if row is None:
            return None

        references = list(
            self._session.scalars(
                select(RetrievedReference)
                .where(RetrievedReference.recommendation_id == recommendation_id)
                .order_by(RetrievedReference.rank)
            )
        )
        return ActionsRunInput(
            recommendation_id=row.id,
            case_id=row.case_id,
            vignette_id=row.vignette_id,
            category=row.category,
            kb_version_id=row.kb_version_id,
            extraction_entities=row.entities,
            passages=[
                Passage(
                    rank=reference.rank,
                    # A mock run stores no chunk id (see the module docstring), and
                    # `Passage.chunk_id` is not optional. The placeholder is derived
                    # from the recommendation and the rank, so it is stable across
                    # retries and across processes, and it is never written back.
                    chunk_id=reference.chunk_id
                    or _placeholder_id(recommendation_id, "chunk", reference.rank),
                    entry_id=_placeholder_id(recommendation_id, "entry", reference.entry_title),
                    entry_title=reference.entry_title,
                    source_title=reference.source_title or "",
                    source_url=reference.source_url,
                    text=reference.passage_text,
                    score=float(reference.score) if reference.score is not None else 0.0,
                )
                for reference in references
            ],
            chunk_ids_by_rank={reference.rank: reference.chunk_id for reference in references},
        )

    def stored_red_flag_hits(self, case_id: uuid.UUID) -> list[RedFlagHit]:
        """The case's stored red-flag alerts, as the hits the safety floor takes.

        A regeneration does not screen again: the description has not changed,
        and the alerts the first run committed are the record of what the
        pre-screen found (FR-12). `matched_text` is read here because the
        contract carries it; it goes no further than the validator, which looks
        only at the rule code and its floor (CLAUDE.md §9).
        """
        rows = self._session.execute(
            select(
                RedFlagAlert.rule_code,
                RedFlagAlert.matched_text,
                RedFlagAlert.min_category,
            )
            .where(RedFlagAlert.case_id == case_id)
            .order_by(RedFlagAlert.created_at.asc(), RedFlagAlert.id.asc())
        ).all()
        return [
            RedFlagHit(
                rule_code=row.rule_code,
                matched_text=row.matched_text,
                min_category=row.min_category,
            )
            for row in rows
        ]

    def extraction_entities(self, case_id: uuid.UUID, extraction_id: uuid.UUID) -> dict | None:
        """The stored contract object of one of this case's extractions, or None.

        Scoped by case so a job built by hand cannot regenerate one patient's
        recommendation from another's extraction.
        """
        return self._session.scalars(
            select(ExtractionResult.entities).where(
                ExtractionResult.id == extraction_id, ExtractionResult.case_id == case_id
            )
        ).one_or_none()

    def has_recommendation_for_extraction(self, extraction_id: uuid.UUID) -> bool:
        """Whether a recommendation was already made from this extraction.

        What makes a re-run of a `REGENERATE` job after a crash harmless: if the
        previous attempt got as far as storing its recommendation, there is
        nothing left to do but restore the status (ADR-08).
        """
        return (
            self._session.scalars(
                select(Recommendation.id).where(Recommendation.extraction_id == extraction_id)
            ).first()
            is not None
        )

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

    def set_status_if(self, case_id: uuid.UUID, expected: CaseStatus, new: CaseStatus) -> bool:
        """Move a case from `expected` to `new`; True if this call did.

        A compare-and-set, so a regeneration can restore `AWAITING_REVIEW` only
        from `PROCESSING` and can never overwrite a decision recorded in the
        meantime (NFR-11). Flushes.
        """
        result = self._session.execute(
            update(Case).where(Case.id == case_id, Case.status == expected).values(status=new)
        )
        self._session.flush()
        return result.rowcount == 1

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
        input_text: str | None,
        extraction: ExtractionOutput,
        model_id: str,
        prompt_version: str,
        latency_ms: int | None,
        complaint_codes: list[tuple[str, bool]],
        corrected_by: uuid.UUID | None = None,
    ) -> ExtractionResult:
        """Store an extraction and its complaint junction rows. Flushes.

        `complaint_codes` is `(code, is_primary)` already mapped to codes that
        exist, so the FK cannot be violated by a stage that invented one.

        `input_text` is the **de-identified** description the stage was given,
        never the raw one (ADR-10). It is stored because the evidence spans in
        `entities` are exact substrings of it and the review screen has to map
        them to character offsets (FR-13).

        `corrected_by` marks a reviewer's correction (P07 §7.2): the row is then
        `is_corrected` and names who made it. The original version is a
        different row and is never touched (ADR-14).
        """
        row = ExtractionResult(
            case_id=case_id,
            version=version,
            input_text=input_text,
            entities=extraction.model_dump(mode="json"),
            red_flags=list(extraction.red_flags),
            missing_information=list(extraction.missing_information),
            is_corrected=corrected_by is not None,
            corrected_by=corrected_by,
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

    def set_actions_status(
        self,
        recommendation_id: uuid.UUID,
        status: ActionsStatus,
        *,
        error: str | None = None,
        rejected_count: int | None = None,
    ) -> None:
        """Record how the actions job for this recommendation ended (FR-77).

        `error` is a reason code, never a model message — a message could carry
        action text (SR-17). `rejected_count` is left as it is when None, so the
        failure path does not erase a count a previous attempt recorded.

        A missing recommendation is ignored rather than raised: the job's own
        caller has already reported that, and this is bookkeeping.
        """
        recommendation = self._session.get(Recommendation, recommendation_id)
        if recommendation is None:
            return
        recommendation.actions_status = status
        recommendation.actions_error = error
        if rejected_count is not None:
            recommendation.actions_rejected_count = rejected_count

    def next_action_generation(self, recommendation_id: uuid.UUID) -> int:
        """The number a regeneration's set will have: one past the newest stored.

        Chosen when the job is enqueued and carried in its payload, so a re-run
        of that job after a crash replaces its own set instead of adding another.
        A failed regeneration stores nothing, so the next attempt gets the same
        number again.
        """
        newest = self._session.scalar(
            select(func.max(ActionSuggestion.generation)).where(
                ActionSuggestion.recommendation_id == recommendation_id
            )
        )
        return (newest or 0) + 1

    def replace_action_suggestions(
        self,
        *,
        recommendation_id: uuid.UUID,
        case_id: uuid.UUID | None,
        vignette_id: uuid.UUID | None,
        category: VTLCategory,
        kb_version_id: uuid.UUID | None,
        rows: list[ActionSuggestionValues],
        generation: int = FIRST_ACTION_GENERATION,
    ) -> list[ActionSuggestion]:
        """Store one generation of this recommendation's suggestions.

        Delete-then-insert **within the generation**, because the actions job can
        be retried — by the startup sweep after a crash (ADR-08) or by a
        reviewer — and a retry must leave one set of rows rather than two
        overlapping ones. Other generations are never touched: a regeneration
        for a changed category adds a later set and keeps the earlier one
        (FR-78, ADR-18 §6). `action_suggestions` is not append-only;
        `final_actions`, which records what a reviewer decided, is (DR-09,
        ADR-12).

        `generated_for_category` is written on every row, so a later change of
        category marks these outdated instead of silently re-labelling them
        (FR-78).
        """
        self._session.execute(
            delete(ActionSuggestion).where(
                ActionSuggestion.recommendation_id == recommendation_id,
                ActionSuggestion.generation == generation,
            )
        )
        stored = [
            ActionSuggestion(
                case_id=case_id,
                vignette_id=vignette_id,
                recommendation_id=recommendation_id,
                generated_for_category=category,
                generation=generation,
                rank=values.rank,
                text=values.text,
                source=values.source,
                cited_chunk_ids=values.cited_chunk_ids,
                model_id=values.model_id,
                prompt_version=values.prompt_version,
                kb_version_id=kb_version_id,
                latency_ms=values.latency_ms,
            )
            for values in rows
        ]
        self._session.add_all(stored)
        self._session.flush()
        return stored

    @staticmethod
    def cited_chunk_ids(
        cited_ranks: list[int], chunk_ids_by_rank: dict[int, uuid.UUID | None]
    ) -> list[dict]:
        """The citation record for one action: `{"rank", "chunk_id"}` per rank.

        Objects rather than bare chunk ids, because while the stages are mocked
        every `retrieved_references.chunk_id` is NULL — a list of ids would be
        empty on every run and the FR-74 citation link would be unverifiable
        until M5 and M6 land. The rank always survives, which is also what the
        review screen needs: it shows a tailored action beside the passage at
        that rank. The `chunk_id` fills itself in once real chunks exist.

        A rank with no reference row is dropped. The validator has already
        narrowed the ranks to passages that were retrieved, so this only guards
        against a reference row that was never stored.
        """
        record: list[dict] = []
        for rank in cited_ranks:
            if rank not in chunk_ids_by_rank:
                continue
            chunk_id = chunk_ids_by_rank[rank]
            record.append({"rank": rank, "chunk_id": None if chunk_id is None else str(chunk_id)})
        return record

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
