"""`/eval`: the Administrator's evaluation harness (P09 §9.2, FR-64..FR-69, BR-05, SR-05).

The job worker is off in the test app (ADR-08), so a queued run is executed by
`run_pending_jobs_once` with the eval job types, exactly as the eval worker would.
All data is fictitious (CLAUDE.md §9).
"""

import csv
import io
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.jobs.queue import EVAL_RUN_ID_KEY
from app.jobs.worker import EVAL_JOB_TYPES, run_pending_jobs_once
from app.models import EvaluationSet, Job, JobStatus, JobType, User, UserRole
from app.pipeline.orchestrator import TriagePipeline
from scripts.seed import seed
from tests.conftest import audit_actions, csrf_headers, make_user, sign_in

PASSWORD = "Sampaguita2026"
EVAL = "/api/v1/eval"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "vignettes_mock.csv"


def signed_in(client: TestClient, session: Session, role: UserRole) -> User:
    user = make_user(session, password=PASSWORD, role=role)
    sign_in(client, user.email, PASSWORD)
    return user


def as_admin(client: TestClient, session: Session) -> User:
    return signed_in(client, session, UserRole.ADMINISTRATOR)


def upload(
    client: TestClient, content: bytes | None = None, name: str | None = "mock-set"
) -> object:
    data = {} if name is None else {"name": name}
    return client.post(
        f"{EVAL}/sets",
        data=data,
        files={"file": ("vignettes.csv", FIXTURE.read_bytes() if content is None else content)},
        headers=csrf_headers(client),
    )


def start(client: TestClient, set_id: str) -> object:
    return client.post(f"{EVAL}/runs", json={"set_id": set_id}, headers=csrf_headers(client))


@pytest.fixture
def finished_run(
    api_client: TestClient,
    db_session: Session,
    app_session_factory: sessionmaker,
    pipeline: TriagePipeline,
) -> str:
    """A completed run over the mock set, started and executed through the API."""
    seed(db_session)
    as_admin(api_client, db_session)
    set_id = upload(api_client).json()["id"]
    run_id = start(api_client, set_id).json()["id"]
    assert run_pending_jobs_once(app_session_factory, pipeline, job_types=EVAL_JOB_TYPES) == 1
    return run_id


# --- Import -----------------------------------------------------------------


def test_upload_stores_the_set_and_reports_unknown_slugs(
    api_client: TestClient, db_session: Session
) -> None:
    admin = as_admin(api_client, db_session)

    response = upload(api_client)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "mock-set"
    assert body["vignette_count"] == 10
    # No knowledge-base entries exist in the test database, so all three slugs warn.
    assert len(body["warnings"]) == 3
    assert "EVAL_SET_IMPORTED" in audit_actions(db_session, admin.id)
    # The response says how many vignettes there are, never what they say.
    assert "keeps going in and out" not in response.text


def test_a_bad_file_stores_nothing_and_names_every_row(
    api_client: TestClient, db_session: Session
) -> None:
    as_admin(api_client, db_session)
    long_enough = "A description that is certainly long enough to pass."
    content = (
        "external_id,species,description,reference_category,relevant_entry_slugs\n"
        f'V-1,DOG,"{long_enough}",GREEN,\n'
        f'V-2,HORSE,"{long_enough}",GREEN,\n'
        f'V-3,CAT,"{long_enough}",PURPLE,\n'
    ).encode()

    response = upload(api_client, content)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert [(item["row"], item["field"]) for item in error["rows"]] == [
        (3, "species"),
        (4, "reference_category"),
    ]
    assert db_session.scalar(select(func.count()).select_from(EvaluationSet)) == 0


def test_upload_validation_failures(api_client: TestClient, db_session: Session) -> None:
    as_admin(api_client, db_session)

    no_name = upload(api_client, name=None)
    blank_name = upload(api_client, name="   ")
    empty = upload(api_client, b"")

    assert no_name.status_code == 422
    assert no_name.json()["error"]["field"] == "name"
    assert blank_name.status_code == 422
    assert empty.status_code == 422
    assert empty.json()["error"]["rows"][0]["field"] == "file"


