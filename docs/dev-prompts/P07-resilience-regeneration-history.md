# P07 — Resilience, Extraction Correction and Regeneration, Case History

**Branch prefix:** `feat/p07-<n>-<name>`
**Requirements:** FR-14, FR-16, FR-27, FR-44, FR-46, NFR-09, NFR-13, IR-19 · UC-08, UC-09, UC-11 · ADR-08 · wireframes W-04 (editing), W-06 (retry), W-07

## Goal

The system recovers cleanly from every failure. Reviewers can correct extracted values and regenerate a recommendation, keeping every earlier version. Staff can search past cases.

## Out of scope

- Real AI stages. Test every failure path with `MOCK_LLM_BEHAVIOR` and the mocks.
- KB and admin screens (P08, P09)

---

## Subphase 7.1 — Failure handling and retry

**Tasks**

1. Map every failure to a reason code stored in `jobs.last_error` and shown in W-06. Use these codes:
   - `LLM_TIMEOUT`
   - `LLM_UNAVAILABLE`
   - `LLM_INVALID_OUTPUT`
   - `RETRIEVAL_FAILED`
   - `GENERATION_FAILED`
   - `DEIDENTIFICATION_FAILED` — the pipeline must stop *before* any external stage (ADR-10, fail closed)
   - `INTERNAL_ERROR`
2. Add plain-language messages in `app/pipeline/messages.py`. Example: "The language model did not respond after 2 attempts (09:20:41). The case is safe to triage; no data was lost."
3. `POST /cases/{id}/retry` (reviewer only):
   - Allowed only in `MANUAL_TRIAGE_REQUIRED` and when no decision exists.
   - Enqueues a new `PIPELINE_RUN` job and returns 202.
   - Audit: `PIPELINE_RETRY`.
   - Enable the Retry button on W-06. While the retry runs, poll the status and show progress.
4. Add a mock mode `MOCK_LLM_BEHAVIOR=slow` that sleeps 12 s. Use it to show the processing state.
5. Timeout budget: the whole job has a timeout of `2 × timeout_s + 10` seconds. The worker marks a job that exceeds it as failed using the failure path.
6. Restart safety: start a slow job, kill the backend container, and restart it. Recovery (P05) re-runs the job, and the case never stays in `PROCESSING`. Automate this in an integration test using `run_pending_jobs_once()` and a manually aged `RUNNING` job.
7. Add a demo toggle. The setting `DEMO_FORCE_FAILURE_CASE_TEXT` holds a phrase; a case whose description contains that phrase triggers the timeout behavior, **in `APP_ENV=dev` only**. This lets the PD8 demo show the fallback without editing `.env` live. Document it in the README.

**Tests:** each reason code leads to `MANUAL_TRIAGE_REQUIRED` with the correct message; a de-identification failure makes no LLM call (assert with a spy); retry permissions and allowed states; the timeout budget.

---

## Subphase 7.2 — Extraction correction and regenerate (UC-09)

**Tasks**

1. `PATCH /cases/{id}/extraction` (reviewer only), body: the edited `ExtractionOutput` fields.
   - Validate against the contract, and require complaint codes to be in `presenting_complaints`.
   - Store a **new** `ExtractionResult` version with `is_corrected=True` and `corrected_by`. Keep the original.
   - Audit: `EXTRACTION_CORRECTED`, listing the changed field names only.
   - Enqueue a `REGENERATE` job and return 202.
2. `TriagePipeline.regenerate(case_id, extraction_id)` runs only retrieval, generation, and safety, using the corrected extraction.
   - The red-flag hits for the safety floor are the stored `RedFlagAlert` rows for the case, plus any `red_flags` the reviewer added. When a reviewer-added red flag matches a rule label, map it to that rule code; otherwise ignore it for the floor. Comment in the code that the match is on the exact rule label.
   - It stores the next recommendation version.
3. Frontend W-04 panel 2:
   - Values become editable. Click to edit; complaints use a multi-select from the complaint list with a primary radio.
   - The "Save and regenerate" button is enabled only when something changed.
   - While regenerating, show a progress state. Afterwards, show the new recommendation with the note "Version 2 – regenerated after correction (version 1 kept in audit)."
   - Decisions always apply to the latest recommendation version.
4. The case detail response includes `recommendation_versions: [{version, category, created_at, is_current}]`. Show them in a small version switcher that is read-only for older versions.

**Tests:** the original extraction is preserved; a new version is created; regeneration skips extraction (spy); decisions reference the latest version; older versions are read-only.

---

## Subphase 7.3 — Case history search (W-07)

**Tasks**

1. Extend `GET /cases` with `scope=history` (includes closed cases). Filters:
   - case number
   - date range
   - species
   - complaint code
   - AI category
   - final category
   - status
   - `disagreement=true` (AI category ≠ final category)
   - Use page/limit pagination (default 25).
2. `pages/CaseHistory`, matching W-07:
   - the filter bar
   - a results table with **AI category and final category side by side**
   - selecting a row shows the P06 `AuditTimeline` on the right, with the two computed intervals
3. Available to all three roles. Administrators have read-only access.

**Tests:** filters, pagination, access for each role, and disagreement rows shown (AI ≠ final).

---

## Verification

1. Submit a case with the demo failure phrase → W-06 shows the reason. Click Retry after removing the forced failure (use a new case text) and check that it succeeds.
2. On `DEMO_3`, change the primary complaint and add a red flag that maps to a RED rule. Regenerate: version 2 is RED with the safety floor applied, and version 1 is still viewable.
3. In Case History, filter for "AI ≠ final" cases. Open the timeline.
4. Kill the backend during a slow job, restart it, and confirm recovery.

```bash
docker compose exec backend pytest -q
```

Final report as in CLAUDE.md §12.
