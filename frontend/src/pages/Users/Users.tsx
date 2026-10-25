/**
 * W-09 User Management (FR-60, FR-63, SR-03, SR-05, BR-04, BR-05 · UC-12).
 *
 * An administrator's screen: the account table on the left, "Add user" on the
 * right. Three behaviours matter more than the layout:
 *
 * - **A temporary password is shown once.** Creating an account and resetting a
 *   password both answer with one. It is kept in this component's state for the
 *   dialog and dropped when the dialog closes; it is never put in the query
 *   cache, so the table's refetch cannot bring it back (FR-60).
 * - **The approval permission follows the role.** The checkbox is available only
 *   for a Veterinary Reviewer and is cleared when the role changes away from
 *   it, because nobody else may hold it (BR-04). The server refuses the
 *   combination as well.
 * - **Status is text, not colour.** "Locked until HH:MM", "Active" and
 *   "Deactivated" are written out, and a locked row is tinted as well (IR-03).
 *
 * The server refuses a change that would leave no active administrator; this
 * screen reports that in plain language instead of hiding the controls, because
 * whether another administrator is active is the server's to know (409).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import type { UserRole } from "../../api/auth";
import { ApiErrorCode, isApiError } from "../../api/errors";
import {
  createUser,
  listUsers,
  resetUserPassword,
  unlockUser,
  updateUser,
  type AdminUser,
  type UserUpdateRequest,
} from "../../api/users";
import { useToast } from "../../hooks/useToast";
import { strings } from "../../i18n/strings";
import { formatArrivalTime, formatDisplayDate } from "../../lib/datetime";
import { EditUserDialog } from "./EditUserDialog";
import { ROLE_OPTIONS } from "./roles";
import { TemporaryPasswordDialog } from "./TemporaryPasswordDialog";
import styles from "./Users.module.css";
import { userStatus } from "./userStatus";

const copy = strings.users;

/** Same loose shape the server checks; the server has the final say. */
const EMAIL_SHAPE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** A message and, when it belongs to one input, which one. */
interface FailureMessage {
  field: string | null;
  message: string;
}

function describeFailure(error: unknown): FailureMessage {
  if (!isApiError(error)) {
    return { field: null, message: copy.errors.actionFailed };
  }
  switch (error.code) {
    case ApiErrorCode.lastAdministrator:
      return { field: null, message: copy.errors.lastAdministrator };
    case ApiErrorCode.emailAlreadyInUse:
      return { field: "email", message: copy.errors.emailInUse };
    case ApiErrorCode.validationError:
      return { field: error.field, message: error.message };
    case ApiErrorCode.notFound:
      return { field: null, message: copy.errors.notFound };
    case ApiErrorCode.forbidden:
      return { field: null, message: copy.errors.forbidden };
    default:
      return { field: null, message: copy.errors.actionFailed };
  }
}

function formatLastLogin(iso: string | null): string {
  if (iso === null) {
    return copy.neverSignedIn;
  }
  const date = formatDisplayDate(iso);
  const time = formatArrivalTime(iso);
  return date !== null && time !== null ? `${date}, ${time}` : copy.neverSignedIn;
}

/** The password a dialog is showing, and whose it is. */
interface IssuedPassword {
  fullName: string;
  password: string;
}

