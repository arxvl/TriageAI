/**
 * The modal every decision dialog is built on (IR-08, NFR-21 · W-05, W-06).
 *
 * A decision in this system is permanent and audited, so the dialogs that record
 * one must be reachable and escapable without a mouse. That is the whole job
 * here, and it is four behaviours:
 *
 * 1. **Focus moves in.** On open, the first focusable control inside is focused,
 *    so a keyboard user is already in the dialog rather than tabbing towards it
 *    from behind the overlay.
 * 2. **Focus stays in.** Tab from the last control wraps to the first and
 *    Shift+Tab from the first wraps to the last, so the page behind is
 *    unreachable while the dialog is open.
 * 3. **Escape closes.** A dialog that cannot be dismissed from the keyboard is a
 *    trap, not a confirmation.
 * 4. **Focus comes back.** On close, focus returns to whatever opened the dialog,
 *    so the reviewer's place on the page is not lost.
 *
 * Not the native `<dialog>` element: `showModal` is only partly implemented in
 * jsdom, and the focus behaviour above is exactly what these dialogs are tested
 * on. A real overlay that works the same in the browser and in the tests is
 * worth more here than the built-in element.
 *
 * `onClose` is the caller's — it is called for Escape and for the overlay, and
 * the caller decides what that means. A dialog with a request in flight should
 * pass `isBusy` so a half-saved decision cannot be dismissed out from under
 * itself.
 */
import { useCallback, useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";

import styles from "./Dialog.module.css";

/** Everything a keyboard can reach, minus anything deliberately taken out of order. */
const FOCUSABLE =
  "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), " +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Dialog({
  title,
  isBusy = false,
  onClose,
  children,
}: {
  title: string;
  /** While true, Escape and the overlay do not close the dialog. */
  isBusy?: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  // Captured on mount rather than read on unmount: by the time the dialog
  // closes, the element that opened it may already have been re-rendered.
  const opener = useRef<HTMLElement | null>(null);

  const focusable = useCallback((): HTMLElement[] => {
    return Array.from(panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
  }, []);

  useEffect(() => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;

    // The first control, or the panel itself for a dialog that has none — there
    // is always somewhere for focus to be, so it is never left on the page
    // behind the overlay.
    const first = panel.current?.querySelector<HTMLElement>(FOCUSABLE) ?? panel.current;
    first?.focus();

    return () => opener.current?.focus();
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      if (!isBusy) {
        event.stopPropagation();
        onClose();
      }
      return;
    }

    if (event.key !== "Tab") {
      return;
    }

    const controls = focusable();
    if (controls.length === 0) {
      event.preventDefault();
      return;
    }

    const first = controls[0];
    const last = controls[controls.length - 1];
    const active = document.activeElement;

    // Only the two ends are handled; everything between them is the browser's
    // own Tab order, which is also the reading order.
    if (event.shiftKey && (active === first || active === panel.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div
      className={styles.overlay}
      // A click on the backdrop is a dismissal, like Escape. The panel stops the
      // event, so a click inside never closes the dialog.
      onMouseDown={() => {
        if (!isBusy) {
          onClose();
        }
      }}
    >
      <div
        ref={panel}
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}

/** The row the action buttons sit in, so every dialog puts them in one place. */
export function DialogActions({ children }: { children: ReactNode }) {
  return <div className={styles.actions}>{children}</div>;
}
