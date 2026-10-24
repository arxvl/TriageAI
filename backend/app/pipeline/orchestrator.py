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
9. **`AWAITING_REVIEW`, audit `RECOMMENDATION_CREATED`, enqueue
   `SUGGEST_ACTIONS`** — category and confidence only, never the text
   (CLAUDE.md §9).

`run_actions(recommendation_id)` is the second entry point, called by the worker
for that enqueued job. It reads the stored recommendation, extraction and
passages back, asks the `ActionSuggester` for tailored actions, screens them with
the deterministic action validator and stores what survives beside the baseline
set. **It never reads or writes the case status.** A reviewer can already see the
category by the time it runs, so its failure is recorded on
`recommendations.actions_status` and nothing else moves (FR-77, NFR-29,
ADR-18 §3).

`regenerate(case_id, extraction_id)` is the third entry point (P07 §7.2, FR-27). A
reviewer corrected the extracted information, and this makes the next
recommendation version from it: retrieval, generation and the safety validator
only. **De-identification, the red-flag screen and extraction are never called**
— the description has not changed, and the alerts the first run stored are the
record of what the pre-screen found. A failure here puts the case back in
`AWAITING_REVIEW` with the previous recommendation still current, because that
recommendation is still a valid thing to decide on (NFR-09, NFR-11).

Any failure takes the failure path: `MANUAL_TRIAGE_REQUIRED`, a reason code the
worker writes into the job's `last_error`, audit `PIPELINE_FAILED`. A case is
never lost and never left in `PROCESSING` (NFR-09, ADR-08) — which is why the
outermost handler catches `Exception` and not only `PipelineError`.

