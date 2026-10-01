/**
 * Whether the category on screen is an AI recommendation or a staff decision
 * (FR-36, IR-04, NFR-07).
 *
 * This chip is the Human-in-the-Loop guarantee made visible. A recommendation
 * waiting for review says so in words — "AI recommendation · pending", in a
 * dashed outline that marks every machine-written value in this interface —
 * and only a case with a `StaffDecision` behind it reads as settled. An
 * adjustment names both categories, so the queue shows what the reviewer
 * changed rather than only what they landed on.
 *
 * The chip is driven by `CaseStatus` alone, never by the presence of a category,
 * because a case can carry a recommendation and still be unreviewed — that is
 * the whole point.
 */
import type { CaseStatus, VTLCategory } from "../api/cases";
import { strings } from "../i18n/strings";
import styles from "./StatusChip.module.css";

const copy = strings.statusChip;

interface StatusChipProps {
  status: CaseStatus;
  /** Needed only by ADJUSTED, which names the category the reviewer moved from. */
  recommendedCategory?: VTLCategory | null;
  confirmedCategory?: VTLCategory | null;
}

export function StatusChip({
  status,
  recommendedCategory = null,
  confirmedCategory = null,
}: StatusChipProps) {
  const { text, variant } = describe(status, recommendedCategory, confirmedCategory);
  return <span className={`${styles.chip} ${variant}`}>{text}</span>;
}

function describe(
  status: CaseStatus,
  recommendedCategory: VTLCategory | null,
  confirmedCategory: VTLCategory | null,
): { text: string; variant: string } {
  switch (status) {
    // A case is recorded and then picked up by the worker; from the counter both
    // are simply "being worked on" (ADR-08).
    case "SUBMITTED":
    case "PROCESSING":
      return { text: copy.processing, variant: styles.processing };

    // IR-04. The one state where a category exists and is explicitly not final.
    case "AWAITING_REVIEW":
      return { text: copy.awaitingReview, variant: styles.ai };

    case "MANUAL_TRIAGE_REQUIRED":
      return { text: copy.manualTriageRequired, variant: styles.bad };

    case "CONFIRMED":
      return { text: copy.confirmed, variant: styles.decided };

    case "ADJUSTED":
      return {
        text: adjustedText(recommendedCategory, confirmedCategory),
        variant: styles.decided,
      };

    case "MANUALLY_TRIAGED":
      return { text: copy.manuallyTriaged, variant: styles.decided };

    // Never reached from the Triage Queue, which lists open cases only. Here so
    // the switch is exhaustive and Case History (P07) can reuse the chip.
    case "CLOSED":
      return { text: copy.closed, variant: styles.decided };
  }
}

/**
 * "Adjusted (Yellow → Green)", or plain "Adjusted" if either side is missing.
 *
 * Both sides should always be there on an ADJUSTED case; the fallback exists so
 * a gap in the data reads as a shorter sentence rather than as "Adjusted (→ )".
 */
function adjustedText(from: VTLCategory | null, to: VTLCategory | null): string {
  if (from === null || to === null) {
    return strings.queue.status.ADJUSTED;
  }
  return copy.adjusted
    .replace("{from}", strings.vtl.names[from])
    .replace("{to}", strings.vtl.names[to]);
}
