# P06 — Case Review Dashboard and Human-in-the-Loop Decisions

**Branch prefix:** `feat/p06-<n>-<name>`
**Requirements:** FR-13, FR-31–FR-38, FR-41–FR-43, FR-45, FR-46, FR-48, NFR-07, NFR-10, NFR-11, BR-01–BR-03, IR-03, IR-04, IR-06, IR-08 · UC-05–UC-08, UC-10 · wireframes W-04, W-05, W-06, W-07 (timeline only)

## Goal

A Veterinary Reviewer opens a case, sees the evidence, the extraction, and the recommendation side by side, and then decides. The reviewer can confirm, adjust with a reason, triage manually, add notes, or close the case.

Every step is audited and visible on a per-case timeline.

## Out of scope

- Extraction correction and regenerate, and the Retry AI button's backend (P07). Show both buttons disabled with the tooltip "Available in P07".
- The case history search list (P07). This phase builds only the timeline for one case.

---

## Subphase 6.1 — Review API

**Tasks**

1. `GET /cases/{id}`, for reviewers, staff (read-only flag), and administrators (read-only). Response:
   - case header (case number, species, signalment, channel, created by, times, waiting vs. target, status)
   - `description` (verbatim) and the de-identified text used by the pipeline. Store it on `ExtractionResult` as `input_text` in a new migration; it is needed to map evidence spans.
   - the latest extraction, with `evidence_spans` converted to character offsets by exact substring search on `input_text`, marked `found: false` when absent
   - the latest recommendation, with `safety_floor_applied`, rule labels, and `low_confidence_reasons`
   - references in rank order, with `is_cited`
   - configuration (`model_id`, `prompt_version`, `kb_version_no`, generated time, latency)
   - red-flag alerts, the latest decision, notes, and `permissions: {can_decide, can_regenerate, can_close}`
2. Opening the case as a reviewer sets `acknowledged_at` on its alerts. The queue banner then disappears.
3. `POST /cases/{id}/decision` (reviewer only, FR-35) with body `{type, final_category?, reason_code?, reason_text?, note?}`:
   - **`CONFIRM`:** `final_category` = the recommendation's category. Requires status `AWAITING_REVIEW`.
   - **`ADJUST`:** requires a `final_category` different from the recommendation, and a `reason_code` from the list below. Compute `direction` (UP or DOWN).
   - **`MANUAL`:** allowed from `MANUAL_TRIAGE_REQUIRED` or `AWAITING_REVIEW`. Requires `final_category` and `note` (FR-34). Sets status `MANUALLY_TRIAGED`.
   - A second decision on a decided case is only allowed as an **amendment** (`amends_id` set, reason required). The original is never modified (FR-48).
   - Audit `DECISION_RECORDED` with before and after (category and status only).
   - The system never changes a staff-confirmed category automatically (NFR-11).
4. Reason codes, stored as enum `AdjustReason`:
   - `CONDITION_DIFFERS_ON_ARRIVAL`
   - `SIGN_NOT_CAPTURED`
   - `RECOMMENDATION_TOO_LOW`
   - `RECOMMENDATION_TOO_HIGH`
   - `OTHER` (`reason_text` required)
5. `POST /cases/{id}/notes` (reviewer) and `POST /cases/{id}/close` (reviewer).
   - Close requires a decided status (`CONFIRMED`, `ADJUSTED`, or `MANUALLY_TRIAGED`) and sets `closed_at`.
   - Both write audit entries.
6. `GET /cases/{id}/audit` returns the timeline from `audit_log` and the related tables, in chronological order. Each item has: time, actor name and role, action label, short details. It also returns the intervals submission → recommendation and recommendation → decision (FR-46).
7. The queue now uses the decision's category when present. Show the status chip "Adjusted (Yellow → Green)" for adjusted cases.

**Tests**

- Each decision type succeeds, and invalid transitions return 409.
- Adjust without a reason returns 422.
- Intake Staff and Administrator decisions return 403.
- An amendment keeps the original decision.
- Close before a decision returns 409.
- Alerts are acknowledged on open.
- The audit timeline order is correct and the intervals are computed.
- Evidence offsets are right for found spans, and missing spans come back marked `found: false`.

---

