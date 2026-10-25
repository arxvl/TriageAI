"""The evaluation runner on the mock pipeline (P09 §9.2, FR-64, FR-65, NFR-23, DR-06).

Each test imports `tests/fixtures/vignettes_mock.csv` - the four demo scenarios and
six invented ones - and runs it through the real orchestrator, safety validator and
database. Only the AI stages are mocks (ADR-17), so this proves the harness, not a
model.

What these tests keep true:

1. **Evaluation mode touches no case.** No case, status, alert, audit entry or
   queue job comes out of a vignette run (DR-06, FR-65).
2. **A failed vignette is a result, not a stop.** The run records why and goes on.
3. **The configuration is on the run,** so a later reader knows what produced the
   numbers (NFR-23).
4. **A run can be picked up again** without scoring a vignette twice.

All data is fictitious (CLAUDE.md §9).
"""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import MockLLMBehavior
from app.eval.runner import (
    EVAL_RUN_NOT_FOUND,
    NO_KNOWLEDGE_BASE_VERSION,
    run_evaluation,
)
from app.models import (
    AuditEntry,
    Case,
    EvaluationResult,
    EvaluationRun,
    ExtractionResult,
    Job,
    JobStatus,
    JobType,
    KBVersion,
    Recommendation,
    RedFlagAlert,
    RetrievedReference,
    User,
    UserRole,
    Vignette,
    VTLCategory,
)
from app.pipeline.orchestrator import FailureReason, TriagePipeline
from app.services.evaluation_service import EvaluationService
from scripts.seed import seed
from tests.conftest import make_kb_entry, make_user

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "vignettes_mock.csv"
VIGNETTE_COUNT = 10


@pytest.fixture
def seeded(db_session: Session) -> None:
    """Complaints, red-flag rules and knowledge-base version 0, as a deployment has."""
    seed(db_session)


@pytest.fixture
def admin(db_session: Session) -> User:
    return make_user(db_session, role=UserRole.ADMINISTRATOR)


@pytest.fixture
def run_id(db_session: Session, admin: User, seeded: None):
    """A queued run over the imported mock set, not yet executed."""
    service = EvaluationService(db_session)
    chosen = service.import_set("mock-set", FIXTURE.read_bytes(), admin)
    return service.start_run(chosen.id, admin, enqueue=False).id


def counts(session: Session) -> dict[str, int]:
    """Row counts of every table a vignette run must leave alone."""

    def count(model: type) -> int:
        return session.scalar(select(func.count()).select_from(model)) or 0

    return {
        "cases": count(Case),
        "alerts": count(RedFlagAlert),
        "audit": count(AuditEntry),
        "jobs": count(Job),
        "case_extractions": session.scalar(
            select(func.count())
            .select_from(ExtractionResult)
            .where(ExtractionResult.case_id.is_not(None))
        )
        or 0,
        "case_recommendations": session.scalar(
            select(func.count())
            .select_from(Recommendation)
            .where(Recommendation.case_id.is_not(None))
        )
        or 0,
    }


def results_by_id(session: Session, run_id) -> dict[str, EvaluationResult]:
    rows = session.execute(
        select(Vignette.external_id, EvaluationResult)
        .join(EvaluationResult, EvaluationResult.vignette_id == Vignette.id)
        .where(EvaluationResult.run_id == run_id)
    ).all()
    return {external_id: result for external_id, result in rows}


def test_a_run_scores_every_vignette_and_stores_the_metrics(
    db_session: Session, app_session_factory: sessionmaker, pipeline: TriagePipeline, run_id
) -> None:
    result = run_evaluation(app_session_factory, pipeline, run_id)

    assert result.succeeded
    run = db_session.get(EvaluationRun, run_id)
    db_session.refresh(run)
    assert run.status is JobStatus.DONE
    assert run.started_at is not None and run.finished_at is not None

    stored = results_by_id(db_session, run_id)
    assert len(stored) == VIGNETTE_COUNT
    # The demo scenarios replay their recorded answers: DEMO_1 is drafted YELLOW and
    # raised to ORANGE by the safety floor (FR-23); DEMO_2 is RED; DEMO_3 is BLUE.
    assert stored["V-001"].predicted_category is VTLCategory.ORANGE
    assert stored["V-002"].predicted_category is VTLCategory.RED
    assert stored["V-003"].predicted_category is VTLCategory.BLUE

    assert run.metrics["counts"] == {"total": 10, "failed": 1, "scored": 9}
    assert run.metrics["classification"]["n"] == 9
    # 3 demo scenarios are right (the 6 invented ones get the generic YELLOW).
    assert run.metrics["classification"]["confusion_matrix"][0][0] == 1  # V-002 RED


