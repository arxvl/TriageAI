/**
 * The constants and lookups the W-08 screen shares between its panels.
 *
 * Here rather than on a component so each file exports components only, which
 * is what keeps hot reloading working during development.
 */
import type { ComplaintOption, KBEntryStatus } from "../../api/kb";
import { strings } from "../../i18n/strings";

/** The four W-08 tabs, in the order the workflow moves through them (FR-51). */
export const STATUS_TABS: readonly KBEntryStatus[] = [
  "DRAFT",
  "PENDING_REVIEW",
  "ACTIVE",
  "RETIRED",
];

/** A 422's message and the control the server named for it (IR-05). */
export interface ServerFieldError {
  field: string;
  message: string;
}

/**
 * A presenting complaint's display name (FR-10).
 *
 * Falls back to the code while the fixed list is still loading, so a row never
 * renders blank where a complaint belongs.
 */
export function complaintName(code: string | null, complaints: readonly ComplaintOption[]): string {
  if (code === null) {
    return strings.knowledgeBase.notAvailable;
  }
  return complaints.find((option) => option.code === code)?.name ?? code;
}
