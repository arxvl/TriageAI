/**
 * The five-row urgency picker shared by W-05 and W-06 (IR-03, NFR-21).
 *
 * Both wireframes draw the same control: one full-width row per category,
 * carrying a badge, the category's name, and a line of text that differs between
 * the two screens — the target waiting time on W-05, the example discriminators
 * on W-06. So the row's *content* is the caller's (`note`, `hint`) and only the
 * structure is here.
 *
 * Native `<input type="radio">` inside a `<fieldset>`, not a custom widget and
 * not `SegmentedControl`. Two reasons:
 *
 * 1. **The platform already does the hard part.** A radio group is one tab stop
 *    with arrow-key movement between the options, and screen readers announce
 *    "3 of 5" without being told. Rebuilding that on `<div role="radio">` is how
 *    keyboard access gets lost (P06 §6.2 task 8).
 * 2. `SegmentedControl` is a horizontal strip of short labels. It has nowhere to
 *    put a badge, a target time or a sentence of discriminators, which is most of
 *    what these rows are for.
 *
 * Colour never carries meaning alone: every row names its category and says
 * something about it in words, so the control reads the same in greyscale and to
 * a colour-blind reviewer (IR-03, NFR-21).
 */
import type { VTLCategory } from "../../api/cases";
import { VtlBadge } from "../../components/VtlBadge";
import { strings } from "../../i18n/strings";
import { URGENCY_ORDER } from "../../lib/vtl";
import styles from "./CaseReview.module.css";

export function CategoryOptions({
  name,
  legend,
  value,
  disabled = false,
  note,
  hint,
  onChange,
}: {
  /** The radio group's name; unique on the page. */
  name: string;
  legend: string;
  value: VTLCategory | null;
  disabled?: boolean;
  /** The line under the category's name. W-05 passes the target time, W-06 the discriminators. */
  note: (category: VTLCategory) => string;
  /** The right-hand marker: "current" on the recommendation's row, "Up-triage" on the chosen one. */
  hint?: (category: VTLCategory) => string | null;
  onChange: (category: VTLCategory) => void;
}) {
  return (
    <fieldset className={styles.optionList}>
      <legend className={styles.sectionTitle}>{legend}</legend>

      {URGENCY_ORDER.map((category) => {
        const marker = hint?.(category) ?? null;
        const isSelected = value === category;

        return (
          <label
            key={category}
            className={isSelected ? `${styles.option} ${styles.optionSelected}` : styles.option}
          >
            <input
              type="radio"
              name={name}
              value={category}
              checked={isSelected}
              disabled={disabled}
              onChange={() => onChange(category)}
            />
            <VtlBadge category={category} size="sm" />
            <span className={styles.optionNote}>
              <b>{strings.vtl.labels[category]}</b> · {note(category)}
            </span>
            {marker !== null && <span className={styles.optionHint}>{marker}</span>}
          </label>
        );
      })}
    </fieldset>
  );
}
