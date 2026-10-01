/**
 * W-01 Login (FR-57, UC-01).
 *
 * Two rules shape this screen:
 *
 * - One message for every sign-in failure, so the form cannot be used to find
 *   out which e-mail addresses have accounts (SR-03). The string comes from the
 *   resource file, not from the response, so a future API change cannot leak a
 *   more specific reason into the UI.
 * - A locked account (423) is the one case that says more, because the user
 *   needs the unlock time. The API puts it in the message as ISO-8601 UTC, so it
 *   is read back out and shown in the clinic's timezone.
 */
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ApiErrorCode, isApiError } from "../../api/errors";
import { PasswordField } from "../../components/PasswordField";
import { homePathFor, useAuth } from "../../hooks/useAuth";
import { strings } from "../../i18n/strings";
import { extractIsoTimestamp, formatDisplayTime } from "../../lib/datetime";
import styles from "./Login.module.css";

const ERROR_ID = "login-error";

export function Login() {
  const { user, isLoading, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Already signed in: do not show the form again.
  if (!isLoading && user !== null) {
    return (
      <Navigate to={user.must_change_password ? "/change-password" : homePathFor(user)} replace />
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (email.trim() === "") {
      setError(strings.login.errors.missingEmail);
      return;
    }
    if (password === "") {
      setError(strings.login.errors.missingPassword);
      return;
    }

    setError(null);
    setIsSubmitting(true);
    try {
      const signedIn = await login(email.trim(), password);
      const requested = (location.state as { from?: string } | null)?.from;
      const destination = signedIn.must_change_password
        ? "/change-password"
        : (requested ?? homePathFor(signedIn));
      await navigate(destination, { replace: true });
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className={styles.page}>
      <div className={styles.card}>
        {/* No theme control here on purpose: the sign-in screen follows the
            device setting, and the toggle belongs to the signed-in shell
            (see ThemeProvider). */}
        <h1 className={styles.title}>{strings.login.title}</h1>
        <p className={styles.subtitle}>{strings.login.subtitle}</p>
        <p className={styles.intro}>{strings.login.intro}</p>

        <form onSubmit={(event) => void handleSubmit(event)} noValidate>
          <label className={styles.label} htmlFor="login-email">
            {strings.login.emailLabel}
          </label>
          <input
            id="login-email"
            className={error === null ? styles.input : styles.inputInvalid}
            type="text"
            name="email"
            autoComplete="username"
            value={email}
            aria-describedby={error === null ? undefined : ERROR_ID}
            onChange={(event) => setEmail(event.target.value)}
          />

          <PasswordField
            id="login-password"
            name="password"
            label={strings.login.passwordLabel}
            autoComplete="current-password"
            value={password}
            invalid={error !== null}
            describedBy={error === null ? undefined : ERROR_ID}
            onChange={setPassword}
          />

          {/* Always rendered so the live region exists before the first failure. */}
          <p id={ERROR_ID} className={styles.error} role="alert">
            {error}
          </p>

          <p className={styles.notice}>{strings.login.lockoutNotice}</p>

          <div className={styles.actions}>
            <button type="submit" className={styles.submit} disabled={isSubmitting}>
              {isSubmitting ? strings.login.submitting : strings.login.submit}
            </button>
            <span className={styles.notice}>{strings.login.forgotPassword}</span>
          </div>
        </form>

        <hr className={styles.divider} />
        <p className={styles.notice}>{strings.login.privacyNotice}</p>
      </div>
    </main>
  );
}

/** Turn a failed sign-in into one plain sentence (IR-05). */
function messageFor(error: unknown): string {
  if (!isApiError(error)) {
    return strings.login.errors.unexpected;
  }

  if (error.code === ApiErrorCode.accountLocked) {
    return lockoutMessage(error.message);
  }

  // Everything else about the credentials themselves gets the one generic line,
  // including a 422 from a malformed address (SR-03).
  if (
    error.code === ApiErrorCode.invalidCredentials ||
    error.code === ApiErrorCode.validationError
  ) {
    return strings.login.errors.invalidCredentials;
  }

  return strings.login.errors.unexpected;
}

/**
 * Re-state the lockout with the unlock time in local time. If the timestamp
 * cannot be read, the server's own sentence is still accurate — show it rather
 * than hide when the account unlocks.
 */
function lockoutMessage(serverMessage: string): string {
  const iso = extractIsoTimestamp(serverMessage);
  const localTime = iso === null ? null : formatDisplayTime(iso);
  return localTime === null
    ? serverMessage
    : strings.login.lockedUntil.replace("{time}", localTime);
}
