# CLAUDE.md — TriageAI

**Project:** TriageAI: A Transformer-Based NLP System for Canine and Feline Symptom Triage and Clinical Decision Support
**Team:** Letada, Alzaga, Bataller — BSCS Software Engineering, Bicol University College of Science
**Deliverable in progress:** PD8 (initial MVP prototype), due 2026-10-29

This file is read at the start of every Claude Code session. Follow it in every phase.

---

## 1. What the system does

TriageAI helps veterinary clinic staff prioritize incoming dog and cat cases.

1. Intake Staff enter the owner's free-text description of the pet's symptoms.
2. An AI pipeline extracts clinical details and recommends one of five
   Veterinary Triage List (VTL) urgency categories, with a rationale and cited
   knowledge-base passages.
3. A Veterinary Reviewer confirms or adjusts the recommendation
   (Human-in-the-Loop). Every action is audited.

The system gives **decision support only**. It never diagnoses, never
recommends treatment, and never finalizes a category without a human decision.

## 2. Source documents (in `docs/`)

- `docs/srs/` — Software Requirements Specification v1.0. Requirement IDs:
  FR-xx (functional), NFR-xx, IR-xx (interface), DR-xx (data), SR-xx
  (security), BR-xx (business rules).
- `docs/diagrams/` — PD6 DFDs and UML (use cases UC-01..UC-16, domain model).
- `docs/adr/` — PD7 architecture decisions ADR-01..ADR-15.
- `docs/prototype/TriageAI_Prototype.html` — clickable wireframes W-01..W-11.
  **Match these screens when building UI.**
- `docs/dev-prompts/` — the phase prompts (Pxx) and manual guides (Mxx).

When a task cites an ID (FR-23, ADR-08, W-04), look it up in these documents.
Do not invent requirements.

## 3. Tech stack (fixed — do not substitute)

| Layer | Choice |
|---|---|
| Frontend | React 18, TypeScript (strict), Vite, React Router v6, TanStack Query, CSS Modules + `src/styles/tokens.css` |
| Frontend tests | Vitest + React Testing Library; Playwright for end-to-end tests (`e2e/`) |
| Backend | Python 3.11, FastAPI, Pydantic v2, pydantic-settings, Uvicorn |
| Database | PostgreSQL 16 + pgvector (image `pgvector/pgvector:pg16`) |
| ORM / migrations | SQLAlchemy 2.0 (sync sessions, `psycopg` v3 driver), Alembic |
| Auth | argon2-cffi (Argon2id), PyJWT (signed session token in an HttpOnly cookie) |
| HTTP client | httpx |
| Backend tests | pytest, pytest-cov |
| Lint/format | Ruff (lint + format) for Python; ESLint + Prettier for TypeScript; pre-commit |
| Runtime | Docker Compose (dev: `docker-compose.yml`; prod: `deploy/docker-compose.prod.yml`), Nginx in prod |
| Node | Node.js 24 LTS |

## 4. Repository layout (summary)

```
frontend/            React app (pages/ = one folder per wireframe W-xx)
backend/app/         api/v1, core, db, models, schemas, repositories, services,
                     pipeline, adapters/{llm,embeddings}, jobs, eval, kb
backend/prompts/     versioned prompt templates (filled in manually, see Mxx guides)
backend/migrations/  Alembic
backend/scripts/     seed.py, import_kb.py
backend/tests/       unit/, integration/, fixtures/
knowledge_base/      entries/*.yaml, red_flags.yaml, APPROVALS.md
evaluation/          vignettes/, results/
e2e/                 Playwright tests
db/init/             01-extensions.sql
deploy/              prod compose, nginx, backup
docs/                srs, diagrams, adr, prototype, dev-prompts
```

Keep to this layout. Create a new top-level folder only if a phase prompt says so.

## 5. Commands

```bash
docker compose up --build                                      # start the dev stack
docker compose exec backend alembic upgrade head               # apply migrations
docker compose exec backend python -m scripts.seed             # seed dev data
docker compose exec backend pytest                             # backend tests
docker compose exec backend ruff check . && docker compose exec backend ruff format --check .
cd frontend && npm run lint && npm run test && npm run build   # frontend checks
cd e2e && npx playwright test                                  # end-to-end tests
```

URLs:

