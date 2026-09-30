# P01 — Repository Scaffold and Development Environment

**Branch prefix:** `chore/p01-<n>-<name>`
**Requirements:** NFR-24, NFR-26, SR-11, IR-11 · ADR-01, ADR-02, ADR-03, ADR-13

## Goal

At the end of this phase, an empty but running TriageAI stack (database, backend, frontend) starts with one command. Every member can develop on it, and CI checks every pull request.

## Read first

- `CLAUDE.md`, sections 3, 4, 5, and 11
- `docs/adr/ADR-01`, `ADR-13`

## Out of scope (do NOT do in this phase)

- Any database tables or models (P02)
- Authentication (P03)
- Any feature screen except a placeholder home page
- Anything under CLAUDE.md §8 (AI boundary)

---

## Subphase 1.1 — Folder structure and tooling

**Tasks**

1. Create the full folder layout from CLAUDE.md §4. Add a `.gitkeep` in every folder that would otherwise be empty. Include these folders:
   - `backend/app/pipeline`
   - `backend/app/adapters/llm`
   - `backend/app/adapters/embeddings`
   - `backend/app/kb`
   - `backend/prompts`
   - `knowledge_base/entries`
   - `evaluation/vignettes`
   - `evaluation/results`
   - `e2e`
   - `db/init`
   - `deploy/nginx`
   - `deploy/backup`
   - `docs/dev-prompts`
2. Backend: create `backend/pyproject.toml` with the following.
   - Runtime dependencies: `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `sqlalchemy>=2`, `psycopg[binary]`, `alembic`, `argon2-cffi`, `pyjwt`, `httpx`, `python-multipart`, `pyyaml`
   - Dev dependencies: `pytest`, `pytest-cov`, `ruff`
   - Configuration sections for Ruff (line length 100, target py311, select `E,F,I,B,UP,S`) and pytest (`testpaths = ["tests"]`)
   - Do NOT add `sentence-transformers`, `torch`, `pgvector`, or any LLM SDK. Those are added manually in M2 and M4.
3. Frontend: scaffold with Vite's `react-ts` template in `frontend/`.
   - Add `react-router-dom`, `@tanstack/react-query`, `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom`, `eslint`, `prettier`, and `openapi-typescript`.
   - Enable TypeScript `strict`.
   - Add these scripts: `dev`, `build`, `lint`, `format`, `test`, and `gen:api` (generates `src/api/generated/schema.ts` from `http://localhost:8000/openapi.json`).
4. Root files:
   - `.gitignore`: Python, Node, `.env`, `evaluation/results/*` except `.gitkeep`, and `models/`
   - `.editorconfig`
   - `.pre-commit-config.yaml`: Ruff lint and format, Prettier, end-of-file fixer
   - `README.md`: title, one-paragraph description, and a "Quick start" section filled in during 1.2
5. `.env.example` with every variable, each with a comment explaining it:
   - `DB_PASSWORD`
   - `DATABASE_URL`
   - `TEST_DATABASE_URL`
   - `SECRET_KEY`
   - `SESSION_IDLE_MINUTES=30`
   - `CORS_ORIGINS=http://localhost:5173`
   - `APP_ENV=dev`
   - `TZ_DISPLAY=Asia/Manila`
   - All `PIPELINE_*`, `KB_INDEXER`, and `LLM_PROVIDER` settings from CLAUDE.md §8.3, set to `mock`
   - `MOCK_LLM_BEHAVIOR=ok`

**Acceptance**

- `ruff check backend` and `npm run lint` pass on the empty project.
- No forbidden dependencies (CLAUDE.md §8) appear in `pyproject.toml` or `package.json`.

---

## Subphase 1.2 — Docker Compose, backend app factory, frontend shell

**Tasks**