## Subphase 6.2 — Case Review screen (W-04)

Build `pages/CaseReview` to match W-04.

1. **Header**
   - case number, species, pet name, age, sex, neuter status
   - arrival and recorded-by line
   - live "waiting X min of Y min", updated every 30 s
   - the chip "AI Recommendation – requires staff confirmation", shown until decided
2. **Red-flag banner** when alerts exist.
3. **Panel 1 – Owner's description (verbatim)**
   - Show the text as submitted. Highlight evidence spans with `<mark>`, positioned against the de-identified text.
   - If the de-identified text differs from the original, add the note "Highlights refer to the de-identified text" and show that text instead.
4. **Panel 2 – Extracted information**
   - Rows in a key-value grid: complaints (primary marked), onset/duration, frequency/severity, associated signs, negated findings, red flags (in red), and "Ask the owner" (missing information).
   - Values are *read-only* in this phase. Editing arrives in P07.
5. **Panel 3 – Recommended urgency**
   - a large `VtlBadge`
   - the safety-floor notice when applied, naming the rule label
   - the rationale
   - a confidence indicator with low-confidence reasons in plain language
   - the reference list with rank, entry title, source, a passage excerpt of 300 characters with "Show more", and a "cited" marker
   - the configuration footnote
6. **Fixed decision bar**
   - buttons: Confirm \<Category\>, Adjust category…, Mark for manual triage, Add note, View audit
   - the disclaimer: "Decision support only – this is not a diagnosis. The final urgency category is decided by veterinary staff." (IR-06)
   - The buttons are hidden, with a read-only notice, for users without `can_decide`.
7. **Confirm** opens a small confirmation dialog (IR-08), then posts the decision and returns to the queue with a toast.
8. **Keyboard access:** every action is reachable by Tab, and dialogs trap focus.

**Tests:** the AI label shows before a decision and hides after; the safety-floor notice renders; decision buttons are hidden for Intake Staff; references mark cited items.

---

## Subphase 6.3 — Adjust dialog (W-05), manual triage (W-06), notes, close

1. **W-05 Adjust dialog**
   - five category options with target times, with the AI recommendation marked "current"
   - a required reason dropdown and optional details
   - a live summary, e.g. "Change: Orange → Red (up-triage)", and the notice that it is recorded permanently
   - Save stays disabled until a different category and a reason are chosen.
2. **W-06 Manual triage view**, shown when status is `MANUAL_TRIAGE_REQUIRED` or the reviewer chooses "Mark for manual triage"
   - a yellow banner: "AI unavailable – triage manually using the VTL". For AI failures, include the failure reason and time from the job.
   - the description, and "Extracted information: not available" when there is no extraction
   - five category options, each with the example discriminators from W-06 in `src/content/vtlReference.ts`
   - a required note and "Save manual triage"
   - a disabled "Retry AI processing" button, enabled in P07
3. **Add note** dialog, and **Close case** (confirmation dialog, shown after a decision).

**Tests:** Save is disabled without a reason; the direction label is computed; the manual-triage note is required.

---

## Subphase 6.4 — Audit timeline (W-07 right panel)

1. `components/AuditTimeline.tsx` renders `GET /cases/{id}/audit` as a vertical timeline, as in W-07. Add the caption "Entries are append-only and cannot be edited or deleted."
2. Build the route `/cases/:id/audit`, and a "View audit" link from W-04. For now it shows only the timeline; P07 adds the search list beside it.

---

## Verification

1. Submit `DEMO_1`. As reviewer, open it:
   - the banner disappears from the queue;
   - W-04 shows ORANGE with the safety-floor notice.
2. Adjust to RED with reason `CONDITION_DIFFERS_ON_ARRIVAL`. The queue re-sorts and the chip reads "Adjusted (Orange → Red)".
3. Submit `DEMO_3` and confirm BLUE.
4. With `MOCK_LLM_BEHAVIOR=timeout`, submit a case and manually triage it as ORANGE with a note.
5. Close one case and check the audit timeline shows each step with actor, role, and time.
6. Log in as intake and confirm the review screen is read-only.

```bash
docker compose exec backend pytest -q
cd frontend && npm run test
```

Final report as in CLAUDE.md §12.
