# P05 — Triage Pipeline Framework (Mocks Only)

**Branch prefix:** `feat/p05-<n>-<name>`
**Requirements:** FR-06, FR-12 (alert flow only), FR-15 (failure path), FR-20–FR-24, FR-26, NFR-05, NFR-07, NFR-09, IR-12, IR-15, IR-19 · ADR-06–ADR-09, ADR-14 · PD7 Figure 7.3 and §7.1.4

## Goal

Build the complete pipeline machinery with **mock AI stages**:

- data contracts and interfaces;
- a database-backed job queue and worker;
- the orchestrator and status transitions;
- red-flag alerts;
- the deterministic safety and citation validator.

After this phase, submitting a case produces a stored extraction, recommendation, references, alerts, and audit entries. The Triage Queue shows real categories.

## ⚠️ AI boundary (CLAUDE.md §8) — strictly enforced in this phase

Do **not** write de-identification patterns, red-flag phrase matching, prompts, LLM calls, embedding code, or vector SQL. Real stages are added later by the team (M1–M6).

The registry must load the non-mock modules lazily. The modules `app.pipeline.deidentify_rules`, `app.pipeline.redflags_keywords`, `app.pipeline.extraction_llm`, `app.pipeline.retrieval_pgvector`, `app.pipeline.generation_llm`, `app.adapters.llm.hosted`, `app.adapters.llm.ollama`, `app.kb.indexer_pgvector`, and `app.adapters.embeddings.sentence_transformer` **do not exist yet**. If a setting selects one of them, fail with a clear startup error: "Stage X=real selected but module not implemented yet (see M-guide)".

## Out of scope

- Review screen and decisions (P06)
- Regeneration, correction, and retry endpoints (P07)
- KB management (P08)

---

## Subphase 5.1 — Contracts, interfaces, errors, registry

**Tasks**

1. `app/pipeline/types.py`: all contracts **exactly** as in CLAUDE.md §8.1.
2. `app/adapters/llm/base.py`, `app/adapters/embeddings/base.py`, and `app/pipeline/stages.py`: all protocols **exactly** as in CLAUDE.md §8.2.
3. `app/pipeline/errors.py`: `PipelineError` as the base, plus `LLMTimeout`, `LLMUnavailable`, `LLMInvalidOutput`, `ExtractionFailed`, `RetrievalFailed`, and `GenerationFailed`.
4. `app/pipeline/registry.py`:
   - `build_pipeline(settings) -> TriagePipeline`, choosing each stage from settings with lazy imports.
   - Follow the table and the `from_settings(settings, deps)` construction convention in CLAUDE.md §8.3 exactly, including the `PipelineDeps` dataclass and the `EMBEDDING_PROVIDER` setting (default empty).
   - Build the `LLMProvider` and `EmbeddingProvider` once. They go into `deps` only when a real stage needs them.
   - Enforce the safety guard: a non-mock `LLM_PROVIDER` together with the mock de-identifier is a startup error.
5. `app/pipeline/config.py`: a `PipelineConfig` with `model_id`, `prompt_version`, `temperature=0`, `top_k=5`, `timeout_s=30`, `max_retries=1`, and `retrieval_min_score=0.30`. Add these to settings and `.env.example`.

**Tests:** the registry returns mocks by default; a non-mock value produces the "not implemented yet" error; the safety guard blocks the forbidden combination.

---

## Subphase 5.2 — Mock stages (fixture-driven, deterministic)

Create `app/pipeline/mocks.py` and `app/adapters/llm/mock.py`.

**Fixture lookup.** The mocks read `backend/tests/fixtures/demo_cases.yaml`. Extend that file so each demo case has `mock_red_flags`, `mock_extraction`, `mock_passages`, and `mock_draft`. A description matches a fixture when the two are equal after whitespace normalization. This is exact matching, not NLP.

**Mock stages**

