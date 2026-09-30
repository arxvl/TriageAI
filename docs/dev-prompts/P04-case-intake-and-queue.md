# P04 — Case Intake and Triage Queue

**Branch prefix:** `feat/p04-<n>-<name>`
**Requirements:** FR-01–FR-07, FR-18, FR-29, FR-30, FR-36, FR-39, IR-01–IR-05, IR-22 · UC-02, UC-04 · Wireframes W-02, W-03, W-11

## Goal

Staff can create cases through the intake form. The Triage Queue lists open cases in the correct urgency order, with waiting times, and refreshes automatically.

At the end of this phase, a new case stays in status `SUBMITTED`. Starting the pipeline is added in P05.

## Out of scope

- Any pipeline processing, job creation, or recommendation data. The queue shows "—" for the category until P05.
- The Case Review screen (P06). Queue rows link to a placeholder page.

---

## Subphase 4.1 — Case API

**Tasks**

1. `schemas/case.py` — request and response models.
   - **`CaseCreate`**
     - Required: `species` (`DOG`, `CAT`, or `OTHER`) and `description` (20–2,000 characters after trimming).
     - Optional: `intake_channel`, and signalment fields `pet_name` (≤ 60), `age_value` (0–40), `age_unit`, `sex`, `neutered`, `breed` (≤ 60), `weight_kg` (0.1–120, decimal).
     - Optional owner reference: `owner_name` (≤ 80) and `contact_number` (≤ 30).
   - Validation messages must be plain language (IR-05). Example: "Enter the weight as a number, e.g. 4.2."
2. `repositories/case_repository.py` and `services/case_service.py`.
   - **`create_case`**
     - Reject `species=OTHER` with a 422 error, code `SPECIES_OUT_OF_SCOPE`: "Other species are not processed by the AI and must be triaged manually." (FR-02)
     - In one transaction, insert `Case` (status `SUBMITTED`), `Signalment`, `OwnerDescription` (text stored exactly as entered, FR-05), and, only if provided, `OwnerReference`.
     - Write the audit entry `CASE_CREATED`, with no description text in `after`.
     - Return the new case number.
   - **`list_queue(filters)`**
     - Returns open cases: status not `CLOSED`.
     - Include the category source: the latest `StaffDecision.final_category` if one exists, else the latest `Recommendation.category`, else none. Both are empty in this phase; still write the query now.
     - Sort exactly as CLAUDE.md §6 describes.
     - Compute `waiting_minutes = now - created_at`, `target_minutes` from the category, and `is_overdue`.
     - Filters: species, category, status, date (today / range), and free-text `q` matching the case number, pet name, or primary complaint name.
   - **`get_status(case_id)`** returns `{status, category, has_red_flag, updated_at}`.
3. Endpoints in `api/v1/cases.py`.
   - `POST /cases` → 201 `{id, case_no, status}`, for `INTAKE_STAFF` and `VETERINARY_REVIEWER`.
     - When P05 adds the pipeline, this will return 202. Write the handler so that change is a single line.
   - `GET /cases` (queue and search) for staff, reviewers, and administrators.
   - `GET /cases/{id}/status` for staff and reviewers.
   - Every response must exclude `owner_references`.
4. Add the queue counters from W-02 to the list response: counts per category, a MANUAL count, and `awaiting_review_count`.

**Tests**

- Validation for each field.
- `species=OTHER` is rejected.
- The owner reference is stored in its own table and absent from every response.
- Sort order, using fixtures with mixed categories inserted directly into `recommendations` and `staff_decisions`.
- The overdue flag.
- RBAC: an administrator gets 403 on `POST /cases`.
- The audit entry is written and contains no description text.

---

## Subphase 4.2 — Case Intake screen (W-03)

**Tasks**

1. Build `pages/CaseIntake` to match W-03 in `docs/prototype/TriageAI_Prototype.html`.
   - Species segmented control: Dog / Cat / Other species. Choosing "Other" shows the manual-triage message and disables Submit.
   - Optional signalment grid, and an intake channel segmented control.
   - Description textarea with a live counter ("143 / 2,000") and the helper text (FR-18): "Enter the description in English. Translate any Filipino or Bikol words the owner used, and keep their exact wording in quotation marks if you are unsure of the meaning. Do not include the owner's name or phone number here."
   - An "Owner reference (optional)" box. Its caption: "stored separately and never sent to AI services".
   - A red-flag side panel. It shows static text from `src/content/redFlagSigns.ts` with the caption "Final list to be validated by the veterinary reviewer".
2. Validation.
   - Validate on the client with the same limits as the server.
   - Show server errors under the matching field.
   - Never clear entered data on error (FR-04).
3. On success, show a toast "Case C-00xx submitted" and navigate to `/queue`.

**Tests:** client-side validation messages, the "Other species" behavior, that the counter updates as the user types, and that the English-entry helper text is rendered (FR-18).

---

## Subphase 4.3 — Triage Queue screen (W-02, W-11)

**Tasks**

1. `components/VtlBadge.tsx` (IR-03).
   - Props: `category | "MANUAL" | null`, and `size`.
   - Always renders the category name plus its target time. Yellow uses dark text. MANUAL uses a dashed outline.
   - Colors come from the tokens.
2. `components/StatusChip.tsx`.
   - AI recommendation pending (dashed outline), Confirmed, Adjusted (X → Y), Manual triage required (red text), Manually triaged, Processing.
3. Build `pages/TriageQueue` to match W-02.
   - Red-flag banner area. It stays empty until P05 supplies alerts, but build the component with a prop.
   - Category counters, search, and filters.
   - Table columns: urgency, case, patient, primary complaint, arrived, waiting / target progress bar, status, flags.
   - Tint overdue rows and label them "overdue".
   - A "New Case" button.
   - An "Updated N s ago · auto-refresh every 15 s" indicator.
4. Polling (IR-22): TanStack Query `refetchInterval: 15000`, paused while the browser tab is hidden.
5. Responsive layout (W-11): below 900 px, table rows become cards with labelled fields and the header wraps. Test at a 768 px viewport.
6. Clicking a row navigates to `/cases/:id`, a placeholder page for now.

**Tests:** `VtlBadge` renders a text label for every category (it never relies on color alone), and the queue renders counters and rows from mocked API data.

---

## Verification

```bash
docker compose exec backend pytest -q tests -k "case or queue"
cd frontend && npm run test
```

In the browser:

1. Log in as the intake user. Submit one case with an invalid weight, check the error, fix it, and submit.
2. Try "Other species".
3. Open the queue in a second browser as the reviewer. The new case appears within 15 seconds without reloading.
4. Resize the window to 768 px and check the card layout.

In the database, the owner name is only in `owner_references`:

```bash
docker compose exec db psql -U triageai -d triageai -c "select * from owner_references;"
```

Final report as defined in CLAUDE.md §12.
