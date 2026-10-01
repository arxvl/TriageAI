/**
 * The Veterinary Triage List numbers, on the client side (CLAUDE.md §6).
 *
 * This is the mirror of `backend/app/core/vtl.py`. The API already sends
 * `target_minutes` and `is_overdue` per row, so nothing here re-derives the
 * queue's meaning — these are the constants the *display* needs: how wide to
 * draw a progress bar, and which badge a row carries when it has no category
 * yet.
 *
 * One rule of its own lives here, `isOverdueForDisplay`. RED's target is 0, so
 * the API reports a RED case as overdue one minute after arrival, which is FR-30
 * read literally. The queue does not repeat that: every RED case would carry the
 * word, and a flag that is always on tells a reviewer nothing. A RED row shows a
 * full bar and the word "Immediate" instead, which is what W-02 draws. The
 * backend's own `is_overdue` docstring leaves this to the screen.
 */
import type { CaseQueueItem, VTLCategory } from "../api/cases";

/** Target waiting time in minutes, per CLAUDE.md §6. */
export const TARGET_MINUTES: Record<VTLCategory, number> = {
  RED: 0,
  ORANGE: 15,
  YELLOW: 60,
  GREEN: 120,
  BLUE: 240,
};

/** Most urgent first. */
export const URGENCY_ORDER: readonly VTLCategory[] = ["RED", "ORANGE", "YELLOW", "GREEN", "BLUE"];

/**
 * What a badge can show.
 *
 * MANUAL is not a VTL category. It is the badge for a case a reviewer has to
 * triage by hand, which by definition has no category.
 */
export type QueueBadgeCategory = VTLCategory | "MANUAL";

/** The row's badge: its category, else MANUAL, else nothing yet (still processing). */
export function badgeCategoryOf(
  item: Pick<CaseQueueItem, "category" | "status">,
): QueueBadgeCategory | null {
  if (item.category !== null) {
    return item.category;
  }
  return item.status === "MANUAL_TRIAGE_REQUIRED" ? "MANUAL" : null;
}

/** Whether the row is tinted and labelled "overdue". See the module docblock. */
export function isOverdueForDisplay(category: VTLCategory | null, isOverdue: boolean): boolean {
  return isOverdue && category !== null && TARGET_MINUTES[category] > 0;
}

/**
 * How full to draw the waiting bar, 0–100.
 *
 * A category with a target of 0 (RED) is always full: the case is already past
 * its target the moment it arrives. A case with no target has no bar at all, so
 * the caller checks `targetMinutes` before drawing one; 0 here is only a safe
 * value, not a width anyone shows.
 */
export function waitProgressPercent(waitingMinutes: number, targetMinutes: number | null): number {
  if (targetMinutes === null) {
    return 0;
  }
  if (targetMinutes === 0) {
    return 100;
  }
  return Math.min(100, Math.max(0, Math.round((waitingMinutes / targetMinutes) * 100)));
}
