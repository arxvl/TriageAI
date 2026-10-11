"""The suggested-actions job end to end, on mocks (P05b §5b.3, FR-71..FR-79,
NFR-29, NFR-30, SR-17, ADR-18).

Every run here goes through the real orchestrator, the real action validator and
the real database. Only the actions stage is mocked, and it replays
`tests/fixtures/demo_cases.yaml` (ADR-17).

Five properties these tests exist to keep:

1. **The category arrives before the actions.** The triage run stores the
   recommendation, moves the case to `AWAITING_REVIEW` and *enqueues* the actions
   job. A reviewer can act while the actions are still pending (NFR-29,
   ADR-18 §3).
2. **The actions job never touches the case.** Not on any path, not for any
   `MOCK_LLM_BEHAVIOR`. A failure is recorded on the recommendation and the case
   keeps its category and its status (FR-77).
3. **Baseline actions are always there.** They are curated knowledge-base
   content read by category, so they survive a failed job, a job that has not run
   and a model switched off entirely (FR-71, FR-72).
4. **Only validated text is stored.** The stage's output goes through the
   deterministic validator, and what it drops is counted rather than corrected
   (FR-74, ADR-18 §4).
5. **No action text reaches the audit log or the log** (SR-17).

`seed()` runs inside the test transaction because the actions lookup needs the
five `URGENCY_ACTIONS` entries a real deployment seeds. All data is fictitious
(CLAUDE.md §9).
"""

import logging
import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import MockLLMBehavior
from app.jobs.worker import run_pending_jobs_once
from app.models import (
    ActionSource,
    ActionsStatus,
    ActionSuggestion,
    AuditEntry,
    Case,
    CaseStatus,
    Job,
    JobStatus,
    JobType,
    Recommendation,
    User,
    UserRole,
    VTLCategory,
)
from app.pipeline.errors import ActionsFailed
from app.pipeline.orchestrator import (
    ACTIONS_JOB_RECOMMENDATION_KEY,
    BASELINE_MODEL_ID,
    BASELINE_PROMPT_VERSION,
    ActionsFailureReason,
)
from app.pipeline.types import SuggestedAction
from app.services.audit_service import AuditAction
from app.services.case_service import CaseService
from scripts.seed import URGENCY_ACTIONS, seed
from tests.conftest import (
    demo_cases,
    make_case,
    make_demo_case,
    make_owner_description,
    make_recommendation,
    make_user,
)

SEEDED_BASELINE = {category: list(actions) for category, _, actions in URGENCY_ACTIONS}


@pytest.fixture
def seeded(db_session: Session) -> None:
    """Complaints, red-flag rules, KB version 0 and the five baseline entries."""
    seed(db_session)
    db_session.flush()


@pytest.fixture
def reviewer(db_session: Session) -> User:
    return make_user(db_session, role=UserRole.VETERINARY_REVIEWER)


# --- Reads the tests share -------------------------------------------------


def recommendation_of(session: Session, case: Case) -> Recommendation:
    recommendation = session.scalars(
        select(Recommendation)
        .where(Recommendation.case_id == case.id)
        .order_by(Recommendation.version.desc())
    ).first()
    assert recommendation is not None
    session.expire(recommendation)
    return recommendation


def suggestions_of(session: Session, recommendation: Recommendation) -> list[ActionSuggestion]:
    return list(
        session.scalars(
            select(ActionSuggestion)
            .where(ActionSuggestion.recommendation_id == recommendation.id)
            .order_by(ActionSuggestion.rank)
        )
    )


def texts(suggestions: list[ActionSuggestion], source: ActionSource) -> list[str]:
    return [item.text for item in suggestions if item.source is source]


def actions_jobs(session: Session, case: Case) -> list[Job]:
    return list(
        session.scalars(
            select(Job)
            .where(Job.case_id == case.id, Job.type == JobType.SUGGEST_ACTIONS)
            .order_by(Job.created_at, Job.id)
        )
    )


def status_of(session: Session, case: Case) -> CaseStatus:
    session.expire(case)
    return case.status