- Frontend dev server: http://localhost:5173
- API: http://localhost:8000/api/v1
- API docs: http://localhost:8000/docs

## 6. Domain constants (use these exact values)

VTL categories, in order of urgency, with target waiting times (minutes):

| Code | Label | Target | Display |
|---|---|---|---|
| `RED` | Immediate | 0 | Immediate |
| `ORANGE` | Very urgent | 15 | ≤ 15 min |
| `YELLOW` | Urgent | 60 | ≤ 30–60 min |
| `GREEN` | Standard | 120 | ≤ 120 min |
| `BLUE` | Non-urgent | 240 | ≤ 240 min |

**CaseStatus:**

- `SUBMITTED`
- `PROCESSING`
- `AWAITING_REVIEW`
- `MANUAL_TRIAGE_REQUIRED`
- `CONFIRMED`
- `ADJUSTED`
- `MANUALLY_TRIAGED`
- `CLOSED`

**Other enums:**

- **UserRole:** `INTAKE_STAFF`, `VETERINARY_REVIEWER`, `ADMINISTRATOR`. KB approval is a separate boolean, `can_approve_kb`, which is only allowed for `VETERINARY_REVIEWER`.
- **KBEntryStatus:** `DRAFT`, `PENDING_REVIEW`, `ACTIVE`, `RETIRED`.
- **DecisionType:** `CONFIRM`, `ADJUST`, `MANUAL`.
- **ConfidenceLevel:** `HIGH`, `MEDIUM`, `LOW`.
- **Species:** `DOG`, `CAT`. Other species are rejected from AI processing.

**Language scope (FR-18):** all input, UI text, and stored content are in **English**. Clinic staff translate Filipino or Bikol wording reported by owners when entering the case, and may quote uncertain terms in quotation marks. Do not add language detection, translation, or non-English phrase lists, prompts, or fixtures anywhere. Interface strings still live in resource files so a translated UI can be added later (NFR-27).

Queue sort order (FR-29):

1. Rank the category: confirmed category if present, else recommended.
   Order: RED, then cases with no category (MANUAL_TRIAGE_REQUIRED or still
   processing), then ORANGE, YELLOW, GREEN, BLUE.
2. Within the same rank, sort by arrival time, oldest first.

## 7. Architecture rules

- Layering: `api` → `services` → (`pipeline` | `repositories`) → `models`.
  Routers contain no business logic. Services never import FastAPI.
- Enforce authorization on the server with the `require_role(...)` dependency
  on every endpoint except `/health` and `/auth/login` (SR-05).
- Use `/api/v1` as the base path for all API routes, with JSON in UTF-8.
- Store all timestamps in UTC. The frontend displays them in Asia/Manila.
- The audit log is append-only (FR-43, ADR-12). Services write audit entries
  through `AuditService` only.
- `owner_descriptions.text` is never updated after insert (FR-05).
- `owner_references` is never read by any pipeline code (DR-04).
- The pipeline runs in a background worker, never inside a request (ADR-08).

## 8. AI BOUNDARY — READ BEFORE EVERY PHASE

The team implements all NLP/AI components **manually**, using the guides
`docs/dev-prompts/M1..M7`.

**Claude Code must NOT:**

- call any real LLM API, or write provider-specific LLM code;
- write prompt templates or tune prompts;
- install or load embedding models (`sentence-transformers`, `torch`) or
  write embedding code;
- write vector-search SQL, create pgvector columns or indexes, or write
  chunking or indexing code;
- write de-identification patterns or red-flag phrase-matching logic;
- write real extraction, retrieval, or generation stage logic.

**Claude Code MAY and SHOULD:**

- define the interfaces and data contracts below exactly;
- write **mock** implementations (deterministic, fixture-based) so the
  whole app works end to end without AI;
- wire stage selection through configuration;
- implement deterministic, non-AI logic:
  - the safety and citation validator (FR-22, FR-23, FR-25);
  - the job queue;
  - status transitions;
  - metrics computation from stored results.

If a task seems to need anything on the NOT list, leave a comment
`# TODO(manual:Mx): <what>` and mention it in your final report.

### 8.1 Contracts (`backend/app/pipeline/types.py`, Pydantic models)

