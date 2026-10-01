/**
 * The one brief confirmation message the shell can show.
 *
 * Context and hook only — no JSX, so any page can import it without pulling a
 * component along. The provider is `src/components/ToastProvider.tsx`.
 *
 * It sits above the router on purpose: intake submits a case and navigates to the
 * queue in the same tick, so the message has to outlive the screen that asked for
 * it (W-03 → W-02).
 */
import { createContext, useContext } from "react";

export interface ToastContextValue {
  /** Show a short confirmation. A second call replaces the first. */
  showToast: (message: string) => void;
}

export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const value = useContext(ToastContext);
  if (value === null) {
    throw new Error("useToast must be used inside a ToastProvider.");
  }
  return value;
}
