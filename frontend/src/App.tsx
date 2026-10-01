/**
 * The route table (ADR-02).
 *
 * `allowedRoles` on each route matches the `require_role` guard on the endpoints
 * that route will call, so the UI and the API agree on who may go where. The
 * server is still the one enforcing it (SR-05).
 *
 * Provider order matters: `AuthProvider` sits inside `BrowserRouter` because it
 * navigates when a session expires, and inside `QueryClientProvider` because it
 * caches `/auth/me`. `ToastProvider` sits above the routes because a confirmation
 * outlives the screen that asked for it — intake submits a case and leaves for the
 * queue in the same tick. `ThemeProvider` sits inside `BrowserRouter` because the
 * sign-in screen always follows the device while the signed-in shell applies the
 * stored choice, and the route is what tells the two apart.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import type { UserRole } from "./api/auth";
import { AppLayout } from "./components/AppLayout";
import { AuthProvider } from "./components/AuthProvider";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { RoleHomeRedirect } from "./components/RoleHomeRedirect";
import { ThemeProvider } from "./components/ThemeProvider";
import { ToastProvider } from "./components/ToastProvider";
import { strings } from "./i18n/strings";
import { CaseIntake } from "./pages/CaseIntake/CaseIntake";
import { ChangePassword } from "./pages/ChangePassword/ChangePassword";
import { Login } from "./pages/Login/Login";
import { NotFound } from "./pages/NotFound/NotFound";
import { Placeholder } from "./pages/Placeholder/Placeholder";
import { TriageQueue } from "./pages/TriageQueue/TriageQueue";

const queryClient = new QueryClient();

const CASE_ROLES: readonly UserRole[] = ["INTAKE_STAFF", "VETERINARY_REVIEWER"];
const ADMIN_ROLES: readonly UserRole[] = ["ADMINISTRATOR"];
const KB_ROLES: readonly UserRole[] = ["ADMINISTRATOR", "VETERINARY_REVIEWER"];

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ThemeProvider>
          <ToastProvider>
            <AuthProvider>
              <Routes>
                <Route path="/login" element={<Login />} />

                {/* Signed in, temporary password still allowed. */}
                <Route element={<ProtectedRoute allowPasswordChangePending />}>
                  <Route element={<AppLayout />}>
                    <Route path="/change-password" element={<ChangePassword />} />

                    {/* Everything past here needs a permanent password (FR-61). */}
                    <Route element={<ProtectedRoute />}>
                      <Route path="/" element={<RoleHomeRedirect />} />

                      <Route element={<ProtectedRoute allowedRoles={CASE_ROLES} />}>
                        <Route path="/queue" element={<TriageQueue />} />
                        <Route path="/cases/new" element={<CaseIntake />} />
                        <Route
                          path="/history"
                          element={<Placeholder title={strings.nav.caseHistory} />}
                        />
                      </Route>

                      {/* Administrators may read a case but never decide one (BR-02). */}
                      <Route
                        path="/cases/:caseId"
                        element={<Placeholder title={strings.nav.caseDetail} />}
                      />

                      {/* A reviewer needs the separate KB approval permission (BR-04);
                      an administrator drafts entries without it (FR-52). */}
                      <Route
                        element={
                          <ProtectedRoute allowedRoles={KB_ROLES} requireKbApprovalForReviewers />
                        }
                      >
                        <Route
                          path="/kb"
                          element={<Placeholder title={strings.nav.knowledgeBase} />}
                        />
                      </Route>

                      <Route element={<ProtectedRoute allowedRoles={ADMIN_ROLES} />}>
                        <Route
                          path="/admin/users"
                          element={<Placeholder title={strings.nav.users} />}
                        />
                        <Route
                          path="/admin/evaluation"
                          element={<Placeholder title={strings.nav.evaluation} />}
                        />
                        <Route
                          path="/admin/exports"
                          element={<Placeholder title={strings.nav.exports} />}
                        />
                      </Route>

                      <Route path="/help" element={<Placeholder title={strings.common.help} />} />
                      <Route path="*" element={<NotFound />} />
                    </Route>
                  </Route>
                </Route>
              </Routes>
            </AuthProvider>
          </ToastProvider>
        </ThemeProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
