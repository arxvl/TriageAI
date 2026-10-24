/**
 * The state behind W-04's suggested-action checklist, and what it sends (FR-76).
 *
 * The screen shows two layers that the API keeps apart — `baseline`, read from
 * the knowledge base for the case's category, and `tailored`, written by the
 * model and already filtered by the deterministic validator (FR-74) — and the
 * reviewer works on both as one list. This module is the translation: rows in,
 * `FinalActionInput[]` out, with the status each row earned.
 *
 * The statuses are the record of what the reviewer did, so they are derived from
 * the row rather than chosen by the UI:
 *
 * | the reviewer                   | status    |
 * |--------------------------------|-----------|
 * | left the row alone             | `KEPT`    |
 * | changed its wording            | `EDITED`  |
 * | unticked it                    | `REMOVED` |
 * | typed a new one                | `ADDED`   |
 *
 * An unticked row is still sent. FR-76 wants the list the reviewer was shown and
 * what they did to it, and a row that silently vanished would leave "the model
 * suggested this and a reviewer rejected it" unrecorded — which is the single
 * most useful thing in the whole record (ADR-18 §4).
 *
 * `suggestion_id` is never set: `SuggestedActionOut` carries no id, so this
 * screen has nothing to put there. It is left out of the object entirely rather
 * than sent as null, the same rule the intake form follows.
 */
import type { ActionSource, FinalActionInput, SuggestedAction } from "../api/cases";

/** One row of the checklist, as the screen holds it. */
export interface ChecklistRow {
  /** Stable within one render of one case; not an API id. */
  key: string;
  /** The current wording, which is `originalText` until the reviewer edits it. */
  text: string;
  /** What the row said when it arrived. Null for a row the reviewer wrote. */
  originalText: string | null;
  source: ActionSource;
  /** Ticked means "keep". Unticked rows are recorded as `REMOVED`. */
  isKept: boolean;
  /** The `references[].rank` values supporting it; empty for baseline and added rows. */
  citedRanks: readonly number[];
}

/**
 * The checklist as the screen first shows it: baseline rows, then tailored ones.
 *
 * Everything starts ticked. The reviewer's job is to take things off a list that
 * reflects the case, not to build one from nothing.
 *
 * **Outdated tailored rows are left out.** They were suggested for a category
 * the case no longer has (FR-78), so they must never be sent as `KEPT`: the
 * screen shows them separately, greyed, and the reviewer asks for new ones
 * instead of approving these.
 */
export function initialChecklist(
  baseline: readonly string[],
  tailored: readonly SuggestedAction[],
): ChecklistRow[] {
  const rows: ChecklistRow[] = baseline.map((text, index) => ({
    key: `baseline-${index}`,
    text,
    originalText: text,
    source: "BASELINE",
    isKept: true,
    citedRanks: [],
  }));

  tailored.forEach((action, index) => {
    if (action.is_outdated) {
      return;
    }
    rows.push({
      key: `tailored-${index}`,
      text: action.text,
      originalText: action.text,
      source: action.source,
      isKept: true,
      citedRanks: action.cited_ranks,
    });
  });

  return rows;
}

/** A row for an action the reviewer typed. `key` must be unique in the list. */
export function addedRow(key: string, text: string): ChecklistRow {
  return { key, text, originalText: null, source: "REVIEWER", isKept: true, citedRanks: [] };
}

/** What one row did, as the audit will read it. */
export function statusOf(row: ChecklistRow): FinalActionInput["status"] {
  if (!row.isKept) {
    return "REMOVED";
  }
  if (row.originalText === null) {
    return "ADDED";
  }
  return row.text === row.originalText ? "KEPT" : "EDITED";
}

/**
 * The checklist as the decision's `final_actions`, in the order on screen.
 *
 * Rows whose text is blank after trimming are left out: a row the reviewer
 * emptied is a row they did not mean to send, and an empty action would fail the
 * server's own validation anyway.
 */
export function toFinalActions(rows: readonly ChecklistRow[]): FinalActionInput[] {
  return rows
    .filter((row) => row.text.trim() !== "")
    .map((row) => ({ text: row.text.trim(), source: row.source, status: statusOf(row) }));
}

/** How many actions the decision will record as kept, edited, or added. */
export function keptCount(rows: readonly ChecklistRow[]): number {
  return rows.filter((row) => row.isKept && row.text.trim() !== "").length;
}