def audit_for(session: Session, case: Case) -> list[AuditEntry]:
    return list(
        session.scalars(
            select(AuditEntry).where(AuditEntry.entity_id == str(case.id)).order_by(AuditEntry.id)
        )
    )


# --- The triage run hands the work over (ADR-18 §3, NFR-29) ---------------


def test_the_triage_run_enqueues_the_actions_job_and_stops_there(
    db_session: Session, seeded: None, pipeline
) -> None:
    """The reviewer has the category before any action exists.

    This is the ordering P05b's verification asks for: the category is in the
    queue *before* the actions become ready. Asserted by not running the second
    job.
    """
    case = make_demo_case(db_session, "DEMO_1")

    pipeline.run(case.id)

    recommendation = recommendation_of(db_session, case)
    assert status_of(db_session, case) is CaseStatus.AWAITING_REVIEW
    assert recommendation.category is VTLCategory.ORANGE
    assert recommendation.actions_status is ActionsStatus.PENDING
    assert suggestions_of(db_session, recommendation) == []

    jobs = actions_jobs(db_session, case)
    assert [job.status for job in jobs] == [JobStatus.QUEUED]
    assert jobs[0].payload == {ACTIONS_JOB_RECOMMENDATION_KEY: str(recommendation.id)}


def test_the_worker_runs_both_jobs_in_one_pass(
    db_session: Session, seeded: None, app_session_factory: sessionmaker, pipeline
) -> None:
    """The triage job, then the actions job it enqueued (ADR-08)."""
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)

    assert run_pending_jobs_once(app_session_factory, pipeline) == 1

    recommendation = recommendation_of(db_session, case)
    assert recommendation.actions_status is ActionsStatus.READY
    assert [job.status for job in actions_jobs(db_session, case)] == [JobStatus.DONE]


# --- The happy path --------------------------------------------------------


def test_demo_1_ends_with_baseline_and_tailored_actions(
    db_session: Session, seeded: None, pipeline
) -> None:
    """FR-71, FR-72, FR-73: the curated set for ORANGE plus the fixture's own."""
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)

    result = pipeline.run_actions(recommendation.id)

    assert result.succeeded
    assert result.actions_status is ActionsStatus.READY
    recommendation = recommendation_of(db_session, case)
    assert recommendation.actions_status is ActionsStatus.READY
    assert recommendation.actions_error is None
    assert recommendation.actions_rejected_count == 0

    suggestions = suggestions_of(db_session, recommendation)
    assert texts(suggestions, ActionSource.BASELINE) == SEEDED_BASELINE[VTLCategory.ORANGE]
    assert texts(suggestions, ActionSource.AI) == [
        action["text"] for action in demo_cases()["DEMO_1"]["mock_actions"]
    ]


def test_the_ranks_are_one_sequence_with_the_baseline_first(
    db_session: Session, seeded: None, pipeline
) -> None:
    """`order by rank` is the order W-04 shows them in (IR-23)."""
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)

    pipeline.run_actions(recommendation.id)

    suggestions = suggestions_of(db_session, recommendation)
    baseline_count = len(SEEDED_BASELINE[VTLCategory.ORANGE])
    assert [item.rank for item in suggestions] == list(range(1, len(suggestions) + 1))
    assert all(item.source is ActionSource.BASELINE for item in suggestions[:baseline_count])
    assert all(item.source is ActionSource.AI for item in suggestions[baseline_count:])