export function Users() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<UserRole>("INTAKE_STAFF");
  const [canApproveKb, setCanApproveKb] = useState(false);
  const [addErrors, setAddErrors] = useState<Record<string, string>>({});
  const [addFailure, setAddFailure] = useState<string | null>(null);

  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [editFailure, setEditFailure] = useState<string | null>(null);
  const [pageFailure, setPageFailure] = useState<string | null>(null);
  const [issued, setIssued] = useState<IssuedPassword | null>(null);

  const users = useQuery({
    queryKey: ["users", { q: search }],
    queryFn: () => listUsers(search),
    placeholderData: (previous) => previous,
  });

  function refreshUsers() {
    void queryClient.invalidateQueries({ queryKey: ["users"] });
  }

  const create = useMutation({
    mutationFn: createUser,
    onSuccess: (result) => {
      setIssued({ fullName: result.user.full_name, password: result.temporary_password });
      setFullName("");
      setEmail("");
      setRole("INTAKE_STAFF");
      setCanApproveKb(false);
      setAddErrors({});
      setAddFailure(null);
      showToast(copy.toasts.created);
      refreshUsers();
    },
    onError: (error) => {
      const failure = describeFailure(error);
      const field = failure.field;
      if (field === "full_name" || field === "email" || field === "can_approve_kb") {
        setAddErrors({ [field]: failure.message });
        setAddFailure(null);
      } else {
        setAddFailure(failure.message);
      }
    },
  });

  const update = useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: UserUpdateRequest }) =>
      updateUser(id, changes),
    onSuccess: (_user, variables) => {
      setEditing(null);
      setEditFailure(null);
      showToast(
        variables.changes.is_active === true ? copy.toasts.reactivated : copy.toasts.updated,
      );
      refreshUsers();
    },
    onError: (error) => {
      const message = describeFailure(error).message;
      if (editing !== null) {
        setEditFailure(message);
      } else {
        setPageFailure(message);
      }
    },
  });

  const unlock = useMutation({
    mutationFn: unlockUser,
    onSuccess: () => {
      showToast(copy.toasts.unlocked);
      refreshUsers();
    },
    onError: (error) => setPageFailure(describeFailure(error).message),
  });

  const reset = useMutation({
    mutationFn: resetUserPassword,
    onSuccess: (result) => {
      setEditing(null);
      setEditFailure(null);
      setIssued({ fullName: result.user.full_name, password: result.temporary_password });
      refreshUsers();
    },
    onError: (error) => setEditFailure(describeFailure(error).message),
  });

  function handleSearch(event: FormEvent) {
    event.preventDefault();
    setSearch(searchInput.trim());
  }

  function handleClearSearch() {
    setSearchInput("");
    setSearch("");
  }

  function handleRoleChange(next: UserRole) {
    setRole(next);
    if (next !== "VETERINARY_REVIEWER") {
      setCanApproveKb(false);
    }
  }

  function handleCreate(event: FormEvent) {
    event.preventDefault();
    const name = fullName.trim();
    const address = email.trim();

    const errors: Record<string, string> = {};
    if (name === "") {
      errors.full_name = copy.add.fullNameMissing;
    }
    if (!EMAIL_SHAPE.test(address)) {
      errors.email = copy.add.emailInvalid;
    }
    setAddErrors(errors);
    setAddFailure(null);
    if (Object.keys(errors).length > 0) {
      return;
    }

    create.mutate({ full_name: name, email: address, role, can_approve_kb: canApproveKb });
  }

  function handleSaveEdit(changes: UserUpdateRequest) {
    if (editing === null) {
      return;
    }
    if (Object.keys(changes).length === 0) {
      setEditing(null);
      return;
    }
    setEditFailure(null);
    update.mutate({ id: editing.id, changes });
  }

  function openEdit(user: AdminUser) {
    setPageFailure(null);
    setEditFailure(null);
    setEditing(user);
  }

  const rows = users.data?.items ?? [];
  const isEditBusy = update.isPending || reset.isPending;

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>{copy.title}</h1>

      <div className={styles.layout}>
        <section className={styles.listPanel} aria-label={copy.title}>
          <form className={styles.searchBar} onSubmit={handleSearch} role="search">
            <div className={styles.field}>
              <label className={styles.label} htmlFor="user-search">
                {copy.searchLabel}
              </label>
              <input
                id="user-search"
                className={styles.input}
                type="search"
                autoComplete="off"
                placeholder={copy.searchPlaceholder}
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
              />
            </div>
            <button type="submit" className={styles.primary}>
              {copy.searchButton}
            </button>
            {search !== "" ? (
              <button type="button" className={styles.secondary} onClick={handleClearSearch}>
                {copy.clearSearch}
              </button>
            ) : null}
          </form>

          {pageFailure !== null ? (
            <p className={styles.error} role="alert">
              {pageFailure}
            </p>
          ) : null}

          {users.isError ? (
            <p className={styles.error} role="alert">
              {copy.errors.unexpected}
            </p>
          ) : null}

          {users.isPending ? <p className={styles.notice}>{copy.loading}</p> : null}

          {users.data !== undefined && rows.length === 0 ? (
            <p className={styles.notice}>{copy.empty}</p>
          ) : null}

          {rows.length > 0 ? (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">{copy.columns.name}</th>
                  <th scope="col">{copy.columns.email}</th>
                  <th scope="col">{copy.columns.role}</th>
                  <th scope="col">{copy.columns.kbApproval}</th>
                  <th scope="col">{copy.columns.status}</th>
                  <th scope="col">{copy.columns.lastLogin}</th>
                  <th scope="col">
                    <span className={styles.visuallyHidden}>{copy.columns.actions}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((user) => {
                  const status = userStatus(user);
                  return (
                    <tr
                      key={user.id}
                      className={status.kind === "LOCKED" ? styles.locked : undefined}
                    >
                      <td>{user.full_name}</td>
                      <td className={styles.email}>{user.email}</td>
                      <td>{strings.roles[user.role]}</td>
                      <td>
                        {user.can_approve_kb ? (
                          <strong>{copy.kbApprovalYes}</strong>
                        ) : (
                          copy.kbApprovalNo
                        )}
                      </td>
                      <td>
                        <span className={`${styles.chip} ${styles[status.kind]}`}>
                          {status.label}
                        </span>
                      </td>
                      <td>{formatLastLogin(user.last_login_at)}</td>
                      <td>
                        <div className={styles.rowActions}>
                          {status.kind === "LOCKED" ? (
                            <button
                              type="button"
                              className={styles.small}
                              disabled={unlock.isPending}
                              aria-label={`${copy.unlock} ${user.full_name}`}
                              onClick={() => {
                                setPageFailure(null);
                                unlock.mutate(user.id);
                              }}
                            >
                              {copy.unlock}
                            </button>
                          ) : null}
                          {status.kind === "DEACTIVATED" ? (
                            <button
                              type="button"
                              className={styles.small}
                              disabled={update.isPending}
                              aria-label={`${copy.reactivate} ${user.full_name}`}
                              onClick={() => {
                                setPageFailure(null);
                                update.mutate({ id: user.id, changes: { is_active: true } });
                              }}
                            >
                              {copy.reactivate}
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className={styles.small}
                            aria-label={`${copy.edit} ${user.full_name}`}
                            onClick={() => openEdit(user)}
                          >
                            {copy.edit}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : null}
        </section>

        <aside className={styles.addPanel} aria-label={copy.add.title}>
          <h2 className={styles.panelTitle}>{copy.add.title}</h2>
          <form onSubmit={handleCreate} noValidate>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="add-full-name">
                {copy.add.fullName}
              </label>
              <input
                id="add-full-name"
                className={styles.input}
                type="text"
                autoComplete="off"
                value={fullName}
                aria-invalid={addErrors.full_name !== undefined}
                onChange={(event) => setFullName(event.target.value)}
              />
              <p className={styles.fieldError}>{addErrors.full_name ?? ""}</p>
            </div>

            <div className={styles.field}>
              <label className={styles.label} htmlFor="add-email">
                {copy.add.email}
              </label>
              <input
                id="add-email"
                className={styles.input}
                type="email"
                autoComplete="off"
                value={email}
                aria-invalid={addErrors.email !== undefined}
                onChange={(event) => setEmail(event.target.value)}
              />
              <p className={styles.fieldError}>{addErrors.email ?? ""}</p>
            </div>

            <div className={styles.field}>
              <label className={styles.label} htmlFor="add-role">
                {copy.add.role}
              </label>
              <select
                id="add-role"
                className={styles.input}
                value={role}
                onChange={(event) => handleRoleChange(event.target.value as UserRole)}
              >
                {ROLE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            <div className={styles.field}>
              <label className={styles.checkbox}>
                <input
                  type="checkbox"
                  checked={canApproveKb}
                  disabled={role !== "VETERINARY_REVIEWER"}
                  onChange={(event) => setCanApproveKb(event.target.checked)}
                />
                {copy.add.kbApproval}
              </label>
              <span className={styles.helper}>{copy.add.kbApprovalHelp}</span>
              <p className={styles.fieldError}>{addErrors.can_approve_kb ?? ""}</p>
            </div>

            <p className={styles.helper}>{copy.add.temporaryPasswordNote}</p>

            {addFailure !== null ? (
              <p className={styles.error} role="alert">
                {addFailure}
              </p>
            ) : null}

            <button type="submit" className={styles.primary} disabled={create.isPending}>
              {create.isPending ? copy.add.submitting : copy.add.submit}
            </button>
          </form>
        </aside>
      </div>

      {editing !== null ? (
        <EditUserDialog
          user={editing}
          isBusy={isEditBusy}
          error={editFailure}
          onSave={handleSaveEdit}
          onResetPassword={() => {
            setEditFailure(null);
            reset.mutate(editing.id);
          }}
          onCancel={() => setEditing(null)}
        />
      ) : null}

      {issued !== null ? (
        <TemporaryPasswordDialog
          fullName={issued.fullName}
          password={issued.password}
          onClose={() => setIssued(null)}
        />
      ) : null}
    </div>
  );
}
