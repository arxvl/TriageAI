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

## Disclaimer
The system provides decision support only. It never diagnoses, never recommends treatment, and
never finalizes a category without a human decision.
