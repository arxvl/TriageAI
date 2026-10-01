import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { AuthenticatedUser, UserRole } from "../api/auth";
import { AuthContext, type AuthContextValue } from "../hooks/useAuth";
import { makeUserWithRole } from "../test/testUtils";
import { ProtectedRoute } from "./ProtectedRoute";

/**
 * Mount the guard inside a router with distinguishable destinations, so a test
 * asserts on where the user actually landed rather than on an implementation
 * detail of `<Navigate>`.
 */
function renderGuardedApp(
  options: {
    user?: AuthenticatedUser | null;
    isLoading?: boolean;
    route?: string;
    allowedRoles?: readonly UserRole[];
    requireKbApprovalForReviewers?: boolean;
    allowPasswordChangePending?: boolean;
  } = {},
) {
  const value: AuthContextValue = {
    user: options.user ?? null,
    isLoading: options.isLoading ?? false,
    login: vi.fn(),
    logout: vi.fn(),
    changePassword: vi.fn(),
  };

  return render(
    <AuthContext.Provider value={value}>
      <MemoryRouter initialEntries={[options.route ?? "/protected"]}>
        <Routes>
          <Route path="/login" element={<p>login screen</p>} />
          <Route path="/change-password" element={<p>change password screen</p>} />
          <Route path="/queue" element={<p>queue screen</p>} />
          <Route path="/admin/users" element={<p>users screen</p>} />
          <Route
            path="/protected"
            element={
              <ProtectedRoute
                allowedRoles={options.allowedRoles}
                requireKbApprovalForReviewers={options.requireKbApprovalForReviewers}
                allowPasswordChangePending={options.allowPasswordChangePending}
              >
                <p>protected content</p>
              </ProtectedRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("ProtectedRoute session handling (FR-57)", () => {
  it("sends an unauthenticated visitor to the login screen", () => {
    renderGuardedApp({ user: null });

    expect(screen.getByText("login screen")).toBeInTheDocument();
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });

  it("waits for the session probe instead of bouncing to login first", () => {
    renderGuardedApp({ user: null, isLoading: true });

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("login screen")).not.toBeInTheDocument();
  });

  it("lets an authorised user through", () => {
    renderGuardedApp({ user: makeUserWithRole("INTAKE_STAFF") });

    expect(screen.getByText("protected content")).toBeInTheDocument();
  });
});

describe("ProtectedRoute forced password change (FR-61)", () => {
  it("diverts a user with a temporary password", () => {
    renderGuardedApp({
      user: makeUserWithRole("INTAKE_STAFF", { must_change_password: true }),
    });

    expect(screen.getByText("change password screen")).toBeInTheDocument();
  });

  it("checks the password change before the role, as the server does", () => {
    renderGuardedApp({
      user: makeUserWithRole("INTAKE_STAFF", { must_change_password: true }),
      allowedRoles: ["ADMINISTRATOR"],
    });

    expect(screen.getByText("change password screen")).toBeInTheDocument();
    expect(screen.queryByText("queue screen")).not.toBeInTheDocument();
  });

  it("allows the change-password screen itself through", () => {
    renderGuardedApp({
      user: makeUserWithRole("INTAKE_STAFF", { must_change_password: true }),
      allowPasswordChangePending: true,
    });

    expect(screen.getByText("protected content")).toBeInTheDocument();
  });
});

describe("ProtectedRoute role checks (FR-59, BR-02)", () => {
  it("returns a staff user to their own home when the role is wrong", () => {
    renderGuardedApp({
      user: makeUserWithRole("INTAKE_STAFF"),
      allowedRoles: ["ADMINISTRATOR"],
    });

    expect(screen.getByText("queue screen")).toBeInTheDocument();
  });

  it("returns an administrator to user management when the role is wrong", () => {
    renderGuardedApp({
      user: makeUserWithRole("ADMINISTRATOR"),
      allowedRoles: ["INTAKE_STAFF", "VETERINARY_REVIEWER"],
    });

    expect(screen.getByText("users screen")).toBeInTheDocument();
  });

  it("blocks a reviewer without the KB approval permission (BR-04)", () => {
    renderGuardedApp({
      user: makeUserWithRole("VETERINARY_REVIEWER", { can_approve_kb: false }),
      allowedRoles: ["ADMINISTRATOR", "VETERINARY_REVIEWER"],
      requireKbApprovalForReviewers: true,
    });

    expect(screen.getByText("queue screen")).toBeInTheDocument();
  });

  it("admits a reviewer who holds the KB approval permission", () => {
    renderGuardedApp({
      user: makeUserWithRole("VETERINARY_REVIEWER", { can_approve_kb: true }),
      allowedRoles: ["ADMINISTRATOR", "VETERINARY_REVIEWER"],
      requireKbApprovalForReviewers: true,
    });

    expect(screen.getByText("protected content")).toBeInTheDocument();
  });

  it("admits an administrator to the knowledge base without that permission (FR-52)", () => {
    renderGuardedApp({
      user: makeUserWithRole("ADMINISTRATOR", { can_approve_kb: false }),
      allowedRoles: ["ADMINISTRATOR", "VETERINARY_REVIEWER"],
      requireKbApprovalForReviewers: true,
    });

    expect(screen.getByText("protected content")).toBeInTheDocument();
  });
});
