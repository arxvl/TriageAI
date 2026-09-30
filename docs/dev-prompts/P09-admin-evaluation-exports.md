# P09 — Administration: User Management, Evaluation Harness, Exports

**Branch prefix:** `feat/p09-<n>-<name>`
**Requirements:** FR-47, FR-58–FR-61, FR-63–FR-70, NFR-14, NFR-16, NFR-17, NFR-23, SR-03, BR-05, BR-08, DR-06 · UC-12, UC-15, UC-16 · wireframes W-09, W-10

## Goal

Administrators manage accounts, run the evaluation harness over a labeled vignette set, see the metrics, and export de-identified data.

The harness and metrics are deterministic code. With mocks they produce mock results. When the team switches to real stages (M6), the same harness produces real results (M7).

**Allowed new dependencies in this phase:** `scikit-learn` and `numpy`, for metric computation only.

## Out of scope

- Real AI stages
- Deployment (P10)

---

## Subphase 9.1 — User management (W-09)

**Tasks**

1. Administrator-only endpoints:
   - **`GET /users`** — list, with search.
   - **`POST /users`** `{full_name, email, role, can_approve_kb}`
     - Generates a random 16-character temporary password and returns it **once** in the response. It is never stored in plain text and never logged.
     - Sets `must_change_password=true`.
   - **`PATCH /users/{id}`** — edit name, role, `can_approve_kb` (DB constraint from P02), and `is_active`.
   - **`POST /users/{id}/unlock`** — resets `failed_login_count` and `locked_until`.
   - **`POST /users/{id}/reset-password`** — returns a new temporary password once.
   - An administrator cannot deactivate or demote themselves when they are the last active administrator (409).
   - Every change writes an audit entry, with no password material.
2. Build `pages/Users` to match W-09:
   - **User table:** name, e-mail, role, KB approval, status (Locked until HH:MM / Active / Deactivated), last login, actions.
   - **Add-user panel:** the checkbox "Grant knowledge base approval permission — only for licensed veterinarians with the Veterinary Reviewer role (BR-04)", disabled for other roles.
   - **Temporary password:** show it in a one-time dialog with a Copy button and the warning "This password is shown only once."

**Tests:** last-administrator protection; the approval-permission constraint; the temporary password appears only in the create/reset responses; 403 for non-administrators.

---

## Subphase 9.2 — Evaluation harness (backend and CLI)

**Vignette file format** (`evaluation/vignettes/*.csv`, UTF-8):

```csv
external_id,species,description,reference_category,relevant_entry_slugs
V-001,CAT,"Since this morning he keeps going to the litter box...",ORANGE,urinary-straining-cat
V-002,DOG,"Breathing very fast with mouth open...",RED,respiratory-distress-dog;heat-stress
```

**Tasks**

1. `app/eval/importer.py` and `POST /eval/sets` (multipart upload):
   - Validate every row and report errors by row number.
   - Resolve slugs to entry IDs, and warn when a slug is unknown.
   - Store an `EvaluationSet` and its `Vignette` rows (DR-06: never in the `cases` tables).
2. `app/eval/runner.py`, run as an `EVAL_RUN` job:
   - Record the configuration snapshot: every `PIPELINE_*` setting, `model_id`, `prompt_version`, `kb_version_id`, `top_k`, and temperature (NFR-23).
   - For each vignette, run the **same** `TriagePipeline` in evaluation mode, which:
     - stores extraction and recommendation rows with `vignette_id` (no case, no queue, no alerts);
     - records red-flag hits in `EvaluationResult.payload`;
     - on failure, records the error and continues with the next vignette.
   - Record stage latencies from the orchestrator's `params.stage_ms`.
