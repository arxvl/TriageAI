/**
 * Editing one account (FR-60, FR-63, BR-04 · W-09).
 *
 * W-09 draws only an "Edit" button, so this dialog carries what the API offers
 * beyond creating an account: name, role, the knowledge base approval
 * permission, active or deactivated, and a password reset.
 *
 * The approval checkbox follows the add-user panel: it is available to a
 * Veterinary Reviewer only, and changing to any other role clears it, because
 * the permission cannot be held by anyone else and the server refuses the
 * combination (BR-04). The e-mail is shown but fixed.
 *
 * Presentational: the page owns the requests and reports the server's answer in
 * `error`, and a reset needs a second click so a password is not replaced by
 * accident.
 */
import { useState } from "react";

import type { UserRole } from "../../api/auth";
import type { AdminUser, UserUpdateRequest } from "../../api/users";
import { Dialog, DialogActions } from "../../components/Dialog";
import { strings } from "../../i18n/strings";
import { ROLE_OPTIONS } from "./roles";
import styles from "./Users.module.css";

const copy = strings.users.editDialog;

export function EditUserDialog({
  user,
  isBusy,
  error,
  onSave,
  onResetPassword,
  onCancel,
}: {
  user: AdminUser;
  isBusy: boolean;
  /** The server's answer to the last attempt, or null. */
  error: string | null;
  onSave: (changes: UserUpdateRequest) => void;
  onResetPassword: () => void;
  onCancel: () => void;
}) {
  const [fullName, setFullName] = useState(user.full_name);
  const [role, setRole] = useState<UserRole>(user.role);
  const [canApproveKb, setCanApproveKb] = useState(user.can_approve_kb);
  const [isActive, setIsActive] = useState(user.is_active);
  const [nameMissing, setNameMissing] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);

  const mayApprove = role === "VETERINARY_REVIEWER";

  function handleRoleChange(next: UserRole) {
    setRole(next);
    if (next !== "VETERINARY_REVIEWER") {
      setCanApproveKb(false);
    }
  }

  function handleSave() {
    const name = fullName.trim();
    if (name === "") {
      setNameMissing(true);
      return;
    }
    setNameMissing(false);

    // Only what changed, so an untouched field is never re-sent.
    const changes: UserUpdateRequest = {};
    if (name !== user.full_name) changes.full_name = name;
    if (role !== user.role) changes.role = role;
    if (canApproveKb !== user.can_approve_kb) changes.can_approve_kb = canApproveKb;
    if (isActive !== user.is_active) changes.is_active = isActive;
    onSave(changes);
  }

  return (
    <Dialog title={copy.title} isBusy={isBusy} onClose={onCancel}>
      <div className={styles.field}>
        <label className={styles.label} htmlFor="edit-full-name">
          {copy.fullName}
        </label>
        <input
          id="edit-full-name"
          className={styles.input}
          type="text"
          autoComplete="off"
          value={fullName}
          aria-invalid={nameMissing}
          onChange={(event) => setFullName(event.target.value)}
        />
        <p className={styles.fieldError}>{nameMissing ? copy.fullNameMissing : ""}</p>
      </div>

      <div className={styles.field}>
        <span className={styles.label}>{copy.email}</span>
        <span>{user.email}</span>
        <span className={styles.helper}>{copy.emailFixed}</span>
      </div>

      <div className={styles.field}>
        <label className={styles.label} htmlFor="edit-role">
          {copy.role}
        </label>
        <select
          id="edit-role"
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
            disabled={!mayApprove}
            onChange={(event) => setCanApproveKb(event.target.checked)}
          />
          {copy.kbApproval}
        </label>
        <span className={styles.helper}>{copy.kbApprovalHelp}</span>
      </div>

      <div className={styles.field}>
        <label className={styles.checkbox}>
          <input
            type="checkbox"
            checked={isActive}
            onChange={(event) => setIsActive(event.target.checked)}
          />
          {copy.active}
        </label>
        <span className={styles.helper}>{copy.activeHelp}</span>
      </div>

      <div className={styles.field}>
        <span className={styles.helper}>{copy.resetPasswordHelp}</span>
        {confirmingReset ? (
          <button
            type="button"
            className={styles.danger}
            disabled={isBusy}
            onClick={onResetPassword}
          >
            {copy.resetPasswordConfirm}
          </button>
        ) : (
          <button
            type="button"
            className={styles.secondary}
            disabled={isBusy}
            onClick={() => setConfirmingReset(true)}
          >
            {copy.resetPassword}
          </button>
        )}
      </div>

      {error !== null ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}

      <DialogActions>
        <button type="button" className={styles.secondary} disabled={isBusy} onClick={onCancel}>
          {copy.cancel}
        </button>
        <button type="button" className={styles.primary} disabled={isBusy} onClick={handleSave}>
          {isBusy ? copy.saving : copy.save}
        </button>
      </DialogActions>
    </Dialog>
  );
}
