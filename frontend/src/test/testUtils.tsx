/**
 * The shared test harness for the frontend.
 *
 * Two ways in, on purpose:
 *
 * - `renderWithAuth` injects an `AuthContextValue` directly. Use it when the
 *   session is a precondition, not the thing under test (the header, route
 *   guards).
 * - `renderWithProviders` mounts the real `AuthProvider` over a stubbed `fetch`.
 *   Use it when the request itself matters (login, change password).
 *
 * Both wrap `ToastProvider`, because it sits above the routes in `App.tsx` and a
 * page that shows a confirmation must be able to reach it, and `ThemeProvider`,
 * because the header carries the theme control. `ThemeProvider` sits inside the
 * router, as it does in `App.tsx`: it reads the route to decide whether the
 * stored preference applies, so `options.route` changes what it does.
 *
 * There is no MSW and no `user-event`: `vi.stubGlobal("fetch", ...)` and
 * `fireEvent` cover everything these screens do, and both avoid a new
 * dependency (CLAUDE.md §13).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import type { AuthenticatedUser, UserRole } from "../api/auth";
import { AuthProvider } from "../components/AuthProvider";
import { ThemeProvider } from "../components/ThemeProvider";
import { ToastProvider } from "../components/ToastProvider";
import { AuthContext, type AuthContextValue } from "../hooks/useAuth";

/** A fictitious account (CLAUDE.md §9). Override whatever the test cares about. */
export function makeUser(overrides: Partial<AuthenticatedUser> = {}): AuthenticatedUser {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    full_name: "J. Cruz",
    email: "intake@triageai.local",
    role: "INTAKE_STAFF",
    can_approve_kb: false,
    must_change_password: false,
    ...overrides,
  };
}

export function makeUserWithRole(role: UserRole, overrides: Partial<AuthenticatedUser> = {}) {
  return makeUser({ role, ...overrides });
}

/** Queries must not retry in tests, or a failure case waits for backoff. */
function newQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

interface AuthOptions {
  user?: AuthenticatedUser | null;
  isLoading?: boolean;
  route?: string;
  login?: AuthContextValue["login"];
  logout?: AuthContextValue["logout"];
  changePassword?: AuthContextValue["changePassword"];
}

export function renderWithAuth(ui: ReactNode, options: AuthOptions = {}): RenderResult {
  const value: AuthContextValue = {
    user: options.user ?? null,
    isLoading: options.isLoading ?? false,
    login: options.login ?? vi.fn(),
    logout: options.logout ?? vi.fn(),
    changePassword: options.changePassword ?? vi.fn(),
  };

  return render(
    <QueryClientProvider client={newQueryClient()}>
      <MemoryRouter initialEntries={[options.route ?? "/"]}>
        <ThemeProvider>
          <ToastProvider>
            <AuthContext.Provider value={value}>{ui}</AuthContext.Provider>
          </ToastProvider>
        </ThemeProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export function renderWithProviders(ui: ReactNode, options: { route?: string } = {}): RenderResult {
  return render(
    <QueryClientProvider client={newQueryClient()}>
      <MemoryRouter initialEntries={[options.route ?? "/"]}>
        <ThemeProvider>
          <ToastProvider>
            <AuthProvider>{ui}</AuthProvider>
          </ToastProvider>
        </ThemeProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

interface StubbedResponse {
  status?: number;
  body?: unknown;
}

/**
 * Replace `fetch` with a queue of canned responses, matched by path substring.
 *
 * The returned mock is the assertion target for headers and bodies.
 */
export function stubFetch(routes: Record<string, StubbedResponse>) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const match = Object.keys(routes).find((path) => url.includes(path));
    const stub: StubbedResponse = match === undefined ? { status: 404 } : routes[match];
    const status = stub.status ?? 200;

    void init;
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => stub.body ?? {},
    } as Response;
  });

  vi.stubGlobal("fetch", mock);
  return mock;
}

/**
 * The error envelope every 4xx and 5xx uses (backend `core/errors.py`).
 *
 * `field` is present only on a validation error, and names the input the message
 * belongs to (IR-05).
 */
export function errorBody(code: string, message: string, field?: string) {
  return { error: field === undefined ? { code, message } : { code, message, field } };
}
