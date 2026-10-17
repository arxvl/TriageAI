import { describe, expect, it } from "vitest";

import type { EvidenceSpan } from "../api/cases";
import { highlightSegments, unmatchedSpans } from "./evidenceHighlight";

/** Fictitious, as every fixture in this project is (CLAUDE.md §9). */
const TEXT = "Since this morning he keeps going to the litter box and cries.";

function span(overrides: Partial<EvidenceSpan> = {}): EvidenceSpan {
  return { field: "onset_duration", text: "", start: null, end: null, found: false, ...overrides };
}

/** The offsets of `fragment` in `TEXT`, so a fixture cannot count wrong. */
function at(field: string, fragment: string): EvidenceSpan {
  const start = TEXT.indexOf(fragment);
  expect(start).toBeGreaterThanOrEqual(0);
  return span({ field, text: fragment, start, end: start + fragment.length, found: true });
}

describe("highlightSegments", () => {
  it("returns the whole text as one plain run when there are no spans", () => {
    expect(highlightSegments(TEXT, [])).toEqual([{ text: TEXT, fields: [] }]);
  });

  it("returns nothing for an empty text", () => {
    expect(highlightSegments("", [])).toEqual([]);
  });

  it("marks each span and leaves the text between them plain", () => {
    const segments = highlightSegments(TEXT, [
      at("onset_duration", "Since this morning"),
      at("associated_signs", "cries"),
    ]);

    expect(segments).toEqual([
      { text: "Since this morning", fields: ["onset_duration"] },
      { text: " he keeps going to the litter box and ", fields: [] },
      { text: "cries", fields: ["associated_signs"] },
      { text: ".", fields: [] },
    ]);
  });

  it("gives back the input exactly, whatever the spans", () => {
    const segments = highlightSegments(TEXT, [
      at("associated_signs", "cries"),
      at("onset_duration", "this morning"),
    ]);

    expect(segments.map((segment) => segment.text).join("")).toBe(TEXT);
  });

  // The panel cannot nest one mark inside another, so two overlapping spans
  // become a single run that names both fields.
  it("merges overlapping spans into one run carrying both fields", () => {
    const segments = highlightSegments(TEXT, [
      at("onset_duration", "Since this morning"),
      at("frequency_severity", "morning he keeps"),
    ]);

    expect(segments[0]).toEqual({
      text: "Since this morning he keeps",
      fields: ["onset_duration", "frequency_severity"],
    });
  });

  it("keeps two touching spans apart", () => {
    const segments = highlightSegments("abcd", [
      span({ field: "a", start: 0, end: 2, found: true }),
      span({ field: "b", start: 2, end: 4, found: true }),
    ]);

    expect(segments).toEqual([
      { text: "ab", fields: ["a"] },
      { text: "cd", fields: ["b"] },
    ]);
  });

  it("names a field once when two of its spans overlap", () => {
    const segments = highlightSegments("abcdef", [
      span({ field: "a", start: 0, end: 4, found: true }),
      span({ field: "a", start: 2, end: 6, found: true }),
    ]);

    expect(segments).toEqual([{ text: "abcdef", fields: ["a"] }]);
  });

  // `found: false` means the stored substring no longer matches the text. A
  // highlight in roughly the right place would claim more than the data says.
  it("ignores a span the server could not place", () => {
    const segments = highlightSegments(TEXT, [
      span({ field: "onset_duration", text: "last night", found: false }),
    ]);

    expect(segments).toEqual([{ text: TEXT, fields: [] }]);
  });

  it("ignores offsets outside the text rather than throwing", () => {
    const segments = highlightSegments("abc", [
      span({ field: "a", start: 1, end: 99, found: true }),
      span({ field: "b", start: -4, end: 2, found: true }),
      span({ field: "c", start: 2, end: 2, found: true }),
    ]);

    expect(segments).toEqual([{ text: "abc", fields: [] }]);
  });
});

describe("unmatchedSpans", () => {
  it("returns the unplaceable spans in their stored order", () => {
    const missing = span({ field: "relevant_history", text: "fine last night" });

    expect(unmatchedSpans([at("onset_duration", "cries"), missing])).toEqual([missing]);
  });
});
