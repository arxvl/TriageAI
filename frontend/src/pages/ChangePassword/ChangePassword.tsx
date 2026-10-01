/**
 * Forced password change at first login (FR-61, SR-02).
 *
 * Every seeded account starts with a temporary password, so this is the first
 * screen most users see. The policy is checked here only to give an answer
 * without a round trip; the server decides (SR-09), and its message is what gets
 * shown when it refuses.
 */
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { ApiErrorCode, isApiError } from "../../api/errors";
import { homePathFor, useAuth } from "../../hooks/useAuth";
import { strings } from "../../i18n/strings";
import styles from "./ChangePassword.module.css";

const POLICY_HINT_ID = "new-password-policy";
const ERROR_ID = "change-password-error";

/** Mirrors `validate_password_policy` in the backend's `core/security.py` (SR-02). */
function meetsPolicy(password: string): boolean {
  return password.length >= 12 && /[A-Za-z]/.test(password) && /\d/.test(password);
}

export function ChangePassword() {
  const { user, changePassword } = useAuth();
  const navigate = useNavigate();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (currentPassword === "") {
      setError(strings.changePassword.errors.missingCurrent);
      return;
    }
    if (!meetsPolicy(newPassword)) {
      setError(strings.changePassword.errors.policy);
      return;
    }
    if (newPassword !== confirmPassword) {
      setError(strings.changePassword.errors.mismatch);
      return;
    }

    setError(null);
    setIsSubmitting(true);
    try {
      const updated = await changePassword(currentPassword, newPassword);
      await navigate(homePathFor(updated), { replace: true });
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className={styles.panel}>
      <h1 className={styles.title}>{strings.changePassword.title}</h1>
      {user?.must_change_password === true && (
        <p className={styles.intro}>{strings.changePassword.intro}</p>
      )}

      <form onSubmit={(event) => void handleSubmit(event)} noValidate>
        <label className={styles.label} htmlFor="current-password">
          {strings.changePassword.currentLabel}
        </label>
        <input
          id="current-password"
          className={styles.input}
          type="password"
          autoComplete="current-password"
          value={currentPassword}
          onChange={(event) => setCurrentPassword(event.target.value)}
        />

        <label className={styles.label} htmlFor="new-password">
          {strings.changePassword.newLabel}
        </label>
        <input
          id="new-password"
          className={styles.input}
          type="password"
          autoComplete="new-password"
          value={newPassword}
          aria-describedby={POLICY_HINT_ID}
          onChange={(event) => setNewPassword(event.target.value)}
        />
        <p id={POLICY_HINT_ID} className={styles.hint}>
          {strings.changePassword.policyHint}
        </p>

        <label className={styles.label} htmlFor="confirm-password">
          {strings.changePassword.confirmLabel}
        </label>
        <input
          id="confirm-password"
          className={styles.input}
          type="password"
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(event) => setConfirmPassword(event.target.value)}
        />

        <p id={ERROR_ID} className={styles.error} role="alert">
          {error}
        </p>

        <button type="submit" className={styles.submit} disabled={isSubmitting}>
          {isSubmitting ? strings.changePassword.submitting : strings.changePassword.submit}
        </button>
      </form>
    </section>
  );
}

/**
 * The server's own wording for a refused password, because it says precisely
 * what is wrong — too short, or previously used (IR-05).
 */
function messageFor(error: unknown): string {
  if (!isApiError(error)) {
    return strings.changePassword.errors.unexpected;
  }

  if (
    error.code === ApiErrorCode.weakPassword ||
    error.code === ApiErrorCode.currentPasswordIncorrect ||
    error.code === ApiErrorCode.validationError
  ) {
    return error.message;
  }

  return strings.changePassword.errors.unexpected;
}
