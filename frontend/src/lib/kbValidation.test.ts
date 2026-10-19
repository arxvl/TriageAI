/**
 * `lib/kbValidation`: the W-08 editor's own checks (FR-49, FR-50, IR-05).
 *
 * Every bound asserted here mirrors one in the backend's `app/schemas/kb.py`,
 * so a change on the server that is not mirrored fails in this file rather than
 * in the browser. All content is fictitious (CLAUDE.md §9).
 */
import { describe, expect, it } from "vitest";

import {
  ACTIONS_MAX_LINES,
  ACTIONS_MIN_LINES,
  CONTENT_MIN_WORDS,
  actionLines,
  asKBEntryField,
  contentProblem,
  countWords,
  emptyEntryForm,
  firstInvalidField,
  toEntryCreateRequest,
  toEntryUpdateRequest,
  validateEntryForm,
  type KBEntryFormValues,
} from "./kbValidation";

/** A fictitious entry body of exactly `words` words. */
function words(count: number): string {
  return Array.from({ length: count }, (_, index) => `word${index}`).join(" ");
}

function completeForm(overrides: Partial<KBEntryFormValues> = {}): KBEntryFormValues {
  return {
    ...emptyEntryForm("COMPLAINT"),
    title: "Straining or inability to urinate - cats",
    complaintCode: "URINARY_OBSTRUCTION",
    content: words(CONTENT_MIN_WORDS),
    sourceTitle: "Fixture Source Title",
    sourcePublisher: "Fixture Publisher",
    sourceUrl: "https://example.invalid/fixture",
    accessDate: "2026-10-12",
    ...overrides,
  };
}

function actionSetForm(overrides: Partial<KBEntryFormValues> = {}): KBEntryFormValues {
  return completeForm({
    kind: "URGENCY_ACTIONS",
    complaintCode: "",
    urgencyCategory: "ORANGE",
    content: [
      "Alert the veterinarian now and move the patient to the treatment area.",
      "Recheck breathing effort every few minutes while waiting.",
      "Keep handling to a minimum to limit stress.",
    ].join("\n"),
    ...overrides,
  });
}

describe("countWords and actionLines", () => {
  it("counts words the way the server splits them", () => {
    expect(countWords("  two   words  ")).toBe(2);
    expect(countWords("")).toBe(0);
    expect(countWords("\n\n")).toBe(0);
  });

  it("counts an action set's non-empty lines only", () => {
    expect(actionLines("one\n\n  two  \n")).toEqual(["one", "two"]);
  });
});

describe("contentProblem", () => {
  it("accepts a clinical entry inside the word range", () => {
    expect(contentProblem(words(CONTENT_MIN_WORDS), "COMPLAINT")).toBeNull();
  });

  it("refuses a clinical entry under the floor, naming the actual count", () => {
    const problem = contentProblem(words(CONTENT_MIN_WORDS - 1), "COMPLAINT");
    expect(problem).not.toBeNull();
    expect(problem).toContain("49");
    expect(problem).toContain("50");
  });

  it("refuses a clinical entry over the ceiling", () => {
    expect(contentProblem(words(1_501), "COMPLAINT")).not.toBeNull();
  });

  it("measures a baseline action set in lines, not words", () => {
    // Three short lines: far under the 50-word floor, and valid (P08 §8.2b).
    const threeLines = ["Escalate now.", "Monitor breathing.", "Prepare oxygen."].join("\n");
    expect(contentProblem(threeLines, "URGENCY_ACTIONS")).toBeNull();
    expect(contentProblem(threeLines, "COMPLAINT")).not.toBeNull();
  });

  it("refuses too few and too many actions", () => {
    const tooFew = Array.from({ length: ACTIONS_MIN_LINES - 1 }, () => "Escalate now.").join("\n");
    const tooMany = Array.from({ length: ACTIONS_MAX_LINES + 1 }, () => "Escalate now.").join("\n");
    expect(contentProblem(tooFew, "URGENCY_ACTIONS")).not.toBeNull();
    expect(contentProblem(tooMany, "URGENCY_ACTIONS")).not.toBeNull();
  });
});

describe("validateEntryForm", () => {
  it("passes a complete clinical entry", () => {
    expect(validateEntryForm(completeForm())).toEqual({});
  });

  it("passes a complete baseline action set", () => {
    expect(validateEntryForm(actionSetForm())).toEqual({});
  });

  it.each([
    ["source_title", "sourceTitle"],
    ["source_publisher", "sourcePublisher"],
    ["source_url", "sourceUrl"],
    ["access_date", "accessDate"],
  ] as const)("requires %s (FR-50)", (field, key) => {
    const errors = validateEntryForm(completeForm({ [key]: "" }));
    expect(errors[field]).toBeDefined();
  });

  it("requires a title", () => {
    expect(validateEntryForm(completeForm({ title: "   " })).title).toBeDefined();
  });

  it("requires a complaint on a clinical entry and a category on an action set", () => {
    expect(validateEntryForm(completeForm({ complaintCode: "" })).complaint_code).toBeDefined();
    expect(
      validateEntryForm(actionSetForm({ urgencyCategory: "" })).urgency_category,
    ).toBeDefined();
  });

  it("does not ask a clinical entry for a category, or an action set for a complaint", () => {
    expect(validateEntryForm(completeForm()).urgency_category).toBeUndefined();
    expect(validateEntryForm(actionSetForm()).complaint_code).toBeUndefined();
  });

  it("requires at least one species", () => {
    expect(validateEntryForm(completeForm({ species: [] })).species).toBeDefined();
  });

  it("reports every problem at once, not only the first", () => {
    const errors = validateEntryForm(emptyEntryForm("COMPLAINT"));
    expect(Object.keys(errors).length).toBeGreaterThan(4);
  });
});

describe("firstInvalidField", () => {
  it("names the first problem in the order the editor lays the fields out", () => {
    const errors = validateEntryForm(completeForm({ title: "", sourceUrl: "" }));
    expect(firstInvalidField(errors)).toBe("title");
  });

  it("is null for a valid form", () => {
    expect(firstInvalidField({})).toBeNull();
  });
});

describe("asKBEntryField", () => {
  it("accepts a field this form has and refuses anything else", () => {
    expect(asKBEntryField("content")).toBe("content");
    expect(asKBEntryField("description")).toBeNull();
    expect(asKBEntryField(null)).toBeNull();
  });
});

describe("request bodies", () => {
  it("sends the complaint and the rules for a clinical entry, and no category", () => {
    const body = toEntryCreateRequest(completeForm(), ["MALE_CAT_NO_URINE"]);

    expect(body.kind).toBe("COMPLAINT");
    expect(body.complaint_code).toBe("URINARY_OBSTRUCTION");
    expect(body.red_flag_codes).toEqual(["MALE_CAT_NO_URINE"]);
    expect(body.urgency_category).toBeUndefined();
  });

  it("sends the category for an action set, and neither complaint nor rules", () => {
    const body = toEntryCreateRequest(actionSetForm(), ["MALE_CAT_NO_URINE"]);

    expect(body.urgency_category).toBe("ORANGE");
    expect(body.complaint_code).toBeUndefined();
    expect(body.red_flag_codes).toBeUndefined();
  });

  it("trims the text it sends", () => {
    const body = toEntryCreateRequest(completeForm({ title: "  Padded title  " }));
    expect(body.title).toBe("Padded title");
  });

  it("leaves `kind` out of an edit: an entry never changes kind", () => {
    expect("kind" in toEntryUpdateRequest(completeForm())).toBe(false);
  });
});
