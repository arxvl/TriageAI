# ADR-03: Python 3.11 and FastAPI for the backend

- **Status:** Accepted
- **Requirements:** IR-09 to IR-16, NFR-01, NFR-24
- **Related:** ADR-01, ADR-05, ADR-07

## Context

The backend must orchestrate an NLP pipeline (prompting, JSON validation,
sentence embeddings, vector search), expose a REST API, and run background jobs.
The NLP and vector tooling the project depends on — `sentence-transformers`,
`pgvector` bindings, LLM SDKs — is strongest in Python.

The API contract must be documented for the deliverables, and request payloads
must be validated strictly, because free-text case data reaches an external
model.

## Decision

Use **Python 3.11** with **FastAPI** and **Pydantic v2**, served by **Uvicorn**.

- Every request and response body is a Pydantic model. The same models generate
  the OpenAPI schema used by the front end (ADR-02).
- The AI contracts in `app/pipeline/types.py` are Pydantic models too, so model
  output is validated with the same machinery as HTTP input (ADR-09).
- Sync SQLAlchemy sessions are used, not async. The workload is small, and
  mixing async ORM code with the synchronous embedding model would add
  complexity with no measurable gain.
- Errors use one shape: `{"error": {"code": "...", "message": "..."}}`.

## Consequences

**Positive**

- One language across the API, the pipeline and the evaluation harness, so the
  same test fixtures serve all three.
- `/docs` gives the professors an interactive API reference at no cost, and the
  endpoint table in PD7 is generated from the same source.
- Pydantic validation of LLM output is the mechanism that makes the retry path
  (FR-15) deterministic.

**Negative**

- Python is slower than a compiled language, but the latency budget (NFR-01,
  10 s median) is dominated by the LLM call, not by framework overhead.
- Sync endpoints occupy a worker thread during I/O. Mitigated by keeping the
  slow pipeline out of the request cycle entirely (ADR-08).
- The team must keep to the layering rules, since FastAPI makes it easy to write
  logic straight into a router.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Node.js / Express | Would split the stack: embeddings and evaluation metrics would still need Python |
| Django REST Framework | Heavier; its ORM and admin bring little here, and the pipeline is not a CRUD problem |
| Flask | Would require assembling validation, OpenAPI and dependency injection by hand |

## Implementation notes

- Dependencies live in `backend/pyproject.toml`. Ruff is the linter and
  formatter (line length 100, target `py311`).
- New endpoints go under `/api/v1` and must declare a `require_role(...)`
  dependency (ADR-11).
- All timestamps are stored in UTC; the front end renders Asia/Manila.
