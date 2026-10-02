"""The assembled pipeline and the run it performs (P05 §5.1 task 4, §5.4 task 4).

`TriagePipeline` is what `app.pipeline.registry.build_pipeline` returns: the
stages chosen from settings, plus the config and deps they were built with. It is
built once at startup and shared; the stages hold no per-case state beyond
`last_latency_ms`, which the run reads immediately after each call.

`run(case_id)` is called by the job worker, never inside a request (ADR-08). The
steps, and the reason each boundary is where it is:

1. **`PROCESSING`, audit `PIPELINE_STARTED`, commit.** The case is visibly being
   worked on before anything that can hang is called.
2. **`deidentify`** — the owner reference is read here and nowhere else, and is
   never bound to anything that outlives the call (DR-04, ADR-10).
3. **`screen`, then insert each `RedFlagAlert` and commit immediately.** This is
   the one commit the design depends on: an alert reaches the queue within about
   two seconds even when every model call after it times out (NFR-05, FR-12).
4. **`extract`**, retried `config.max_retries` times on `LLMInvalidOutput` only.
   A schema violation is often transient; a timeout under load is not, and
   retrying one would spend the job's budget waiting (FR-15, IR-19).
5. **Store the `ExtractionResult`** and its complaint rows, at version
   previous + 1 — outputs are versioned, never updated (ADR-14).
6. **Resolve the latest `KBVersion`, then `retrieve` and `generate`.**
7. **`SafetyValidator.finalize`,** then the `Recommendation` and its
   `RetrievedReference` rows. The model's category is never what gets stored
   (ADR-09).
8. **Provenance** — each stage's `model_id`, `prompt_version` and
   `last_latency_ms` onto the row it produced, and every stage's latency into
   `params.stage_ms` (FR-26, NFR-23, ADR-14).
9. **`AWAITING_REVIEW`, audit `RECOMMENDATION_CREATED`** — category and
   confidence only, never the text (CLAUDE.md §9).

Any failure takes the failure path: `MANUAL_TRIAGE_REQUIRED`, a reason code the
worker writes into the job's `last_error`, audit `PIPELINE_FAILED`. A case is
never lost and never left in `PROCESSING` (NFR-09, ADR-08) — which is why the
outermost handler catches `Exception` and not only `PipelineError`.

**Nothing in this module is AI.** Every stage is called through the Protocols in
`app.pipeline.stages`, and the only decision made here is which of them to call
next (CLAUDE.md §8).
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, TypeVar

from sqlalchemy.orm import Session

from app.jobs.queue import JobQueue, JobStage
from app.models import CaseStatus
from app.pipeline.config import PipelineConfig
from app.pipeline.errors import (
    ExtractionFailed,
    GenerationFailed,
    LLMInvalidOutput,
    LLMTimeout,
    LLMUnavailable,
    RetrievalFailed,
)
from app.pipeline.safety import SafetyValidator, citation_flags
from app.pipeline.stages import (
    Deidentifier,
    EntityExtractor,
    KBIndexer,
    RecommendationGenerator,
    RedFlagScreener,
    Retriever,
)
from app.pipeline.types import (
    DraftRecommendation,
    ExtractionOutput,
    FinalRecommendation,
    Passage,
    RedFlagHit,
)
from app.repositories.pipeline_repository import CaseRunInput, PipelineRepository
from app.services.audit_service import CASE_ENTITY, AuditAction, AuditService

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.pipeline.registry import PipelineDeps

logger = logging.getLogger(__name__)

__all__ = ["FailureReason", "PipelineRunResult", "TriagePipeline"]

_T = TypeVar("_T")


class FailureReason(StrEnum):
    """Why a run ended in `MANUAL_TRIAGE_REQUIRED` (NFR-09).

    Codes, not prose. They go into `jobs.last_error`, into the `PIPELINE_FAILED`
    audit entry and — in P07 — into the W-06 banner and the retry endpoint's
    decision about whether retrying could help. None of them may contain a model
    response, a prompt or an owner description (CLAUDE.md §9).
    """

    CASE_NOT_FOUND = "CASE_NOT_FOUND"
    DESCRIPTION_MISSING = "DESCRIPTION_MISSING"
    EXTRACTION_INVALID_OUTPUT = "EXTRACTION_INVALID_OUTPUT"
    EXTRACTION_TIMEOUT = "EXTRACTION_TIMEOUT"
    EXTRACTION_UNAVAILABLE = "EXTRACTION_UNAVAILABLE"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    KB_VERSION_MISSING = "KB_VERSION_MISSING"
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    GENERATION_INVALID_OUTPUT = "GENERATION_INVALID_OUTPUT"
    GENERATION_TIMEOUT = "GENERATION_TIMEOUT"
    GENERATION_UNAVAILABLE = "GENERATION_UNAVAILABLE"
    GENERATION_FAILED = "GENERATION_FAILED"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


# Which reason code each stage reports for each failure. Both model stages are
# retried on `LLMInvalidOutput` and only on that: a draft that does not match its
# schema is as transient as an extraction that does not, while a timeout under load
# is not transient and retrying one would spend the job's budget waiting (FR-15,
# IR-19). First match wins, so the stage's own error is listed last.
_EXTRACTION_REASONS: tuple[tuple[type[Exception], "FailureReason"], ...] = (
    (LLMInvalidOutput, FailureReason.EXTRACTION_INVALID_OUTPUT),
    (LLMTimeout, FailureReason.EXTRACTION_TIMEOUT),
    (LLMUnavailable, FailureReason.EXTRACTION_UNAVAILABLE),
    (ExtractionFailed, FailureReason.EXTRACTION_FAILED),
)

_GENERATION_REASONS: tuple[tuple[type[Exception], "FailureReason"], ...] = (
    (LLMInvalidOutput, FailureReason.GENERATION_INVALID_OUTPUT),
    (LLMTimeout, FailureReason.GENERATION_TIMEOUT),
    (LLMUnavailable, FailureReason.GENERATION_UNAVAILABLE),
    (GenerationFailed, FailureReason.GENERATION_FAILED),
)


@dataclass(frozen=True)
class PipelineRunResult:
    """What one run did, for the worker that called it.

    The worker turns this into the job's final state: a `failure_reason` becomes
    `FAILED` with that code in `last_error`, and its absence becomes `DONE`. The
    run has already put the *case* in its final state; this only reports it, so
    the two cannot disagree.
    """

    case_id: uuid.UUID
    status: CaseStatus | None
    failure_reason: FailureReason | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure_reason is None


def _reason_for(
    error: Exception, reasons: tuple[tuple[type[Exception], FailureReason], ...]
) -> FailureReason | None:
    """The reason code for this error, or None if the stage did not raise one of
    its declared failures — which is a bug, and must not be disguised as a
    pipeline failure."""
    for error_type, reason in reasons:
        if isinstance(error, error_type):
            return reason
    return None


class _StageFailure(Exception):
    """Internal: a stage failed and the run must take the failure path.

    Not exported and never raised out of `run`. It exists so each stage's call
    site can name its own reason code once, instead of the step order being
    rebuilt from a chain of return values.
    """

    def __init__(self, reason: FailureReason) -> None:
        super().__init__(str(reason))
        self.reason = reason


@dataclass(frozen=True)
class TriagePipeline:
    config: PipelineConfig
    deps: "PipelineDeps"
    deidentifier: Deidentifier
    red_flag_screener: RedFlagScreener
    extractor: EntityExtractor
    retriever: Retriever
    generator: RecommendationGenerator
    # Not used by a triage run; selected by the same registry and handed to the
    # knowledge-base approval workflow (P08).
    kb_indexer: KBIndexer

    @property
    def is_fully_mocked(self) -> bool:
        """True when every stage is a mock.

        W-10 shows a persistent "MOCK MODE" banner on this, because evaluation
        numbers from a mock run mean nothing (ADR-17).
        """
        return all(
            getattr(stage, "model_id", None) == "mock"
            for stage in (
                self.deidentifier,
                self.red_flag_screener,
                self.extractor,
                self.retriever,
                self.generator,
            )
        )

    def run(self, case_id: uuid.UUID, *, job_id: uuid.UUID | None = None) -> PipelineRunResult:
        """Triage one case, end to end. Never raises.

        `job_id` is optional so the pipeline can be driven without the queue — the
        evaluation harness does that (M7) — and when it is given, each step's
        progress is recorded on the job for `GET /cases/{id}/status` (IR-22).

        A session is opened here rather than passed in, because a run commits
        several times and must not be inside anybody else's transaction. It comes
        from `deps.session_factory`, which the registry accepts an override for.
        """
        with self.deps.session_factory() as session:
            return _TriageRun(self, session, case_id, job_id).execute()


class _TriageRun:
    """One run's mutable state: the session, the stage latencies, the job.

    Separate from `TriagePipeline` so the pipeline itself stays frozen and
    shareable between the worker thread and the request handlers.
    """

    def __init__(
        self,
        pipeline: TriagePipeline,
        session: Session,
        case_id: uuid.UUID,
        job_id: uuid.UUID | None,
    ) -> None:
        self._pipeline = pipeline
        self._config = pipeline.config
        self._session = session
        self._repo = PipelineRepository(session)
        self._audit = AuditService(session)
        self._jobs = JobQueue(session)
        self._case_id = case_id
        self._job_id = job_id
        # Per-stage wall time, as `params.stage_ms` on the recommendation (FR-68
        # computes p50/p95 from these).
        self._stage_ms: dict[str, int] = {}

    # --- Entry point -------------------------------------------------------

    def execute(self) -> PipelineRunResult:
        try:
            return self._run()
        except _StageFailure as failure:
            return self._fail(failure.reason)
        except Exception:
            # The guarantee is that no case is lost and none is left in
            # PROCESSING (NFR-09). A bug in this module must not be the exception
            # to it, so the net is `Exception` and the traceback goes to the log,
            # not to the case.
            logger.exception("triage pipeline raised", extra=self._log_context())
            return self._fail(FailureReason.UNEXPECTED_ERROR)

    def _run(self) -> PipelineRunResult:
        case = self._repo.case_for_run(self._case_id)
        if case is None:
            # No row to move and nothing to audit against. Logged as an error
            # because it means a job outlived its case, which the single-
            # transaction enqueue in `CaseService` should make impossible.
            logger.error("triage pipeline: case not found", extra=self._log_context())
            return PipelineRunResult(self._case_id, None, FailureReason.CASE_NOT_FOUND)

        self._start()

        text = self._deidentify(case)
        red_flag_hits = self._screen(case, text)
        extraction = self._extract(case, text)
        extraction_row_id = self._store_extraction(case, extraction)

        kb_version_id = self._repo.latest_kb_version_id()
        if kb_version_id is None:
            # Nothing to retrieve from means nothing to cite, and FR-22 requires a
            # citation. `scripts/seed.py` creates version 0 for exactly this.
            logger.warning("triage pipeline: no knowledge base version", extra=self._log_context())
            raise _StageFailure(FailureReason.KB_VERSION_MISSING)

        passages = self._retrieve(extraction, kb_version_id)
        draft = self._generate(extraction, passages)

        final = SafetyValidator.finalize(draft, passages, red_flag_hits, extraction, self._config)
        self._store_recommendation(
            case=case,
            extraction_id=extraction_row_id,
            kb_version_id=kb_version_id,
            passages=passages,
            final=final,
        )
        return self._finish(final)

    # --- Steps -------------------------------------------------------------

    def _start(self) -> None:
        """Step 1: `PROCESSING`, audit `PIPELINE_STARTED`, commit."""
        self._repo.set_status(self._case_id, CaseStatus.PROCESSING)
        self._record(
            AuditAction.PIPELINE_STARTED,
            {
                "status": CaseStatus.PROCESSING.value,
                "job_id": str(self._job_id) if self._job_id else None,
                "model_id": self._config.model_id,
                "prompt_version": self._config.prompt_version,
            },
        )
        self._session.commit()

    def _deidentify(self, case: CaseRunInput) -> str:
        """Step 2: de-identify the description (ADR-10).

        The owner reference is read inside the call expression and bound to
        nothing: there is no local here holding an owner's name or number, so no
        later step can reach one (DR-04).
        """
        self._stage(JobStage.DEIDENTIFY)
        stage = self._pipeline.deidentifier
        text = stage.deidentify(
            case.description,
            *self._repo.owner_reference_for_deidentification(self._case_id),
        )
        self._measured("deidentify", stage)
        return text

    def _screen(self, case: CaseRunInput, text: str) -> list[RedFlagHit]:
        """Step 3: pre-screen and commit the alerts at once (FR-12, NFR-05).

        The commit is the requirement. A hit for a rule the clinic has not defined
        cannot be stored — `rule_code` is a foreign key — so it is skipped with a
        warning and still counts toward the safety floor, which works from the
        returned hits rather than from the rows.
        """
        self._stage(JobStage.SCREEN)
        stage = self._pipeline.red_flag_screener
        hits = stage.screen(text, case.species, case.sex)
        self._measured("screen", stage)

        known = self._repo.known_rule_codes([hit.rule_code for hit in hits])
        for hit in hits:
            if hit.rule_code not in known:
                logger.warning(
                    "red-flag hit for an unknown rule code; no alert row written",
                    extra={**self._log_context(), "rule_code": hit.rule_code},
                )
                continue
            self._repo.insert_red_flag_alert(self._case_id, hit)
            # The matched text is not audited: it is a substring of the owner's
            # description, and the audit log cannot be corrected (CLAUDE.md §9).
            self._record(
                AuditAction.RED_FLAG_ALERT,
                {"rule_code": hit.rule_code, "min_category": hit.min_category.value},
            )

        self._session.commit()
        if hits:
            logger.info(
                "red-flag alerts written",
                extra={**self._log_context(), "hits": len(hits)},
            )
        return hits

    def _extract(self, case: CaseRunInput, text: str) -> ExtractionOutput:
        """Step 4: extract, retrying unusable output only (FR-15, IR-19)."""
        self._stage(JobStage.EXTRACT)
        stage = self._pipeline.extractor
        return self._attempt(
            "extract",
            stage,
            _EXTRACTION_REASONS,
            lambda: stage.extract(text, case.species, case.signalment),
        )

    def _store_extraction(self, case: CaseRunInput, extraction: ExtractionOutput) -> uuid.UUID:
        """Step 5: store the extraction and its complaint rows, then commit."""
        stage = self._pipeline.extractor
        known = self._repo.known_complaint_codes(
            [complaint.code for complaint in extraction.presenting_complaints] + ["OTHER"]
        )
        row = self._repo.insert_extraction(
            case_id=self._case_id,
            version=self._repo.next_extraction_version(self._case_id),
            extraction=extraction,
            model_id=stage.model_id,
            prompt_version=stage.prompt_version,
            latency_ms=self._stage_ms.get("extract"),
            complaint_codes=PipelineRepository.mapped_complaints(extraction, known),
        )
        self._session.commit()
        return row.id

    def _retrieve(self, extraction: ExtractionOutput, kb_version_id: uuid.UUID) -> list[Passage]:
        """Step 6a: retrieve the supporting passages (FR-19)."""
        self._stage(JobStage.RETRIEVE)
        stage = self._pipeline.retriever
        try:
            passages = stage.retrieve(extraction, kb_version_id, self._config.top_k)
        except RetrievalFailed:
            self._measured("retrieve", stage)
            raise _StageFailure(FailureReason.RETRIEVAL_FAILED) from None
        self._measured("retrieve", stage)
        return passages

    def _generate(
        self, extraction: ExtractionOutput, passages: list[Passage]
    ) -> DraftRecommendation:
        """Step 6b: generate a draft, with the same retry rule as extraction.

        The draft is never the stored category: the deterministic validator
        produces that (ADR-09).
        """
        self._stage(JobStage.GENERATE)
        stage = self._pipeline.generator
        return self._attempt(
            "generate",
            stage,
            _GENERATION_REASONS,
            lambda: stage.generate(extraction, passages),
        )

    def _attempt(
        self,
        name: str,
        stage: object,
        reasons: tuple[tuple[type[Exception], FailureReason], ...],
        call: "Callable[[], _T]",
    ) -> "_T":
        """Call a model stage, retrying unusable output `max_retries` times.

        Shared by extraction and generation, because the retry rule is the same for
        both and is a property of the orchestrator rather than of either stage
        (FR-15, IR-19). The latency is recorded after every attempt, including a
        failed one: an attempt that timed out still took time, and the stored
        provenance should say so.
        """
        attempts = max(1, self._config.max_retries + 1)
        last_reason = reasons[-1][1]

        for attempt in range(1, attempts + 1):
            try:
                value = call()
            except Exception as error:
                self._measured(name, stage)
                reason = _reason_for(error, reasons)
                if reason is None:
                    raise
                last_reason = reason
                if isinstance(error, LLMInvalidOutput) and attempt < attempts:
                    logger.info(
                        "stage returned unusable output; retrying",
                        extra={**self._log_context(), "stage": name, "attempt": attempt},
                    )
                    continue
                logger.warning(
                    "stage failed",
                    extra={
                        **self._log_context(),
                        "stage": name,
                        "attempts": attempt,
                        "reason": str(reason),
                    },
                )
                raise _StageFailure(reason) from None
            else:
                self._measured(name, stage)
                return value

        # Unreachable: the loop either returns or raises. Here so the function has
        # no implicit `None` return for a type checker to worry about.
        raise _StageFailure(last_reason)

    def _store_recommendation(
        self,
        *,
        case: CaseRunInput,
        extraction_id: uuid.UUID,
        kb_version_id: uuid.UUID,
        passages: list[Passage],
        final: FinalRecommendation,
    ) -> None:
        """Steps 7 and 8: the recommendation, its references and its provenance."""
        stage = self._pipeline.generator
        recommendation = self._repo.insert_recommendation(
            case_id=self._case_id,
            extraction_id=extraction_id,
            kb_version_id=kb_version_id,
            version=self._repo.next_recommendation_version(self._case_id),
            category=final.category,
            rationale=final.rationale,
            confidence=final.confidence,
            safety_floor_applied=final.safety_floor_applied,
            safety_floor_rule_codes=final.safety_floor_rule_codes,
            low_confidence_reasons=final.low_confidence_reasons,
            model_id=stage.model_id,
            prompt_version=stage.prompt_version,
            params=self._params(),
            latency_ms=self._stage_ms.get("generate"),
        )
        self._repo.insert_retrieved_references(
            recommendation_id=recommendation.id,
            passages=passages,
            # From the *validated* ranks, so a rank the model invented is never
            # stored as a citation (FR-22).
            cited=citation_flags(passages, final.cited_ranks),
            storable_chunk_ids=self._repo.known_chunk_ids(
                [passage.chunk_id for passage in passages]
            ),
        )

    def _finish(self, final: FinalRecommendation) -> PipelineRunResult:
        """Step 9: `AWAITING_REVIEW`, audit `RECOMMENDATION_CREATED`, commit.

        The audit entry carries the decision and nothing a reviewer typed or a
        model wrote: no rationale, no description, no passage text (CLAUDE.md §9).
        """
        self._repo.set_status(self._case_id, CaseStatus.AWAITING_REVIEW)
        self._record(
            AuditAction.RECOMMENDATION_CREATED,
            {
                "status": CaseStatus.AWAITING_REVIEW.value,
                "category": final.category.value,
                "confidence": final.confidence.value,
                "safety_floor_applied": final.safety_floor_applied,
                "safety_floor_rule_codes": list(final.safety_floor_rule_codes),
                "low_confidence_reasons": list(final.low_confidence_reasons),
                "cited_rank_count": len(final.cited_ranks),
            },
        )
        self._session.commit()
        self._stage(JobStage.DONE)
        logger.info(
            "triage pipeline finished",
            extra={
                **self._log_context(),
                "category": final.category.value,
                "confidence": final.confidence.value,
                "safety_floor_applied": final.safety_floor_applied,
                "stage_ms": dict(self._stage_ms),
            },
        )
        return PipelineRunResult(self._case_id, CaseStatus.AWAITING_REVIEW)

    # --- The failure path (NFR-09) ----------------------------------------

    def _fail(self, reason: FailureReason) -> PipelineRunResult:
        """`MANUAL_TRIAGE_REQUIRED`, audit `PIPELINE_FAILED`, commit.

        The transaction is rolled back first: this is reached from a handler that
        may have caught anything, including a database error that left the session
        unusable. Alerts committed in step 3 survive that rollback, which is the
        point of committing them when they are written.

        Written defensively — if even this cannot be stored, the case would be
        stuck in `PROCESSING`, so the second failure is logged and the reason is
        still returned so the job is marked `FAILED`.
        """
        self._session.rollback()
        try:
            self._repo.set_status(self._case_id, CaseStatus.MANUAL_TRIAGE_REQUIRED)
            self._record(
                AuditAction.PIPELINE_FAILED,
                {
                    "status": CaseStatus.MANUAL_TRIAGE_REQUIRED.value,
                    "reason": str(reason),
                    "failed_at": datetime.now(UTC).isoformat(),
                },
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            logger.exception(
                "triage pipeline could not record the failure path",
                extra={**self._log_context(), "reason": str(reason)},
            )
        else:
            self._stage(JobStage.FAILED)
            logger.warning(
                "triage pipeline failed; case sent to manual triage",
                extra={**self._log_context(), "reason": str(reason)},
            )
        return PipelineRunResult(self._case_id, CaseStatus.MANUAL_TRIAGE_REQUIRED, reason)

    # --- Internals --------------------------------------------------------

    def _params(self) -> dict:
        """The run's parameters, stored with the recommendation (FR-26, ADR-14).

        `stage_ms` is every stage's measured wall time, including the ones that are
        not model calls: FR-68 reports p50 and p95 per stage, and "retrieval took
        no time because it was mocked" is itself a result worth being able to read
        back.
        """
        return {
            "top_k": self._config.top_k,
            "temperature": self._config.temperature,
            "timeout_s": self._config.timeout_s,
            "max_retries": self._config.max_retries,
            "retrieval_min_score": self._config.retrieval_min_score,
            "stage_ms": dict(self._stage_ms),
        }

    def _measured(self, name: str, stage: object) -> None:
        """Copy a stage's `last_latency_ms` into `stage_ms` (CLAUDE.md §8.2).

        Read immediately after the call, including after a failed one: an attempt
        that timed out still took time, and the stored provenance should say so.
        """
        self._stage_ms[name] = int(getattr(stage, "last_latency_ms", 0) or 0)

    def _stage(self, stage: JobStage) -> None:
        """Record progress on the job, for `GET /cases/{id}/status` (IR-22)."""
        if self._job_id is not None:
            self._jobs.set_stage(self._job_id, stage)

    def _record(self, action: AuditAction, after: dict) -> None:
        """Append one audit entry for this case.

        No `user_id` and no `role`: the pipeline is not a person. The decision a
        person makes about this recommendation is audited separately, in P06.
        """
        self._audit.record(
            action=action,
            entity_type=CASE_ENTITY,
            entity_id=str(self._case_id),
            after=after,
        )

    def _log_context(self) -> dict:
        """Identifiers and nothing else (CLAUDE.md §9)."""
        return {
            "case_id": str(self._case_id),
            "job_id": str(self._job_id) if self._job_id else None,
        }
