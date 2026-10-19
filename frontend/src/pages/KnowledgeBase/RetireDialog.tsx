/**
 * Confirming a retirement (FR-53, FR-54, IR-08).
 *
 * Irreversible from the screen's point of view — retiring removes the entry's
 * chunks from retrieval and publishes a new knowledge-base version — so it is
 * confirmed first, like every other irreversible action in the system.
 *
 * What it does not say is that the entry is deleted, because it is not: the row
 * is kept so a recommendation that cited it stays explainable (ADR-14).
 *
 * Presentational: the screen owns the request, and reports the warning the
 * server answers with.
 */
import { Dialog, DialogActions } from "../../components/Dialog";
import { strings } from "../../i18n/strings";
import styles from "./KnowledgeBase.module.css";

const copy = strings.knowledgeBase.retireDialog;

export function RetireDialog({
  title,
  isBusy,
  onRetire,
  onCancel,
}: {
  /** The entry's own title, so the dialog names what is being retired. */
  title: string;
  isBusy: boolean;
  onRetire: () => void;
  onCancel: () => void;
}) {
  return (
    <Dialog title={copy.title} isBusy={isBusy} onClose={onCancel}>
      <p className={styles.dialogEntry}>{title}</p>
      <p className={styles.helper}>{copy.body}</p>

      <DialogActions>
        <button type="button" className={styles.secondary} disabled={isBusy} onClick={onCancel}>
          {copy.cancel}
        </button>
        <button type="button" className={styles.danger} disabled={isBusy} onClick={onRetire}>
          {copy.confirm}
        </button>
      </DialogActions>
    </Dialog>
  );
}
