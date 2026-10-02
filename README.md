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

A validation error carries one more key, `field`, naming the input it belongs to so
the form can put the message beside it rather than at the top of the page (IR-05):

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Enter the weight as a number, e.g. 4.2.",
    "field": "weight_kg"
  }
}
```

The wording for each field lives in `app/core/validation_messages.py`, so the API
and the forms cannot drift apart.

Authorisation is enforced on the server only: every endpoint except
`/api/v1/health` and `/api/v1/auth/login` declares the `require_role(...)`
dependency, and a test scans the route table to prove it (SR-05).

## Cases

| Endpoint | Roles | Purpose |
|---|---|---|
| `POST /api/v1/cases` | Intake Staff, Veterinary Reviewer | Create a case and start its triage → 202 `{id, case_no, status}` |
| `GET /api/v1/cases` | all roles | The Triage Queue, with filters and counters |
| `GET /api/v1/cases/{id}/status` | Intake Staff, Veterinary Reviewer | Poll one case |

Species is Dog or Cat. `OTHER` is accepted by the form and answered with 422
`SPECIES_OUT_OF_SCOPE` — those cases are triaged by clinic procedure and no AI
pipeline runs for them (FR-02, BR-06). Nothing is written when a case is refused.

A submission writes the case, its signalment, the owner's description and, only
when one is given, the owner reference in a single transaction, plus a
`CASE_CREATED` audit entry holding identifiers and a character count and never the
description text. `owner_descriptions.text` is stored verbatim and cannot be
updated afterwards — a database trigger, not just application code (FR-05).

Owner name and contact number go to `owner_references` and are returned by no
endpoint (FR-07, DR-04). No response model has a field for them:

```bash
docker compose exec db psql -U triageai -d triageai -c "select * from owner_references;"
```

The queue returns open cases — anything not `CLOSED` — ordered by the category it
displays, which is the reviewer's confirmed category when there is one and the AI's
recommendation otherwise: **RED, then cases with no category at all, then ORANGE,
YELLOW, GREEN, BLUE**, oldest first within a rank (FR-29). An unclassified case
sits second because nobody has looked at it yet. Each row carries its waiting time
against the category's target and an `is_overdue` flag (FR-30).

Filters are `species`, `category` (the five categories plus `MANUAL`), `status`,
`date_from`/`date_to` and a free-text `q` over case number, pet name and primary
complaint, with `limit` and `offset` to bound the response (FR-39). `date_from` and
`date_to` are inclusive calendar dates read in the clinic's timezone, so "today"
means the clinic's working day although every timestamp is stored in UTC (DR-03).
The counters always describe the whole open queue and do not move when a filter is
applied, so a counter can be used to apply one.

The queue response also carries `red_flag_alerts`: every unacknowledged alert on
an open case, with the case number, the species, the pet's name and the clinic's
own label for the rule that fired. It is deliberately unfiltered — an alert is
about a patient who needs someone now, and a filter the user happens to have on
must not hide it — and it carries no part of the owner's description (FR-12,
NFR-05).

`GET /cases/{id}/status` answers `{status, category, has_red_flag, pipeline_stage,
updated_at}`. `pipeline_stage` is `queued`, `deidentify`, `screen`, `extract`,
`retrieve`, `generate`, `done` or `failed`, read from the case's newest
`PIPELINE_RUN` job, so W-03 can say which step is running rather than only
"processing" (IR-22).

## Triage pipeline

The AI stages are implemented manually by the team, guided by
`docs/dev-prompts/M1`–`M7`. Everything around them — the contracts, the stage
registry, the job queue, the deterministic safety validator — is ordinary
application code, so the whole system runs end to end before any AI component
exists (ADR-17).

Each stage is a Protocol in `backend/app/pipeline/stages.py` with two
implementations: a deterministic mock, and a real one written later. **All stage
settings default to `mock`**, so a clean checkout starts, serves and passes its
tests with no API key, no model download and no network.

| Setting | Default | Real value | Guide |
|---|---|---|---|
| `PIPELINE_DEIDENTIFIER` | `mock` | `rules` | M1 |
| `PIPELINE_REDFLAGS` | `mock` | `keywords` | M1 |
| `LLM_PROVIDER` | `mock` | `hosted`, `ollama` | M2 |
| `PIPELINE_EXTRACTOR` | `mock` | `llm` | M3 |
| `EMBEDDING_PROVIDER` | *(blank)* | `sentence_transformer` | M4 |
| `KB_INDEXER` | `mock` | `pgvector` | M5 |
| `PIPELINE_RETRIEVER` | `mock` | `pgvector` | M6 |
| `PIPELINE_GENERATOR` | `mock` | `llm` | M6 |

`backend/app/pipeline/registry.py` imports a real stage's module **only if it is
selected**. Selecting one before its guide has been followed is a startup error
naming the guide, not an import traceback:

```
Stage PIPELINE_EXTRACTOR=llm selected but module not implemented yet
(see M3: docs/dev-prompts/M3-entity-extraction.md).
Set PIPELINE_EXTRACTOR=mock to run on the deterministic placeholder.
```

`EMBEDDING_PROVIDER` has no mock. Mock stages need no embeddings, so leaving it
blank is the working configuration.

**The de-identification guard.** The application refuses to start if
`LLM_PROVIDER` is anything other than `mock` while `PIPELINE_DEIDENTIFIER` is
still `mock` — the mock de-identifier returns the text unchanged, and only
de-identified text may ever leave the server (IR-20, ADR-10). The check is in
both `Settings` and the registry.

`MOCK_LLM_BEHAVIOR` chooses which failure the mocks simulate — `ok`,
`invalid_json`, `timeout`, `flaky` or `slow` — so the retry and manual-triage
paths can be demonstrated without a network call. The remaining pipeline
parameters (`PIPELINE_TOP_K`, `PIPELINE_TIMEOUT_S`, `PIPELINE_MAX_RETRIES`,
`RETRIEVAL_MIN_SCORE`, …) are documented in `.env.example`; keep
`PIPELINE_TEMPERATURE=0`, or a run stops being reproducible (ADR-14).

A mock run is not a result. Every mock reports `model_id=mock` and
`prompt_version=mock-0`, which is how a stored output can always be told apart
from a real one (FR-26, NFR-23).

### A run, end to end

`POST /cases` writes the case and a `PIPELINE_RUN` job **in one transaction** and
answers 202 (FR-06, ADR-08). There is no window in which a case exists that no
worker will pick up. A worker thread started from the FastAPI lifespan claims jobs
with `SELECT … FOR UPDATE SKIP LOCKED`, so two workers can never take the same one,
and `TriagePipeline.run` then does, in order:

1. `PROCESSING`, audit `PIPELINE_STARTED`.
2. **De-identify.** The only place `owner_references` is read inside a run, and the
   value is passed straight to the stage and bound to nothing (DR-04, ADR-10).
3. **Pre-screen,** then insert each `RedFlagAlert` and **commit at once**. This is
   the commit the design rests on: an alert reaches the queue within about two
   seconds even when every model call after it times out (NFR-05, FR-12).
4. **Extract,** retried `PIPELINE_MAX_RETRIES` times on unusable output and only on
   that — a timeout under load is not transient, and retrying one would spend the
   job's budget waiting (FR-15, IR-19).
5. Store the `ExtractionResult` at version previous + 1. Outputs are versioned,
   never updated, so a re-run after a crash leaves what a reviewer was shown
   intact (ADR-14).
6. Resolve the latest `KBVersion`, then **retrieve** and **generate**.
7. Run the **safety validator**, then store the `Recommendation` and one
   `RetrievedReference` per passage, each with the passage text copied and
   `is_cited` set from the *validated* citation ranks (FR-22).
8. `AWAITING_REVIEW`, audit `RECOMMENDATION_CREATED` — category and confidence
   only, never the rationale or the description.

The model never writes the stored category. `backend/app/pipeline/safety.py` takes
the draft and applies four deterministic rules: invalid citations are dropped and
their absence forces LOW confidence (FR-22); a red flag raises the category to its
minimum and records the rule code, **never lowering it** (FR-23, NFR-08); a best
retrieval score under `RETRIEVAL_MIN_SCORE` caps confidence at MEDIUM; and a
primary complaint of `OTHER` recommends manual triage. Confidence can only ever
fall (FR-24, ADR-09).

**Every failure ends somewhere.** Any stage failure sets the case to
`MANUAL_TRIAGE_REQUIRED`, writes `PIPELINE_FAILED` to the audit log and records a
reason code — `EXTRACTION_TIMEOUT`, `GENERATION_INVALID_OUTPUT`,
`KB_VERSION_MISSING`, … — in the job's `last_error`. A case is never lost and never
left in `PROCESSING` (NFR-09). Jobs a crash left `RUNNING` for more than
`JOB_STALE_AFTER_MINUTES` are returned to the queue on the next startup (NFR-13).

A run needs the rows `scripts/seed.py` creates: the presenting complaints, the
placeholder red-flag rules and knowledge-base version 0. Without a `KBVersion`
there is nothing to cite, so the run fails to manual triage rather than inventing
one (FR-22, FR-54).

```bash
docker compose exec backend python -m scripts.seed
docker compose exec db psql -U triageai -d triageai \
  -c "select action, entity_type, ts from audit_log order by id;"