- **`MockDeidentifier`:** returns the text unchanged. Add a docstring saying so and pointing to M1.
- **`MockRedFlagScreener`:** returns the fixture's hits. With no fixture match, returns `[]`.
- **`MockEntityExtractor`:** returns the fixture's `ExtractionOutput`. With no fixture match, returns a generic output: complaint `OTHER` (primary), the other fields empty, and `missing_information=["duration","appetite","water intake"]`.
  - It honors `MOCK_LLM_BEHAVIOR`:
    - `ok`: normal behavior
    - `invalid_json`: raises `LLMInvalidOutput` on every attempt
    - `timeout`: raises `LLMTimeout`
    - `flaky`: fails the first attempt and succeeds on the retry
- **`MockRetriever`:** returns the fixture's passages. With no fixture match, returns two generic passages with score 0.20. `chunk_id` values are `uuid5(NAMESPACE_URL, fixture_id+rank)`.
- **`MockRecommendationGenerator`:** returns the fixture's `mock_draft`. With no fixture match, returns YELLOW with MEDIUM confidence, citing rank 1. It also honors `MOCK_LLM_BEHAVIOR`.
- **`MockLLMProvider`:** implements `LLMProvider`. It is used only by tests of the adapter contract.
- **`MockKBIndexer`:** returns 0 and does nothing. It is used by P08.

Every mock exposes `model_id="mock"`, `prompt_version="mock-0"`, and `last_latency_ms`, and provides `from_settings(settings, deps)` (CLAUDE.md §8.3).

**Required fixture content.** `DEMO_1` (male cat, no urine) has `mock_red_flags: [MALE_CAT_NO_URINE → ORANGE]` and `mock_draft.category: YELLOW`. The safety validator must then raise it to ORANGE, which demonstrates FR-23 in the UI.

**Tests:** each mock for each behavior mode.

---

## Subphase 5.3 — Safety and citation validator (deterministic, fully tested)

Create `app/pipeline/safety.py` with a `SafetyValidator` class.

```python
def finalize(draft: DraftRecommendation, passages: list[Passage],
             red_flag_hits: list[RedFlagHit], extraction: ExtractionOutput,
             config: PipelineConfig) -> FinalRecommendation
```

**Rules, applied in this order**

1. **Citations (FR-22).**
   - Keep only `cited_ranks` that exist in `passages`.
   - If none remain, add `NO_VALID_CITATION` to `low_confidence_reasons` and set confidence to LOW.
   - Record each passage's `is_cited` flag for storage.
2. **Safety floor (FR-23, NFR-08).**
   - For each red-flag hit whose `min_category` is more urgent than the current category, raise the category to that minimum.
   - Set `safety_floor_applied=True` and append the rule code.
   - Urgency order: RED > ORANGE > YELLOW > GREEN > BLUE.
   - The category is **never lowered**.
3. **Retrieval quality.** If the maximum passage score is below `retrieval_min_score`, add `LOW_RETRIEVAL_SCORE` and cap confidence at MEDIUM.
4. **Unsupported complaint.** If the primary complaint is `OTHER`, add `UNSUPPORTED_COMPLAINT_MANUAL_TRIAGE_RECOMMENDED` and set confidence to LOW.
5. **Model confidence.** Keep the model's LOW if it said LOW. Never raise confidence above the model's value.

FR-25 (tie-break toward the more urgent category) is implemented in the generation prompt (M6). Note this in the docstring.

**Tests (non-negotiable).** Write at least 15 cases, covering:

- a floor raising YELLOW to ORANGE
- a floor never lowering RED
- multiple hits taking the most urgent
- invalid citations removed
- all citations invalid → LOW
- low retrieval score
- `OTHER` complaint
- combined conditions

---

## Subphase 5.4 — Job queue, worker, orchestrator

**Tasks**

1. **`app/jobs/queue.py`**
   - `enqueue(type, case_id=None, vignette_id=None, payload=None)`
   - `claim_next()`: `SELECT ... FOR UPDATE SKIP LOCKED` on `QUEUED` jobs whose `run_after <= now`; sets the job to `RUNNING` and increments `attempts`
   - `complete(job)`, `fail(job, error)`
2. **`app/jobs/worker.py`**
   - A background thread started from the FastAPI lifespan when `JOB_WORKER_ENABLED=true`. Add that setting, defaulting to true, and set it to false in tests.
   - The worker polls every 0.5 s.
   - Provide `run_pending_jobs_once()` so tests can run jobs synchronously.
