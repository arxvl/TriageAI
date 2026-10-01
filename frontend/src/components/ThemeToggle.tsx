/**
 * The light/dark control (W-01 sign-in card, IR-02 header).
 *
 * A real radio group, like `SegmentedControl`: one tab stop, arrow keys between
 * the three choices, and "2 of 3" announced for free (NFR-21, IR-07). It is its
 * own component rather than a use of `SegmentedControl` because this one is
 * header-sized — icon plus label at the small type scale — and carries a hidden
 * legend instead of a visible one.
 *
 * The icons are decorative: each option keeps its word, so the control never
 * relies on a glyph alone.
 */
import type { ReactElement } from "react";

import { useTheme } from "../hooks/useTheme";
import { strings } from "../i18n/strings";
import { THEME_PREFERENCES, type ThemePreference } from "../lib/theme";
import styles from "./ThemeToggle.module.css";

const LABELS: Record<ThemePreference, string> = {
  system: strings.theme.system,
  light: strings.theme.light,
  dark: strings.theme.dark,
};

const ICONS: Record<ThemePreference, () => ReactElement> = {
  system: SystemIcon,
  light: SunIcon,
  dark: MoonIcon,
};

export function ThemeToggle() {
  const { preference, resolvedTheme, setPreference } = useTheme();

  return (
    <fieldset className={styles.group}>
      <legend className="visuallyHidden">{strings.theme.label}</legend>
      <div className={styles.track}>
        {THEME_PREFERENCES.map((option) => {
          const Icon = ICONS[option];
          return (
            <label
              key={option}
              className={
                option === preference ? `${styles.option} ${styles.selected}` : styles.option
              }
              // Only "System" has something extra to say, and only about itself.
              title={
                option === "system"
                  ? strings.theme.systemHint.replace("{theme}", LABELS[resolvedTheme])
                  : undefined
              }
            >
              <input
                className={styles.radio}
                type="radio"
                name="theme"
                value={option}
                checked={option === preference}
                onChange={() => setPreference(option)}
              />
              <Icon />
              {LABELS[option]}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/* The three glyphs. `currentColor` keeps them on the token palette in both
   themes, and `aria-hidden` keeps them out of the accessible name. */

function SunIcon() {
  return (
    <svg className={styles.icon} viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="8" r="3.2" fill="currentColor" />
      <g stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
        <line x1="8" y1="0.8" x2="8" y2="2.6" />
        <line x1="8" y1="13.4" x2="8" y2="15.2" />
        <line x1="0.8" y1="8" x2="2.6" y2="8" />
        <line x1="13.4" y1="8" x2="15.2" y2="8" />
        <line x1="2.9" y1="2.9" x2="4.2" y2="4.2" />
        <line x1="11.8" y1="11.8" x2="13.1" y2="13.1" />
        <line x1="2.9" y1="13.1" x2="4.2" y2="11.8" />
        <line x1="11.8" y1="4.2" x2="13.1" y2="2.9" />
      </g>
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg className={styles.icon} viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d="M10 1.6A6.4 6.4 0 1 0 14.4 9 5.2 5.2 0 0 1 10 1.6Z" fill="currentColor" />
    </svg>
  );
}

function SystemIcon() {
  return (
    <svg className={styles.icon} viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <rect
        x="1.3"
        y="2.4"
        width="13.4"
        height="9"
        rx="1.4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <line
        x1="5.2"
        y1="13.8"
        x2="10.8"
        y2="13.8"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}
