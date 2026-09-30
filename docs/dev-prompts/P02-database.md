# P02 — Database Schema, Migrations, and Seed Data

**Branch prefix:** `feat/p02-<n>-<name>`
**Requirements:** DR-01–DR-08, FR-03, FR-05, FR-43, FR-54 · ADR-04, ADR-12 · PD6 domain model (Figures 6.15–6.16) · PD7 §7.1.6

## Goal

All persistent tables exist, managed by Alembic, with the integrity rules the SRS requires. A seed script creates realistic *fictitious* development data.

## Read first

- `CLAUDE.md` §6–§9
- PD7 §7.1.6 (table list) and the PD6 domain model in `docs/diagrams/`

## Out of scope

- Any API endpoints, apart from keeping `/health` working
- Password hashing logic beyond what the seed needs. Use a helper that P03 will reuse: put `hash_password()` in `app/core/security.py` now, using argon2-cffi.
- **The `embedding` column on `kb_chunks` and any vector index.** These are added manually in M4. Create `kb_chunks` without them.

---

## Subphase 2.1 — Enums, base model, SQLAlchemy models

**Tasks**

1. Write `app/db/base.py` (declarative base, UUID primary key mixin, `created_at` and `updated_at` in UTC) and `app/db/session.py` (engine, `SessionLocal`, `get_db` dependency).
2. Write `app/models/enums.py` with the Python enums from CLAUDE.md §6, mapped to PostgreSQL enum types.
3. Write the models, one file per aggregate, as follows.
   - **`user.py`:** `User`
     - Columns: `id`, `full_name`, `email` (unique, lower-case), `password_hash`, `role`, `can_approve_kb` (bool, default false), `is_active`, `must_change_password`, `failed_login_count`, `locked_until`, `last_login_at`
     - Check constraint: `can_approve_kb` implies `role = VETERINARY_REVIEWER`
   - **`case.py`:**
     - `Case`: `id`, `case_no` (unique, from a sequence formatted as `C-0001`), `species`, `intake_channel` (enum `WALK_IN|PHONE|MESSAGE`), `status`, `created_by`, `created_at`, `closed_at`
     - `Signalment` (1–1): `pet_name`, `age_value`, `age_unit` (`MONTHS|YEARS`), `sex` (`MALE|FEMALE|UNKNOWN`), `neutered`, `breed`, `weight_kg`
     - `OwnerDescription` (1–1): `text`, `char_count`, `submitted_at`
     - `OwnerReference` (0..1): `owner_name`, `contact_number`
   - **`ai_output.py`:**
     - `ExtractionResult`: `id`, `case_id` *or* `vignette_id`, `version`, `entities` (JSONB), `red_flags` (JSONB), `missing_information` (JSONB), `is_corrected`, `corrected_by`, `model_id`, `prompt_version`, `latency_ms`, `created_at`
     - `extraction_complaints` junction table (`extraction_id`, `complaint_code`, `is_primary`)
     - `Recommendation`: `id`, `case_id` *or* `vignette_id`, `extraction_id`, `kb_version_id` (nullable while mocks run), `version`, `category`, `rationale`, `confidence`, `safety_floor_applied`, `safety_floor_rule_codes` (JSONB), `low_confidence_reasons` (JSONB), `model_id`, `prompt_version`, `params` (JSONB), `latency_ms`, `created_at`
     - `RetrievedReference`: `recommendation_id`, `rank`, `chunk_id` (nullable FK), `score`, `is_cited`, `entry_title`, `source_title`, `source_url`, `passage_text`. The passage text is copied so the audit stays readable after a KB change.
   - **`alert.py`:** `RedFlagAlert`: `id`, `case_id`, `rule_code`, `matched_text`, `min_category`, `created_at`, `acknowledged_at`
   - **`decision.py`:**
     - `StaffDecision`: `id`, `case_id`, `type`, `final_category`, `reason_code`, `reason_text`, `direction` (`UP|DOWN|SAME|NONE`), `decided_by`, `decided_at`, `amends_id` (self-FK)
     - `ClinicalNote`: `id`, `case_id`, `author_id`, `text`, `created_at`
   - **`audit.py`:** `AuditEntry`: `id` (bigserial), `ts`, `user_id` (nullable for system), `role`, `action`, `entity_type`, `entity_id`, `before` (JSONB), `after` (JSONB)
   - **`job.py`:** `Job`: `id`, `type` (`PIPELINE_RUN|REGENERATE|EVAL_RUN|KB_INDEX`), `case_id`, `vignette_id`, `payload` (JSONB), `status` (`QUEUED|RUNNING|DONE|FAILED`), `attempts`, `last_error`, `run_after`, `created_at`, `updated_at`
   - **`knowledge_base.py`:**
     - `PresentingComplaint`: `code` PK, `name`, `sort_order`
     - `KBEntry`: `id`, `complaint_code`, `title`, `content`, `species` (array of Species), `source_title`, `source_publisher`, `source_url`, `access_date`, `status`, `created_by`, `approved_by`, `approved_at`, `review_comments`
     - `RedFlagRule`: `id`, `code` (unique), `label`, `min_category`, `species` (array), `entry_id` (nullable), `is_placeholder` (bool), `approved_by`, `approved_at`
     - `KBChunk`: `id`, `entry_id`, `chunk_index`, `text`, `word_count`, `created_at`. **No embedding column.**
     - `KBVersion`: `id`, `version_no` (unique), `published_at`, `published_by`, `note`
     - `kb_version_entries` junction table
   - **`evaluation.py`:**
     - `EvaluationSet`: `id`, `name`, `imported_at`, `imported_by`
     - `Vignette`: `id`, `set_id`, `external_id`, `species`, `description`, `reference_category`, `relevant_entry_ids` (JSONB)
     - `EvaluationRun`: `id`, `set_id`, `kb_version_id`, `config` (JSONB), `status`, `metrics` (JSONB), `started_at`, `finished_at`
     - `EvaluationResult`: `run_id`, `vignette_id`, `recommendation_id`, `extraction_id`, `predicted_category`, `stage_latencies` (JSONB), `error`
