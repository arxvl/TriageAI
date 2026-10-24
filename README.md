# TriageAI

**A Transformer-Based NLP System for Canine and Feline Symptom Triage and Clinical Decision Support**

TriageAI helps veterinary clinic staff prioritize incoming dog and cat cases. Intake staff
enter the owner's free-text description; an NLP and retrieval-augmented generation pipeline
extracts the clinical details, recommends one of five Veterinary Triage List (VTL) urgency
categories with a rationale and cited sources, and proposes suggested staff actions for that
urgency level. A Veterinary Reviewer confirms, adjusts or replaces every recommendation.

> **Decision support only.** The system does not diagnose, does not give a prognosis, and never
> names a medication, dose or treatment protocol. No urgency category or action list is final
> until veterinary staff decide it. The knowledge base is compiled from published,
> veterinarian-authored sources and has **not** been clinically validated; this prototype is for
> academic evaluation and is never a substitute for a clinic's own triage procedure.

## Features

| Area | What it does |
|---|---|
| Intake and queue | Case registration with validation, verbatim description capture, triage queue ordered by urgency then waiting time, 15-second auto-refresh |
| AI triage pipeline | De-identification → red-flag pre-screen → LLM entity extraction → pgvector retrieval → LLM recommendation → deterministic safety validator |
| Suggested actions | Baseline actions per urgency category from the knowledge base, plus up to five case-specific LLM suggestions, each cited and content-checked |
| Clinical review | Three-panel review screen, confirm / adjust with reason / manual triage, note taking, case closure |
| Knowledge base | Curated entries with mandatory source citations, approval workflow, immutable published versions |
| Records and audit | Searchable case history, append-only audit trail enforced in the database |
| Evaluation | Vignette import, metric computation (classification, retrieval, latency), CSV and JSON export |

## Architecture

A modular monolith: a React single-page application talks to a FastAPI backend over
`/api/v1`, with one PostgreSQL 16 instance (pgvector) for both relational data and knowledge-base
embeddings. The triage pipeline runs as a background job, so intake returns immediately and the
browser polls for status.

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript (strict), Vite, React Router v6, TanStack Query |
| Backend | Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic |
| Database | PostgreSQL 16 with pgvector (HNSW, cosine) |
| LLM | Any OpenAI-compatible provider through an adapter port, with a local Ollama fallback and a deterministic mock |
| Embeddings | Local sentence-transformers model (CPU), 384 dimensions |
| Runtime | Container images orchestrated with Compose; Nginx terminates TLS in production |

Decisions and their reasoning are recorded in [`docs/adr/`](docs/adr/README.md) (ADR-01 to ADR-18).

## Requirements

- A container engine with the Compose CLI (Docker Desktop, or Podman with `podman-compose`)
- Node.js 24 LTS and Python 3.11, only for running tools outside the containers
- About 6 GB of free RAM once the embedding model is enabled

## Quick start

```bash
git clone <repository-url> triageai && cd triageai
cp .env.example .env            # the defaults run the whole app on mock AI stages
docker compose up --build       # or: podman-compose up --build
```

