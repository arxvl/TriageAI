/** The shell every screen after login sits in: skip link, header (IR-02), main. */
import { Navigate, Outlet } from "react-router-dom";

import { useAuth } from "../hooks/useAuth";
import { strings } from "../i18n/strings";
import { AppHeader } from "./AppHeader";
import styles from "./AppLayout.module.css";

export function AppLayout() {
  const { user } = useAuth();

  // Unreachable behind ProtectedRoute; narrows the type.
  if (user === null) {
    return <Navigate to="/login" replace />;
  }

  return (
    <>
      <a className="visuallyHidden" href="#main">
        {strings.common.skipToContent}
      </a>
      <AppHeader user={user} />
      <main id="main" className={styles.main}>
        <Outlet />
      </main>
    </>
  );
}
