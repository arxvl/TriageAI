import { describe, expect, it } from "vitest";

import type { CaseQueueItem } from "../api/cases";
import { badgeCategoryOf, isOverdueForDisplay, TARGET_MINUTES, waitProgressPercent } from "./vtl";

function row(overrides: Partial<CaseQueueItem> = {}): Pick<CaseQueueItem, "category" | "status"> {
  return { category: null, status: "AWAITING_REVIEW", ...overrides };
}

describe("TARGET_MINUTES", () => {
  it("matches CLAUDE.md §6 and the backend's core/vtl.py", () => {
    expect(TARGET_MINUTES).toEqual({ RED: 0, ORANGE: 15, YELLOW: 60, GREEN: 120, BLUE: 240 });
  });
});

describe("badgeCategoryOf", () => {
  it("uses the category the server resolved for the row", () => {
    expect(badgeCategoryOf(row({ category: "ORANGE" }))).toBe("ORANGE");
  });

  it("shows MANUAL for a case waiting to be triaged by hand", () => {
    expect(badgeCategoryOf(row({ status: "MANUAL_TRIAGE_REQUIRED" }))).toBe("MANUAL");
  });

  it("shows nothing for a case still in the pipeline", () => {
    expect(badgeCategoryOf(row({ status: "PROCESSING" }))).toBeNull();
  });

  it("prefers the category over MANUAL if a case somehow has both", () => {
    expect(badgeCategoryOf(row({ category: "RED", status: "MANUAL_TRIAGE_REQUIRED" }))).toBe("RED");
  });
});

describe("isOverdueForDisplay", () => {
  // The point of the function: RED's target is 0, so the API reports every RED
  // case as overdue a minute after arrival. The queue does not repeat that.
  it("does not call a RED case overdue, even when the API does", () => {
    expect(isOverdueForDisplay("RED", true)).toBe(false);
  });

  it("calls a case past a real target overdue", () => {
    expect(isOverdueForDisplay("YELLOW", true)).toBe(true);
  });

  it("trusts the server when it says a case is not overdue", () => {
    expect(isOverdueForDisplay("YELLOW", false)).toBe(false);
  });

  it("never calls a case with no category overdue", () => {
    expect(isOverdueForDisplay(null, true)).toBe(false);
  });
});

describe("waitProgressPercent", () => {
  it("is the share of the target that has elapsed", () => {
    expect(waitProgressPercent(6, 15)).toBe(40);
    expect(waitProgressPercent(37, 60)).toBe(62);
  });

  it("stops at 100 once the target has passed", () => {
    expect(waitProgressPercent(64, 60)).toBe(100);
  });

  it("is full for a target of 0, which is past the moment the case arrives", () => {
    expect(waitProgressPercent(1, 0)).toBe(100);
  });

  it("is 0 with no target, where the caller draws no bar at all", () => {
    expect(waitProgressPercent(22, null)).toBe(0);
  });
});
