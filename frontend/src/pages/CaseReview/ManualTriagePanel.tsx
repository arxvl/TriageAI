/**
 * W-06: assigning the category by hand (FR-34, NFR-09, ADR-15 §4).
 *
 * This takes panel 3's place rather than being a dialog or a separate route,
 * which is how W-06 is drawn and what the work actually needs: the reviewer is
 * reading the owner's description on the left while choosing, and a modal would
 * cover the only evidence they have. Panels 1 and 2 stay exactly as they are —
 * `ExtractionPanel` already says "not available for this case" for a case with no
 * extraction, which is the usual state here.
 *
 * It is reached two ways, and the difference matters enough to show (see
 * `CaseReview`'s banner):
 *
 * - the pipeline failed, so the case is `MANUAL_TRIAGE_REQUIRED` and there is
 *   nothing to review;
 * - a reviewer looked at a sound recommendation and judged the case is not one
 *   the system should be triaging. FR-34 and ADR-15 §4 both require that to be
 *   available at any time, not only after a failure.
 *
 * The note is required, by this screen and by `ReviewService._resolve_category`.
 * A category assigned by hand with no stated basis is the one record in the
 * system that could not be checked afterwards.
 *
 * **The baseline actions are not listed here.** They belong to the category being
 * assigned, and the server has them: a `MANUAL_TRIAGE_REQUIRED` case has no
 * category yet, so `detail.actions.baseline` is empty, and the client has no
 * business reading the knowledge base to fill it (CLAUDE.md §8). Omitting
 * `final_actions` from the request makes the server read the new category's
 * baseline live and record it as kept (FR-72, ADR-18 §6), which is what W-06's
 * "Baseline actions appear for whichever category you assign" promises. The
 * notice says so.
 *
 * Presentational: the page owns the request.
 */
import { useState } from "react";

import type { VTLCategory } from "../../api/cases";
import { VTL_DISCRIMINATORS, vtlReference } from "../../content/vtlReference";
import { strings } from "../../i18n/strings";
import styles from "./CaseReview.module.css";
import { CategoryOptions } from "./CategoryOptions";

const copy = strings.caseReview.manualTriage;

export interface ManualValues {
  final_category: VTLCategory;
  note: string;
}

export function ManualTriagePanel({
  isSaving,
  error,
  fieldError,
  onSubmit,
  onCancel,
}: {
  isSaving: boolean;
  error: string | null;
  fieldError: { field: string; message: string } | null;
  onSubmit: (values: ManualValues) => void;
  /** Null for a case that has no recommendation to go back to. */
  onCancel: (() => void) | null;
}) {
  const [category, setCategory] = useState<VTLCategory | null>(null);
  const [note, setNote] = useState("");

  const trimmedNote = note.trim();
  const canSave = category !== null && trimmedNote !== "";

  return (
    <section className={`${styles.panel} ${styles.manualPanel}`}>
      <h2 className={styles.panelTitle}>{copy.title}</h2>

      <CategoryOptions
        name="manual-category"
        legend={copy.categoryLegend}
        value={category}
        disabled={isSaving}
        note={(option) => `${vtlReference.examplePrefix} ${VTL_DISCRIMINATORS[option]}`}
        onChange={setCategory}
      />
      <p className={styles.footnote}>{vtlReference.caption}</p>
      <FieldError fieldError={fieldError} field="final_category" />

      <label className={styles.field}>
        <span className={styles.sectionTitle}>{copy.noteLabel}</span>
        <textarea
          className={styles.textarea}
          rows={3}
          value={note}
          disabled={isSaving}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      <p className={styles.footnote}>{copy.noteHelper}</p>
      <FieldError fieldError={fieldError} field="note" />

      <p className={styles.dialogNotice}>{copy.actionsNotice}</p>

      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      <div className={styles.manualActions}>
        <button
          type="button"
          className={`${styles.button} ${styles.buttonPrimary}`}
          disabled={isSaving || !canSave}
          onClick={() => {
            if (canSave && category !== null) {
              onSubmit({ final_category: category, note: trimmedNote });
            }
          }}
        >
          {isSaving ? copy.submitting : copy.submit}
        </button>

        {onCancel !== null && (
          <button type="button" className={styles.button} disabled={isSaving} onClick={onCancel}>
            {copy.cancel}
          </button>
        )}

        <span className={styles.footnote}>{copy.statusNotice}</span>
      </div>
    </section>
  );
}

/** The server's message for one control, or nothing (IR-05). */
function FieldError({
  fieldError,
  field,
}: {
  fieldError: { field: string; message: string } | null;
  field: string;
}) {
  if (fieldError === null || fieldError.field !== field) {
    return null;
  }
  return (
    <p className={styles.error} role="alert">
      {fieldError.message}
    </p>
  );
}
