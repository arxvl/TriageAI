# P05b — Suggested Actions Framework (Mocks Only)

**Branch prefix:** `feat/p05b-<n>-<name>`
**Do after:** P05 · **Do before:** P06
**Requirements:** FR-28 (revised), FR-71–FR-79, NFR-29, NFR-30, IR-23, BR-10, DR-09, SR-17 · ADR-18

## Goal

Add suggested actions per urgency level to the existing pipeline, with **mock
generation**:

- schema, contracts and the `ActionSuggester` stage;
- baseline actions as `URGENCY_ACTIONS` knowledge-base entries;
- the deterministic **action validator**;
- a separate `SUGGEST_ACTIONS` background job;
- the status field the UI will poll.

After this phase, every case reaching `AWAITING_REVIEW` has baseline actions for
its category, plus mock tailored actions, stored and retrievable through the
API. The UI for them is built in P06.

## ⚠️ AI boundary (CLAUDE.md §8)

Do **not** write the actions prompt or any real LLM action logic. The module
`app.pipeline.actions_llm` does not exist yet and is built manually in guide
M6b. Selecting it must produce the usual clear startup error.

The **action validator is deterministic code with no model call** — it is yours
to write, and it must be thoroughly tested.

## Out of scope

- W-04 action checklist and the finalize UI (P06)
- Outdated-action handling on category change (P07)
- The real LLM stage (M6b)

---

## Subphase 5b.1 — Schema, contracts, baseline entries

**Tasks**

1. **Migration** `p05b_suggested_actions` (new revision — do not edit 0001/0002):
   - `kb_entries`: add `kind` (enum `COMPLAINT` | `URGENCY_ACTIONS`, default
     `COMPLAINT`, not null) and `urgency_category` (nullable). Add a check
     constraint: `urgency_category` is non-null **iff** `kind = 'URGENCY_ACTIONS'`.
     Add a partial unique index so at most one **ACTIVE** `URGENCY_ACTIONS`
     entry exists per category.
   - New `action_suggestions`: `id`, `case_id` *or* `vignette_id` (same
     exclusive-or check as `recommendations`), `recommendation_id`,
     `generated_for_category`, `rank`, `text`, `source` (enum `ActionSource`),
     `cited_chunk_ids` (JSONB), `model_id`, `prompt_version`, `kb_version_id`,
     `latency_ms`, `created_at`.
   - New `final_actions`: `id`, `case_id`, `decision_id`, `rank`, `text`,
     `source`, `status` (enum `ActionStatus`), `suggestion_id` (nullable FK),
     `finalized_by`, `finalized_at`.
   - Add `SUGGEST_ACTIONS` to the job type. **If P02 created a native
     PostgreSQL enum for job types, this needs `ALTER TYPE ... ADD VALUE` in its
     own transaction**, not a plain column change.
   - Grants for `triageai_app` on both new tables, and a `prevent_modify`
     trigger on `final_actions` (DR-09, ADR-12).
   - Add `actions_status` (`pending` | `ready` | `failed` | `not_applicable`)
     and `actions_error` to `recommendations`, or to a small side table — your
     choice, but it must be readable in one query with the recommendation.
2. **`app/models/enums.py`:** add `ActionSource`, `ActionStatus`, `KBEntryKind`
   and the new job type (CLAUDE.md §6).
3. **`app/models/action.py`:** `ActionSuggestion` and `FinalAction`.
4. **`app/pipeline/types.py`:** add `SuggestedAction` and `ActionPlan` exactly as
   in CLAUDE.md §8.1.
5. **`app/pipeline/stages.py`:** add the `ActionSuggester` Protocol (CLAUDE.md
   §8.2), with the usual `model_id`, `prompt_version`, `last_latency_ms`.
6. **`app/pipeline/errors.py`:** add `ActionsFailed`.
7. **`scripts/seed.py`:** seed five `URGENCY_ACTIONS` entries, one per VTL
   category, as **ACTIVE** in the seed KB version, each marked
   `SAMPLE – replace with sourced content in M5`. Two or three short placeholder
   actions each is enough; the team writes the real text in M5.

