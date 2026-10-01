/**
 * Reading, storing and applying the colour theme.
 *
 * Three preferences, not two: "system" is the default, so a clinic workstation
 * set to dark at the OS level starts dark without anyone choosing (NFR-21). The
 * two explicit values exist for the workstation whose OS setting is wrong for
 * the room it stands in.
 *
 * No colour value appears here. The preference only sets `data-theme` on
 * `<html>`; `src/styles/tokens.css` owns every colour the attribute selects.
 */

export const THEME_PREFERENCES = ["system", "light", "dark"] as const;

export type ThemePreference = (typeof THEME_PREFERENCES)[number];

/** What "system" currently resolves to; what is actually on screen. */
export type ResolvedTheme = "light" | "dark";

/** Namespaced, because a dev server shares an origin with anything else on it. */
export const THEME_STORAGE_KEY = "triageai.theme";

export const DARK_SCHEME_QUERY = "(prefers-color-scheme: dark)";

function isThemePreference(value: unknown): value is ThemePreference {
  return THEME_PREFERENCES.includes(value as ThemePreference);
}

/**
 * The stored preference, or "system" when there is none.
 *
 * Every access is guarded: `localStorage` throws on a blocked origin and in a
 * private window, and a theme is never worth breaking a screen over.
 */
export function readStoredPreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

/** Remember the choice, or forget it again when it goes back to "system". */
export function storePreference(preference: ThemePreference): void {
  try {
    if (preference === "system") {
      window.localStorage.removeItem(THEME_STORAGE_KEY);
    } else {
      window.localStorage.setItem(THEME_STORAGE_KEY, preference);
    }
  } catch {
    // An unwritable store costs the user the choice on the next page load only.
  }
}

/** The OS setting. "light" when the browser cannot say, which is also the default. */
export function systemTheme(): ResolvedTheme {
  // jsdom has no matchMedia, and neither do very old browsers.
  if (typeof window.matchMedia !== "function") {
    return "light";
  }
  return window.matchMedia(DARK_SCHEME_QUERY).matches ? "dark" : "light";
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  return preference === "system" ? systemTheme() : preference;
}

/**
 * Put the preference on `<html>`.
 *
 * "system" removes the attribute rather than writing the resolved value, so the
 * page keeps following the OS if it changes while the tab is open — the CSS does
 * that on its own, without a listener.
 */
export function applyPreference(preference: ThemePreference): void {
  const root = document.documentElement;
  if (preference === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", preference);
  }
}

/**
 * Call `onChange` whenever the OS setting flips. Returns the unsubscribe.
 *
 * Only the label on the toggle needs this; the colours follow `color-scheme`
 * without any help.
 */
export function watchSystemTheme(onChange: (theme: ResolvedTheme) => void): () => void {
  if (typeof window.matchMedia !== "function") {
    return () => {};
  }
  const query = window.matchMedia(DARK_SCHEME_QUERY);
  const listener = (event: MediaQueryListEvent) => onChange(event.matches ? "dark" : "light");
  query.addEventListener("change", listener);
  return () => query.removeEventListener("change", listener);
}
