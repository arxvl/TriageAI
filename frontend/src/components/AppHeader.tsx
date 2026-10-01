/**
 * The persistent header shown on every screen after login (IR-02, W-02).
 *
 * Navigation is role-aware: a user is never shown a link the server would
 * refuse. Administrators do not triage and reviewers do not administer
 * (BR-02, BR-05), so the two sets do not overlap.
 */
import { NavLink, useNavigate } from "react-router-dom";

import type { AuthenticatedUser } from "../api/auth";
import { useAuth } from "../hooks/useAuth";
import { strings } from "../i18n/strings";
import styles from "./AppHeader.module.css";

interface NavItem {
  to: string;
  label: string;
}

/** The links a given account may use. Keep in step with the route table in App.tsx. */
function navItemsFor(user: AuthenticatedUser): NavItem[] {
  if (user.role === "ADMINISTRATOR") {
    return [
      { to: "/admin/users", label: strings.nav.users },
      { to: "/kb", label: strings.nav.knowledgeBase },
      { to: "/admin/evaluation", label: strings.nav.evaluation },
      { to: "/admin/exports", label: strings.nav.exports },
    ];
  }

  const items: NavItem[] = [
    { to: "/queue", label: strings.nav.queue },
    { to: "/cases/new", label: strings.nav.newCase },
    { to: "/history", label: strings.nav.caseHistory },
  ];

  // KB approval is a permission, not a role (BR-04).
  if (user.can_approve_kb) {
    items.push({ to: "/kb", label: strings.nav.kbApprovals });
  }

  return items;
}

export function AppHeader({ user }: { user: AuthenticatedUser }) {
  const { logout } = useAuth();
  const navigate = useNavigate();

  const isAdministrator = user.role === "ADMINISTRATOR";
  // Until the temporary password is replaced the server refuses everything but
  // /auth/*, so offering the links would only produce 403s (FR-61).
  const navItems = user.must_change_password ? [] : navItemsFor(user);

  async function handleLogOut() {
    await logout();
    await navigate("/login", { replace: true });
  }

  return (
    <header className={styles.header}>
      <div className={styles.brand}>
        <span className={styles.brandName}>{strings.common.systemName}</span>
        <small className={styles.brandTagline}>
          {isAdministrator ? strings.common.taglineAdmin : strings.common.tagline}
        </small>
      </div>

      {navItems.length > 0 && (
        <nav className={styles.nav} aria-label={strings.common.mainNavLabel}>
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? styles.navLinkActive : styles.navLink)}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      )}

      <div className={styles.account}>
        <span>
          <b>{user.full_name}</b> · {strings.roles[user.role]}
        </span>
        <NavLink to="/help" className={styles.helpLink}>
          {strings.common.help}
        </NavLink>
        <button type="button" className={styles.logOut} onClick={() => void handleLogOut()}>
          {strings.common.logOut}
        </button>
      </div>
    </header>
  );
}