def test_the_stored_rows_carry_their_provenance(
    db_session: Session, seeded: None, pipeline
) -> None:
    """DR-09, FR-26, ADR-14 — and the two layers do not claim the same origin.

    A baseline row is curated knowledge-base content, so it is not labelled with
    the actions stage's model: its provenance is the knowledge-base version it
    was read from.
    """
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)

    pipeline.run_actions(recommendation.id)

    suggestions = suggestions_of(db_session, recommendation)
    for item in suggestions:
        assert item.case_id == case.id
        assert item.vignette_id is None
        assert item.kb_version_id == recommendation.kb_version_id
        assert item.generated_for_category is VTLCategory.ORANGE

    baseline = [item for item in suggestions if item.source is ActionSource.BASELINE]
    tailored = [item for item in suggestions if item.source is ActionSource.AI]
    assert all(item.model_id == BASELINE_MODEL_ID == "baseline" for item in baseline)
    assert all(item.prompt_version == BASELINE_PROMPT_VERSION == "kb" for item in baseline)
    assert all(item.cited_chunk_ids == [] for item in baseline)
    assert all(item.model_id == "mock" for item in tailored)
    assert all(item.prompt_version == "mock-0" for item in tailored)


def test_a_tailored_action_records_the_rank_it_cites(
    db_session: Session, seeded: None, pipeline
) -> None:
    """FR-74. The rank is the citation while the stages are mocked.

    `retrieved_references.chunk_id` is NULL for a mock passage — no `kb_chunks`
    row exists — so a list of bare ids would be empty on every mock run and the
    citation link would be unverifiable until M5 and M6. The rank survives, and
    the chunk id fills itself in once real chunks exist.
    """
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)

    pipeline.run_actions(recommendation.id)

    tailored = [
        item
        for item in suggestions_of(db_session, recommendation)
        if item.source is ActionSource.AI
    ]
    recorded = demo_cases()["DEMO_1"]["mock_actions"]
    assert [item.cited_chunk_ids for item in tailored] == [
        [{"rank": rank, "chunk_id": None} for rank in action["cited_ranks"]] for action in recorded
    ]


def test_retrieval_is_not_run_again(db_session: Session, seeded: None, pipeline) -> None:
    """ADR-14: the actions cite the passages the recommendation was made from.

    Proved by making the retriever fail: the actions run must never reach it.
    """
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)

    class _Exploding:
        model_id = "mock"
        prompt_version = "mock-0"
        last_latency_ms = 0

        def retrieve(self, extraction, kb_version_id, k):  # pragma: no cover - must not run
            raise AssertionError("the actions job must not re-run retrieval")

    result = replace(pipeline, retriever=_Exploding()).run_actions(recommendation.id)

    assert result.succeeded
    assert result.tailored_count == len(demo_cases()["DEMO_1"]["mock_actions"])


@pytest.mark.parametrize("category", list(VTLCategory), ids=lambda c: c.value)
def test_every_category_has_baseline_actions(
    db_session: Session, seeded: None, category: VTLCategory, reviewer: User
) -> None:
    """FR-71, through the read path a reviewer actually uses.

    All five, including the two no demo scenario produces. No pipeline runs here
    at all: a baseline set is a deterministic lookup, which is what makes it
    survive the model being switched off (FR-72).
    """
    case = make_case(db_session, status=CaseStatus.AWAITING_REVIEW)
    make_recommendation(db_session, case=case, category=category)

    detail = CaseService(db_session).get_detail(case.id, reviewer)

    assert detail.actions.baseline == SEEDED_BASELINE[category]


def test_a_case_with_no_baseline_entry_is_not_a_failure(
    db_session: Session, pipeline, caplog: pytest.LogCaptureFixture
) -> None:
    """A gap in the knowledge base is content for M5 to fill, not a broken job.

    Deliberately not `seeded`, except for the knowledge-base version a run needs:
    there is no `URGENCY_ACTIONS` entry to find, and the job must still finish
    and still store the tailored actions.
    """
    from tests.conftest import make_kb_version

    make_kb_version(db_session)
    case = make_case(db_session)
    make_owner_description(db_session, case=case)
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)

    with caplog.at_level(logging.WARNING):
        result = pipeline.run_actions(recommendation.id)

    assert result.succeeded
    assert result.baseline_count == 0
    assert result.tailored_count == 2
    assert "No ACTIVE URGENCY_ACTIONS entry" in caplog.text


# --- The failure paths, none of which move the case (FR-77) ---------------