3. `app/eval/metrics.py`, a pure function of the stored results:
   - **Classification:** accuracy; per-category precision, recall, and F1; macro-F1; the confusion matrix in VTL order; quadratic-weighted Cohen's kappa; under-triage rate (predicted less urgent than reference); over-triage rate; Red+Orange recall (a reference of RED or ORANGE predicted as RED or ORANGE).
   - **Retrieval:** entry-level Precision@k, Recall@k, MRR, and nDCG@k, using the unique `entry_id`s of the retrieved passages in rank order against `relevant_entry_ids`.
   - **Latency:** p50 and p95 for the whole pipeline and for each stage.
   - Failed vignettes are counted and excluded from the classification metrics. Report the count.
   - Include the list of under-triaged vignettes (NFR-14).
4. Endpoints:
   - `POST /eval/runs {set_id}` → 202
   - `GET /eval/runs`, `GET /eval/runs/{id}` (status, progress n/N, metrics)
   - `GET /eval/runs/{id}/export?format=csv|json` (per-vignette rows plus the metrics)
5. CLI wrapper:

   ```
   python -m app.eval import --file evaluation/vignettes/<name>.csv --name "<set name>"
   python -m app.eval run --set "<set name>"
   python -m app.eval report --run <id> [--format md|json]
   ```

   The markdown report prints a metrics table with the SRS targets from NFR-01, NFR-16, and NFR-17, and a pass/fail mark per target, ready to paste into the PD8 document.

**Tests**

- Metrics against hand-computed small examples. Include a 5×5 confusion case and a retrieval case with known MRR and nDCG.
- Failed vignettes are excluded and counted.
- Evaluation mode never writes to `cases` or alerts.
- The configuration snapshot is stored.

---

## Subphase 9.3 — Evaluation console (W-10)

Build `pages/Evaluation` to match W-10.

1. **Set selector** with an upload button, plus the configuration line and a "Start evaluation run" button.
2. **Run list and selected run:**
   - progress bar while running
   - metric cards with their targets: Macro-F1 ≥ 0.70, Red+Orange recall ≥ 0.90, under-triage ≤ 10%, Recall@5 ≥ 0.80, MRR ≥ 0.70, latency p50 ≤ 10 s / p95 ≤ 20 s
   - the confusion-matrix table
   - the under-triaged vignette list
   - Export CSV and Export JSON buttons
3. When every pipeline setting is `mock`, show a persistent banner: "MOCK MODE – results are not model results". This prevents confusing mock numbers with real ones.

---

## Subphase 9.4 — De-identified exports

**Tasks**

1. `GET /exports/cases?from=&to=&format=csv` (administrator only, FR-47, BR-08). One row per case with:
   - case number, species, created time, status
   - AI category, confidence, and whether the safety floor was applied
   - final category, decision type, reason code, and direction
   - the intervals: submission → recommendation and recommendation → decision
   - **No** description text, owner reference, notes, or names. Reviewers appear only as a role.
2. `GET /exports/audit?from=&to=`: audit rows with user IDs replaced by role and a stable pseudonym (`REVIEWER-1`), and the `before`/`after` columns included.
3. Every export writes an audit entry `DATA_EXPORTED` (SR-12).
4. Build `pages/Exports` for administrators: date range, the two download buttons, and the note "Exports are de-identified and for academic evaluation only (BR-08)."

**Tests:** export columns contain no personal or free-text fields (assert the header); pseudonyms are stable within one export; the audit entry is written.

---

## Verification

1. As administrator, create a user, copy the temporary password, and log in as that user (the password change is forced). Lock an account with 5 wrong passwords, then unlock it.
2. Import `backend/tests/fixtures/vignettes_mock.csv`. Create it in this phase: the 4 demo cases plus 6 more fictitious rows.
3. Run an evaluation. W-10 shows the MOCK MODE banner, and the metrics and confusion matrix render.
4. Export the CSV and JSON.
5. Run the report and check that the markdown table prints:

   ```bash
   docker compose exec backend python -m app.eval report --run <id> --format md
   ```

6. Export cases. Open the CSV and confirm there is no free text.

Final report as in CLAUDE.md §12.