```python
class RedFlagHit(BaseModel):
    rule_code: str
    matched_text: str
    min_category: VTLCategory

class ExtractedComplaint(BaseModel):
    code: str                  # presenting_complaints.code or "OTHER"
    is_primary: bool

class EvidenceSpan(BaseModel):
    field: str                 # e.g. "onset_duration"
    text: str                  # exact substring of the de-identified text

class ExtractionOutput(BaseModel):
    species: Species
    signalment: dict[str, str | None]
    presenting_complaints: list[ExtractedComplaint]
    onset_duration: str | None
    frequency_severity: str | None
    associated_signs: list[str]
    negated_findings: list[str]
    exposure_history: str | None
    relevant_history: str | None
    red_flags: list[str]       # free-text indicators from the model
    missing_information: list[str]
    evidence_spans: list[EvidenceSpan]

class Passage(BaseModel):
    rank: int                  # 1..k
    chunk_id: UUID
    entry_id: UUID
    entry_title: str
    source_title: str
    source_url: str | None
    text: str
    score: float               # cosine similarity 0..1

class DraftRecommendation(BaseModel):
    category: VTLCategory
    rationale: str
    cited_ranks: list[int]     # ranks of Passage objects the model cited
    confidence: ConfidenceLevel

class FinalRecommendation(BaseModel):
    category: VTLCategory
    rationale: str
    cited_ranks: list[int]
    confidence: ConfidenceLevel
    safety_floor_applied: bool
    safety_floor_rule_codes: list[str]
    low_confidence_reasons: list[str]
```

### 8.2 Interfaces (`typing.Protocol`)

```python
# backend/app/adapters/llm/base.py
class LLMProvider(Protocol):
    name: str                  # e.g. "mock", "hosted", "ollama"
    model_id: str
    def complete_json(self, *, system: str, user: str,
                      json_schema: dict, timeout_s: float) -> dict: ...
        # raises LLMTimeout, LLMUnavailable, LLMInvalidOutput

# backend/app/adapters/embeddings/base.py
class EmbeddingProvider(Protocol):
    model_id: str
    dim: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...

# backend/app/pipeline/stages.py
class Deidentifier(Protocol):
    def deidentify(self, text: str, owner_name: str | None,
                   owner_contact: str | None) -> str: ...

class RedFlagScreener(Protocol):
    def screen(self, text: str, species: Species,
               sex: str | None) -> list[RedFlagHit]: ...   # sex: MALE|FEMALE|UNKNOWN|None

class EntityExtractor(Protocol):
    def extract(self, text: str, species: Species,
                signalment: dict | None = None) -> ExtractionOutput: ...
        # raises ExtractionFailed

class Retriever(Protocol):
    def retrieve(self, extraction: ExtractionOutput, kb_version_id: UUID,
                 k: int) -> list[Passage]: ...

class RecommendationGenerator(Protocol):
    def generate(self, extraction: ExtractionOutput,
                 passages: list[Passage]) -> DraftRecommendation: ...
        # raises GenerationFailed

# Every stage (mock or real) also exposes, for storage and reproducibility (FR-26, NFR-23):
#   model_id: str          ("mock" for mocks and non-model stages)
#   prompt_version: str    ("mock-0"; real LLM stages e.g. "extraction/v1.0")
#   last_latency_ms: int   (set after each call)

class KBIndexer(Protocol):   # used by the KB approval workflow
    def index_entry(self, entry_id: UUID) -> int: ...   # returns chunk count
    def remove_entry(self, entry_id: UUID) -> None: ...
```

### 8.3 Stage selection

`backend/app/pipeline/registry.py` builds each stage from settings. The
defaults are all `mock`. Non-mock stages are implemented **manually** by the
team, using exactly these module paths and class names. The registry imports
them lazily, only when selected, so the app starts before they exist.