**Nothing in this module is AI.** Every stage is called through the Protocols in
`app.pipeline.stages`, and the only decision made here is which of them to call
next (CLAUDE.md §8).
"""

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, TypeVar

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.jobs.queue import JobQueue, JobStage
from app.models import (
    ActionSource,
    ActionsStatus,
    CaseStatus,
    JobType,
    Recommendation,
    Species,
    VTLCategory,
)
from app.pipeline.action_validator import baseline_actions
from app.pipeline.action_validator import validate as validate_actions
from app.pipeline.config import PipelineConfig
from app.pipeline.errors import (
    ActionsFailed,
    ExtractionFailed,
    GenerationFailed,
    LLMInvalidOutput,
    LLMTimeout,
    LLMUnavailable,
    RetrievalFailed,
)
from app.pipeline.safety import SafetyValidator, citation_flags, reviewer_red_flag_hits
from app.pipeline.stages import (
    ActionSuggester,
    Deidentifier,
    EntityExtractor,
    KBIndexer,
    RecommendationGenerator,
    RedFlagScreener,
    Retriever,
)
from app.pipeline.types import (
    ActionPlan,
    DraftRecommendation,
    ExtractionOutput,
    FinalRecommendation,
    Passage,
    RedFlagHit,
    SuggestedAction,
)
from app.repositories.pipeline_repository import (
    FIRST_ACTION_GENERATION,
    ActionsRunInput,
    ActionSuggestionValues,
    CaseRunInput,
    PipelineRepository,
)
from app.services.audit_service import CASE_ENTITY, AuditAction, AuditService

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.pipeline.registry import PipelineDeps

logger = logging.getLogger(__name__)

__all__ = [
    "ACTIONS_JOB_CATEGORY_KEY",
    "ACTIONS_JOB_GENERATION_KEY",
    "ACTIONS_JOB_RECOMMENDATION_KEY",
    "BASELINE_MODEL_ID",
    "BASELINE_PROMPT_VERSION",
    "ActionsFailureReason",
    "ActionsRunResult",
    "FailureReason",
    "PipelineRunResult",
    "TriagePipeline",
]

# What `action_suggestions` records as the provenance of a baseline row. These
# rows are curated knowledge-base content, not model output: their real
# provenance is `kb_version_id` and the `URGENCY_ACTIONS` entry it pins
# (FR-72, ADR-18 §2). Labelling them "mock" would make a *real* run's baseline
# rows look mocked, and labelling them with the actions stage's model id would
# claim a model wrote them.
BASELINE_MODEL_ID = "baseline"
BASELINE_PROMPT_VERSION = "kb"

# Where a `SUGGEST_ACTIONS` job carries the recommendation it is about. In the
# payload rather than a column: `jobs` points at a case or a vignette, and this
# job is about one *version* of that case's recommendation (ADR-14).
ACTIONS_JOB_RECOMMENDATION_KEY = "recommendation_id"

# A regeneration for a changed category (P07 §7.2b, FR-78) also carries the
# category the reviewer settled on and the number of the set it will store. Both
# are chosen when the job is enqueued, so a re-run after a crash replaces its own
# set rather than adding another. The first run sends neither: it is for the
# recommendation's own category, as generation 1.
ACTIONS_JOB_CATEGORY_KEY = "category"
ACTIONS_JOB_GENERATION_KEY = "generation"

_T = TypeVar("_T")


class FailureReason(StrEnum):
    """Why a run ended in `MANUAL_TRIAGE_REQUIRED` (NFR-09, P07 §7.1 task 1).

    Codes, not prose. They go into `jobs.last_error`, into the `PIPELINE_FAILED`
    audit entry and into the W-06 banner, whose wording lives in
    `app.pipeline.messages`. None of them may contain a model response, a prompt
    or an owner description (CLAUDE.md §9).

    The `LLM_*` codes say what the model call did, whichever stage made it: a
    reviewer deciding whether to retry needs to know the model did not answer, not
    which of two stages was waiting. What a code does not say stays in the log,
    as identifiers and timings — `INTERNAL_ERROR` covers a bug here and the two
    preconditions a deployment can get wrong (no description row, no knowledge-base
    version).
    """

    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_INVALID_OUTPUT = "LLM_INVALID_OUTPUT"
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    GENERATION_FAILED = "GENERATION_FAILED"
    # Fails closed: the run stops before any stage that could send text anywhere
    # (IR-20, ADR-10).
    DEIDENTIFICATION_FAILED = "DEIDENTIFICATION_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # Returned without touching a case, so it never reaches a reviewer.
    CASE_NOT_FOUND = "CASE_NOT_FOUND"


class ActionsFailureReason(StrEnum):
    """Why a `SUGGEST_ACTIONS` job did not produce tailored actions (FR-77).

    Separate from `FailureReason` because the consequence is different in kind:
    none of these touches the case. The case keeps the category it already has,
    stays in `AWAITING_REVIEW` and shows its baseline actions on their own
    (ADR-18 §3). The code lands in `recommendations.actions_error` and in the
    job's `last_error`, and it is what the W-04 panel turns into one quiet line
    rather than an error dialog (P06).

    Codes, never a model message — a message could carry action text (SR-17).
    """

    RECOMMENDATION_NOT_FOUND = "RECOMMENDATION_NOT_FOUND"
    # The stored extraction could not be read back into the contract. A row
    # written by an older version of the contract, not a model failure.
    ACTIONS_INPUT_UNUSABLE = "ACTIONS_INPUT_UNUSABLE"
    ACTIONS_TIMEOUT = "ACTIONS_TIMEOUT"
    ACTIONS_UNAVAILABLE = "ACTIONS_UNAVAILABLE"
    ACTIONS_INVALID_OUTPUT = "ACTIONS_INVALID_OUTPUT"
    # The stage proposed actions and the validator kept none of them. Not an
    # exception: the job did its work and the answer was unusable, which is a
    # prompt problem to fix in M6b rather than a reason to loosen a rule
    # (ADR-18 §4).
    ACTIONS_ALL_REJECTED = "ACTIONS_ALL_REJECTED"
    ACTIONS_UNEXPECTED_ERROR = "ACTIONS_UNEXPECTED_ERROR"


# Which reason code each stage reports for each failure. Both model stages are
# retried on `LLMInvalidOutput` and only on that: a draft that does not match its
# schema is as transient as an extraction that does not, while a timeout under load
# is not transient and retrying one would spend the job's budget waiting (FR-15,
# IR-19). First match wins, so the stage's own error is listed last.
#
# A stage's own failure comes last, and `_reason_for` reads the cause chain before
# it falls back to it: a real stage raises `ExtractionFailed from LLMTimeout`, and
# the timeout is what the reviewer needs to hear. A bare `ExtractionFailed` is the
# stage saying it could not produce a usable extraction, which from outside is
# unusable output.
_EXTRACTION_REASONS: tuple[tuple[type[Exception], "FailureReason"], ...] = (
    (LLMInvalidOutput, FailureReason.LLM_INVALID_OUTPUT),
    (LLMTimeout, FailureReason.LLM_TIMEOUT),
    (LLMUnavailable, FailureReason.LLM_UNAVAILABLE),
    (ExtractionFailed, FailureReason.LLM_INVALID_OUTPUT),
)

_GENERATION_REASONS: tuple[tuple[type[Exception], "FailureReason"], ...] = (
    (LLMInvalidOutput, FailureReason.LLM_INVALID_OUTPUT),
    (LLMTimeout, FailureReason.LLM_TIMEOUT),
    (LLMUnavailable, FailureReason.LLM_UNAVAILABLE),
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


@dataclass(frozen=True)
class ActionsRunResult:
    """What one actions run did, for the worker that called it.

    Carries no case status, deliberately: this job does not read or write one
    (FR-77). `actions_status` is what was recorded on the recommendation, and the
    worker turns `failure_reason` into the job's `last_error` exactly as it does
    for a triage run.
    """

    recommendation_id: uuid.UUID
    actions_status: ActionsStatus | None
    failure_reason: ActionsFailureReason | None = None
    baseline_count: int = 0
    tailored_count: int = 0
    rejected_count: int = 0

    @property
    def succeeded(self) -> bool:
        return self.failure_reason is None


def _actions_reason(error: Exception) -> ActionsFailureReason | None:
    """The reason code for a failure of the actions stage.

    The stage's declared failure is `ActionsFailed`, and a stage that wrapped a
    provider error chains it — `raise ActionsFailed(...) from error` — so the
    cause is read to tell a timeout from unusable output. The chain is inspected
    rather than the message, because a message may quote model output and must
    never be parsed into behaviour (SR-17).

    A bare `ActionsFailed` with nothing chained means the stage could not answer
    and did not say why, which is `ACTIONS_UNAVAILABLE`.
    """
    for candidate in (error, error.__cause__):
        if isinstance(candidate, LLMTimeout):
            return ActionsFailureReason.ACTIONS_TIMEOUT
        if isinstance(candidate, LLMInvalidOutput):
            return ActionsFailureReason.ACTIONS_INVALID_OUTPUT
        if isinstance(candidate, LLMUnavailable):
            return ActionsFailureReason.ACTIONS_UNAVAILABLE
    if isinstance(error, ActionsFailed):
        return ActionsFailureReason.ACTIONS_UNAVAILABLE
    return None


def _reason_for(
    error: Exception, reasons: tuple[tuple[type[Exception], FailureReason], ...]
) -> FailureReason | None:
    """The reason code for this error, or None if the stage did not raise one of
    its declared failures — which is a bug, and must not be disguised as a
    pipeline failure."""
    # The error itself, then what it was raised from. Each is checked against the
    # whole table in order, so a transport cause wins over the stage's own wrapper.
    for candidate in (error, error.__cause__):
        for error_type, reason in reasons[:-1]:
            if isinstance(candidate, error_type):
                return reason
    if isinstance(error, reasons[-1][0]):
        return reasons[-1][1]
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


class _Cancelled(Exception):
    """Internal: the worker gave up on this run and failed the case itself.

    Raised at a checkpoint when the job's cancel event is set, so a run that
    outlived its budget stops without writing a recommendation over the failure
    the worker already recorded (P07 §7.1 task 5). Never raised out of `run`.
    """


class _ActionsFailure(Exception):
    """Internal: the actions run must take its failure path.

    The counterpart of `_StageFailure`, kept separate so neither path can be
    mistaken for the other: this one never touches the case.
    """

    def __init__(self, reason: ActionsFailureReason) -> None:
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
    # Not called by a triage run either. It runs in the `SUGGEST_ACTIONS` job
    # that `run` enqueues, through `run_actions` below (ADR-18 §3).
    action_suggester: ActionSuggester
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
                self.action_suggester,
            )
        )

    def run(
        self,
        case_id: uuid.UUID,
        *,
        job_id: uuid.UUID | None = None,
        cancel: threading.Event | None = None,
    ) -> PipelineRunResult:
        """Triage one case, end to end. Never raises.

        `job_id` is optional so the pipeline can be driven without the queue — the
        evaluation harness does that (M7) — and when it is given, each step's
        progress is recorded on the job for `GET /cases/{id}/status` (IR-22).

        `cancel` is set by the worker when the job has run past its budget and the
        worker has already failed the case. The run checks it between steps and
        stops without writing anything more (P07 §7.1 task 5). A call that is
        blocked inside a stage cannot be interrupted; it is bounded by the
        provider's own `timeout_s`, and its result is discarded at the next check.

        A session is opened here rather than passed in, because a run commits
        several times and must not be inside anybody else's transaction. It comes
        from `deps.session_factory`, which the registry accepts an override for.
        """
        with self.deps.session_factory() as session:
            return _TriageRun(self, session, case_id, job_id, cancel).execute()

    def fail_timed_out(
        self, case_id: uuid.UUID, *, job_id: uuid.UUID | None = None
    ) -> PipelineRunResult:
        """Take the failure path for a run the worker has given up waiting for.

        The same path every other failure takes — `MANUAL_TRIAGE_REQUIRED`, audit
        `PIPELINE_FAILED` — so a job that exceeded `2 × timeout_s + 10` leaves the
        case exactly where a model timeout would (NFR-09, P07 §7.1 task 5). Never
        raises.
        """
        with self.deps.session_factory() as session:
            return _TriageRun(self, session, case_id, job_id).fail(FailureReason.LLM_TIMEOUT)

    def regenerate(
        self,
        case_id: uuid.UUID,
        extraction_id: uuid.UUID,
        *,
        job_id: uuid.UUID | None = None,
        cancel: threading.Event | None = None,
    ) -> PipelineRunResult:
        """Make the next recommendation version from a corrected extraction.

        Never raises. Called by the worker for a `REGENERATE` job, never inside a
        request (ADR-08). Retrieval, generation and the safety validator only; see
        the module docstring. `job_id` and `cancel` are as for `run`.
        """
        with self.deps.session_factory() as session:
            return _RegenerateRun(self, session, case_id, extraction_id, job_id, cancel).execute()

    def fail_regeneration_timed_out(
        self,
        case_id: uuid.UUID,
        extraction_id: uuid.UUID,
        *,
        job_id: uuid.UUID | None = None,
    ) -> PipelineRunResult:
        """The regeneration counterpart of `fail_timed_out`.

        Puts the case back in `AWAITING_REVIEW` with a `REGENERATE_FAILED` entry,
        for a regeneration the worker has stopped waiting for. Never raises.
        """
        with self.deps.session_factory() as session:
            return _RegenerateRun(self, session, case_id, extraction_id, job_id).fail(
                FailureReason.LLM_TIMEOUT
            )

    def run_actions(
        self,
        recommendation_id: uuid.UUID,
        *,
        job_id: uuid.UUID | None = None,
        category: VTLCategory | None = None,
        generation: int = FIRST_ACTION_GENERATION,
    ) -> ActionsRunResult:
        """Suggest actions for one stored recommendation. Never raises.

        Called by the job worker for the `SUGGEST_ACTIONS` job that `run`
        enqueued, never inside a request and never inside the triage run itself
        (ADR-08, ADR-18 §3). By the time this executes the reviewer can already
        see the category: that is the whole point of the split, and it is why
        nothing here may touch the case (FR-77, NFR-29).

        `job_id` is optional for the same reason as in `run` — the evaluation
        harness drives the pipeline without the queue (M7).

        `category` is set when a reviewer asked for suggestions for a category
        other than the one the recommendation was made for (FR-78); the actions
        are then generated for it and stored as set number `generation`, beside
        the earlier set.
        """
        with self.deps.session_factory() as session:
            return _ActionsRun(
                self, session, recommendation_id, job_id, category=category, generation=generation
            ).execute()


class _TriageRun:
    """One run's mutable state: the session, the stage latencies, the job.

    Separate from `TriagePipeline` so the pipeline itself stays frozen and
    shareable between the worker thread and the request handlers.
    """

    # Where the case is left when this kind of run fails. A regeneration
    # overrides it: its failure leaves the previous recommendation standing.
    _FAILED_STATUS = CaseStatus.MANUAL_TRIAGE_REQUIRED

    def __init__(
        self,
        pipeline: TriagePipeline,
        session: Session,
        case_id: uuid.UUID,
        job_id: uuid.UUID | None,
        cancel: threading.Event | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._config = pipeline.config
        self._session = session
        self._repo = PipelineRepository(session)
        self._audit = AuditService(session)
        self._jobs = JobQueue(session)
        self._case_id = case_id
        self._job_id = job_id
        self._cancel = cancel
        # How many times the stage that failed was called, for the banner's
        # "after 2 attempts". None until a model stage has been called.
        self._attempts: int | None = None
        # Per-stage wall time, as `params.stage_ms` on the recommendation (FR-68
        # computes p50/p95 from these).
        self._stage_ms: dict[str, int] = {}

    # --- Entry point -------------------------------------------------------

    def execute(self) -> PipelineRunResult:
        try:
            return self._run()
        except _Cancelled:
            # The worker has recorded the failure; writing anything now would
            # overwrite it. Whatever this run had not committed is dropped.
            self._session.rollback()
            logger.warning("triage pipeline cancelled after its budget", extra=self._log_context())
            return PipelineRunResult(self._case_id, self._FAILED_STATUS, FailureReason.LLM_TIMEOUT)
        except _StageFailure as failure:
            return self._fail(failure.reason)
        except Exception:
            # The guarantee is that no case is lost and none is left in
            # PROCESSING (NFR-09). A bug in this module must not be the exception
            # to it, so the net is `Exception` and the traceback goes to the log,
            # not to the case.
            logger.exception("triage pipeline raised", extra=self._log_context())
            return self._fail(FailureReason.INTERNAL_ERROR)

    def fail(self, reason: FailureReason) -> PipelineRunResult:
        """The failure path on its own, for `TriagePipeline.fail_timed_out`."""
        return self._fail(reason)

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
        extraction_row_id = self._store_extraction(case, text, extraction)

        kb_version_id = self._repo.latest_kb_version_id()
        if kb_version_id is None:
            # Nothing to retrieve from means nothing to cite, and FR-22 requires a
            # citation. `scripts/seed.py` creates version 0 for exactly this.
            logger.warning("triage pipeline: no knowledge base version", extra=self._log_context())
            raise _StageFailure(FailureReason.INTERNAL_ERROR)

        passages = self._retrieve(extraction, kb_version_id)
        draft = self._generate(extraction, passages)

        final = SafetyValidator.finalize(draft, passages, red_flag_hits, extraction, self._config)
        recommendation_id = self._store_recommendation(
            case=case,
            extraction_id=extraction_row_id,
            kb_version_id=kb_version_id,
            passages=passages,
            final=final,
        )
        return self._finish(final, recommendation_id)

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

        **Any** exception from the stage is a de-identification failure, not only
        `DeidentificationFailed`: a bug in the de-identifier is as unsafe as a
        refusal, and the run must stop before the screener, the extractor and the
        model either way.
        """
        self._stage(JobStage.DEIDENTIFY)
        stage = self._pipeline.deidentifier
        try:
            text = stage.deidentify(
                case.description,
                *self._repo.owner_reference_for_deidentification(self._case_id),
            )
        except Exception as error:
            self._measured("deidentify", stage)
            # Fail closed, whatever was raised: if the text may not be clean, no
            # later stage may see it (IR-20, ADR-10). The class name is logged and
            # nothing else — a de-identifier's message or traceback can quote the
            # very text it failed to clean (CLAUDE.md §9).
            logger.warning(
                "de-identification failed; the run stops before any other stage",
                extra={**self._log_context(), "error_type": type(error).__name__},
            )
            raise _StageFailure(FailureReason.DEIDENTIFICATION_FAILED) from None
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
        phrase = self._config.demo_force_failure_phrase
        if phrase is not None and phrase.lower() in text.lower():
            # The PD8 demo toggle (P07 §7.1 task 7). Taken before the stage is
            # called, so no model call is made, and after the screen has
            # committed, so a red-flag alert still reaches the queue. The config
            # carries a phrase only in `APP_ENV=dev`.
            logger.warning(
                "demo failure phrase matched; forcing a timeout", extra=self._log_context()
            )
            raise _StageFailure(FailureReason.LLM_TIMEOUT)
        return self._attempt(
            "extract",
            stage,
            _EXTRACTION_REASONS,
            lambda: stage.extract(text, case.species, case.signalment),
        )

    def _store_extraction(
        self, case: CaseRunInput, text: str, extraction: ExtractionOutput
    ) -> uuid.UUID:
        """Step 5: store the extraction and its complaint rows, then commit.

        `text` is the de-identified description the extractor was given, stored
        on the row so the review screen can map the evidence spans to character
        offsets later (FR-13, ADR-10). It is the de-identified string and never
        the raw one: raw text does not leave the de-identifier.
        """
        self._checkpoint()
        stage = self._pipeline.extractor
        known = self._repo.known_complaint_codes(
            [complaint.code for complaint in extraction.presenting_complaints] + ["OTHER"]
        )
        row = self._repo.insert_extraction(
            case_id=self._case_id,
            version=self._repo.next_extraction_version(self._case_id),
            input_text=text,
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
            self._attempts = attempt
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
    ) -> uuid.UUID:
        """Steps 7 and 8: the recommendation, its references and its provenance."""
        self._checkpoint()
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
        return recommendation.id

    def _finish(
        self, final: FinalRecommendation, recommendation_id: uuid.UUID
    ) -> PipelineRunResult:
        """Step 9: `AWAITING_REVIEW`, audit, enqueue the actions job, commit.

        The audit entry carries the decision and nothing a reviewer typed or a
        model wrote: no rationale, no description, no passage text (CLAUDE.md §9).

        The `SUGGEST_ACTIONS` job is enqueued in *this* transaction, so a
        recommendation that is visible to a reviewer always has an actions job
        behind it and a rolled-back run leaves neither (ADR-08). The stage is
        never called here: a third model call inside this job would spend the
        recommendation's latency budget on something a reviewer does not have to
        wait for (NFR-29, ADR-18 §3).
        """
        self._checkpoint()
        self._repo.set_status(self._case_id, CaseStatus.AWAITING_REVIEW)
        self._repo.set_actions_status(recommendation_id, ActionsStatus.PENDING)
        self._record(
            AuditAction.RECOMMENDATION_CREATED,
            {
                "status": CaseStatus.AWAITING_REVIEW.value,
                # The row this entry is about, as the actions entries already
                # carry theirs: an audit entry that cannot be tied back to the
                # recommendation it describes is a weaker record, and the P06
                # timeline reads the reference count through it (FR-26, FR-45).
                "recommendation_id": str(recommendation_id),
                "category": final.category.value,
                "confidence": final.confidence.value,
                "safety_floor_applied": final.safety_floor_applied,
                "safety_floor_rule_codes": list(final.safety_floor_rule_codes),
                "low_confidence_reasons": list(final.low_confidence_reasons),
                "cited_rank_count": len(final.cited_ranks),
            },
        )
        # TODO(manual:M7): the evaluation harness runs a vignette rather than a
        # case; when that run path exists it enqueues this job the same way, with
        # `vignette_id` instead of `case_id`. The storage and the run itself
        # already accept either (see `ActionsRunInput`).
        self._jobs.enqueue(
            JobType.SUGGEST_ACTIONS,
            case_id=self._case_id,
            payload={ACTIONS_JOB_RECOMMENDATION_KEY: str(recommendation_id)},
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
        if self._cancel is not None and self._cancel.is_set():
            # The worker has already recorded a failure for this run.
            return PipelineRunResult(self._case_id, self._FAILED_STATUS, reason)
        try:
            self._repo.set_status(self._case_id, CaseStatus.MANUAL_TRIAGE_REQUIRED)
            self._record(
                AuditAction.PIPELINE_FAILED,
                {
                    "status": CaseStatus.MANUAL_TRIAGE_REQUIRED.value,
                    "reason": str(reason),
                    "attempts": self._attempts,
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
        return PipelineRunResult(self._case_id, self._FAILED_STATUS, reason)

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

    def _checkpoint(self) -> None:
        """Stop here if the worker has already failed this run (P07 §7.1 task 5)."""
        if self._cancel is not None and self._cancel.is_set():
            raise _Cancelled

    def _stage(self, stage: JobStage) -> None:
        """Record progress on the job, for `GET /cases/{id}/status` (IR-22).

        Also the checkpoint every step passes through before it starts.
        """
        self._checkpoint()
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


class _RegenerateRun(_TriageRun):
    """One `REGENERATE` job's state (P07 §7.2, FR-27, UC-09).

    A `_TriageRun` that starts from a stored, corrected extraction instead of a
    description, so everything from retrieval onward — the retry rule, the
    checkpoints, the provenance, the safety validator — is the code a first run
    uses, not a copy of it. What it skips is the point: the description is not
    read, nothing is de-identified, no model is asked to extract, and the
    red-flag screener is not run.

    The case is `PROCESSING` when this starts (the correction put it there, in
    the same transaction as the job), which is what kept a decision from being
    recorded on the recommendation this one supersedes. It ends in
    `AWAITING_REVIEW` either way. The status is only ever moved *from*
    `PROCESSING`: a case that is anywhere else was not waiting on this job, and
    a decided category is never touched by a regeneration (NFR-11).
    """

    _FAILED_STATUS = CaseStatus.AWAITING_REVIEW

    def __init__(
        self,
        pipeline: TriagePipeline,
        session: Session,
        case_id: uuid.UUID,
        extraction_id: uuid.UUID,
        job_id: uuid.UUID | None,
        cancel: threading.Event | None = None,
    ) -> None:
        super().__init__(pipeline, session, case_id, job_id, cancel)
        self._extraction_id = extraction_id

    def _run(self) -> PipelineRunResult:
        case = self._repo.case_for_run(self._case_id)
        if case is None:
            logger.error("regeneration: case not found", extra=self._log_context())
            return PipelineRunResult(self._case_id, None, FailureReason.CASE_NOT_FOUND)

        if case.status is not CaseStatus.PROCESSING:
            # Not waiting on this job: decided, closed, or already restored by an
            # earlier attempt of the same job. Nothing to do and nothing to move.
            logger.warning(
                "regeneration: case is not waiting for one; nothing done",
                extra={**self._log_context(), "status": case.status.value},
            )
            return PipelineRunResult(self._case_id, case.status)

        if self._repo.has_recommendation_for_extraction(self._extraction_id):
            # A previous attempt of this job stored its recommendation and was
            # lost before it restored the status (ADR-08). Writing a second
            # version for the same extraction would only duplicate it.
            self._repo.set_status_if(
                self._case_id, CaseStatus.PROCESSING, CaseStatus.AWAITING_REVIEW
            )
            self._session.commit()
            return PipelineRunResult(self._case_id, CaseStatus.AWAITING_REVIEW)

        extraction = self._stored_extraction()
        hits = self._safety_floor_hits(case.species, extraction)

        kb_version_id = self._repo.latest_kb_version_id()
        if kb_version_id is None:
            logger.warning("regeneration: no knowledge base version", extra=self._log_context())
            raise _StageFailure(FailureReason.INTERNAL_ERROR)

        passages = self._retrieve(extraction, kb_version_id)
        draft = self._generate(extraction, passages)

        final = SafetyValidator.finalize(draft, passages, hits, extraction, self._config)
        recommendation_id = self._store_recommendation(
            case=case,
            extraction_id=self._extraction_id,
            kb_version_id=kb_version_id,
            passages=passages,
            final=final,
        )
        return self._finish_regeneration(final, recommendation_id)

    # --- Steps -------------------------------------------------------------

    def _stored_extraction(self) -> ExtractionOutput:
        """The corrected extraction, read back from its row."""
        entities = self._repo.extraction_entities(self._case_id, self._extraction_id)
        if entities is None:
            logger.error("regeneration: extraction not found", extra=self._log_context())
            raise _StageFailure(FailureReason.INTERNAL_ERROR)
        try:
            return ExtractionOutput.model_validate(entities)
        except ValidationError:
            logger.warning(
                "regeneration: stored extraction does not match the contract",
                extra=self._log_context(),
            )
            raise _StageFailure(FailureReason.INTERNAL_ERROR) from None

    def _safety_floor_hits(
        self, species: Species, extraction: ExtractionOutput
    ) -> list[RedFlagHit]:
        """The red-flag hits the safety floor works from (FR-23).

        The case's stored alerts, plus any red flag on the corrected extraction
        that names a rule. The second source is the exact-label match in
        `reviewer_red_flag_hits`: the screener is not run again, so a flag a
        reviewer typed counts only if it is a rule's label word for word.
        """
        hits = self._repo.stored_red_flag_hits(self._case_id)
        hits += reviewer_red_flag_hits(
            extraction.red_flags, self._pipeline.deps.rules_provider(), species
        )
        return hits

    def _finish_regeneration(
        self, final: FinalRecommendation, recommendation_id: uuid.UUID
    ) -> PipelineRunResult:
        """`AWAITING_REVIEW`, audit, enqueue the actions job, commit.

        As `_finish` for a first run, with its own audit action so the timeline
        can say "regenerated after correction". The actions job is enqueued for
        the *new* recommendation: the earlier version keeps the suggestions it
        was made with (ADR-14).
        """
        self._checkpoint()
        self._repo.set_status_if(self._case_id, CaseStatus.PROCESSING, CaseStatus.AWAITING_REVIEW)
        self._repo.set_actions_status(recommendation_id, ActionsStatus.PENDING)
        stored = self._session.get(Recommendation, recommendation_id)
        self._record(
            AuditAction.RECOMMENDATION_REGENERATED,
            {
                "status": CaseStatus.AWAITING_REVIEW.value,
                "recommendation_id": str(recommendation_id),
                "recommendation_version": None if stored is None else stored.version,
                "extraction_id": str(self._extraction_id),
                "category": final.category.value,
                "confidence": final.confidence.value,
                "safety_floor_applied": final.safety_floor_applied,
                "safety_floor_rule_codes": list(final.safety_floor_rule_codes),
                "low_confidence_reasons": list(final.low_confidence_reasons),
                "cited_rank_count": len(final.cited_ranks),
            },
        )
        self._jobs.enqueue(
            JobType.SUGGEST_ACTIONS,
            case_id=self._case_id,
            payload={ACTIONS_JOB_RECOMMENDATION_KEY: str(recommendation_id)},
        )
        self._session.commit()
        self._stage(JobStage.DONE)
        logger.info(
            "regeneration finished",
            extra={
                **self._log_context(),
                "category": final.category.value,
                "safety_floor_applied": final.safety_floor_applied,
                "stage_ms": dict(self._stage_ms),
            },
        )
        return PipelineRunResult(self._case_id, CaseStatus.AWAITING_REVIEW)

    # --- The failure path --------------------------------------------------

    def _fail(self, reason: FailureReason) -> PipelineRunResult:
        """`AWAITING_REVIEW` with the previous recommendation, audit `REGENERATE_FAILED`.

        Not `MANUAL_TRIAGE_REQUIRED`: the case has a valid recommendation that
        the reviewer has not decided on, and taking it away because a second one
        could not be made would make the failure worse than the thing it is
        about. The corrected extraction stays stored, and pressing "Save and
        regenerate" again re-queues it (NFR-09).

        Written defensively, like the triage failure path: if even this cannot be
        stored the case would stay `PROCESSING`, so the second failure is logged
        and the reason is still returned so the job is marked `FAILED`.
        """
        self._session.rollback()
        if self._cancel is not None and self._cancel.is_set():
            return PipelineRunResult(self._case_id, self._FAILED_STATUS, reason)
        try:
            self._repo.set_status_if(
                self._case_id, CaseStatus.PROCESSING, CaseStatus.AWAITING_REVIEW
            )
            self._record(
                AuditAction.REGENERATE_FAILED,
                {
                    "status": CaseStatus.AWAITING_REVIEW.value,
                    "reason": str(reason),
                    "attempts": self._attempts,
                    "extraction_id": str(self._extraction_id),
                    "failed_at": datetime.now(UTC).isoformat(),
                },
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            logger.exception(
                "regeneration could not record the failure path",
                extra={**self._log_context(), "reason": str(reason)},
            )
        else:
            self._stage(JobStage.FAILED)
            logger.warning(
                "regeneration failed; previous recommendation kept",
                extra={**self._log_context(), "reason": str(reason)},
            )
        return PipelineRunResult(self._case_id, self._FAILED_STATUS, reason)

    def _params(self) -> dict:
        return {**super()._params(), "regeneration": True}


class _ActionsRun:
    """One `SUGGEST_ACTIONS` job's state (P05b §5b.3, ADR-18 §3).

    The actions counterpart of `_TriageRun`, and separate from it for one
    reason: **this run must not be able to touch the case.** It holds no
    `case_id` to set a status on and never calls `set_status`, so FR-77 is a
    property of the code rather than a rule someone has to remember.

    The order of the steps, and why:

    1. **Read the inputs back** from the rows the triage run committed —
       extraction and passages, never a fresh retrieval (ADR-14).
    2. **Baseline actions first**, from the `URGENCY_ACTIONS` entry for the
       category. Curated content, so it is read before anything that can fail
       and it is what the reviewer sees when everything after this does fail
       (FR-71, FR-72).
    3. **`suggest`**, once. No retry: a tailored action is best effort by
       design, and spending the job on a second attempt would delay nothing a
       reviewer is waiting for. `MOCK_LLM_BEHAVIOR=flaky` therefore fails this
       job and succeeds when the job itself is retried.
    4. **`validate`**, which is the only thing that screens the text (FR-74).
    5. **Store** baseline and kept rows together, then record the status.

    Nothing in this module is AI. The stage is called through the Protocol in
    `app.pipeline.stages` and the screening is deterministic (CLAUDE.md §8).
    """

    def __init__(
        self,
        pipeline: TriagePipeline,
        session: Session,
        recommendation_id: uuid.UUID,
        job_id: uuid.UUID | None,
        *,
        category: VTLCategory | None = None,
        generation: int = FIRST_ACTION_GENERATION,
    ) -> None:
        self._pipeline = pipeline
        self._config = pipeline.config
        self._session = session
        self._repo = PipelineRepository(session)
        self._audit = AuditService(session)
        self._recommendation_id = recommendation_id
        self._job_id = job_id
        self._category = category
        self._generation = generation
        self._latency_ms: int | None = None

    # --- Entry point -------------------------------------------------------

    def execute(self) -> ActionsRunResult:
        try:
            return self._run()
        except _ActionsFailure as failure:
            return self._fail(failure.reason)
        except Exception:
            # Same guarantee as a triage run: a bug here must not leave a
            # recommendation stuck on `PENDING` forever, with the review screen
            # showing a loading row that never resolves (FR-77).
            logger.exception("actions run raised", extra=self._log_context())
            return self._fail(ActionsFailureReason.ACTIONS_UNEXPECTED_ERROR)

    def _read_input(self) -> ActionsRunInput | None:
        """The stored inputs, aimed at the category this run is for.

        A regeneration asked for a category other than the recommendation's
        (FR-78). Everything downstream — the baseline lookup, the stage call, the
        plan, the stored rows and the audit entry — reads `category` from the
        input, so overriding it here is the one place the difference lives.
        """
        stored = self._repo.actions_run_input(self._recommendation_id)
        if stored is not None and self._category is not None:
            stored = replace(stored, category=self._category)
        return stored

    def _run(self) -> ActionsRunResult:
        stored = self._read_input()
        if stored is None:
            # The recommendation was removed between the enqueue and now, which
            # the single-transaction enqueue in `_TriageRun._finish` should make
            # impossible. Nothing to record it on, so it is only reported.
            logger.error("actions run: recommendation not found", extra=self._log_context())
            return ActionsRunResult(
                self._recommendation_id,
                None,
                ActionsFailureReason.RECOMMENDATION_NOT_FOUND,
            )

        extraction = self._extraction(stored)
        baseline = self._baseline(stored)
        proposed = self._suggest(extraction, stored)
        kept, rejection_reasons = validate_actions(
            proposed, stored.passages, self._config.actions_max_items
        )
        plan = ActionPlan(
            category=stored.category,
            baseline=baseline,
            tailored=kept,
            rejected_count=len(rejection_reasons),
            rejection_reasons=rejection_reasons,
        )
        self._store(stored, plan)
        return self._finish(stored, plan, proposed_count=len(proposed))

    # --- Steps -------------------------------------------------------------

    def _extraction(self, stored: ActionsRunInput) -> ExtractionOutput:
        """Rebuild the extraction contract from the stored JSON.

        A row that cannot be read back is a reason code, not a crash: the
        contract may have moved on since an old case was triaged, and the
        baseline actions for that case are still worth having.
        """
        try:
            return ExtractionOutput.model_validate(stored.extraction_entities)
        except ValidationError:
            logger.warning(
                "actions run: stored extraction does not match the contract",
                extra=self._log_context(),
            )
            raise _ActionsFailure(ActionsFailureReason.ACTIONS_INPUT_UNUSABLE) from None

    def _baseline(self, stored: ActionsRunInput) -> list[str]:
        """The baseline set for this category, or `[]` with a warning (FR-72).

        A recommendation with no knowledge-base version cannot have one — the
        lookup is pinned to a version (FR-54) — and that is not a failure of this
        job either.
        """
        if stored.kb_version_id is None:
            logger.warning(
                "actions run: recommendation has no knowledge base version",
                extra=self._log_context(),
            )
            return []
        return baseline_actions(self._session, stored.category, stored.kb_version_id)

    def _suggest(
        self, extraction: ExtractionOutput, stored: ActionsRunInput
    ) -> list[SuggestedAction]:
        """Ask the stage for tailored actions, once.

        The stage is given the extraction, the decided category and the stored
        passages — never the description, not even the de-identified one
        (ADR-18 §5). The latency is recorded even when the call fails, as
        everywhere else in this module.
        """
        stage = self._pipeline.action_suggester
        try:
            actions = stage.suggest(
                extraction,
                stored.category,
                stored.passages,
                self._config.actions_max_items,
            )
        except Exception as error:
            self._measured(stage)
            reason = _actions_reason(error)
            if reason is None:
                # The stage raised something it does not declare, which is a bug
                # in the stage. Let the outer handler log the traceback.
                raise
            logger.warning(
                "actions stage failed",
                extra={**self._log_context(), "reason": str(reason)},
            )
            raise _ActionsFailure(reason) from None
        self._measured(stage)
        return actions

    def _store(self, stored: ActionsRunInput, plan: ActionPlan) -> None:
        """Write the baseline and the kept tailored rows, replacing any earlier
        set.

        One rank sequence over both layers, baseline first: that is the order
        W-04 shows them in, and it makes `order by rank` the display order
        (IR-23).
        """
        stage = self._pipeline.action_suggester
        rows = [
            ActionSuggestionValues(
                rank=rank,
                text=text,
                source=ActionSource.BASELINE,
                # A baseline action's citation is its knowledge-base entry, which
                # is pinned by `kb_version_id` on the row itself. It cites no
                # retrieved passage, because it was not retrieved (FR-72).
                cited_chunk_ids=[],
                model_id=BASELINE_MODEL_ID,
                prompt_version=BASELINE_PROMPT_VERSION,
                latency_ms=None,
            )
            for rank, text in enumerate(plan.baseline, start=1)
        ]
        rows += [
            ActionSuggestionValues(
                rank=rank,
                text=action.text,
                source=action.source,
                cited_chunk_ids=PipelineRepository.cited_chunk_ids(
                    action.cited_ranks, stored.chunk_ids_by_rank
                ),
                model_id=stage.model_id,
                prompt_version=stage.prompt_version,
                latency_ms=self._latency_ms,
            )
            for rank, action in enumerate(plan.tailored, start=len(plan.baseline) + 1)
        ]
        self._repo.replace_action_suggestions(
            recommendation_id=self._recommendation_id,
            case_id=stored.case_id,
            vignette_id=stored.vignette_id,
            category=plan.category,
            kb_version_id=stored.kb_version_id,
            rows=rows,
            generation=self._generation,
        )

    def _finish(
        self, stored: ActionsRunInput, plan: ActionPlan, *, proposed_count: int
    ) -> ActionsRunResult:
        """Record the outcome and commit. The case is not touched (FR-77).

        A stage that proposed actions and had all of them rejected is reported as
        `ACTIONS_ALL_REJECTED`: the rows are still stored — the baseline set is
        valid — but the status says the tailored list is empty for a reason, so a
        high rejection rate is visible as the prompt problem it is (ADR-18 §4).
        A stage that proposed nothing at all failed nothing; the tailored list is
        simply empty.
        """
        all_rejected = proposed_count > 0 and not plan.tailored
        status = ActionsStatus.FAILED if all_rejected else ActionsStatus.READY
        reason = ActionsFailureReason.ACTIONS_ALL_REJECTED if all_rejected else None

        self._repo.set_actions_status(
            self._recommendation_id,
            status,
            error=None if reason is None else str(reason),
            rejected_count=plan.rejected_count,
        )
        self._record(
            AuditAction.ACTIONS_FAILED if all_rejected else AuditAction.ACTIONS_SUGGESTED,
            stored,
            {
                "actions_status": status.value,
                "reason": None if reason is None else str(reason),
                "generated_for_category": plan.category.value,
                "generation": self._generation,
                "baseline_count": len(plan.baseline),
                "tailored_count": len(plan.tailored),
                "rejected_count": plan.rejected_count,
                "rejection_reasons": list(plan.rejection_reasons),
            },
        )
        self._session.commit()
        logger.info(
            "actions run finished",
            extra={
                **self._log_context(),
                "actions_status": status.value,
                "baseline_count": len(plan.baseline),
                "tailored_count": len(plan.tailored),
                "rejected_count": plan.rejected_count,
                "latency_ms": self._latency_ms,
            },
        )
        return ActionsRunResult(
            recommendation_id=self._recommendation_id,
            actions_status=status,
            failure_reason=reason,
            baseline_count=len(plan.baseline),
            tailored_count=len(plan.tailored),
            rejected_count=plan.rejected_count,
        )

    # --- The failure path (FR-77) -----------------------------------------

    def _fail(self, reason: ActionsFailureReason) -> ActionsRunResult:
        """`actions_status = FAILED` with a reason code, and nothing else.

        The case keeps its status and its category. The baseline actions are not
        stored by this path — the API reads them from the knowledge base for the
        case's current category, so they are shown whether this job ever ran or
        not (FR-71, FR-72).

        Written defensively, like the triage failure path: if even the status
        cannot be recorded the recommendation would sit on `PENDING` forever, so
        the second failure is logged and the reason is still returned.
        """
        self._session.rollback()
        stored = self._read_input()
        try:
            self._repo.set_actions_status(
                self._recommendation_id, ActionsStatus.FAILED, error=str(reason)
            )
            if stored is not None:
                self._record(
                    AuditAction.ACTIONS_FAILED,
                    stored,
                    {
                        "actions_status": ActionsStatus.FAILED.value,
                        "reason": str(reason),
                        "generated_for_category": stored.category.value,
                        "generation": self._generation,
                        "failed_at": datetime.now(UTC).isoformat(),
                    },
                )
            self._session.commit()
        except Exception:
            self._session.rollback()
            logger.exception(
                "actions run could not record the failure path",
                extra={**self._log_context(), "reason": str(reason)},
            )
        else:
            logger.warning(
                "actions run failed; baseline actions only",
                extra={**self._log_context(), "reason": str(reason)},
            )
        return ActionsRunResult(self._recommendation_id, ActionsStatus.FAILED, reason)

    # --- Internals --------------------------------------------------------

    def _measured(self, stage: object) -> None:
        """Copy the stage's `last_latency_ms` onto the rows it produced."""
        self._latency_ms = int(getattr(stage, "last_latency_ms", 0) or 0)

    def _record(self, action: AuditAction, stored: ActionsRunInput, after: dict) -> None:
        """Append one audit entry, against the case this recommendation is for.

        Counts and codes only — never an action's text, which is untrusted model
        output and would be permanent here (SR-17, FR-43, ADR-12).

        A vignette run writes no audit entry: an evaluation run is not a clinical
        event and has no case to record it against. It is logged instead (M7).
        """
        if stored.case_id is None:
            return
        self._audit.record(
            action=action,
            entity_type=CASE_ENTITY,
            entity_id=str(stored.case_id),
            after={**after, "recommendation_id": str(self._recommendation_id)},
        )

    def _log_context(self) -> dict:
        """Identifiers and nothing else (CLAUDE.md §9)."""
        return {
            "recommendation_id": str(self._recommendation_id),
            "job_id": str(self._job_id) if self._job_id else None,
        }