docker compose exec db psql -U triageai -d triageai \
  -c "select type, status, attempts, last_error from jobs order by created_at;"
```

Paste the `DEMO_1` description from `backend/tests/fixtures/demo_cases.yaml` to see
FR-23 on screen: the mock generator drafts **YELLOW**, the pre-screen reports
`MALE_CAT_NO_URINE` at ORANGE, and the stored category is **ORANGE** with the rule
code recorded. `DEMO_4` fails on its own, whatever `MOCK_LLM_BEHAVIOR` is set to,
so the manual-triage path can be shown beside three working cases in one pass.

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

**Triage Queue** (`/queue`) is the screen staff work from (W-02). Rows arrive in
the server's FR-29 order and are never re-sorted in the browser, so one definition
of urgency exists rather than two. Each row carries a VTL badge, which always
prints the category name *and* its target waiting time — colour never carries
meaning on its own (IR-03) — and a status chip, so an AI recommendation reads as
pending until a reviewer decides (FR-36, IR-04). The waiting column shows the
elapsed time against the target with a progress bar; a case past its target is
tinted and labelled "overdue" in words (FR-30). RED is the exception: its target
is 0, so the API reports it overdue a minute after arrival and the screen shows a
full red bar and the minutes without the word, which would otherwise be on every
RED row.

The counters above the table are also the category filter — pressing one applies
it, pressing it again clears it — and they keep describing the whole open queue
while a filter is on. Search covers the case number, pet name and primary
complaint; the date filter defaults to all open dates rather than today, so a case
left open overnight does not disappear. The queue re-asks the server every 15
seconds and stops while the tab is in the background (IR-22). Below 900 px each
row becomes a card whose fields are labelled from the column headings (W-11).

**New Case** (`/cases/new`) is the real intake form (W-03). Species is Dog, Cat or
"Other species" — choosing the third shows the manual-triage message and disables
submission, so the refusal happens before a request is sent as well as after
(FR-02). The description field states the English-entry rule staff follow
(FR-18, ADR-16) and counts characters against the 2,000 limit without truncating
what was pasted. Owner name and contact number sit in their own box, captioned
"stored separately and never sent to AI services" (FR-07). A successful
submission confirms the case number and returns to the queue.

Field limits and error wording are mirrored from the server in
`frontend/src/lib/caseValidation.ts`, so the form answers without a round trip
and still says exactly what the API would say. The form reports every invalid
field at once; the API reports the first, and places it beside the named input
through the envelope's `field` key (FR-04, IR-05).

The remaining feature screens are placeholders until P06-P09; the login screen,
the change-password screen, the Triage Queue, the intake form and the header shell
are real. Submitting a case shows "Processing…" with the number just assigned and
then moves to the queue, where the row carries the AI-pending chip until a reviewer
decides (FR-06, FR-36, IR-04). The banner above the table announces every
unacknowledged red-flag alert, naming the patient and the clinic's label for the
rule — never the text the rule matched (FR-12, NFR-05, DR-04).

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
