/**
 * The one-time view of a temporary password (FR-60, SR-03 · W-09).
 *
 * The server returns the password once and keeps only its hash, so this dialog
 * is the only chance to hand it over. It lives in the page's state and nowhere
 * else: not in the query cache, not in storage, not in the URL. Closing the
 * dialog drops it.
 *
 * Presentational: the page decides when it is open.
 */
import { useState } from "react";

import { Dialog, DialogActions } from "../../components/Dialog";
import { useToast } from "../../hooks/useToast";
import { strings } from "../../i18n/strings";
import styles from "./Users.module.css";

const copy = strings.users.temporaryPassword;

export function TemporaryPasswordDialog({
  fullName,
  password,
  onClose,
}: {
  fullName: string;
  password: string;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const [copyFailed, setCopyFailed] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(password);
      setCopyFailed(false);
      showToast(copy.copied);
    } catch {
      setCopyFailed(true);
    }
  }

  return (
    <Dialog title={copy.title} onClose={onClose}>
      <p className={styles.helper}>{copy.intro.replace("{name}", fullName)}</p>

      <label className={styles.label} htmlFor="temporary-password">
        {copy.label}
      </label>
      <input
        id="temporary-password"
        className={`${styles.input} ${styles.password}`}
        type="text"
        readOnly
        value={password}
        autoComplete="off"
        onFocus={(event) => event.currentTarget.select()}
      />

      <p className={styles.warning} role="note">
        {copy.warning}
      </p>
      {copyFailed ? (
        <p className={styles.fieldError} role="alert">
          {copy.copyFailed}
        </p>
      ) : null}

      <DialogActions>
        <button type="button" className={styles.secondary} onClick={() => void handleCopy()}>
          {copy.copy}
        </button>
        <button type="button" className={styles.primary} onClick={onClose}>
          {copy.done}
        </button>
      </DialogActions>
    </Dialog>
  );
}
