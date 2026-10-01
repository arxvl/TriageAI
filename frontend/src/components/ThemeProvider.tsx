/**
 * Holds the theme preference and keeps `<html data-theme>` in step with it.
 *
 * Two rules live here:
 *
 * - The preference belongs to the device, not to the session, so signing out
 *   never changes it. It is stored and read back by `src/lib/theme.ts`.
 * - The sign-in screen always follows the device, whatever is stored. There is
 *   no theme control there (the toggle is part of the signed-in shell), so a
 *   preference left behind by the previous user is one nobody on that screen
 *   could undo. Signing in brings the stored choice straight back.
 *
 * That is why the provider sits inside the router: the route is what decides
 * which of the two applies. The attribute is written in a layout effect, before
 * the browser paints, so moving to or from the sign-in screen never flashes the
 * other theme. The first frame of all is covered by the stylesheet's
 * `color-scheme: light dark` (src/styles/tokens.css).
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

import { ThemeContext, type ThemeContextValue } from "../hooks/useTheme";
import {
  applyPreference,
  readStoredPreference,
  resolveTheme,
  storePreference,
  watchSystemTheme,
  type ResolvedTheme,
  type ThemePreference,
} from "../lib/theme";

/** Screens outside the signed-in shell, which carry no theme control. */
const SYSTEM_ONLY_PATHS: readonly string[] = ["/login"];

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStoredPreference);
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(() => resolveTheme("system"));
  const { pathname } = useLocation();

  const followsSystemOnly = SYSTEM_ONLY_PATHS.includes(pathname);
  const appliedPreference: ThemePreference = followsSystemOnly ? "system" : preference;

  useLayoutEffect(() => {
    applyPreference(appliedPreference);
  }, [appliedPreference]);

  // Only so the toggle can say what "System" currently means; the colours
  // themselves need no listener (src/styles/tokens.css).
  useEffect(() => watchSystemTheme(setSystemTheme), []);

  const setPreference = useCallback((next: ThemePreference) => {
    storePreference(next);
    setPreferenceState(next);
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      preference,
      resolvedTheme: preference === "system" ? systemTheme : preference,
      setPreference,
    }),
    [preference, systemTheme, setPreference],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
