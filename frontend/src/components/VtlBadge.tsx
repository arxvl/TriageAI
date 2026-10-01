/**
 * The VTL urgency badge (IR-03, FR-20, ADR-15).
 *
 * One rule, and it is the reason this is a component rather than a CSS class:
 * **a badge never carries meaning in colour alone.** Every badge renders the
 * category name *and* its target waiting time as text, so it still reads on a
 * monochrome screen, in a screenshot, and to someone who cannot tell red from
 * green. `VtlBadge.test.tsx` asserts that for every category; a badge that
 * showed colour only would fail it.
 *
 * Three cases beyond the five categories:
 *
 * - `MANUAL` is not a category. It marks a case a reviewer must triage by hand,
 *   which has no category and therefore no target time — a dashed outline rather
 *   than a fill, as W-02 draws it.
 * - `null` is a case still in the pipeline. It shows the column's em dash, with
 *   the reason spelled out for a screen reader (NFR-21).
 * - YELLOW is the one fill light enough to need dark text for 4.5:1 (NFR-21).
 */
import { strings } from "../i18n/strings";
import type { QueueBadgeCategory } from "../lib/vtl";
import styles from "./VtlBadge.module.css";

const copy = strings.vtl;

/** `sm` is the counter tiles and table rows; `md` is a case header (P06). */
type BadgeSize = "sm" | "md";

const CATEGORY_CLASS: Record<QueueBadgeCategory, string> = {
  RED: styles.red,
  ORANGE: styles.orange,
  YELLOW: styles.yellow,
  GREEN: styles.green,
  BLUE: styles.blue,
  MANUAL: styles.manual,
};

export function VtlBadge({
  category,
  size = "sm",
}: {
  category: QueueBadgeCategory | null;
  size?: BadgeSize;
}) {
  if (category === null) {
    return (
      <span className={styles.none}>
        {strings.queue.notAvailable}
        <span className="visuallyHidden">{copy.noCategory}</span>
      </span>
    );
  }

  const className = [styles.badge, CATEGORY_CLASS[category], size === "md" ? styles.md : null]
    .filter((name) => name !== null)
    .join(" ");

  return (
    <span className={className}>
      {copy.codes[category]}
      {/* MANUAL has no target waiting time to show, because it has no category. */}
      {category !== "MANUAL" && <span className={styles.target}>{copy.targets[category]}</span>}
    </span>
  );
}
