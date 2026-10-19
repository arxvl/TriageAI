/**
 * Sending a draft back to its author (FR-51).
 *
 * The comments are required, and the button stays disabled until something has
 * been written: a rejection with no reason gives the author nothing to act on,
 * and the exchange between author and approver is the whole point of the
 * Pending Review state. The server refuses a blank one as well.
 *
 * The comments are returned on the entry, where the author can read and act on
 * them, and are deliberately kept out of the audit log, which cannot be
 * corrected (FR-43, ADR-12).
 *
 * Presentational: the screen owns the request.
 */
import { useState } from "react";

import { Dialog, DialogActions } from "../../components/Dialog";
import { strings } from "../../i18n/strings";
import styles from "./KnowledgeBase.module.css";

const copy = strings.knowledgeBase.rejectDialog;

export function RejectDialog({
  isBusy,
  onReject,
  onCancel,
}: {
  isBusy: boolean;
  onReject: (comments: string) => void;
  onCancel: () => void;
}) {
  const [comments, setComments] = useState("");
  const trimmed = comments.trim();

  return (
    <Dialog title={copy.title} isBusy={isBusy} onClose={onCancel}>
      <label className={styles.field}>
        <span className={styles.fieldLabel}>{copy.commentsLabel}</span>
        <textarea
          className={styles.textarea}
          rows={5}
          value={comments}
          disabled={isBusy}
          onChange={(event) => setComments(event.target.value)}
        />
      </label>

      <p className={styles.helper}>{copy.commentsHint}</p>

      <DialogActions>
        <button type="button" className={styles.secondary} disabled={isBusy} onClick={onCancel}>
          {copy.cancel}
        </button>
        <button
          type="button"
          className={styles.primary}
          disabled={isBusy || trimmed === ""}
          onClick={() => {
            if (trimmed !== "") {
              onReject(trimmed);
            }
          }}
        >
          {copy.submit}
        </button>
      </DialogActions>
    </Dialog>
  );
}