**Acceptance**

- `alembic upgrade head`, then `downgrade base`, then `upgrade head` all succeed.
- Tests prove: the `urgency_category` check constraint rejects a bad row; a
  second ACTIVE `URGENCY_ACTIONS` entry for the same category is rejected; an
  `UPDATE` on `final_actions` is rejected by the database.

---

## Subphase 5b.2 — Action validator (deterministic, fully tested)

Create `app/pipeline/action_validator.py`.

```python
def validate(actions: list[SuggestedAction], passages: list[Passage],
             max_items: int) -> tuple[list[SuggestedAction], list[str]]
```

**Rules, in order.** Return the kept actions and a list of rejection reasons.

1. **Citation check (FR-74).** Drop ranks not present in `passages`. An action
   left with no valid citation is **rejected** — reason `NO_VALID_CITATION`.
   (Unlike FR-22, where the recommendation survives with lowered confidence, an
   uncited action is simply not shown.)
2. **Length.** More than 25 words → `TOO_LONG`.
3. **Dose expression** → `CONTAINS_DOSE`. Match case-insensitively:
   - a number followed by a unit: `mg`, `mcg`, `µg`, `g`, `ml`, `mL`, `L`,
     `IU`, `cc`
   - `mg/kg`, `ml/kg`, `mg/lb`
   - routes next to a number: `IV`, `IM`, `SC`, `SQ`, `PO`, `IN`, `IO`
   - frequency: `q4h`, `q8h`, `BID`, `TID`, `SID`, `QID`, `PRN`
4. **Medication name** → `CONTAINS_DRUG`. Use a block list in
   `app/pipeline/blocklists.py`, seeded from the drug names in the project's
   triage reference (butorphanol, acepromazine, dexmedetomidine, propofol,
   alfaxalone, ketamine, diazepam, midazolam, methocarbamol, levetiracetam,
   phenobarbital, furosemide, terbutaline, albuterol, dexamethasone, mannitol,
   dextrose, calcium gluconate, hypertonic saline) plus generic terms
   (`antibiotic`, `steroid`, `sedative`, `anaesthetic`, `anesthetic`,
   `analgesic`, `NSAID`). Match on word boundaries.
5. **Diagnosis assertion** → `CONTAINS_DIAGNOSIS`. Block a diagnosis-term list
   (pneumonia, pyometra, GDV, bloat, obstruction, parvovirus, pancreatitis,
   hypoglycaemia/hypoglycemia, cardiomyopathy, pleural effusion, pneumothorax,
   asthma, epilepsy, poisoning) **when asserted as fact**. Allow hedged
   references — "ask whether a toxin was eaten" or "rule out obstruction" are
   fine. Implement this as: the term is rejected unless it appears within three
   words of a hedge (`possible`, `suspected`, `rule out`, `ask`, `check`,
   `if`, `whether`, `monitor for`, `watch for`).
6. **Deduplicate** on normalized text, then truncate to `max_items`.

Also expose `baseline_actions(session, category, kb_version_id) -> list[str]`:
read the ACTIVE `URGENCY_ACTIONS` entry for that category in that KB version and
split its content into lines. Returns `[]` if none exists, and logs a warning.

**Tests — at least 20 cases, these are non-negotiable (NFR-30):**

- a clean action with a valid citation passes
- an invalid citation rank is dropped; no citations left → rejected
- 26 words → rejected
- `"Give butorphanol 0.2 mg/kg IV"` → rejected (drug **and** dose)
- `"Administer 2 mL of dextrose"` → rejected
- `"Start antibiotics"` → rejected (generic drug term)
- `"Prepare oxygen and alert the veterinarian"` → **passes**
- `"Monitor respiratory rate every few minutes"` → **passes**
- `"Ask the owner whether the cat has eaten any toxin"` → **passes** (hedged)
- `"The dog has pneumonia"` → rejected
- `"Watch for signs of obstruction"` → **passes** (hedged)
- duplicates collapse; `max_items` truncates
- empty input returns empty, with no exception

---

## Subphase 5b.3 — Mock stage, job, orchestrator wiring

**Tasks**

