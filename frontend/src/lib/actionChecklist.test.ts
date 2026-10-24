import { describe, expect, it } from "vitest";

import type { SuggestedAction } from "../api/cases";
import {
  addedRow,
  initialChecklist,
  keptCount,
  statusOf,
  toFinalActions,
  type ChecklistRow,
} from "./actionChecklist";

/** Fictitious, as every fixture in this project is (CLAUDE.md §9). */
const BASELINE: readonly string[] = [
  "Alert the veterinarian now and move the patient to the treatment area.",
  "Recheck breathing effort and demeanour every few minutes while waiting.",
];

const TAILORED: readonly SuggestedAction[] = [
  {
    text: "Ask the owner when the cat last passed any urine.",
    cited_ranks: [1],
    source: "AI",
    is_outdated: false,
  },
];

describe("initialChecklist", () => {
  it("lists baseline actions before tailored ones, all ticked", () => {
    const rows = initialChecklist(BASELINE, TAILORED);

    expect(rows.map((row) => row.source)).toEqual(["BASELINE", "BASELINE", "AI"]);
    expect(rows.every((row) => row.isKept)).toBe(true);
    expect(rows.every((row) => row.originalText === row.text)).toBe(true);
  });

  it("carries the citations of a tailored action and none for a baseline one", () => {
    const rows = initialChecklist(BASELINE, TAILORED);

    expect(rows[0].citedRanks).toEqual([]);
    expect(rows[2].citedRanks).toEqual([1]);
  });

  it("gives every row its own key", () => {
    const rows = initialChecklist(BASELINE, TAILORED);

    expect(new Set(rows.map((row) => row.key)).size).toBe(rows.length);
  });

  // FR-78. An outdated row was suggested for another category; if it were in the
  // checklist it would be sent as KEPT and recorded as approved.
  it("leaves out tailored actions suggested for another category", () => {
    const outdated: SuggestedAction = { ...TAILORED[0], is_outdated: true };

    const rows = initialChecklist(BASELINE, [outdated]);

    expect(rows.map((row) => row.source)).toEqual(["BASELINE", "BASELINE"]);
    expect(toFinalActions(rows).map((action) => action.text)).toEqual([...BASELINE]);
  });

  it("is empty when the case has no actions at all", () => {
    expect(initialChecklist([], [])).toEqual([]);
  });
});

describe("statusOf", () => {
  const rows = initialChecklist(BASELINE, TAILORED);

  it("reads an untouched row as kept", () => {
    expect(statusOf(rows[0])).toBe("KEPT");
  });

  it("reads a re-worded row as edited", () => {
    expect(statusOf({ ...rows[0], text: "Alert the veterinarian now." })).toBe("EDITED");
  });

  it("reads an unticked row as removed, even when it was also edited", () => {
    expect(statusOf({ ...rows[0], isKept: false })).toBe("REMOVED");
    expect(statusOf({ ...rows[0], isKept: false, text: "Something else." })).toBe("REMOVED");
  });

  it("reads a row the reviewer wrote as added", () => {
    expect(statusOf(addedRow("added-0", "Keep the carrier covered."))).toBe("ADDED");
  });
});

describe("toFinalActions", () => {
  it("records the whole list in screen order, with a status per row", () => {
    const rows = initialChecklist(BASELINE, TAILORED);
    const edited: ChecklistRow[] = [
      rows[0],
      { ...rows[1], text: "Recheck breathing effort every few minutes." },
      { ...rows[2], isKept: false },
      addedRow("added-0", "Keep the carrier covered and handling to a minimum."),
    ];

    expect(toFinalActions(edited)).toEqual([
      { text: BASELINE[0], source: "BASELINE", status: "KEPT" },
      {
        text: "Recheck breathing effort every few minutes.",
        source: "BASELINE",
        status: "EDITED",
      },
      { text: TAILORED[0].text, source: "AI", status: "REMOVED" },
      {
        text: "Keep the carrier covered and handling to a minimum.",
        source: "REVIEWER",
        status: "ADDED",
      },
    ]);
  });

  // FR-76: the record is what the reviewer was shown *and* what they did to it.
  // A rejected suggestion that simply vanished would lose the useful half.
  it("keeps a removed row in the payload", () => {
    const rows = initialChecklist([], TAILORED).map((row) => ({ ...row, isKept: false }));

    expect(toFinalActions(rows)).toHaveLength(1);
    expect(toFinalActions(rows)[0].status).toBe("REMOVED");
  });

  it("never emits a suggestion id, which this screen has no source for", () => {
    const rows = initialChecklist(BASELINE, TAILORED);

    for (const action of toFinalActions(rows)) {
      expect(action).not.toHaveProperty("suggestion_id");
    }
  });

  it("trims whitespace and drops a row the reviewer emptied", () => {
    const rows = [addedRow("added-0", "  Ask about appetite.  "), addedRow("added-1", "   ")];

    expect(toFinalActions(rows)).toEqual([
      { text: "Ask about appetite.", source: "REVIEWER", status: "ADDED" },
    ]);
  });

  it("sends an empty list when the reviewer removed everything", () => {
    expect(toFinalActions([])).toEqual([]);
  });
});

describe("keptCount", () => {
  it("counts the ticked, non-empty rows", () => {
    const rows = initialChecklist(BASELINE, TAILORED);

    expect(keptCount(rows)).toBe(3);
    expect(keptCount([{ ...rows[0], isKept: false }, rows[1], rows[2]])).toBe(2);
    expect(keptCount([addedRow("added-0", "  ")])).toBe(0);
  });
});