| Setting | `mock` class (Claude Code) | Real value → `module:Class` (manual guide) |
|---|---|---|
| `PIPELINE_DEIDENTIFIER` | `app.pipeline.mocks:MockDeidentifier` | `rules` → `app.pipeline.deidentify_rules:RuleBasedDeidentifier` (M1) |
| `PIPELINE_REDFLAGS` | `app.pipeline.mocks:MockRedFlagScreener` | `keywords` → `app.pipeline.redflags_keywords:KeywordRedFlagScreener` (M1) |
| `LLM_PROVIDER` | `app.adapters.llm.mock:MockLLMProvider` | `hosted` → `app.adapters.llm.hosted:HostedLLMProvider`; `ollama` → `app.adapters.llm.ollama:OllamaLLMProvider` (M2) |
| `PIPELINE_EXTRACTOR` | `app.pipeline.mocks:MockEntityExtractor` | `llm` → `app.pipeline.extraction_llm:LLMEntityExtractor` (M3) |
| `EMBEDDING_PROVIDER` | *(none; only needed by real stages)* | `sentence_transformer` → `app.adapters.embeddings.sentence_transformer:SentenceTransformerEmbedder` (M4) |
| `KB_INDEXER` | `app.pipeline.mocks:MockKBIndexer` | `pgvector` → `app.kb.indexer_pgvector:PgVectorKBIndexer` (M5) |
| `PIPELINE_RETRIEVER` | `app.pipeline.mocks:MockRetriever` | `pgvector` → `app.pipeline.retrieval_pgvector:PgVectorRetriever` (M6) |
| `PIPELINE_GENERATOR` | `app.pipeline.mocks:MockRecommendationGenerator` | `llm` → `app.pipeline.generation_llm:LLMRecommendationGenerator` (M6) |

**Construction convention.** Every stage class, mock or real, provides:

```python
@classmethod
def from_settings(cls, settings: Settings, deps: "PipelineDeps") -> "Self": ...
```

`PipelineDeps` is a dataclass in `app/pipeline/registry.py`, built by the
registry in this order:

| Field | Type | Value when unused |
|---|---|---|
| `config` | `PipelineConfig` | — |
| `session_factory` | `sessionmaker` | — |
| `llm` | `LLMProvider \| None` | `None` when every stage is mock |
| `embedder` | `EmbeddingProvider \| None` | `None` unless `EMBEDDING_PROVIDER` is set |
| `rules_provider` | `Callable[[], list[RedFlagRule]]` | — (it is `get_active_rules` from P08) |

Before P08 exists, `rules_provider` returns all rules from the
`red_flag_rules` table.

**Safety guard:** the app must refuse to start if `LLM_PROVIDER` is not `mock`
while `PIPELINE_DEIDENTIFIER` is `mock`. De-identified text only must ever
leave the server (IR-20, ADR-10).

## 9. Safety and privacy rules

- Use fictitious data only: fixtures, seed data, tests, screenshots.
- Never log owner descriptions, owner references, prompts, or model
  responses at INFO level or above. Log IDs and timings instead.
- Never commit `.env`, API keys, or model weights. Keep `.env.example` complete.
- The UI always shows AI output as "AI Recommendation – requires staff
  confirmation" until a reviewer decides (IR-04).
- VTL colors are always shown with the category name and target time
  (IR-03). Never show color alone.

## 10. Testing rules

- Every service and pipeline component gets unit tests. Every endpoint gets
  at least one integration test for success, validation failure, and
  wrong-role (403).
- Tests use the mock stages and a separate test database
  (`triageai_test`), created by the test fixtures.
- Safety logic (validator, status transitions, RBAC, audit append-only)
  must have explicit tests. These are non-negotiable.
- The frontend has component tests for VTL badges, the AI label, and form
  validation.

## 11. Git rules

- Work on the branch named in the phase prompt, created from `develop`.
- Use Conventional Commits with requirement IDs, e.g.
  `feat(cases): validate description length (FR-04)`.
- Keep commits small. Never commit to `main` or `develop` directly.
- At most one Alembic migration per subphase. Name it after the subphase.

## 12. Definition of Done (every subphase)

1. Code follows sections 7–9.
2. Ruff, ESLint, Prettier, and type checks pass.
3. All tests pass, including new ones for the subphase.
4. `docker compose up --build` still works from a clean checkout.
5. `.env.example` and the README are updated if configuration changed.
6. You end with a **report**:
   - files changed;
   - how to verify, with exact commands;
   - requirements covered;
   - any `TODO(manual:Mx)` left;
   - open questions.

## 13. Working style

- Start each subphase in plan mode. List the files you will create or
  change, then wait for approval.
- Implement only the current subphase. If you notice work that belongs to a
  later phase, list it under "Later" in the report instead of doing it.
- Ask before adding any dependency not listed in section 3.
