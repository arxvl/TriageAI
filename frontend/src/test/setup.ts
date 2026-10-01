import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import "@testing-library/jest-dom/vitest";

// Vitest runs with `globals: false`, so React Testing Library's automatic
// cleanup never registers itself. Without this, the DOM and any stubbed `fetch`
// leak from one test into the next.
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.cookie = "triageai_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  // The theme is stored on the device, so it would leak between tests too.
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  stubMatchMedia(false);
});

/**
 * jsdom has no `matchMedia`, and `ThemeProvider` asks it what the device prefers.
 * The default answer is "light"; a test that cares passes `true` (see
 * `src/lib/theme.test.ts`).
 */
export function stubMatchMedia(matches: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();

  window.matchMedia = ((query: string) => ({
    media: query,
    matches,
    onchange: null,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) =>
      listeners.add(listener),
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) =>
      listeners.delete(listener),
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;

  /** Flip the device setting and tell everyone listening, as the browser would. */
  return function emitChange(nextMatches: boolean) {
    for (const listener of listeners) {
      listener({ matches: nextMatches } as MediaQueryListEvent);
    }
  };
}

stubMatchMedia(false);
