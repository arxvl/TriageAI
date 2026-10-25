/**
 * W-10 Evaluation Console (FR-64..FR-69, NFR-01, NFR-14, NFR-16, NFR-17, BR-05 ·
 * UC-15).
 *
 * An administrator's screen: pick a vignette set, start a run, and read the
 * metrics against the SRS targets. Four behaviours matter more than the layout:
 *
 * - **Mock numbers are labelled.** When the selected run used only mock stages
 *   the page carries a persistent "MOCK MODE" banner, so mock results are never
 *   read as model results (ADR-17). The API says so in `fully_mocked`; the
 *   frontend does not guess it from settings.
 * - **Targets come from the API.** Every card renders a threshold, a measured
 *   value and a status the server computed (`targets`), so the SRS numbers are
 *   written down once, in `backend/app/eval/targets.py`. A missed target reads
 *   as data, not as an error (NFR-16).
 * - **Polling stops when there is nothing to wait for.** A queued or running run
 *   is re-read every few seconds and a settled one is not; a backgrounded tab
 *   stops asking altogether (IR-22).
 * - **Under-triage is listed, not just counted.** Each vignette predicted less
 *   urgent than its reference is named for the veterinary reviewer (NFR-14).
 *
 * Vignette text never reaches this screen: sets report a count and runs report
 * categories and ids.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  EVAL_RUN_POLL_INTERVAL_MS,
  downloadEvalExport,
  isRunActive,
  listEvalRuns,
  listEvalSets,
  readEvalRun,
  startEvalRun,
  type EvalExportFormat,
  type EvalRun,
  type EvalSet,
} from "../../api/eval";
import { ApiErrorCode, isApiError } from "../../api/errors";
import { useToast } from "../../hooks/useToast";
import { strings } from "../../i18n/strings";
import { formatArrivalTime, formatDisplayDate } from "../../lib/datetime";
import { saveBlob } from "../../lib/download";
import { ConfusionMatrix } from "./ConfusionMatrix";
import styles from "./Evaluation.module.css";
import { MetricCards } from "./MetricCards";
import {
  configLine,
  exportFileName,
  fill,
  isMockRun,
  progressPercent,
  runNumbers,
} from "./runFormat";
import { UnderTriagedList } from "./UnderTriagedList";
import { UploadSetDialog } from "./UploadSetDialog";

const copy = strings.evaluation;

/** Only a finished run has anything to export (the server answers 409 otherwise). */
function isExportable(run: EvalRun): boolean {
  return run.status === "DONE" || run.status === "FAILED";
}

function describeFailure(error: unknown, fallback: string): string {
  if (!isApiError(error)) {
    return fallback;
  }
  switch (error.code) {
    case ApiErrorCode.forbidden:
      return copy.errors.forbidden;
    case ApiErrorCode.notFound:
      return copy.errors.notFound;
    case ApiErrorCode.evaluationNotFinished:
      return copy.export.unavailable;
    default:
      return fallback;
  }
}

function formatCreated(iso: string): string {
  const date = formatDisplayDate(iso);
  const time = formatArrivalTime(iso);
  return date !== null && time !== null ? `${date}, ${time}` : copy.configUnknown;
}

