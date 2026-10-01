/**
 * The session the whole SPA reads from.
 *
 * Context and hook only — no JSX, so this file stays importable from anywhere
 * without dragging a component along. The provider is
 * `src/components/AuthProvider.tsx`.
 *
 * Nothing here is an authorization check. The UI hides what a user may not do;
 * the server enforces it on every request (SR-05, ADR-11).
 */
import { createContext, useContext } from "react";

import type { AuthenticatedUser } from "../api/auth";

export interface AuthContextValue {
  /** The signed-in account, or null when there is no session. */
  user: AuthenticatedUser | null;
  /** True until the first `/auth/me` probe settles; routes must wait it out. */
  isLoading: boolean;
  login: (email: string, password: string) => Promise<AuthenticatedUser>;
  logout: () => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<AuthenticatedUser>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth must be used inside an AuthProvider.");
  }
  return value;
}

/** Where a signed-in user starts: administrators manage users, everyone else triages. */
export function homePathFor(user: AuthenticatedUser): string {
  return user.role === "ADMINISTRATOR" ? "/admin/users" : "/queue";
}