def test_each_result_carries_its_outputs_latencies_and_red_flag_hits(
    db_session: Session, app_session_factory: sessionmaker, pipeline: TriagePipeline, run_id
) -> None:
    run_evaluation(app_session_factory, pipeline, run_id)

    first = results_by_id(db_session, run_id)["V-001"]
    assert first.recommendation_id is not None and first.extraction_id is not None
    assert {"deidentify", "screen", "extract", "retrieve", "generate", "total"} <= set(
        first.stage_latencies
    )
    assert first.error is None
    # The pre-screen hit is on the result - not as an alert row (FR-12, DR-06).
    assert [hit["rule_code"] for hit in first.payload["red_flag_hits"]] == ["MALE_CAT_NO_URINE"]
    assert first.payload["red_flag_hits"][0]["min_category"] == "ORANGE"
    assert first.payload["safety_floor_applied"] is True
    assert first.payload["retrieved_entry_ids"]  # in rank order, for the retrieval metrics

    recommendation = db_session.get(Recommendation, first.recommendation_id)
    assert recommendation.vignette_id is not None and recommendation.case_id is None
    assert recommendation.kb_version_id is not None
    references = db_session.scalars(
        select(RetrievedReference).where(RetrievedReference.recommendation_id == recommendation.id)
    ).all()
    assert references


def test_evaluation_mode_writes_nothing_about_a_case(
    db_session: Session, app_session_factory: sessionmaker, pipeline: TriagePipeline, run_id
) -> None:
    before = counts(db_session)

    run_evaluation(app_session_factory, pipeline, run_id)

    assert counts(db_session) == before
    # And what it did write is keyed by vignette alone (DR-06).
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ExtractionResult)
            .where(ExtractionResult.vignette_id.is_not(None), ExtractionResult.case_id.is_not(None))
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(Recommendation)
            .where(Recommendation.vignette_id.is_not(None))
        )
        == VIGNETTE_COUNT - 1
    )
    assert (
        db_session.scalar(
            select(func.count()).select_from(Job).where(Job.type == JobType.SUGGEST_ACTIONS)
        )
        == 0
    )


def test_a_failed_vignette_records_its_reason_and_the_run_goes_on(
    db_session: Session, app_session_factory: sessionmaker, pipeline: TriagePipeline, run_id
) -> None:
    run_evaluation(app_session_factory, pipeline, run_id)

    stored = results_by_id(db_session, run_id)
    failed = stored["V-004"]  # DEMO_4 returns unusable output on every attempt
    assert failed.predicted_category is None
    assert failed.error == str(FailureReason.LLM_INVALID_OUTPUT)
    assert failed.recommendation_id is None and failed.extraction_id is None
    # Vignettes after it were still run.
    assert stored["V-010"].predicted_category is not None
    assert db_session.get(EvaluationRun, run_id).status is JobStatus.DONE


def test_when_every_vignette_fails_the_run_still_finishes_with_every_one_counted(
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline_factory,
    run_id,
) -> None:
    broken = pipeline_factory(mock_llm_behavior=MockLLMBehavior.INVALID_JSON)

    run_evaluation(app_session_factory, broken, run_id)

    run = db_session.get(EvaluationRun, run_id)
    assert run.status is JobStatus.DONE
    assert run.metrics["counts"] == {"total": 10, "failed": 10, "scored": 0}
    assert run.metrics["classification"]["accuracy"] is None
    assert all(r.error for r in results_by_id(db_session, run_id).values())


def test_the_configuration_snapshot_is_stored_on_the_run(
    db_session: Session, app_session_factory: sessionmaker, pipeline: TriagePipeline, run_id
) -> None:
    run_evaluation(app_session_factory, pipeline, run_id)

    run = db_session.get(EvaluationRun, run_id)
    config = run.config
    for key in (
        "PIPELINE_DEIDENTIFIER",
        "PIPELINE_REDFLAGS",
        "LLM_PROVIDER",
        "PIPELINE_EXTRACTOR",
        "PIPELINE_RETRIEVER",
        "PIPELINE_GENERATOR",
        "PIPELINE_ACTIONS",
        "model_id",
        "prompt_version",
        "kb_version_id",
        "top_k",
        "temperature",
        "LLM_TEMPERATURE",
    ):
        assert key in config, key
    assert config["PIPELINE_GENERATOR"] == "mock"
    assert config["stages"]["generator"] == {"model_id": "mock", "prompt_version": "mock-0"}
    assert config["top_k"] == pipeline.config.top_k
    assert config["fully_mocked"] is True
    assert config["kb_version_id"] == str(run.kb_version_id)
    # No secret or URL can be in a snapshot built from option names and ids.
    assert "KEY" not in " ".join(config).upper().replace("KB_VERSION_ID", "")