1. **`app/pipeline/mocks.py`: `MockActionSuggester`.**
   - Fixture-driven from `tests/fixtures/demo_cases.yaml`: add a `mock_actions`
     key to each of the four demo cases.
   - With no fixture match, return two generic actions **for the given
     category**, each citing rank 1, so all five categories are exercised.
   - Honour `MOCK_LLM_BEHAVIOR`: `timeout` and `invalid_json` raise
     `ActionsFailed`; `flaky` fails once then succeeds.
   - `model_id="mock"`, `prompt_version="mock-0"`.
2. **Registry and settings:** add `PIPELINE_ACTIONS` (`mock` default),
   `ACTIONS_PROMPT_VERSION` (`v1.0`) and `ACTIONS_MAX_ITEMS` (`5`) to
   `config.py` and `.env.example`, and the registry row from CLAUDE.md §8.3
   with lazy import.
3. **Orchestrator:** after storing the recommendation and setting
   `AWAITING_REVIEW`, set `actions_status = pending` and **enqueue a
   `SUGGEST_ACTIONS` job** with the recommendation ID. Do **not** run the stage
   inline (ADR-18, NFR-29).
4. **`TriagePipeline.run_actions(recommendation_id)`:**
   - Load the recommendation, its extraction, and its stored
     `RetrievedReference` rows (rebuild `Passage` objects from them — do not
     re-run retrieval).
   - Call `suggest(...)`, then `validate(...)`.
   - Store `action_suggestions` rows with provenance; set
     `actions_status = ready` and record `rejected_count`.
   - On `ActionsFailed`, a timeout, or any exception: set
     `actions_status = failed` with a reason code (`ACTIONS_TIMEOUT`,
     `ACTIONS_UNAVAILABLE`, `ACTIONS_INVALID_OUTPUT`, `ACTIONS_ALL_REJECTED`).
     **The case status is never changed by this job** (FR-77).
   - Audit: `ACTIONS_SUGGESTED` or `ACTIONS_FAILED`, with counts only — never
     action text (SR-17).
5. **Worker:** dispatch `SUGGEST_ACTIONS`. Recovery (P05) already covers it.
6. **API:**
   - `GET /cases/{id}/status` gains `actions_status`.
   - `GET /cases/{id}` gains an `actions` object:
     `{status, generated_for_category, baseline: [...], tailored: [...], rejected_count, is_outdated}`.
     Set `is_outdated = true` when a decision exists whose `final_category`
     differs from `generated_for_category` (FR-78; the UI for this is P07).
   - **FR-79:** for a caller without the reviewer role, return `baseline` only
     and omit unfinalized `tailored` actions.
7. **Evaluation mode:** when the pipeline runs a vignette, enqueue the actions
   job the same way, storing `vignette_id`. This supplies the data for the
   action-appropriateness metric in M7.

**Tests**

- A demo case ends with `actions_status = ready`, baseline actions for its
  category, and the fixture's tailored actions.
- With `MOCK_LLM_BEHAVIOR=timeout`: `actions_status = failed`, the case is still
  `AWAITING_REVIEW` (**not** `MANUAL_TRIAGE_REQUIRED`), and baseline actions are
  still returned.
- A case in every one of the five categories returns a non-empty baseline list
  (FR-71).
- An Intake Staff caller receives no unfinalized tailored actions (FR-79).
- No action text appears in any audit row or log record (capture the logs).
- The actions job does not change the case status in any path.

---

## Verification

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m scripts.seed
docker compose exec backend pytest -q tests/unit/pipeline/test_action_validator.py
docker compose exec backend pytest -q
```

Then submit `DEMO_1` through the UI and check the API directly:

```bash
curl -s -b cookies.txt localhost:8000/api/v1/cases/<id> | python3 -m json.tool | grep -A 20 '"actions"'
docker compose exec db psql -U triageai -d triageai \
  -c "select rank, source, left(text,60) from action_suggestions order by rank;"
```

The category must appear in the queue **before** the actions become ready.

Final report as in CLAUDE.md §12, including the validator's rejection reason
codes and every `TODO(manual:M6b)` left.
