/**
 * The confirmation in front of closing a case (FR-38, IR-08).
 *
 * IR-08 asks for a confirmation step before an irreversible action, and closing
 * is one: `require_closable` refuses a decision on a closed case and P06 has no
 * way to reopen one. The dialog therefore says what closing means — the patient
 * has been seen, the case leaves the triage queue — and that it cannot be undone.
 *
 * It is only ever reachable with `permissions.can_close`, which the server sets
 * for a Veterinary Reviewer on a case that has already been decided. Closing an
 * undecided case would drop a patient off the working list with no recorded
 * urgency, which is the one outcome the queue exists to prevent.
 *
 * Presentational: the page owns the request.
 */
import { Dialog, DialogActions } from "../../components/Dialog";
import { strings } from "../../i18n/strings";
import styles from "./CaseReview.module.css";

const copy = strings.caseReview.closeDialog;

export function CloseDialog({
  caseNo,
  isSaving,
  error,
  onConfirm,
  onClose,
}: {
  caseNo: string;
  isSaving: boolean;
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Dialog title={copy.title.replace("{caseNo}", caseNo)} isBusy={isSaving} onClose={onClose}>
      <p className={styles.dialogText}>{copy.body}</p>

      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      <p className={styles.dialogNotice}>{copy.permanentNotice}</p>

      <DialogActions>
        <button type="button" className={styles.button} disabled={isSaving} onClick={onClose}>
          {copy.cancel}
        </button>
        <button
          type="button"
          className={`${styles.button} ${styles.buttonPrimary}`}
          disabled={isSaving}
          onClick={onConfirm}
        >
          {isSaving ? copy.submitting : copy.submit}
        </button>
      </DialogActions>
    </Dialog>
  );
}