def test_the_run_is_pinned_to_one_knowledge_base_version(
    db_session: Session, app_session_factory: sessionmaker, pipeline: TriagePipeline, run_id
) -> None:
    newest = db_session.scalar(select(KBVersion.id).order_by(KBVersion.version_no.desc()).limit(1))

    run_evaluation(app_session_factory, pipeline, run_id)

    assert db_session.get(EvaluationRun, run_id).kb_version_id == newest
    versions = set(
        db_session.scalars(
            select(Recommendation.kb_version_id).where(Recommendation.vignette_id.is_not(None))
        )
    )
    assert versions == {newest}


def test_a_run_picked_up_again_scores_only_what_is_missing(
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline: TriagePipeline,
    run_id,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_evaluation(app_session_factory, pipeline, run_id)
    # Simulate a crash after seven vignettes: three results gone, the run left RUNNING.
    stored = results_by_id(db_session, run_id)
    for external_id in ("V-008", "V-009", "V-010"):
        db_session.delete(stored[external_id])
    run = db_session.get(EvaluationRun, run_id)
    run.status, run.metrics, run.finished_at = JobStatus.RUNNING, None, None
    db_session.flush()

    called: list[object] = []
    original = TriagePipeline.run_vignette

    def spy(self, vignette_id, kb_version_id, **kwargs):
        called.append(vignette_id)
        return original(self, vignette_id, kb_version_id, **kwargs)

    monkeypatch.setattr(TriagePipeline, "run_vignette", spy)
    run_evaluation(app_session_factory, pipeline, run_id)

    assert len(called) == 3
    assert len(results_by_id(db_session, run_id)) == VIGNETTE_COUNT
    db_session.refresh(run)
    assert run.status is JobStatus.DONE
    assert run.metrics["counts"]["total"] == VIGNETTE_COUNT


def test_a_finished_run_is_not_run_a_second_time(
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline: TriagePipeline,
    run_id,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_evaluation(app_session_factory, pipeline, run_id)
    monkeypatch.setattr(
        TriagePipeline, "run_vignette", lambda *a, **k: pytest.fail("ran a finished run")
    )

    assert run_evaluation(app_session_factory, pipeline, run_id).succeeded
    assert len(results_by_id(db_session, run_id)) == VIGNETTE_COUNT


def test_a_repeat_run_adds_a_new_version_beside_the_first(
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline: TriagePipeline,
    admin: User,
    run_id,
) -> None:
    """Both runs' outputs stay on record, which is what the NFR-23 comparison reads."""
    run_evaluation(app_session_factory, pipeline, run_id)
    service = EvaluationService(db_session)
    again = service.start_run(db_session.get(EvaluationRun, run_id).set_id, admin, enqueue=False)

    run_evaluation(app_session_factory, pipeline, again.id)

    versions = db_session.scalars(
        select(Recommendation.version)
        .join(Vignette, Vignette.id == Recommendation.vignette_id)
        .where(Vignette.external_id == "V-001")
    ).all()
    assert sorted(versions) == [1, 2]


def test_an_unknown_run_is_reported_and_not_raised(
    app_session_factory: sessionmaker, pipeline: TriagePipeline
) -> None:
    import uuid

    result = run_evaluation(app_session_factory, pipeline, uuid.uuid4())

    assert result.failure_reason == EVAL_RUN_NOT_FOUND


def test_a_run_with_no_knowledge_base_version_fails_cleanly(
    db_session: Session, app_session_factory: sessionmaker, pipeline: TriagePipeline, admin: User
) -> None:
    service = EvaluationService(db_session)
    chosen = service.import_set("no-kb", FIXTURE.read_bytes(), admin)
    started = service.start_run(chosen.id, admin, enqueue=False)

    result = run_evaluation(app_session_factory, pipeline, started.id)

    assert result.failure_reason == NO_KNOWLEDGE_BASE_VERSION
    run = db_session.get(EvaluationRun, started.id)
    db_session.refresh(run)
    assert run.status is JobStatus.FAILED
    assert results_by_id(db_session, started.id) == {}


def test_relevance_judgements_are_resolved_from_slugs(
    db_session: Session, admin: User, seeded: None
) -> None:
    entry = make_kb_entry(db_session, slug="urinary-obstruction-cat")

    stored = EvaluationService(db_session).import_set("with-slugs", FIXTURE.read_bytes(), admin)

    # The fixture names three slugs; only one exists here, so two warnings.
    assert sorted(stored.warnings) == [
        "Unknown knowledge-base entry slug: respiratory-distress-dog-cat",
        "Unknown knowledge-base entry slug: skin-itch-dog",
    ]
    ids = db_session.scalars(
        select(Vignette.relevant_entry_ids).where(Vignette.external_id == "V-001")
    ).all()
    assert ids == [[str(entry.id)]]