def test_a_failing_actions_stage_leaves_the_case_awaiting_review(
    db_session: Session, seeded: None, pipeline, pipeline_factory, reviewer: User
) -> None:
    """The headline requirement: `failed`, **not** `MANUAL_TRIAGE_REQUIRED`.

    The triage run is given a working pipeline and the actions run a timing-out
    one, because `MOCK_LLM_BEHAVIOR` applies to every model stage — a timeout
    from the start would fail extraction and there would be no recommendation to
    suggest actions for.
    """
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)

    result = pipeline_factory(mock_llm_behavior=MockLLMBehavior.TIMEOUT).run_actions(
        recommendation.id
    )

    assert result.failure_reason is ActionsFailureReason.ACTIONS_TIMEOUT
    assert status_of(db_session, case) is CaseStatus.AWAITING_REVIEW

    recommendation = recommendation_of(db_session, case)
    assert recommendation.category is VTLCategory.ORANGE
    assert recommendation.actions_status is ActionsStatus.FAILED
    assert recommendation.actions_error == ActionsFailureReason.ACTIONS_TIMEOUT.value

    # And the reviewer still gets something to do (FR-71, FR-72).
    detail = CaseService(db_session).get_detail(case.id, reviewer)
    assert detail.actions.status is ActionsStatus.FAILED
    assert detail.actions.baseline == SEEDED_BASELINE[VTLCategory.ORANGE]
    assert detail.actions.tailored == []


def test_unusable_actions_output_is_reported_as_its_own_reason(
    db_session: Session, seeded: None, pipeline, pipeline_factory
) -> None:
    """The reason code comes from the chained cause, never from a message (SR-17)."""
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)

    result = pipeline_factory(mock_llm_behavior=MockLLMBehavior.INVALID_JSON).run_actions(
        recommendation.id
    )

    assert result.failure_reason is ActionsFailureReason.ACTIONS_INVALID_OUTPUT
    assert status_of(db_session, case) is CaseStatus.AWAITING_REVIEW


def test_an_actions_stage_that_fails_without_saying_why_is_unavailable(
    db_session: Session, seeded: None, pipeline
) -> None:
    """A bare `ActionsFailed` means the stage could not answer and did not say why."""
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)

    result = replace(pipeline, action_suggester=_Suggester(raises=ActionsFailed("no"))).run_actions(
        recommendation.id
    )

    assert result.failure_reason is ActionsFailureReason.ACTIONS_UNAVAILABLE


def test_every_rejected_action_is_reported_as_such(
    db_session: Session, seeded: None, pipeline
) -> None:
    """ADR-18 §4: the tally is surfaced, not swallowed — and never corrected.

    The baseline rows are still stored, because they were never in doubt.
    """
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)
    unusable = [
        SuggestedAction(
            text="Give butorphanol 0.2 mg/kg IV", cited_ranks=[1], source=ActionSource.AI
        ),
        SuggestedAction(text="The cat has an obstruction", cited_ranks=[1], source=ActionSource.AI),
    ]

    result = replace(pipeline, action_suggester=_Suggester(unusable)).run_actions(recommendation.id)

    assert result.failure_reason is ActionsFailureReason.ACTIONS_ALL_REJECTED
    assert result.rejected_count == 2
    assert status_of(db_session, case) is CaseStatus.AWAITING_REVIEW

    recommendation = recommendation_of(db_session, case)
    assert recommendation.actions_status is ActionsStatus.FAILED
    assert recommendation.actions_error == ActionsFailureReason.ACTIONS_ALL_REJECTED.value
    assert recommendation.actions_rejected_count == 2

    suggestions = suggestions_of(db_session, recommendation)
    assert texts(suggestions, ActionSource.BASELINE) == SEEDED_BASELINE[VTLCategory.ORANGE]
    assert texts(suggestions, ActionSource.AI) == []


def test_a_stage_that_proposes_nothing_has_not_failed(
    db_session: Session, seeded: None, pipeline
) -> None:
    """Nothing to reject is not the same as everything rejected."""
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)

    result = replace(pipeline, action_suggester=_Suggester([])).run_actions(recommendation.id)

    assert result.succeeded
    assert result.actions_status is ActionsStatus.READY
    assert result.tailored_count == 0
    assert result.rejected_count == 0


