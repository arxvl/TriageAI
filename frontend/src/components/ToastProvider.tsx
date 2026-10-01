/**
 * Holds and renders the shell's confirmation message (IR-05).
 *
 * One message at a time, announced politely rather than assertively: a successful
 * submission is not an alert, and `role="alert"` would interrupt whatever the
 * screen reader is in the middle of. The region is always in the DOM so the live
 * region exists before the first message arrives — the same reason the form error
 * paragraphs are always rendered.
 *
 * It never carries an error: a failure belongs beside the field or the form that
 * caused it, where the user is already looking.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { strings } from "../i18n/strings";
import { ToastContext, type ToastContextValue } from "../hooks/useToast";
import styles from "./ToastProvider.module.css";

/** Long enough to read a case number, short enough not to sit over the queue. */
const TOAST_DURATION_MS = 6_000;

interface Toast {
  /** Rises on every call, so the same message twice restarts the timer. */
  id: number;
  text: string;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);

  const showToast = useCallback((message: string) => {
    setToast((previous) => ({ id: (previous?.id ?? 0) + 1, text: message }));
  }, []);

  useEffect(() => {
    if (toast === null) {
      return;
    }
    const timer = setTimeout(() => setToast(null), TOAST_DURATION_MS);
    return () => clearTimeout(timer);
  }, [toast]);

  const value = useMemo<ToastContextValue>(() => ({ showToast }), [showToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className={styles.region} role="status" aria-live="polite">
        {toast !== null && (
          <div className={styles.toast}>
            <span>{toast.text}</span>
            <button
              type="button"
              className={styles.dismiss}
              onClick={() => setToast(null)}
              aria-label={strings.common.dismiss}
            >
              &times;
            </button>
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}