1. Write `db/init/01-extensions.sql` with `CREATE EXTENSION IF NOT EXISTS vector;` and nothing else. Vector columns and indexes are manual (M4).
2. Write `backend/Dockerfile`:
   - base image `python:3.11-slim`
   - install the project, then run `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
   - in dev, mount the source directory as a volume
3. Write `backend/app/core/config.py`:
   - a `Settings` class (pydantic-settings) for all variables in `.env.example`, with typed enums for the pipeline stage settings
   - a cached `get_settings()`
4. Write `backend/app/main.py`:
   - an app factory `create_app()` that sets title "TriageAI API", version `0.0.1`, CORS from settings, and a `/api/v1` router
   - `GET /api/v1/health` returns `{"status": "ok", "version": "0.0.1"}`
5. Write `backend/app/core/logging.py`: JSON-ish structured logging. Follow CLAUDE.md §9: no free-text case content in logs.
6. Write `frontend/Dockerfile`: Node 24, `npm ci`, `npm run dev -- --host`.
7. Build the frontend shell:
   - `src/main.tsx`, `src/App.tsx` with React Router and a QueryClient
   - a placeholder `HomePage` that calls `/api/v1/health` and shows the status
   - `src/api/client.ts` with a `fetch` wrapper that sends `credentials: "include"` and reads the base URL from `VITE_API_BASE_URL`
8. Write `src/styles/tokens.css` with CSS variables for:
   - neutral colors
   - VTL colors: `--vtl-red: #C62828; --vtl-orange: #E65100; --vtl-yellow: #F9A825; --vtl-green: #2E7D32; --vtl-blue: #1565C0`
   - spacing and radius
   - base font: system sans-serif
9. Write `docker-compose.yml` with three services:
   - `db`: `pgvector/pgvector:pg16`, a named volume, and a healthcheck using `pg_isready`
   - `backend`: depends on a healthy `db`, reads `env_file: .env`, port 8000
   - `frontend`: port 5173
10. Write `backend/tests/test_health.py` using FastAPI's `TestClient`.
11. Fill in the README "Quick start":
    - copy `.env.example` to `.env`
    - run `docker compose up --build`
    - list the URLs

**Acceptance**

- A clean clone plus `cp .env.example .env` plus `docker compose up --build` shows the React page with "API status: ok".
- `docker compose exec db psql -U triageai -d triageai -c "\dx"` lists `vector`.
- `docker compose exec backend pytest` passes.

---

## Subphase 1.3 — Continuous integration and repository conventions

**Tasks**

1. Write `.github/workflows/ci.yml` with two jobs, both running on pull requests to `develop` and `main`:
   - **backend:** set up Python 3.11, install, `ruff check`, `ruff format --check`, `pytest` against a `pgvector/pgvector:pg16` service container
   - **frontend:** set up Node 24, `npm ci`, `lint`, `test`, `build`
2. Write `.github/pull_request_template.md` with:
   - linked issue
   - requirements covered (FR/NFR IDs)
   - how to test
   - screenshots for UI changes
   - a checklist: tests added, audit entries where required, no real data, `.env.example` updated
3. Write `.github/CODEOWNERS` with placeholder GitHub usernames for three lanes:
   - A: backend api, services, models
   - B: pipeline, adapters, prompts, knowledge_base
   - C: frontend, deploy, e2e
4. Write `docs/CONTRIBUTING.md` covering:
   - the branch model: `main`, `develop`, and `feat/`, `fix/`, `chore/`, `docs/`, `test/`, `spike/`, `hotfix/` branches
   - Conventional Commits with requirement IDs
   - squash-merge into `develop`
   - one migration per PR

**Acceptance**

- The CI workflow file is valid YAML, and jobs reference the correct paths.
- `pre-commit run --all-files` passes locally.

---

## Verification (run yourself after the phase)

```bash
git clone <repo> t && cd t && cp .env.example .env
docker compose up --build -d
curl -s http://localhost:8000/api/v1/health        # {"status":"ok",...}
open http://localhost:5173                          # shows API status ok
docker compose exec backend pytest -q
cd frontend && npm run lint && npm run test && npm run build
```

## Final report required from Claude Code

- Files created
- Commands run and their results
- Anything deviating from CLAUDE.md
- Items noticed for later phases