def test_a_set_name_can_be_used_once(api_client: TestClient, db_session: Session) -> None:
    as_admin(api_client, db_session)
    assert upload(api_client).status_code == 201

    duplicate = upload(api_client)

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "EVALUATION_NAME_IN_USE"
    assert duplicate.json()["error"]["field"] == "name"


def test_sets_are_listed_with_their_size(api_client: TestClient, db_session: Session) -> None:
    as_admin(api_client, db_session)
    upload(api_client)

    body = api_client.get(f"{EVAL}/sets").json()

    assert body["total"] == 1
    assert body["items"][0]["name"] == "mock-set"
    assert body["items"][0]["vignette_count"] == 10


# --- Start and read a run ---------------------------------------------------


def test_starting_a_run_returns_202_and_queues_a_job(
    api_client: TestClient, db_session: Session
) -> None:
    admin = as_admin(api_client, db_session)
    set_id = upload(api_client).json()["id"]

    response = start(api_client, set_id)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "QUEUED"
    assert body["progress"] == {"done": 0, "total": 10}
    assert body["metrics"] is None and body["fully_mocked"] is None
    job = db_session.scalars(select(Job).where(Job.type == JobType.EVAL_RUN)).one()
    assert job.status is JobStatus.QUEUED
    assert job.payload == {EVAL_RUN_ID_KEY: body["id"]}
    assert "EVAL_RUN_STARTED" in audit_actions(db_session, admin.id)


def test_start_validation_failures(api_client: TestClient, db_session: Session) -> None:
    as_admin(api_client, db_session)

    unknown = start(api_client, str(uuid.uuid4()))
    malformed = api_client.post(
        f"{EVAL}/runs", json={"set_id": "nope"}, headers=csrf_headers(api_client)
    )

    assert unknown.status_code == 404
    assert malformed.status_code == 422


def test_a_run_reports_its_progress_metrics_and_targets(
    api_client: TestClient, finished_run: str
) -> None:
    body = api_client.get(f"{EVAL}/runs/{finished_run}").json()

    assert body["status"] == "DONE"
    assert body["progress"] == {"done": 10, "total": 10}
    assert body["set_name"] == "mock-set"
    assert body["fully_mocked"] is True
    assert body["config"]["PIPELINE_GENERATOR"] == "mock"
    assert body["metrics"]["counts"] == {"total": 10, "failed": 1, "scored": 9}
    targets = {target["key"]: target for target in body["targets"]}
    assert set(targets) == {
        "macro_f1",
        "red_orange_recall",
        "under_triage_rate",
        "recall_at_k",
        "mrr",
        "latency_p50",
        "latency_p95",
    }
    assert targets["macro_f1"]["threshold"] == 0.70
    assert targets["macro_f1"]["requirement"] == "NFR-16"
    assert targets["latency_p50"]["unit"] == "s"
    assert {target["status"] for target in targets.values()} <= {"PASS", "FAIL", "n/a"}
    # Mock retrieval returns invented entries, so nothing matches the judgements.
    assert targets["recall_at_k"]["status"] in {"FAIL", "n/a"}


def test_runs_are_listed_newest_first(api_client: TestClient, finished_run: str) -> None:
    body = api_client.get(f"{EVAL}/runs").json()

    assert body["total"] == 1
    assert body["items"][0]["id"] == finished_run


def test_an_unknown_run_is_404(api_client: TestClient, db_session: Session) -> None:
    as_admin(api_client, db_session)
    missing = uuid.uuid4()

    assert api_client.get(f"{EVAL}/runs/{missing}").status_code == 404
    assert api_client.get(f"{EVAL}/runs/{missing}/export").status_code == 404


# --- Export -----------------------------------------------------------------


