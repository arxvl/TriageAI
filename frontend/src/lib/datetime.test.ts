/**
 * Timestamps are stored in UTC and read in the clinic's timezone (CLAUDE.md §7),
 * so these tests are all about the +08:00 shift: the queue's "Arrived" column and
 * the date filter both have to agree with the working day staff are standing in.
 */
import { describe, expect, it } from "vitest";

import { clinicDaysAgo, clinicToday, formatArrivalTime, formatDisplayTime } from "./datetime";

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