Then, in a second terminal:

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m scripts.seed
```

| Service | URL |
|---|---|
| Application | http://localhost:5173 |
| API | http://localhost:8000/api/v1 |
| API documentation | http://localhost:8000/docs |

Seeded accounts use the password `ChangeMe!2026` and force a password change at first login:
`admin@triageai.local`, `intake@triageai.local`, `reviewer@triageai.local`,
`approver@triageai.local`.

## Pipeline modes

Every AI stage has a deterministic mock and a real implementation, chosen in `.env`. **All
default to `mock`**, so the application runs end to end with no API key, no model download and no
cost. Each stage is switched on by the manual guide that builds it.

| Setting | `mock` → real | Built in |
|---|---|---|
| `PIPELINE_DEIDENTIFIER` | `rules` | M1 |
| `PIPELINE_REDFLAGS` | `keywords` | M1 |
| `LLM_PROVIDER` | `hosted` or `ollama` | M2 |
| `PIPELINE_EXTRACTOR` | `llm` | M3 |
| `EMBEDDING_PROVIDER` | `sentence_transformer` | M4 |
| `KB_INDEXER` | `pgvector` | M5 |
| `PIPELINE_RETRIEVER` | `pgvector` | M6 |
| `PIPELINE_GENERATOR` | `llm` | M6 |
| `PIPELINE_ACTIONS` | `llm` | M6b |

Two settings deserve attention:

- **`LLM_TEMPERATURE` is blank by default**, which means "send no temperature". Some current
  model families recommend their own default and may ignore a lower value. Set `0` only for a
  provider that honours it. Reproducibility is measured rather than assumed (NFR-23).
- **`MOCK_LLM_BEHAVIOR`** (`ok`, `invalid_json`, `timeout`, `flaky`, `slow`) exercises every
  failure path without a network call. `slow` delays each model stage by `MOCK_SLOW_DELAY_S`
  (12 s by default), so a full mocked run takes about 24 s.

## Failures, retry and the demo toggle

Every pipeline failure ends the same way: the case moves to `MANUAL_TRIAGE_REQUIRED`, nothing is
lost, and a reviewer sees one of these reasons on W-06 (NFR-09). The code is stored in
`jobs.last_error` and the `PIPELINE_FAILED` audit entry; the sentence comes from
`backend/app/pipeline/messages.py`.

| Code | Meaning |
|---|---|
| `LLM_TIMEOUT` | The model did not answer within `PIPELINE_TIMEOUT_S`, or the whole job passed `2 × timeout + 10` seconds |
| `LLM_UNAVAILABLE` | The model could not be reached or refused the request |
| `LLM_INVALID_OUTPUT` | The model's answer was unusable after one retry |
| `RETRIEVAL_FAILED` | The knowledge base could not be searched |
| `GENERATION_FAILED` | The recommendation step did not finish |
| `DEIDENTIFICATION_FAILED` | The text could not be de-identified; the run stops before any other stage (ADR-10) |
| `INTERNAL_ERROR` | Anything else, including a missing knowledge-base version |

A Veterinary Reviewer can press **Retry AI processing** on W-06, or call
`POST /api/v1/cases/{id}/retry`. It is allowed only for a case in `MANUAL_TRIAGE_REQUIRED` with no
decision, answers 202, puts the case back to `SUBMITTED`, queues a new `PIPELINE_RUN` job and
audits `PIPELINE_RETRY`. The earlier failure stays in the audit log.

**Showing the fallback in the PD8 demo.** Set `DEMO_FORCE_FAILURE_CASE_TEXT` in `.env` to an invented
phrase, restart the backend, and enter a case whose description contains it. The case fails as
`LLM_TIMEOUT` after the red-flag pre-screen has run, so any alert still reaches the queue. It works
only with `APP_ENV=dev`. Retrying the same text fails again: to show a successful retry, clear the
setting and restart the backend first. To check restart safety, use `MOCK_LLM_BEHAVIOR=slow`,
submit a case, run `docker compose kill backend`, then `docker compose up -d backend`. The
startup sweep returns a job to the queue only once it has been `RUNNING` for
`JOB_STALE_AFTER_MINUTES` (2 by default, so a second process's live job is never taken), so
either wait that long before restarting or set `JOB_STALE_AFTER_MINUTES=0` for the check. The
case is then triaged and never stays in `PROCESSING` (NFR-13).

## Correcting the extraction and regenerating

On W-04 a Veterinary Reviewer can click a value in **Extracted information**, correct it, and press
**Save and regenerate** (UC-09, FR-27); the API is `PATCH /api/v1/cases/{id}/extraction` (reviewer
only, answers 202). It is allowed only while the case is `AWAITING_REVIEW`, so a decided category is
never changed by regeneration (NFR-11). Nothing is edited in place:

- the correction is stored as a **new extraction version** (`is_corrected`, `corrected_by`) and the
  original is kept; the audit entry `EXTRACTION_CORRECTED` lists the changed field *names* only;
- a `REGENERATE` job runs retrieval, generation and the safety validator only — never
  de-identification, the red-flag screen or extraction — and stores the next **recommendation
  version**; older versions stay readable (`GET /api/v1/cases/{id}/recommendations/{version}`) and
  cannot be decided on;
- the safety floor uses the case's stored red-flag alerts plus any red flag the reviewer typed that
  equals a rule's label *exactly* (W-08 shows the labels); anything else is ignored for the floor;
- the case is `PROCESSING` while it runs. If it fails, the case returns to `AWAITING_REVIEW` with
  the previous recommendation still current, `REGENERATE_FAILED` is audited, and pressing **Save and
  regenerate** again re-queues the saved correction. With `MOCK_LLM_BEHAVIOR=timeout` the mock
  generator fails, which shows the banner; the mocks have no fixture for a corrected extraction, so a
  successful mock regeneration returns the generic YELLOW draft.

The application **refuses to start** if a real LLM provider is selected while de-identification is
still mocked, so raw owner text cannot leave the server (ADR-10).

## Knowledge base workflow

Clinical content is curated, not fetched: nothing becomes retrievable until an account holding the
knowledge-base approval permission has approved it (FR-51, FR-52, BR-04).

```
DRAFT --submit--> PENDING_REVIEW --approve--> (KB_INDEX job) --> ACTIVE --retire--> RETIRED
                        |                                          |
                        +----------- reject with comments ---------+--> publishes KB version N+1
