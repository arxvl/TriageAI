/**
 * The `/auth` endpoints and the one account shape the SPA stores (FR-57, FR-61,
 * FR-62).
 *
 * Field names match the API's `UserOut` verbatim — snake_case, no mapping layer
 * on either side.
 */
import { apiFetch } from "./client";

export type UserRole = "INTAKE_STAFF" | "VETERINARY_REVIEWER" | "ADMINISTRATOR";

export interface AuthenticatedUser {
  id: string;
  full_name: string;
  email: string;
  role: UserRole;
  /** A separate permission from the role, held only by reviewers (BR-04). */
  can_approve_kb: boolean;
  must_change_password: boolean;
}

interface UserEnvelope {
  user: AuthenticatedUser;
}

/** Throws `ApiError` with code `NOT_AUTHENTICATED` when there is no session. */
export async function fetchCurrentUser(): Promise<AuthenticatedUser> {
  const body = await apiFetch<UserEnvelope>("/auth/me");
  return body.user;
}

export async function login(email: string, password: string): Promise<AuthenticatedUser> {
  const body = await apiFetch<UserEnvelope>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  return body.user;
}

export async function logout(): Promise<void> {
  await apiFetch<{ status: string }>("/auth/logout", { method: "POST" });
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<AuthenticatedUser> {
  const body = await apiFetch<UserEnvelope>("/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  return body.user;
}