export function Evaluation() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();

  const [chosenSetId, setChosenSetId] = useState<string | null>(null);
  const [chosenRunId, setChosenRunId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [startFailure, setStartFailure] = useState<string | null>(null);
  const [exportFailure, setExportFailure] = useState<string | null>(null);

  const sets = useQuery({ queryKey: ["eval", "sets"], queryFn: listEvalSets });

  const runs = useQuery({
    queryKey: ["eval", "runs"],
    queryFn: listEvalRuns,
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => isRunActive(run.status))
        ? EVAL_RUN_POLL_INTERVAL_MS
        : false,
    // IR-22: a backgrounded tab stops asking. The default, written out because
    // the requirement rests on it.
    refetchIntervalInBackground: false,
  });

  const setItems = sets.data?.items ?? [];
  const runItems = runs.data?.items ?? [];
  const numbers = runNumbers(runItems);

  // The newest run until one is chosen, and the first set until one is chosen.
  const newestRun = [...runItems].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const selectedRunId = chosenRunId ?? newestRun?.id ?? null;
  const selectedSetId = chosenSetId ?? setItems[0]?.id ?? null;

  const detail = useQuery({
    queryKey: ["eval", "run", selectedRunId],
    queryFn: () => readEvalRun(selectedRunId ?? ""),
    enabled: selectedRunId !== null,
    // The list already holds the run, so it shows at once instead of after a
    // second round trip.
    placeholderData: () => runItems.find((run) => run.id === selectedRunId),
    refetchInterval: (query) =>
      isRunActive(query.state.data?.status) ? EVAL_RUN_POLL_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });

  const selectedRun = selectedRunId === null ? undefined : detail.data;
  const anyRunActive = runItems.some((run) => isRunActive(run.status));

  const start = useMutation({
    mutationFn: startEvalRun,
    onSuccess: (run) => {
      setStartFailure(null);
      setExportFailure(null);
      setChosenRunId(run.id);
      showToast(copy.toasts.started);
      void queryClient.invalidateQueries({ queryKey: ["eval", "runs"] });
    },
    onError: (error) => setStartFailure(describeFailure(error, copy.errors.startFailed)),
  });

  const exportRun = useMutation({
    mutationFn: async ({ run, format }: { run: EvalRun; format: EvalExportFormat }) => {
      const blob = await downloadEvalExport(run.id, format);
      saveBlob(blob, exportFileName(run.id, format));
    },
    onSuccess: () => setExportFailure(null),
    onError: (error) => setExportFailure(describeFailure(error, copy.export.failed)),
  });

  function handleUploaded(set: EvalSet) {
    setChosenSetId(set.id);
    void queryClient.invalidateQueries({ queryKey: ["eval", "sets"] });
  }

  function handleStart() {
    if (selectedSetId === null) {
      return;
    }
    setStartFailure(null);
    start.mutate(selectedSetId);
  }

  function handleSelectRun(id: string) {
    setChosenRunId(id);
    setExportFailure(null);
  }

  const line = configLine(selectedRun);
  const loadFailed = sets.isError || runs.isError;
  const startDisabled = selectedSetId === null || start.isPending || anyRunActive;

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>{copy.title}</h1>

      {isMockRun(selectedRun) ? (
        <p className={styles.mockBanner} role="status">
          {copy.mockBanner}
        </p>
      ) : null}

      <section className={styles.header}>
        <div className={styles.headerRow}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="eval-set">
              {copy.setLabel}
            </label>
            <select
              id="eval-set"
              className={styles.input}
              value={selectedSetId ?? ""}
              disabled={setItems.length === 0}
              onChange={(event) => setChosenSetId(event.target.value)}
            >
              {setItems.map((set) => (
                <option key={set.id} value={set.id}>
                  {fill(copy.setOption, { name: set.name, count: set.vignette_count })}
                </option>
              ))}
            </select>
          </div>

          <div className={styles.headerActions}>
            <button type="button" className={styles.secondary} onClick={() => setUploading(true)}>
              {copy.upload}
            </button>
            <button
              type="button"
              className={styles.primary}
              disabled={startDisabled}
              onClick={handleStart}
            >
              {start.isPending ? copy.starting : copy.start}
            </button>
          </div>
        </div>

        {sets.data !== undefined && setItems.length === 0 ? (
          <p className={styles.helper}>{copy.noSets}</p>
        ) : null}
        {anyRunActive ? <p className={styles.helper}>{copy.startBlockedRunning}</p> : null}
        <p className={styles.helper}>{line ?? copy.configPending}</p>

        {startFailure !== null ? (
          <p className={styles.error} role="alert">
            {startFailure}
          </p>
        ) : null}
      </section>

      {loadFailed ? (
        <p className={styles.error} role="alert">
          {copy.errors.unexpected}
        </p>
      ) : null}

      <section className={styles.panel} aria-labelledby="eval-runs-title">
        <h2 id="eval-runs-title" className={styles.panelTitle}>
          {copy.runs.title}
        </h2>
        {runs.isPending ? <p className={styles.notice}>{copy.loading}</p> : null}
        {runs.data !== undefined && runItems.length === 0 ? (
          <p className={styles.notice}>{copy.runs.empty}</p>
        ) : null}
        {runItems.length > 0 ? (
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">{copy.runs.columns.run}</th>
                <th scope="col">{copy.runs.columns.set}</th>
                <th scope="col">{copy.runs.columns.status}</th>
                <th scope="col">{copy.runs.columns.progress}</th>
                <th scope="col">{copy.runs.columns.started}</th>
              </tr>
            </thead>
            <tbody>
              {[...runItems]
                .sort((a, b) => b.created_at.localeCompare(a.created_at))
                .map((run) => {
                  const number = numbers.get(run.id) ?? 0;
                  const isSelected = run.id === selectedRunId;
                  return (
                    <tr key={run.id} className={isSelected ? styles.selectedRow : undefined}>
                      <td>
                        <button
                          type="button"
                          className={styles.link}
                          aria-current={isSelected ? "true" : undefined}
                          aria-label={fill(copy.runs.select, { number })}
                          onClick={() => handleSelectRun(run.id)}
                        >
                          {fill(copy.runs.name, { number })}
                        </button>
                      </td>
                      <td>{run.set_name}</td>
                      <td>{copy.runs.status[run.status]}</td>
                      <td>
                        {fill(copy.runs.progress, {
                          done: run.progress.done,
                          total: run.progress.total,
                        })}
                      </td>
                      <td>{formatCreated(run.created_at)}</td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        ) : null}
      </section>

      {selectedRun !== undefined ? (
        <section aria-labelledby="eval-run-title">
          <h2 id="eval-run-title" className={styles.runHeading}>
            {fill(copy.runs.heading, {
              number: numbers.get(selectedRun.id) ?? 0,
              status: copy.runs.status[selectedRun.status],
              done: selectedRun.progress.done,
              total: selectedRun.progress.total,
            })}
          </h2>

          {isRunActive(selectedRun.status) ? (
            <div className={styles.progress}>
              <div
                className={styles.bar}
                role="progressbar"
                aria-label={copy.runs.progressLabel}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={progressPercent(
                  selectedRun.progress.done,
                  selectedRun.progress.total,
                )}
                aria-valuetext={fill(copy.runs.progress, {
                  done: selectedRun.progress.done,
                  total: selectedRun.progress.total,
                })}
              >
                <div
                  className={styles.barFill}
                  style={{
                    width: `${progressPercent(
                      selectedRun.progress.done,
                      selectedRun.progress.total,
                    )}%`,
                  }}
                />
              </div>
              <p className={styles.helper}>{copy.runs.noMetrics}</p>
            </div>
          ) : null}

          {selectedRun.status === "FAILED" ? (
            <p className={styles.error} role="alert">
              {copy.runs.failedRun}
            </p>
          ) : null}

          {selectedRun.metrics !== null ? (
            <>
              <MetricCards targets={selectedRun.targets} />

              {selectedRun.metrics.counts.failed > 0 ? (
                <p className={styles.notice}>
                  {fill(copy.runs.failedVignettes, { count: selectedRun.metrics.counts.failed })}
                </p>
              ) : null}

              <div className={styles.lower}>
                <ConfusionMatrix
                  labels={selectedRun.metrics.classification.labels}
                  matrix={selectedRun.metrics.classification.confusion_matrix}
                />
                <UnderTriagedList items={selectedRun.metrics.classification.under_triaged} />
              </div>
            </>
          ) : null}

          <div className={styles.exportRow}>
            {(["csv", "json"] as const).map((format) => (
              <button
                key={format}
                type="button"
                className={styles.secondary}
                disabled={!isExportable(selectedRun) || exportRun.isPending}
                onClick={() => {
                  setExportFailure(null);
                  exportRun.mutate({ run: selectedRun, format });
                }}
              >
                {exportRun.isPending && exportRun.variables?.format === format
                  ? copy.export.exporting
                  : copy.export[format]}
              </button>
            ))}
          </div>
          {exportFailure !== null ? (
            <p className={styles.error} role="alert">
              {exportFailure}
            </p>
          ) : null}
        </section>
      ) : null}

      {uploading ? (
        <UploadSetDialog onUploaded={handleUploaded} onClose={() => setUploading(false)} />
      ) : null}
    </div>
  );
}