```

| Endpoint | Who |
|---|---|
| `GET /kb/entries`, `GET /kb/entries/{id}`, `GET /kb/versions`, `GET /kb/red-flag-rules` | Administrator, Veterinary Reviewer |
| `POST`/`PATCH /kb/entries`, `POST /kb/entries/{id}/submit`, `POST /kb/entries/{id}/retire` | Administrator |
| `POST /kb/entries/{id}/approve`, `.../reject` | Veterinary Reviewer with `can_approve_kb` |
| `POST`/`PATCH /kb/red-flag-rules` | Administrator |
| `POST /kb/red-flag-rules/{id}/approve`, `.../retire` | Veterinary Reviewer with `can_approve_kb` |

Three consequences worth knowing:

- **Approval is asynchronous.** It answers `202` and enqueues a `KB_INDEX` job, which chunks and
  embeds the entry (the mock until M5), sets it `ACTIVE` and publishes the next version. If
  indexing fails, the entry stays `PENDING_REVIEW` and nothing is published; the reason code is
  shown on the entry (FR-53).
- **Every approval and retirement publishes an immutable version** listing all active entries,
  red-flag rule changes included, so the safety floor is versioned with the content it floors.
  A published version's entry list cannot be updated — the database rejects it (FR-54, DR-05).
- **Red-flag rules screen cases only once approved.** The eight rules the seed writes are marked
  as placeholders, which `APP_ENV=dev` includes and any other environment excludes (NFR-08).
- **Baseline action sets are knowledge-base entries too.** An entry is either a `COMPLAINT` entry
  — clinical content, chunked and retrievable — or an `URGENCY_ACTIONS` entry holding the baseline
  suggested actions for one VTL category (FR-71, FR-72, ADR-18). A baseline set carries a citation
  and is versioned like any other entry, but is looked up by category and never chunked, embedded
  or similarity-searched. At most one may be ACTIVE per category, so approving a replacement
  answers 409 until the live one is retired — and retiring it warns that the category will show no
  baseline actions until a replacement is approved. Its lines are held to the same FR-28 boundary
  as the AI-tailored actions: no medication, no dose, no diagnosis.

### Importing curated files

Entries and red-flag rules are curated as YAML under `knowledge_base/` and imported as drafts;
nothing is fetched from an external source at run time (FR-55, FR-56).

```bash
docker compose exec backend python -m scripts.import_kb --dry-run   # report only, writes nothing
docker compose exec backend python -m scripts.import_kb             # rules, then entries
```

Re-importing an unchanged file does nothing at all — no row write and no audit entry — and
**an ACTIVE entry is never modified in place**: a changed file becomes a new `DRAFT` revision with
`revises_entry_id` set and the slug `<slug>-rev2`, which goes through approval again (ADR-14). An
entry waiting for review, and an already-approved red-flag rule, are skipped rather than edited.
The formats, the fields and the full upsert table are in
[`knowledge_base/README.md`](knowledge_base/README.md).

The two entries in `knowledge_base/entries/` today are **SAMPLE** placeholders with a deliberately
fake citation, there so the workflow can be walked end to end; M5 replaces them with sourced
content.

## Running tests

```bash
docker compose exec backend pytest -q                 # unit and integration (mocks, no network)
docker compose exec backend pytest -q -m llm          # golden tests; these call the real model
cd frontend && npm run lint && npm run test
cd e2e && npx playwright test                         # the four demo scenarios
```

Tests marked `llm` are excluded by default because they consume provider quota.

## Repository layout

```
backend/app/        api · core · db · models · schemas · repositories · services
                    pipeline (stages, orchestrator, safety and action validators)
                    adapters (llm, embeddings) · jobs · kb · eval