def test_a_job_for_a_recommendation_that_does_not_exist_is_reported(
    db_session: Session, seeded: None, pipeline
) -> None:
    result = pipeline.run_actions(uuid.uuid4())

    assert result.failure_reason is ActionsFailureReason.RECOMMENDATION_NOT_FOUND
    assert result.actions_status is None


def test_an_extraction_that_does_not_match_the_contract_is_a_reason_code(
    db_session: Session, seeded: None, pipeline
) -> None:
    """An old row must not crash the job. `make_recommendation` stores `{}`."""
    case = make_case(db_session, status=CaseStatus.AWAITING_REVIEW)
    recommendation = make_recommendation(db_session, case=case, category=VTLCategory.GREEN)

    result = pipeline.run_actions(recommendation.id)

    assert result.failure_reason is ActionsFailureReason.ACTIONS_INPUT_UNUSABLE
    assert status_of(db_session, case) is CaseStatus.AWAITING_REVIEW


@pytest.mark.parametrize("behavior", list(MockLLMBehavior), ids=lambda b: b.value)
def test_the_actions_job_never_changes_the_case_status(
    db_session: Session, seeded: None, pipeline, pipeline_factory, behavior: MockLLMBehavior
) -> None:
    """FR-77, stated once over every behaviour the mocks can simulate.

    The counterpart of `test_no_failure_path_leaves_a_case_in_processing` for the
    triage run: there, every path ends in one of two case statuses; here, no path
    changes the case status at all.
    """
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)
    assert status_of(db_session, case) is CaseStatus.AWAITING_REVIEW

    pipeline_factory(mock_llm_behavior=behavior).run_actions(recommendation.id)

    assert status_of(db_session, case) is CaseStatus.AWAITING_REVIEW, behavior
    assert recommendation_of(db_session, case).category is VTLCategory.ORANGE


# --- Retries and versions --------------------------------------------------


def test_a_retry_replaces_the_rows_rather_than_duplicating_them(
    db_session: Session, seeded: None, pipeline
) -> None:
    """The job can be retried by the startup sweep (ADR-08) or by P07."""
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)

    pipeline.run_actions(recommendation.id)
    first = [item.id for item in suggestions_of(db_session, recommendation)]
    pipeline.run_actions(recommendation.id)
    second = suggestions_of(db_session, recommendation)

    assert len(second) == len(first)
    assert {item.id for item in second}.isdisjoint(first)
    assert [item.rank for item in second] == list(range(1, len(second) + 1))


def test_a_failed_retry_keeps_the_count_the_previous_attempt_recorded(
    db_session: Session, seeded: None, pipeline, pipeline_factory
) -> None:
    """The failure path records a reason, not a reset tally."""
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)
    unusable = [
        SuggestedAction(text="Start antibiotics", cited_ranks=[1], source=ActionSource.AI),
    ]
    replace(pipeline, action_suggester=_Suggester(unusable)).run_actions(recommendation.id)

    pipeline_factory(mock_llm_behavior=MockLLMBehavior.TIMEOUT).run_actions(recommendation.id)

    recommendation = recommendation_of(db_session, case)
    assert recommendation.actions_error == ActionsFailureReason.ACTIONS_TIMEOUT.value
    assert recommendation.actions_rejected_count == 1


def test_a_second_triage_run_gets_its_own_actions_job(
    db_session: Session, seeded: None, pipeline
) -> None:
    """ADR-14: a re-run adds a recommendation version, and actions follow it."""
    case = make_demo_case(db_session, "DEMO_1")

    pipeline.run(case.id)
    pipeline.run(case.id)

    jobs = actions_jobs(db_session, case)
    versions = list(
        db_session.scalars(
            select(Recommendation.id)
            .where(Recommendation.case_id == case.id)
            .order_by(Recommendation.version)
        )
    )
    # As sets: both jobs are created inside one transaction, so `created_at` is
    # the same instant for both and their order is the tie-break on `id`.
    assert len(jobs) == 2
    assert {job.payload[ACTIONS_JOB_RECOMMENDATION_KEY] for job in jobs} == {
        str(version) for version in versions
    }