3. **`app/jobs/recovery.py`** (ADR-08): on startup, reset `RUNNING` jobs older than 2 minutes to `QUEUED` and log how many were recovered.
4. **`app/pipeline/orchestrator.py`: `TriagePipeline.run(case_id)`**
   1. Set the case to `PROCESSING` and write the audit entry `PIPELINE_STARTED`.
   2. Load the description, signalment, and owner reference, then call `deidentify`. The owner reference is passed *only* to the de-identifier and never stored with outputs.
   3. Call `screen(text, species, signalment.sex)` → insert a `RedFlagAlert` row for each hit **immediately** and commit (NFR-05). Audit: `RED_FLAG_ALERT`.
   4. Call `extract(text, species, signalment_dict)`, retrying `max_retries` times on `LLMInvalidOutput`. If it still fails, or on `LLMTimeout`/`LLMUnavailable`, go to the **failure path**.
   5. Store the `ExtractionResult` (version = previous + 1) and the complaint junction rows.
   6. Resolve the latest `KBVersion`, call `retrieve(extraction, kb_version_id, top_k)`, then `generate(extraction, passages)`. Failures go to the failure path.
   7. Call `SafetyValidator.finalize`. Store the `Recommendation` (next version) and the `RetrievedReference` rows, copying each passage's text and source fields.
   8. Read `model_id`, `prompt_version`, and `last_latency_ms` from each stage (CLAUDE.md §8.2). Store the extractor's values on the extraction row and the generator's values on the recommendation, and the per-stage latencies in `params.stage_ms`.
   9. Set the case to `AWAITING_REVIEW`. Audit: `RECOMMENDATION_CREATED`, with category and confidence only, no text.
   - **Failure path (NFR-09):** set `MANUAL_TRIAGE_REQUIRED` and store the reason code and time in the job's `last_error`. Audit: `PIPELINE_FAILED`. Never lose the case and never leave it in `PROCESSING`.
5. **`POST /cases`** now enqueues a `PIPELINE_RUN` job after commit and returns **202** `{id, case_no, status}` (FR-06).
6. Extend the status endpoint and the queue:
   - `GET /cases/{id}/status` returns `pipeline_stage` (`queued|deidentify|screen|extract|retrieve|generate|done|failed`), from job progress written by the orchestrator.
   - The queue response includes `red_flag_alerts`: unacknowledged alerts on open cases, each with case number, species, pet name, and the rule label.
7. **Frontend**
   - The W-02 red-flag banner uses `red_flag_alerts`.
   - The intake page shows "Processing…" after submit, then navigates to the queue.
   - Queue rows show the AI-pending chip for `AWAITING_REVIEW` and the MANUAL badge for `MANUAL_TRIAGE_REQUIRED`.

**Tests (integration, `MOCK_LLM_BEHAVIOR` varied)**

- `DEMO_1` ends as ORANGE with `safety_floor_applied`, an alert row is created before the extraction row, the status is `AWAITING_REVIEW`, and audit entries are in order.
- The `timeout` behavior ends in `MANUAL_TRIAGE_REQUIRED`, and the job is marked `FAILED`.
- The `flaky` behavior succeeds after one retry.
- Recovery re-queues a stale `RUNNING` job.
- No description text appears in any audit entry or log record. Capture the logs in the test.

---

## Verification

```bash
docker compose exec backend pytest -q
docker compose up --build
```

1. Log in as intake and paste the `DEMO_1` text. The red-flag banner appears within about 2 s, and the queue shows ORANGE with an AI-pending chip.
2. Enter `DEMO_2` and `DEMO_3`. Check the sort order: RED, ORANGE, then BLUE.
3. Set `MOCK_LLM_BEHAVIOR=timeout` in `.env`, restart the backend, and submit any case. It shows MANUAL, "Manual triage required".
4. Check the audit table: `select action, entity_type, ts from audit_log order by id;`

Final report as in CLAUDE.md §12. List every `TODO(manual:Mx)`.
