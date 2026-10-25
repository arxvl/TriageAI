/**
 * The `/exports` endpoints: de-identified case and audit files (FR-47, BR-08).
 *
 * Administrator only on the server. Each call returns the file as a blob for
 * `saveBlob`; the server audits every download (`DATA_EXPORTED`, SR-12). A date
 * is a calendar day in Asia/Manila, sent as `YYYY-MM-DD`; an empty one is left
 * out so that side of the range is open.
 */
import { apiFetchBlob } from "./client";

export type ExportKind = "cases" | "audit";

export interface ExportRange {
  /** `YYYY-MM-DD`, or "" for no lower limit. */
  from: string;
  /** `YYYY-MM-DD`, or "" for no upper limit. */
  to: string;
}

export function exportPath(kind: ExportKind, range: ExportRange): string {
  const params = new URLSearchParams();
  if (range.from !== "") {
    params.set("from", range.from);
  }
  if (range.to !== "") {
    params.set("to", range.to);
  }
  if (kind === "cases") {
    params.set("format", "csv");
  }
  const query = params.toString();
  return query === "" ? `/exports/${kind}` : `/exports/${kind}?${query}`;
}

export function downloadExport(kind: ExportKind, range: ExportRange): Promise<Blob> {
  return apiFetchBlob(exportPath(kind, range));
}
