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
