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

/**
 * "09:36:14" in the clinic's timezone, or null if the input is not a valid instant.
 *
 * Seconds matter in exactly two places, and both are provenance rather than
 * clinical: W-04's configuration footnote, which records when a recommendation
 * was generated (FR-26), and the audit timeline (FR-45).
 */
export function formatPreciseTime(iso: string): string | null {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) {
    return null;
  }

  return new Intl.DateTimeFormat("en-PH", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
    timeZone: DISPLAY_TIME_ZONE,
  }).format(instant);
}

/**
 * "17 Oct 2026" in the clinic's timezone, or null if the input is not a valid instant.
 *
 * The audit timeline's day headings. A case that arrives one evening and is closed
 * the next morning would otherwise show a closing time earlier than its arrival
 * time, so the day is named whenever it changes (FR-45).
 */
export function formatDisplayDate(iso: string): string | null {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) {
    return null;
  }

  // "en-GB" and not "en-PH", which renders "Oct 1, 2026": the clinic writes a
  // date day first, as the SRS and the wireframes do ("24 Sep 2026").
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: DISPLAY_TIME_ZONE,
  }).format(instant);
}

/**
 * "12 Oct 2026" from a plain calendar date, `YYYY-MM-DD`.
 *
 * Not the same as `formatDisplayDate`, which converts an instant into the
 * clinic's day. A knowledge-base entry's access date is a date and nothing more
 * (FR-50), so it is read in UTC and never shifted by a timezone — a source
 * accessed on the 12th was accessed on the 12th wherever it is read.
 */
export function formatCalendarDate(date: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return null;
  }
  const instant = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(instant.getTime())) {
    return null;
  }

  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
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

/**
 * A duration in seconds as W-07 writes it: "10 s", "8 min 28 s", "1 h 2 min".
 *
 * The audit timeline's two FR-46 intervals. The API sends them as floats, and the
 * largest unit is dropped from the tail rather than carried in decimals: the
 * figure is there to show whether the system or the reviewer took seconds or
 * minutes, and a tenth of a second past the first minute says nothing.
 *
 * Negative input is clamped to zero. Two clocks never disagree here — the server
 * computes both intervals from the same stored timestamps — but a stray "-3 s"
 * would read as a defect in the audit trail, which is the one thing it may not do.
 */
export function formatElapsed(seconds: number): string {
  if (!Number.isFinite(seconds)) {
    return "";
  }

  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;

  if (hours > 0) {
    return `${hours} h ${minutes} min`;
  }
  if (minutes > 0) {
    return `${minutes} min ${rest} s`;
  }
  return `${total} s`;
}
