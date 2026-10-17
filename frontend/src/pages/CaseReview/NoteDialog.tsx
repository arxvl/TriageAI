/**
 * Adding a clinical note to a case (FR-37, FR-45).
 *
 * A note is not a decision, which is why this is the one control on the bar that
 * does not leave the screen afterwards: the reviewer writes down what they
 * observed and carries on reading the case. `ReviewService.add_note` accepts one
 * at any status, closed cases included — the moment to record an observation is
 * when it is known, not when the workflow permits it.
 *
 * The text is never audited, only that a note was added and how long it was: it
 * is clinical content, and the log cannot be corrected afterwards (FR-43, SR-17).
 * The note itself lives on `clinical_notes`, beside the case, where it can be
 * read and added to.
 *
 * Presentational: the page owns the request, because the page is what shows the
 * note once it exists.
 */
import { useState } from "react";

import { Dialog, DialogActions } from "../../components/Dialog";
import { strings } from "../../i18n/strings";
import styles from "./CaseReview.module.css";

const copy = strings.caseReview.noteDialog;

export function NoteDialog({
  isSaving,
  error,
  onSubmit,
  onClose,
}: {
  isSaving: boolean;
  error: string | null;
  onSubmit: (text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const trimmed = text.trim();

  return (
    <Dialog title={copy.title} isBusy={isSaving} onClose={onClose}>
      <label className={styles.field}>
        <span className={styles.sectionTitle}>{copy.label}</span>
        <textarea
          className={styles.textarea}
          rows={4}
          value={text}
          disabled={isSaving}
          onChange={(event) => setText(event.target.value)}
        />
      </label>

      <p className={styles.dialogNotice}>{copy.helper}</p>

      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      <DialogActions>
        <button type="button" className={styles.button} disabled={isSaving} onClick={onClose}>
          {copy.cancel}
        </button>
        <button
          type="button"
          className={`${styles.button} ${styles.buttonPrimary}`}
          disabled={isSaving || trimmed === ""}
          onClick={() => {
            if (trimmed !== "") {
              onSubmit(trimmed);
            }
          }}
        >
          {isSaving ? copy.submitting : copy.submit}
        </button>
      </DialogActions>
    </Dialog>
  );
}
