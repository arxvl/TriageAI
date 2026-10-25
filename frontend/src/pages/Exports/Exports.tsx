/**
 * Exports (FR-47, BR-05, BR-08, SR-12 · UC-16).
 *
 * An administrator's screen: choose a date range and download the two
 * de-identified files. The page never sees a row of either — the file goes from
 * the API to the browser's download — and says on the screen that the data is
 * for academic evaluation only (BR-08).
 *
 * The range is checked here so an inverted one is explained beside the field
 * instead of costing a request; the server checks it again and is the one that
 * refuses (422). Every download is audited by the server, not by this page.
 */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { ApiErrorCode, isApiError } from "../../api/errors";
import { downloadExport, type ExportKind, type ExportRange } from "../../api/exports";
import { useToast } from "../../hooks/useToast";
import { strings } from "../../i18n/strings";
import { saveBlob } from "../../lib/download";
import styles from "./Exports.module.css";

const copy = strings.exports;

const KINDS: readonly ExportKind[] = ["cases", "audit"];

function fill(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => values[key] ?? "");
}

function fileName(kind: ExportKind, range: ExportRange): string {
  const base = fill(copy.fileName, { kind });
  if (range.from === "" && range.to === "") {
    return base;
  }
  // `triageai-cases-export.csv` -> `triageai-cases-export-2026-03-01_2026-03-31.csv`
  return base.replace(/\.csv$/, `-${range.from || "start"}_${range.to || "end"}.csv`);
}

function describeFailure(error: unknown): string {
  if (isApiError(error) && error.code === ApiErrorCode.forbidden) {
    return copy.errors.forbidden;
  }
  if (isApiError(error) && error.code === ApiErrorCode.validationError) {
    return error.message;
  }
  return copy.errors.failed;
}

export function Exports() {
  const { showToast } = useToast();
  const [range, setRange] = useState<ExportRange>({ from: "", to: "" });
  const [failure, setFailure] = useState<string | null>(null);

  const rangeInvalid = range.from !== "" && range.to !== "" && range.from > range.to;

  const download = useMutation({
    mutationFn: async (kind: ExportKind) => {
      const blob = await downloadExport(kind, range);
      saveBlob(blob, fileName(kind, range));
      return kind;
    },
    onSuccess: (kind) => {
      setFailure(null);
      showToast(fill(copy.done, { kind }));
    },
    onError: (error) => setFailure(describeFailure(error)),
  });

  const busyKind = download.isPending ? download.variables : null;

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>{copy.title}</h1>

      <p className={styles.note}>{copy.note}</p>

      <fieldset className={styles.range}>
        <legend className={styles.legend}>{copy.rangeLegend}</legend>
        <div className={styles.rangeRow}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="export-from">
              {copy.fromLabel}
            </label>
            <input
              id="export-from"
              type="date"
              className={styles.input}
              value={range.from}
              onChange={(event) => setRange({ ...range, from: event.target.value })}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="export-to">
              {copy.toLabel}
            </label>
            <input
              id="export-to"
              type="date"
              className={styles.input}
              value={range.to}
              aria-invalid={rangeInvalid}
              aria-describedby={rangeInvalid ? "export-range-error" : undefined}
              onChange={(event) => setRange({ ...range, to: event.target.value })}
            />
          </div>
        </div>
        <p className={styles.help}>{copy.rangeHelp}</p>
        {rangeInvalid ? (
          <p id="export-range-error" className={styles.fieldError}>
            {copy.rangeInvalid}
          </p>
        ) : null}
      </fieldset>

      {failure !== null ? (
        <p className={styles.error} role="alert">
          {failure}
        </p>
      ) : null}

      <div className={styles.cards}>
        {KINDS.map((kind) => (
          <section key={kind} className={styles.card}>
            <h2 className={styles.cardTitle}>{copy[kind].heading}</h2>
            <p className={styles.cardText}>{copy[kind].description}</p>
            <button
              type="button"
              className={styles.primary}
              disabled={rangeInvalid || download.isPending}
              onClick={() => {
                setFailure(null);
                download.mutate(kind);
              }}
            >
              {busyKind === kind ? copy.exporting : copy[kind].button}
            </button>
          </section>
        ))}
      </div>
    </div>
  );
}