4. Check constraints:
   - On `extraction_results` and `recommendations`: `(case_id IS NULL) <> (vignette_id IS NULL)`.
   - On `staff_decisions`: `reason_code` is required when `type = 'ADJUST'`.
5. Indexes:
   - `cases(status, created_at)`
   - `recommendations(case_id, version DESC)`
   - `audit_log(entity_type, entity_id, ts)`
   - `jobs(status, run_after)`

**Acceptance**

- The models import cleanly.
- `python -c "from app.models import *"` works.
- Unit tests confirm the enum values match CLAUDE.md §6.

---

## Subphase 2.2 — Alembic migrations and database-level protections

**Tasks**

1. Initialize Alembic in `backend/`. Its `env.py` reads `DATABASE_URL` from settings and uses `app.db.base.Base.metadata`.
2. Create the migration `0001_initial_schema` from the models.
   - Review the autogenerated output by hand.
   - Enums must be created before the tables and dropped after them on downgrade.
3. Create the migration `0002_db_protections` with raw SQL (ADR-12, FR-05, FR-43):
   - Create an application role `triageai_app`. Its password comes from the `DB_APP_PASSWORD` environment variable; add that variable to `.env.example`.
   - Grant it the normal privileges on all tables.
   - Revoke `UPDATE` and `DELETE` on `audit_log` and `UPDATE` on `owner_descriptions` from `triageai_app`.
   - Add a trigger function `prevent_modify()` that raises an exception, fired `BEFORE UPDATE OR DELETE` on `audit_log`, and `BEFORE UPDATE` on `owner_descriptions` and `kb_version_entries`.
   - Change `DATABASE_URL` in `.env.example` so the app connects as `triageai_app`. Migrations keep using the owner account through `MIGRATION_DATABASE_URL`; add that variable too.
