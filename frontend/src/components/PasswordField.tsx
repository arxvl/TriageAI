/**
 * A labelled password input with a reveal button (W-01, FR-61).
 *
 * Why one component for both screens: the reveal has rules that are easy to get
 * wrong twice. The field starts hidden on every mount, so a revealed password
 * never survives a navigation; the button is a real `<button type="button">`, so
 * it neither submits the form nor sits in the tab order after the submit; and its
 * accessible name states the next action while `aria-pressed` carries the current
 * state (IR-07, NFR-21).
 *
 * The input keeps its own `autoComplete` value: a browser that fills a password
 * manager entry must still recognise the field after a reveal, which it does
 * because only `type` changes.
 */
import { useState, type ReactNode } from "react";

import { strings } from "../i18n/strings";
import styles from "./PasswordField.module.css";

interface PasswordFieldProps {
  /** Must be unique on the page; ties the label and the button to the input. */
  id: string;
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  /** "current-password" on a sign-in or re-authentication field, else "new-password". */
  autoComplete: "current-password" | "new-password";
  /** Ids of the hint or error text that explains this field. */
  describedBy?: string;
  /** Draws the error outline; set when the form has a message about this field. */
  invalid?: boolean;
  name?: string;
}

export function PasswordField({
  id,
  label,
  value,
  onChange,
  autoComplete,
  describedBy,
  invalid = false,
  name,
}: PasswordFieldProps) {
  const [isVisible, setIsVisible] = useState(false);

  return (
    <>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      <div className={invalid ? `${styles.shell} ${styles.shellInvalid}` : styles.shell}>
        <input
          id={id}
          className={styles.input}
          // The only thing the reveal changes. Everything else stays put so the
          // browser keeps treating it as the same password field.
          type={isVisible ? "text" : "password"}
          name={name}
          autoComplete={autoComplete}
          value={value}
          aria-describedby={describedBy}
          onChange={(event) => onChange(event.target.value)}
        />
        <button
          type="button"
          className={styles.reveal}
          // The name is the next action; aria-pressed is the state (IR-07).
          aria-label={isVisible ? strings.common.hidePassword : strings.common.showPassword}
          aria-pressed={isVisible}
          aria-controls={id}
          onClick={() => setIsVisible((visible) => !visible)}
        >
          {isVisible ? <EyeOffIcon /> : <EyeIcon />}
        </button>
      </div>
    </>
  );
}

/* Decorative: the button's `aria-label` is its name, so the glyph is hidden from
   the accessibility tree. `currentColor` keeps both icons on the token palette. */

function EyeIcon() {
  return (
    <svg className={styles.icon} viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <path
        d="M1.6 10S4.7 4.6 10 4.6 18.4 10 18.4 10 15.3 15.4 10 15.4 1.6 10 1.6 10Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <circle cx="10" cy="10" r="2.6" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg className={styles.icon} viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <path
        d="M1.6 10S4.7 4.6 10 4.6 18.4 10 18.4 10 15.3 15.4 10 15.4 1.6 10 1.6 10Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <circle cx="10" cy="10" r="2.6" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <line
        x1="3.2"
        y1="16.8"
        x2="16.8"
        y2="3.2"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
