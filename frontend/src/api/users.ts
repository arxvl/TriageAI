/**
 * The `/users` endpoints: account administration (FR-60, FR-63, SR-03, BR-04).
 *
 * Field names match the API's own schemas verbatim — snake_case, no mapping
 * layer, the rule `api/cases.ts` follows.
 *
 * `temporary_password` exists on two responses only, create and reset. It is
 * shown once and never read back (FR-60), so nothing here caches it: the page
 * keeps it in component state until the dialog closes.
 */
import type { UserRole } from "./auth";
import { apiFetch } from "./client";

/** The administrator's view of an account. Never carries a credential. */
export interface AdminUser {
  id: string;
  full_name: string;
  email: string;
  role: UserRole;
  can_approve_kb: boolean;
  is_active: boolean;
  must_change_password: boolean;
  /** ISO instant, UTC. In the past once the lock has expired. */
  locked_until: string | null;
  last_login_at: string | null;
}

export interface UserListResponse {
  items: AdminUser[];
  total: number;
}

export interface UserCreateRequest {
  full_name: string;
  email: string;
  role: UserRole;
  can_approve_kb: boolean;
}

/** Only what FR-60 lets an administrator change; the e-mail is fixed. */
export interface UserUpdateRequest {
  full_name?: string;
  role?: UserRole;
  can_approve_kb?: boolean;
  is_active?: boolean;
}

export interface UserWithTemporaryPassword {
  user: AdminUser;
  temporary_password: string;
}

export function listUsers(search: string): Promise<UserListResponse> {
  const params = new URLSearchParams();
  if (search !== "") {
    params.set("q", search);
  }
  const query = params.toString();
  return apiFetch<UserListResponse>(query === "" ? "/users" : `/users?${query}`);
}

export function createUser(payload: UserCreateRequest): Promise<UserWithTemporaryPassword> {
  return apiFetch<UserWithTemporaryPassword>("/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateUser(id: string, payload: UserUpdateRequest): Promise<AdminUser> {
  return apiFetch<AdminUser>(`/users/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function unlockUser(id: string): Promise<AdminUser> {
  return apiFetch<AdminUser>(`/users/${id}/unlock`, { method: "POST" });
}

export function resetUserPassword(id: string): Promise<UserWithTemporaryPassword> {
  return apiFetch<UserWithTemporaryPassword>(`/users/${id}/reset-password`, { method: "POST" });
}