backend/prompts/    versioned prompt templates
backend/scripts/    seed, import_kb, llm_* developer scripts
frontend/src/       pages (one folder per wireframe), components, hooks, api
knowledge_base/     entries, red-flag rules and phrases, APPROVALS.md
evaluation/         vignettes and run results
docs/               srs · adr · dev-prompts · prototype · deliverables
deploy/             production compose, Nginx, backup
```

## Documentation

| Document | Contents |
|---|---|
| [`docs/srs/`](docs/srs/README.md) | All 168 requirements as tables (FR, NFR, IR, BR, DR, SR) |
| [`docs/adr/`](docs/adr/README.md) | ADR-01 to ADR-18 with diagrams and a decision map |
| `docs/prototype/TriageAI_Prototype.html` | Clickable wireframes W-01 to W-11 |
| `docs/dev-prompts/` | Build guides: `00-START-HERE.md` first |
| `docs/deliverables/` | `SE_Project_Deliverables` — the course deliverable document |
| `CLAUDE.md` | Project context and constraints for AI-assisted development |

## Build progress

Complete: P01 scaffold, P02 database, P03 auth and RBAC, P04 intake and queue, P05 pipeline
framework, P05b suggested actions, P06 clinical review, M1 de-identification and red-flag
screening, M2 LLM provider adapter, M3 extraction, M4 embeddings, P08 knowledge-base
management, M5 KB authoring, chunking, and indexing, M6 Retrieval and recommendation generation
Next: M6b LLM action suggestion. See
`docs/dev-prompts/00-START-HERE.md`.

## Privacy and data handling

- Owner name and contact number are stored in a separate table that no pipeline or export query
  reads, and they never appear in an API response.
- The description is de-identified before any external call, and the pipeline **fails closed**: if
  de-identification errors, the case is routed to manual triage before the model is contacted.
- Prompts, model responses and suggested action text are never written to application logs.
- The project runs on a free provider tier whose terms may permit the provider to use submitted
  text to improve its products, so only fictitious or de-identified text is ever sent. A clinical
  deployment would require a paid no-training agreement or a self-hosted model.

## Known limitations

- English input only; staff translate Filipino or Bikol wording at intake (ADR-16).
- Dogs and cats only; other species are routed to manual triage.
- The knowledge base is compiled from published sources and is not clinically validated.
- Evaluation uses fictitious vignettes labelled by the team against a written rubric, with
  inter-rater agreement reported, not by an external veterinarian.
- Single-server deployment with no horizontal scaling or high availability.

## License and use

Academic coursework. Clinical guidance in the knowledge base is paraphrased from published
sources, each cited in its entry; third-party reference material is not redistributed in this
repository.