def test_export_is_refused_until_the_run_has_finished(
    api_client: TestClient, db_session: Session
) -> None:
    as_admin(api_client, db_session)
    run_id = start(api_client, upload(api_client).json()["id"]).json()["id"]

    response = api_client.get(f"{EVAL}/runs/{run_id}/export")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EVALUATION_NOT_FINISHED"


def test_csv_export_has_one_row_per_vignette_then_the_metrics(
    api_client: TestClient, finished_run: str
) -> None:
    response = api_client.get(f"{EVAL}/runs/{finished_run}/export", params={"format": "csv"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    table, metrics = response.text.split("\n\n", 1)
    rows = list(csv.DictReader(io.StringIO(table)))
    assert [row["external_id"] for row in rows][:2] == ["V-001", "V-002"]
    assert len(rows) == 10
    by_id = {row["external_id"]: row for row in rows}
    assert by_id["V-001"]["reference_category"] == "ORANGE"
    assert by_id["V-001"]["predicted_category"] == "ORANGE"
    assert by_id["V-001"]["outcome"] == "CORRECT"
    assert by_id["V-001"]["red_flag_rules"] == "MALE_CAT_NO_URINE"
    assert by_id["V-004"]["outcome"] == "FAILED"
    assert by_id["V-004"]["error"] == "LLM_INVALID_OUTPUT"
    assert by_id["V-001"]["latency_total_ms"] != ""
    # The metrics follow as `metric,value` lines.
    lines = metrics.splitlines()
    assert lines[0] == "metric,value"
    assert "counts.failed,1" in lines
    assert "classification.confusion.RED.RED,1" in lines


def test_json_export_carries_the_rows_and_the_metrics(
    api_client: TestClient, finished_run: str
) -> None:
    response = api_client.get(f"{EVAL}/runs/{finished_run}/export", params={"format": "json"})

    assert response.status_code == 200
    body = json.loads(response.text)
    assert body["run"]["id"] == finished_run
    assert body["metrics"]["counts"]["scored"] == 9
    assert len(body["vignettes"]) == 10
    assert body["vignettes"][0]["external_id"] == "V-001"


def test_an_export_never_contains_vignette_text(api_client: TestClient, finished_run: str) -> None:
    for file_format in ("csv", "json"):
        text = api_client.get(
            f"{EVAL}/runs/{finished_run}/export", params={"format": file_format}
        ).text
        assert "litter box" not in text
        assert "motorbike" not in text


def test_export_rejects_an_unknown_format(api_client: TestClient, finished_run: str) -> None:
    response = api_client.get(f"{EVAL}/runs/{finished_run}/export", params={"format": "xml"})

    assert response.status_code == 422


# --- Roles ------------------------------------------------------------------


def _calls(client: TestClient, run_id: uuid.UUID):
    headers = csrf_headers(client)
    return [
        lambda: client.get(f"{EVAL}/sets"),
        lambda: client.post(
            f"{EVAL}/sets", data={"name": "x"}, files={"file": ("v.csv", b"x")}, headers=headers
        ),
        lambda: client.get(f"{EVAL}/runs"),
        lambda: client.post(f"{EVAL}/runs", json={"set_id": str(uuid.uuid4())}, headers=headers),
        lambda: client.get(f"{EVAL}/runs/{run_id}"),
        lambda: client.get(f"{EVAL}/runs/{run_id}/export"),
    ]


@pytest.mark.parametrize("role", [UserRole.INTAKE_STAFF, UserRole.VETERINARY_REVIEWER])
def test_non_administrators_get_403_on_every_evaluation_endpoint(
    api_client: TestClient, db_session: Session, role: UserRole
) -> None:
    signed_in(api_client, db_session, role)

    for call in _calls(api_client, uuid.uuid4()):
        response = call()
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"


def test_an_unauthenticated_caller_gets_401(api_client: TestClient) -> None:
    for path in (f"{EVAL}/sets", f"{EVAL}/runs", f"{EVAL}/runs/{uuid.uuid4()}"):
        assert api_client.get(path).status_code == 401