4. Create a test-database fixture in `tests/conftest.py`:
   - Create `triageai_test` if it is missing.
   - Run migrations once per session.
   - Wrap each test in a transaction that rolls back.

**Acceptance**

- `alembic upgrade head` succeeds on an empty database.
- `alembic downgrade base` and `alembic upgrade head` also succeed.
- Tests prove that, when run as `triageai_app`:
  - `UPDATE audit_log ...` fails;
  - `DELETE FROM audit_log ...` fails;
  - `UPDATE owner_descriptions ...` fails;
  - an insert that violates the `can_approve_kb` constraint fails;
  - an `extraction_results` row with both `case_id` and `vignette_id` fails.

---

## Subphase 2.3 — Seed data (fictitious only)

**Tasks**

1. Write `scripts/seed.py`. It must be idempotent: safe to run twice.
   - **Users**, each with the password `ChangeMe!2026` and `must_change_password=true`:
     - `admin@triageai.local` — ADMINISTRATOR
     - `intake@triageai.local` — INTAKE_STAFF, "J. Cruz"
     - `reviewer@triageai.local` — VETERINARY_REVIEWER, "Dr. M. Santos"
     - `approver@triageai.local` — VETERINARY_REVIEWER with `can_approve_kb=true`, "Dr. A. Rivera"
   - **Presenting complaints:** the 20 SRS complaints (SRS §4.2.1) with stable codes, e.g. `RESPIRATORY_DISTRESS`, `COLLAPSE`, `SEIZURES`, `TRAUMA`, `BLEEDING`, `VOMITING`, `DIARRHEA`, `TOXIN_INGESTION`, `FOREIGN_BODY`, `URINARY_OBSTRUCTION`, `ABDOMINAL_DISTENSION`, `DYSTOCIA`, `HEAT_STRESS`, `LETHARGY`, `INAPPETENCE`, `COUGH_SNEEZE`, `LAMENESS`, `EYE`, `SKIN_ITCH`, `EAR`, plus `OTHER`.
   - **Placeholder red-flag rules** with `is_placeholder=true`:
     - `NOT_BREATHING` → RED
     - `UNRESPONSIVE` → RED
     - `ACTIVE_SEIZURE` → RED
     - `UNCONTROLLED_BLEEDING` → RED
     - `MALE_CAT_NO_URINE` → ORANGE
     - `TOXIN_INGESTION` → ORANGE
     - `PALE_OR_BLUE_GUMS` → RED
   - Add a comment: *"Placeholder — replaced by vet-approved rules in P08/M5."*
   - **An empty KB version:** `version_no=0`, note "Seed – no entries".
2. Write `backend/tests/fixtures/demo_cases.yaml` with the four demo scenarios from the PD8 roadmap. Each has a fixture ID, species, signalment, the owner's text, and the expected category.
   - `DEMO_1`: male cat, urinary, expected ORANGE with the safety floor
   - `DEMO_2`: dog, breathing, expected RED
   - `DEMO_3`: dog, itching, expected BLUE
   - `DEMO_4`: any case with forced failure, expected MANUAL
3. Add `python -m scripts.seed --reset` (development only). It truncates all tables except `alembic_version` and re-seeds. It must refuse to run when `APP_ENV != dev`.

**Acceptance**

- `python -m scripts.seed` twice in a row creates no duplicates.
- `--reset` refuses when `APP_ENV=prod`.

---

## Verification

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m scripts.seed
docker compose exec db psql -U triageai -d triageai -c "\dt"
docker compose exec db psql -U triageai -d triageai -c "select email, role, can_approve_kb from users;"
docker compose exec backend pytest -q
```

Final report: tables created, constraints and triggers added, seed contents, anything left for later phases.
