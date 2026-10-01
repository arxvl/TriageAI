/**
 * Timestamps are stored and sent in UTC; the clinic reads them in local time
 * (CLAUDE.md §7).
 */

export const DISPLAY_TIME_ZONE: string = import.meta.env.VITE_TZ_DISPLAY ?? "Asia/Manila";

/** An ISO-8601 instant anywhere inside a sentence, with optional fractional seconds. */
const ISO_TIMESTAMP = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/;

/**
 * Pull an ISO-8601 instant out of prose.
 *
 * The 423 lockout response carries the unlock time inside its message rather
 * than as a field, so the login screen has to read it back out.
 */
export function extractIsoTimestamp(text: string): string | null {
  return text.match(ISO_TIMESTAMP)?.[0] ?? null;
}

/** "9:15 AM" in the clinic's timezone, or null if the input is not a valid instant. */
export function formatDisplayTime(iso: string): string | null {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) {
    return null;
  }

  return new Intl.DateTimeFormat("en-PH", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: DISPLAY_TIME_ZONE,
  }).format(instant);
}

/**
 * "09:42" in the clinic's timezone, or null if the input is not a valid instant.
 *
 * The Triage Queue's "Arrived" column (W-02). 24-hour and zero-padded, because
 * the column is scanned down rather than read: two rows minutes apart should
 * differ in one place, not in an AM/PM suffix as well. `hourCycle` rather than
 * `hour12: false`, which can render midnight as "24:00".
 */
export function formatArrivalTime(iso: string): string | null {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) {
    return null;
  }

  return new Intl.DateTimeFormat("en-PH", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: DISPLAY_TIME_ZONE,
  }).format(instant);
}

/** Today's date in the clinic's timezone as `YYYY-MM-DD`, for a date filter. */
export function clinicToday(now: Date = new Date()): string {
  // "en-CA" is the short way to an ISO calendar date in a given timezone.
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: DISPLAY_TIME_ZONE,
  }).format(now);
}

/** `YYYY-MM-DD` for `days` before today in the clinic's timezone. */
export function clinicDaysAgo(days: number, now: Date = new Date()): string {
  return clinicToday(new Date(now.getTime() - days * 24 * 60 * 60 * 1000));
}