# --- Privacy (SR-17, CLAUDE.md §9) ----------------------------------------


def test_the_audit_trail_records_counts_and_never_action_text(
    db_session: Session, seeded: None, pipeline
) -> None:
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)

    pipeline.run_actions(recommendation.id)

    entry = audit_for(db_session, case)[-1]
    assert entry.action == AuditAction.ACTIONS_SUGGESTED.value
    assert entry.after == {
        "actions_status": ActionsStatus.READY.value,
        "reason": None,
        "generated_for_category": VTLCategory.ORANGE.value,
        "baseline_count": len(SEEDED_BASELINE[VTLCategory.ORANGE]),
        "tailored_count": len(demo_cases()["DEMO_1"]["mock_actions"]),
        "rejected_count": 0,
        "rejection_reasons": [],
        "recommendation_id": str(recommendation.id),
    }
    # The pipeline is not a person; the reviewer's finalization is audited in P06.
    assert entry.user_id is None
    assert entry.role is None


def test_a_failure_is_audited_as_a_reason_code(
    db_session: Session, seeded: None, pipeline, pipeline_factory
) -> None:
    case = make_demo_case(db_session, "DEMO_1")
    pipeline.run(case.id)
    recommendation = recommendation_of(db_session, case)

    pipeline_factory(mock_llm_behavior=MockLLMBehavior.TIMEOUT).run_actions(recommendation.id)

    entry = audit_for(db_session, case)[-1]
    assert entry.action == AuditAction.ACTIONS_FAILED.value
    assert entry.after["reason"] == ActionsFailureReason.ACTIONS_TIMEOUT.value


def test_no_action_text_reaches_the_audit_log_or_the_log(
    db_session: Session, seeded: None, pipeline, caplog: pytest.LogCaptureFixture
) -> None:
    """SR-17. Action text is untrusted model output and the audit log is permanent.

    Read over every audit payload and every log record the two runs produce,
    baseline text included: a baseline action is curated, but it is still
    clinical content and the container log is not where it belongs.
    """
    case = make_demo_case(db_session, "DEMO_1")
    secrets = [action["text"] for action in demo_cases()["DEMO_1"]["mock_actions"]]
    secrets += SEEDED_BASELINE[VTLCategory.ORANGE]

    with caplog.at_level(logging.DEBUG):
        pipeline.run(case.id)
        recommendation = recommendation_of(db_session, case)
        pipeline.run_actions(recommendation.id)

    audited = repr(
        [(entry.action, entry.before, entry.after) for entry in audit_for(db_session, case)]
    )
    logged = repr([record.getMessage() + repr(record.__dict__) for record in caplog.records])

    for secret in secrets:
        assert secret not in audited, secret
        assert secret not in logged, secret

    # Stored where it belongs, so the test above is about the log and the audit
    # trail rather than about having dropped the text.
    stored = [item.text for item in suggestions_of(db_session, recommendation)]
    assert set(secrets) <= set(stored)


# --- A stage the tests drive directly -------------------------------------


class _Suggester:
    """An `ActionSuggester` that answers from a script.

    Used where the point is what the *validator* and the orchestrator do with an
    answer, so the answer has to be chosen rather than replayed from a fixture
    (which is written to pass).
    """

    model_id = "mock"
    prompt_version = "mock-0"
    last_latency_ms = 0

    def __init__(
        self,
        actions: list[SuggestedAction] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._actions = actions or []
        self._raises = raises

    def suggest(
        self,
        extraction: object,
        category: VTLCategory,
        passages: list,
        max_items: int,
    ) -> list[SuggestedAction]:
        if self._raises is not None:
            raise self._raises
        return list(self._actions[:max_items])
