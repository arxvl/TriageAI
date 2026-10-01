/**
 * The `.seg` control the wireframes draw for a short, exclusive choice (W-03
 * species and intake channel).
 *
 * It is a real radio group — a `<fieldset>` with a `<legend>` and one radio per
 * option — rather than a row of buttons. That is what gives arrow-key movement,
 * a single tab stop and the "2 of 3" announcement for free (NFR-21, IR-07). The
 * radios are visually hidden and the adjacent span carries the look.
 */
import type { ReactNode } from "react";

import styles from "./SegmentedControl.module.css";

interface SegmentedControlProps<T extends string> {
  /** Groups the radios; must be unique on the page. */
  name: string;
  /** The visible group label, e.g. "Species (required)". */
  legend: ReactNode;
  options: readonly { value: T; label: string }[];
  /** The chosen option, or null when nothing is chosen yet. */
  value: T | null;
  onChange: (value: T) => void;
  /** Ids of the notice or error text that explains this group. */
  describedBy?: string;
  invalid?: boolean;
}

export function SegmentedControl<T extends string>({
  name,
  legend,
  options,
  value,
  onChange,
  describedBy,
  invalid = false,
}: SegmentedControlProps<T>) {
  return (
    <fieldset className={styles.group} aria-describedby={describedBy} aria-invalid={invalid}>
      <legend className={styles.legend}>{legend}</legend>
      <div className={invalid ? `${styles.track} ${styles.trackInvalid}` : styles.track}>
        {options.map((option) => (
          <label
            key={option.value}
            className={
              option.value === value ? `${styles.option} ${styles.selected}` : styles.option
            }
          >
            <input
              className={styles.radio}
              type="radio"
              name={name}
              value={option.value}
              checked={option.value === value}
              onChange={() => onChange(option.value)}
            />
            {option.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
