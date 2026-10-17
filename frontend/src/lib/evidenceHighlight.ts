/**
 * Turn evidence spans into the segments W-04's panel 1 highlights (FR-13).
 *
 * The extraction stores, for each value it read, the exact substring of the
 * **de-identified** text it read it from (`EvidenceSpan`). 6.1 resolves those to
 * character offsets server-side by exact substring search, so the only work left
 * here is laying them over the string: the panel cannot nest elements inside one
 * another, so overlapping spans have to become one flat left-to-right list of
 * marked and unmarked pieces.
 *
 * Three rules, all of them about not lying to the reviewer:
 *
 * 1. **A span the server could not place is dropped**, not guessed at. `found:
 *    false` means the stored substring no longer matches, and a highlight in
 *    roughly the right area would be a claim the data does not support. The
 *    panel lists those spans separately as quoted text instead, which is what
 *    `unmatchedSpans` is for.
 * 2. **Overlapping spans merge into one mark** carrying both field names, rather
 *    than producing two marks that disagree about where one ends.
 * 3. **An offset outside the string is ignored.** It should not happen — the
 *    offsets and the text come from the same response — but a highlight is
 *    decoration, and decoration must never be what makes a case unreadable.
 */
import type { EvidenceSpan } from "../api/cases";

/** One run of text, either plain or highlighted. */
export interface HighlightSegment {
  text: string;
  /** The extraction fields whose evidence this run is. Empty for plain text. */
  fields: readonly string[];
}

/**
 * Split `text` into plain and highlighted runs.
 *
 * Always returns the whole string: concatenating every `text` gives back the
 * input, so nothing can be lost to a highlighting bug. An empty input gives an
 * empty list, which renders as nothing.
 */
export function highlightSegments(
  text: string,
  spans: readonly EvidenceSpan[],
): HighlightSegment[] {
  const ranges = usableRanges(text, spans);
  if (ranges.length === 0) {
    return text === "" ? [] : [{ text, fields: [] }];
  }

  const segments: HighlightSegment[] = [];
  let cursor = 0;

  for (const range of ranges) {
    if (range.start > cursor) {
      segments.push({ text: text.slice(cursor, range.start), fields: [] });
    }
    segments.push({ text: text.slice(range.start, range.end), fields: range.fields });
    cursor = range.end;
  }

  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), fields: [] });
  }

  return segments;
}

/** The spans the server could not place, in the order the extraction stored them. */
export function unmatchedSpans(spans: readonly EvidenceSpan[]): EvidenceSpan[] {
  return spans.filter((span) => !span.found);
}

interface Range {
  start: number;
  end: number;
  fields: string[];
}

/**
 * The placeable spans as non-overlapping ranges, left to right.
 *
 * Touching ranges (`end === start`) are left as two marks: they are adjacent,
 * not overlapping, and merging them would attribute one field's evidence to the
 * other's words.
 */
function usableRanges(text: string, spans: readonly EvidenceSpan[]): Range[] {
  const placed = spans
    .filter(
      (span): span is EvidenceSpan & { start: number; end: number } =>
        span.found &&
        span.start !== null &&
        span.end !== null &&
        span.start >= 0 &&
        span.end <= text.length &&
        span.start < span.end,
    )
    .map((span) => ({ start: span.start, end: span.end, fields: [span.field] }))
    .sort((left, right) => left.start - right.start || left.end - right.end);

  const merged: Range[] = [];

  for (const range of placed) {
    const previous = merged.at(-1);
    if (previous !== undefined && range.start < previous.end) {
      previous.end = Math.max(previous.end, range.end);
      if (!previous.fields.includes(range.fields[0])) {
        previous.fields.push(range.fields[0]);
      }
      continue;
    }
    merged.push({ ...range, fields: [...range.fields] });
  }

  return merged;
}
