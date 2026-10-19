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
  failure path without a network call.

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
screening, M2 LLM provider adapter, M3 extraction, M4 embeddings, P08 §8.1 knowledge-base
workflow and versioning.
Next: P08 §8.2 YAML importer and §8.3 the knowledge-base screen. See
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
