/**
 * The confirmation step in front of a CONFIRM decision (IR-08, FR-32).
 *
 * A decision is append-only and audited: once recorded it is never edited, only
 * amended (FR-48, ADR-12). So the one thing this dialog has to do beyond asking
 * is to say that out loud — which category is being recorded, how many actions
 * go with it, and that the reviewer's name and the time go into the audit trail
 * and cannot be taken back out.
 *
 * It owns the request rather than the page, because the two outcomes belong
 * here: a failure keeps the reviewer in the dialog with the message beside the
 * button they pressed, and only success closes it. The 409 case is special and
 * deliberately not phrased as an error — someone else decided first, the screen
 * was simply out of date, and the page refetches behind the dialog so the
 * reviewer closes it onto the current state (FR-32).
 */
import type { VTLCategory } from "../../api/cases";
import { Dialog, DialogActions } from "../../components/Dialog";
import { strings } from "../../i18n/strings";
import styles from "./CaseReview.module.css";

const copy = strings.caseReview.confirmDialog;

export function ConfirmDialog({
  category,
  actionCount,
  isSaving,
  error,
  onConfirm,
  onClose,
}: {
  category: VTLCategory;
  /** How many actions the decision will record as kept, edited, or added. */
  actionCount: number;
  isSaving: boolean;
  /** A message from the failed attempt, shown in place of nothing. */
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const name = strings.vtl.names[category];

  return (
    <Dialog title={copy.title.replace("{category}", name)} isBusy={isSaving} onClose={onClose}>
      <p className={styles.dialogText}>{copy.body.replaceAll("{category}", name)}</p>
      <p className={styles.dialogText}>{actionsSummary(actionCount)}</p>

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

function actionsSummary(count: number): string {
  if (count === 0) {
    return copy.actionsSummaryNone;
  }
  return count === 1
    ? copy.actionsSummaryOne
    : copy.actionsSummaryMany.replace("{count}", String(count));
}
