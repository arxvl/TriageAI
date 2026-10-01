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
