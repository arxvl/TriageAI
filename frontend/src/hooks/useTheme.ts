/**
 * The colour theme the whole SPA reads from.
 *
 * Context and hook only — no JSX, so any screen can import it without pulling a
 * component along. The provider is `src/components/ThemeProvider.tsx`.
 */
import { createContext, useContext } from "react";

import type { ResolvedTheme, ThemePreference } from "../lib/theme";

export interface ThemeContextValue {
  /** What the user chose: "system", "light" or "dark". */
  preference: ThemePreference;
  /** What that currently means on screen; follows the OS while on "system". */
  resolvedTheme: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
}

export const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (value === null) {
    throw new Error("useTheme must be used inside a ThemeProvider.");
  }
  return value;
}
