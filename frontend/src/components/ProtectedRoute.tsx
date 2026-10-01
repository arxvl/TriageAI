/**
 * Route guard (ADR-02).
 *
 * The props deliberately mirror the server's `require_role(*roles, kb_approver,
 * allow_password_change_pending)` and the checks run in the same order, so the
 * UI hides exactly what the API would refuse. This is convenience, not
 * security: every rule is enforced again on the server (SR-05).
 */
import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import type { UserRole } from "../api/auth";
import { homePathFor, useAuth } from "../hooks/useAuth";
import { strings } from "../i18n/strings";

interface ProtectedRouteProps {
  /** Omitted means "any signed-in role". */
  allowedRoles?: readonly UserRole[];
  /**
   * Reviewers additionally need the separate KB approval permission (BR-04).
   * Other allowed roles are unaffected: an administrator drafts knowledge-base
   * entries without ever approving one (FR-52).
   */
  requireKbApprovalForReviewers?: boolean;
  /** Let a user with a temporary password through; only `/change-password` does. */
  allowPasswordChangePending?: boolean;
  children?: ReactNode;
}

export function ProtectedRoute({
  allowedRoles,
  requireKbApprovalForReviewers = false,
  allowPasswordChangePending = false,
  children,
}: ProtectedRouteProps) {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <p role="status">{strings.common.loadingSession}</p>;
  }

  if (user === null) {
    // Remember where they were headed so login can return them there.
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  if (user.must_change_password && !allowPasswordChangePending) {
    return <Navigate to="/change-password" replace />;
  }

  const roleAllowed = allowedRoles === undefined || allowedRoles.includes(user.role);
  const kbApprovalAllowed =
    !requireKbApprovalForReviewers || user.role !== "VETERINARY_REVIEWER" || user.can_approve_kb;

  if (!roleAllowed || !kbApprovalAllowed) {
    return <Navigate to={homePathFor(user)} replace />;
  }

  return <>{children ?? <Outlet />}</>;
}
