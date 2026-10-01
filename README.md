# TriageAI

TriageAI is a transformer-based NLP system that helps veterinary clinic staff
prioritize incoming dog and cat cases. Intake staff enter the owner's free-text
description of a pet's symptoms; an AI pipeline extracts clinical details and
recommends one of five Veterinary Triage List (VTL) urgency categories with a
rationale and cited knowledge-base passages; a veterinary reviewer confirms or
adjusts the recommendation before it is finalized. 

## Quick start

```bash
cp .env.example .env
docker compose up --build
docker compose exec backend alembic upgrade head
```

- Frontend: http://localhost:5173
- API: http://localhost:8000/api/v1
- API docs: http://localhost:8000/docs

## Database

Two database roles, because the append-only guarantees are enforced by
PostgreSQL rather than by application code (FR-05, FR-43, ADR-12):

| Role | Connection string | Used by |
|---|---|---|
| owner (`triageai`) | `MIGRATION_DATABASE_URL` | Alembic only |
| `triageai_app` | `DATABASE_URL` | the application |

`triageai_app` is created by migration `0002_db_protections` with the password
from `DB_APP_PASSWORD`. It has no `UPDATE` or `DELETE` on `audit_log` and no
`UPDATE` on `owner_descriptions`, and a `prevent_modify()` trigger rejects
those statements even for the owner. **Run `alembic upgrade head` before
anything else touches the database** — the application's role does not exist
until that migration has run.

```bash
docker compose exec backend alembic upgrade head     # apply migrations
docker compose exec backend alembic downgrade base   # reverse them
docker compose exec backend alembic upgrade head --sql   # review the SQL
docker compose exec backend pytest                   # tests (creates triageai_test)
```

Tests run as `triageai_app` against a separate `triageai_test` database, which
the fixtures create and migrate; that is what proves the restrictions hold.

## Seed data

```bash
docker compose exec backend python -m scripts.seed           # insert what is missing
docker compose exec backend python -m scripts.seed --reset   # dev only: wipe, then re-seed
```

Everything seeded is fictitious. The script inserts four accounts
(`admin@`, `intake@`, `reviewer@`, `approver@triageai.local`), the 21 presenting
complaints, seven placeholder red-flag rules, and an empty knowledge-base
version 0. All four accounts use the password `ChangeMe!2026` and must change it
on first login.

Re-running the script is safe: it looks each row up by its natural key and never
overwrites an existing one, so it also never picks up an edit you made to
`scripts/seed.py`. Use `--reset` for that. `--reset` truncates every table —
including the append-only `audit_log` — so it refuses unless `APP_ENV=dev` and
connects as the owner role, which is the only role holding `TRUNCATE`.

The red-flag rules are placeholders (`is_placeholder=true`, no approver). They
give the FR-23 safety floor something to apply while the pipeline runs on mocks;
veterinarian-approved rules replace them in P08.

## Authentication

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/auth/login` | `{email, password}` → `{user: {...}}`, sets both cookies |
| `POST /api/v1/auth/logout` | Clears both cookies |
| `GET /api/v1/auth/me` | The signed-in account |
| `POST /api/v1/auth/change-password` | `{current_password, new_password}` |

The session is a signed token in `triageai_session` — `HttpOnly`, `SameSite=Lax`,
and `Secure` whenever `APP_ENV` is not `dev`. It is re-issued on every
authenticated request, so the 30-minute timeout in `SESSION_IDLE_MINUTES` is an
idle one (SR-04).

`triageai_csrf` is readable on purpose: every `POST`, `PATCH`, `PUT` and `DELETE`
must repeat its value in an `X-CSRF-Token` header or the request is rejected with
403 (SR-09). Login is the only exemption.

Five consecutive failed logins lock an account for 15 minutes and the API answers
423; every other rejection is the same 401, so accounts cannot be enumerated
(SR-03). While `must_change_password` is set, every endpoint outside `/auth/*`
answers 403 `PASSWORD_CHANGE_REQUIRED` (FR-61). Logins, failures, lockouts,
logouts and password changes all reach the append-only audit log (SR-12).

Every 4xx and 5xx response has the same shape:

```json
{ "error": { "code": "INVALID_CREDENTIALS", "message": "Incorrect username or password." } }
```

Authorisation is enforced on the server only: every endpoint except
`/api/v1/health` and `/api/v1/auth/login` declares the `require_role(...)`
dependency, and a test scans the route table to prove it (SR-05).

## Web interface

```bash
cd frontend
npm run lint      # ESLint
npm run test      # Vitest + React Testing Library
npm run build     # tsc -b, then the production bundle
```

Sign in at http://localhost:5173 with any seeded account and the password
`ChangeMe!2026`. Every seeded account starts with a temporary password, so the
first screen after login is always **Change password** (FR-61); nothing else is
reachable until it is replaced.

Navigation is role-aware (IR-02). The server enforces the same rules on every
request, so the UI only hides what the API would refuse (SR-05):

| Account | Lands on | Navigation |
|---|---|---|
| `intake@triageai.local` (Intake Staff) | `/queue` | Triage Queue, New Case, Case History |
| `reviewer@triageai.local` (Veterinary Reviewer) | `/queue` | Triage Queue, New Case, Case History |
| `approver@triageai.local` (Reviewer + `can_approve_kb`) | `/queue` | the three above, plus KB Approvals |
| `admin@triageai.local` (Administrator) | `/admin/users` | Users, Knowledge Base, Evaluation, Exports |

The feature screens behind those links are placeholders until P04-P09; the login
screen, the change-password screen and the header shell are real.

Interface text lives in `frontend/src/i18n/strings.ts` rather than inline, so a
translated UI can be added without touching components (NFR-27). All of it is
English (FR-18, ADR-16).

`frontend/src/api/client.ts` is the only place that calls the API: it sends the
session cookie, copies `triageai_csrf` into `X-CSRF-Token` on every mutating
request, and turns the error envelope into a typed `ApiError` so screens branch
on a code instead of a status (401 and 403 each cover several codes).

## Disclaimer
The system provides decision support only. It never diagnoses, never recommends treatment, and
never finalizes a category without a human decision.
