/** `/` sends staff and reviewers to the queue and administrators to user management. */
import { Navigate } from "react-router-dom";

import { homePathFor, useAuth } from "../hooks/useAuth";

export function RoleHomeRedirect() {
  const { user } = useAuth();

  // Unreachable behind ProtectedRoute, but the type has to be narrowed somehow.
  if (user === null) {
    return <Navigate to="/login" replace />;
  }

  return <Navigate to={homePathFor(user)} replace />;
}
