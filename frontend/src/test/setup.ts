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
});
