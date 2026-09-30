# M7 — Evaluation with the Real Pipeline (Manual)

**Owner:** Lane B, with the whole team and the veterinary reviewer · **Branch:** `eval/m7-<set-name>`
**Do after:** M6, P09 · **Requirements:** FR-64–FR-68, NFR-01, NFR-14, NFR-16, NFR-17, NFR-19, NFR-23 · TBD-10, TBD-12

You will build the labeled vignette set, run the P09 harness on the real pipeline, and interpret the results against the SRS targets. The results are reported honestly in PD8 (early results) and in the final presentation (full set).

## Prerequisites

- [ ] M6 done: all stages are real, and the demo passes.
- [ ] P09 merged: the importer, runner, metrics, W-10, and the report CLI exist.
- [ ] The veterinary reviewer has agreed to label the vignettes.

---

## Step 1. Build the vignette set (TBD-12)

1. **Size and balance.**
   - For PD8, use **20–30** vignettes. For the final evaluation, use **50–100** (SRS §1.4).
   - Aim for at least 15% per VTL category, so no category is empty.
   - Cover every supported complaint at least once.
   - Include about 10% `OTHER` or out-of-scope cases.
2. **Writing rules.** Every vignette is fictitious and written like a real owner:
   - lay terms
   - lay wording rather than clinical terms, since staff type the description in English (FR-18)
   - negations ("no blood")
   - vague cases with missing information
   - a few with red flags in unusual wording
   - no names, phone numbers, or addresses, except in 3–4 cases written on purpose to test de-identification
3. **Keep the test set separate from tuning.**
   - Split the set: **30% dev** (`vignettes_<name>_dev.csv`) and **70% test** (`vignettes_<name>_test.csv`).
   - Prompts and KB content may be improved using the **dev** split only.
   - Run the test split **once per frozen configuration**.
   - Never tune on the test split. That would make the metrics meaningless.
4. **Reference labels.**
   - The veterinary reviewer assigns `reference_category` to each vignette **without seeing the model's answer**.
   - The reviewer also lists `relevant_entry_slugs`: which KB entries a good answer should rely on.
   - Record the reviewer's name and the date in `evaluation/vignettes/LABELS.md`.
5. Save the files in the P09 CSV format. Import both splits:

   ```bash
   docker compose exec backend python -m app.eval import --file evaluation/vignettes/<name>_dev.csv  --name "<name>-dev"
   docker compose exec backend python -m app.eval import --file evaluation/vignettes/<name>_test.csv --name "<name>-test"
   ```

**Check 1.** The importer reports 0 errors and no unknown slugs.

## Step 2. Dev iterations

1. Run on the dev split:

   ```bash
   docker compose exec backend python -m app.eval run --set "<name>-dev"
   ```

2. Open W-10 and look at:
   - the confusion matrix
   - the under-triaged list
   - failed vignettes
3. For each error, decide the cause and fix only that cause:

   | Cause | Fix |
   |---|---|
   | Extraction missed a sign | Extraction prompt: new version |
   | Wrong passages retrieved | KB content or the query format |
   | Right passages, wrong category | Generation prompt: new version |
   | Red flag missed | Phrase list (M1), with vet approval |

4. Re-run the dev split. Keep a log in `evaluation/results/ITERATIONS.md`:

   | Date | Configuration | Macro-F1 | Red+Orange recall | Under-triage rate | Recall@5 | Note |
   |---|---|---|---|---|---|---|

5. Limit this to **3–4 iterations** for PD8. Stop when the dev split meets the targets, or when time runs out.

## Step 3. Freeze and run the test split

1. Freeze the configuration:
   - commit the prompt versions and the KB version;
   - tag it, for example `eval-freeze-1`.
2. Run the test split **once**:

   ```bash
   docker compose exec backend python -m app.eval run --set "<name>-test"
   docker compose exec backend python -m app.eval report --run <id> --format md > evaluation/results/<name>-test-report.md
   ```

3. **Reproducibility check (NFR-23).** Run the test split a second time with the same configuration. At least 95% of vignettes must get the same category. If not, check that the temperature is 0 and that the provider has no randomness setting you missed. Report the agreement percentage.

## Step 4. Interpret the results against the SRS targets

| Metric | SRS target | Where it comes from |
|---|---|---|
| Macro-F1 | ≥ 0.70 | NFR-16 |
| Red + Orange recall | ≥ 0.90 | NFR-16. **This is the most important one.** Missing a critical case is the worst error. |
| Under-triage rate | ≤ 10% | NFR-16 |
| Recall@5 / MRR | ≥ 0.80 / ≥ 0.70 | NFR-17 |
| Latency p50 / p95 | ≤ 10 s / ≤ 20 s | NFR-01 |
| Reproducibility | ≥ 95% same category | NFR-23 |

How to read the numbers:

- With 20–70 vignettes, one vignette changes a rate by 1.5–5 percentage points. **Report counts along with percentages** (e.g. "2 of 24 under-triaged, 8.3%").
- A missed target is a valid result. Report it together with the error analysis from Step 2. Do not re-run the test split after tuning to "get a better number".
- Over-triage is safer than under-triage, but it still costs clinic time. Report both.

## Step 5. Under-triage review (NFR-14)

1. Export the under-triaged list from W-10.
2. The veterinary reviewer reviews each case and classifies it:
   - (a) a model error
   - (b) the reference label should change
   - (c) a KB gap
3. Record each decision in `evaluation/results/<name>-under-triage-review.md`.
4. **Changing a reference label after seeing model output must be reported openly**, with its reason.
5. This review must be completed before any usability session with clinic staff (NFR-14).

## Step 6. Report

For PD8, include an "Early evaluation" table containing:

- the metrics
- the vignette counts
- the configuration: model ID, prompt versions, KB version, and embedding model
- the limitations: small set, fictitious vignettes, single reviewer

Keep the full run exports in `evaluation/results/`. They are git-ignored, except for the markdown reports and the review file.

For the final presentation, repeat Steps 1–5 with the full 50–100 set.

## Done when

- [ ] The dev and test splits are imported and labeled blind by the vet, with labels recorded.
- [ ] The test split is run on a frozen configuration, with a report and a reproducibility result.
- [ ] The under-triage review is done.
- [ ] Results and limitations are written for PD8.
