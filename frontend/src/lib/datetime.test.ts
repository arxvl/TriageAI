/**
 * Timestamps are stored in UTC and read in the clinic's timezone (CLAUDE.md §7),
 * so these tests are all about the +08:00 shift: the queue's "Arrived" column and
 * the date filter both have to agree with the working day staff are standing in.
 */
import { describe, expect, it } from "vitest";

import {
  clinicDaysAgo,
  clinicToday,
  formatArrivalTime,
  formatDisplayDate,
  formatDisplayTime,
  formatElapsed,
} from "./datetime";

describe("formatArrivalTime", () => {
  it("shows a UTC instant in the clinic's timezone", () => {
    expect(formatArrivalTime("2026-10-01T01:42:00Z")).toBe("09:42");
  });

  it("is 24-hour and zero-padded, so the column can be scanned", () => {
    expect(formatArrivalTime("2026-10-01T05:05:00Z")).toBe("13:05");
    expect(formatArrivalTime("2026-10-01T23:00:00Z")).toBe("07:00");
  });

  // "hour12: false" renders this as 24:00 in some locales; "h23" does not.
  it("shows midnight as 00:xx", () => {
    expect(formatArrivalTime("2026-09-30T16:10:00Z")).toBe("00:10");
  });

  it("returns null rather than 'Invalid Date' for something that is not an instant", () => {
    expect(formatArrivalTime("not a timestamp")).toBeNull();
  });
});

describe("clinicToday", () => {
  it("is the clinic's calendar date, not the UTC one", () => {
    // 16:10 UTC is already the next day in Asia/Manila.
    expect(clinicToday(new Date("2026-09-30T16:10:00Z"))).toBe("2026-10-01");
  });

  it("is an ISO calendar date, which is what the API reads", () => {
    expect(clinicToday(new Date("2026-10-01T03:00:00Z"))).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe("clinicDaysAgo", () => {
  it("counts back whole days in the clinic's timezone", () => {
    expect(clinicDaysAgo(6, new Date("2026-10-01T03:00:00Z"))).toBe("2026-09-25");
  });

  it("is today for zero days", () => {
    const now = new Date("2026-10-01T03:00:00Z");
    expect(clinicDaysAgo(0, now)).toBe(clinicToday(now));
  });
});

describe("formatDisplayTime", () => {
  it("still reads as a 12-hour clock, as the login screen shows it", () => {
    expect(formatDisplayTime("2026-10-01T01:42:00Z")).toMatch(/9:42\s?AM/);
  });
});

// The two FR-46 intervals on the audit timeline (W-07).
describe("formatElapsed", () => {
  it("shows seconds alone below a minute, as W-07's first figure does", () => {
    expect(formatElapsed(10)).toBe("10 s");
    expect(formatElapsed(0)).toBe("0 s");
    expect(formatElapsed(59)).toBe("59 s");
  });

  it("shows minutes and seconds, as W-07's second figure does", () => {
    expect(formatElapsed(508)).toBe("8 min 28 s");
    expect(formatElapsed(60)).toBe("1 min 0 s");
  });

  it("drops the seconds past an hour, where they no longer inform", () => {
    expect(formatElapsed(3720)).toBe("1 h 2 min");
    expect(formatElapsed(3600)).toBe("1 h 0 min");
  });

  // The API sends both intervals as floats.
  it("rounds a fractional second rather than printing it", () => {
    expect(formatElapsed(9.62)).toBe("10 s");
    expect(formatElapsed(507.5)).toBe("8 min 28 s");
  });

  it("never reads as a negative or non-finite duration", () => {
    expect(formatElapsed(-3)).toBe("0 s");
    expect(formatElapsed(Number.NaN)).toBe("");
  });
});

// The audit timeline's day headings (W-07).
describe("formatDisplayDate", () => {
  it("names the clinic's day, not UTC's", () => {
    // 23:30 UTC is already the next morning in Manila.
    expect(formatDisplayDate("2026-10-16T23:30:00Z")).toBe("17 Oct 2026");
  });

  it("is null for a value that is not an instant", () => {
    expect(formatDisplayDate("not a date")).toBeNull();
  });
});
