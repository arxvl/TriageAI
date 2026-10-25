/**
 * The `/eval` endpoints: vignette sets and evaluation runs (FR-64..FR-69, BR-05).
 *
 * Field names match the API's own schemas verbatim — snake_case, no mapping
 * layer, the rule `api/cases.ts` follows. Administrator only on the server.
 *
 * Three things the screen relies on rather than re-derives:
 *
 * - `targets` carries every SRS threshold with its measured value and a
 *   PASS / FAIL / n/a status, so no threshold is written down in the frontend.
 * - `metrics` is the stored JSON of `app.eval.metrics`, typed below as far as
 *   the screen reads it. Undefined values are `null`, never 0, and it is `null`
 *   itself until the run is DONE.
 * - Latency inside `metrics` is in milliseconds; a target's value and threshold
 *   are already in seconds.
 */
import { apiFetch, apiFetchBlob } from "./client";
import type { VTLCategory } from "./cases";

/** How often the console re-reads a run that is queued or running (IR-22). */
export const EVAL_RUN_POLL_INTERVAL_MS = 2_000;

export type EvalRunStatus = "QUEUED" | "RUNNING" | "DONE" | "FAILED";

export type EvalExportFormat = "csv" | "json";

export interface EvalSet {
  id: string;
  name: string;
  vignette_count: number;
  /** ISO instant, UTC. */
  imported_at: string;
  /** Unknown knowledge-base slugs; filled on the upload response only. */
  warnings: string[];
}

export interface EvalSetListResponse {
  items: EvalSet[];
  total: number;
}

export interface EvalProgress {
  done: number;
  total: number;
}

export type EvalTargetStatus = "PASS" | "FAIL" | "n/a";

export interface EvalTarget {
  key: string;
  label: string;
  requirement: string;
  comparison: "at_least" | "at_most";
  threshold: number;
  /** "s" for the latency targets, "" for the rest. */
  unit: string;
  value: number | null;
  status: EvalTargetStatus;
}

export interface UnderTriagedVignette {
  external_id: string;
  reference: VTLCategory;
  predicted: VTLCategory;
  primary_complaint: string | null;
}

export interface EvalMetrics {
  counts: { total: number; failed: number; scored: number };
  classification: {
    /** The row and column order of `confusion_matrix`: RED to BLUE. */
    labels: VTLCategory[];
    /** Rows are the reference category, columns the predicted one. */
    confusion_matrix: number[][];
    under_triage_count: number;
    under_triaged: UnderTriagedVignette[];
  };
}

/** What a run recorded about itself (NFR-23). Only the keys the screen reads. */
export interface EvalRunConfig {
  model_id?: string;
  prompt_version?: string;
  kb_version_id?: string | null;
  temperature?: number | string | null;
  top_k?: number;
  fully_mocked?: boolean;
}

export interface EvalRun {
  id: string;
  set_id: string;
  set_name: string;
  status: EvalRunStatus;
  progress: EvalProgress;
  kb_version_id: string | null;
  /** null until the run has started and a configuration snapshot exists. */
  fully_mocked: boolean | null;
  config: EvalRunConfig | null;
  metrics: EvalMetrics | null;
  targets: EvalTarget[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface EvalRunListResponse {
  items: EvalRun[];
}

/** True while the worker still has work on the run, so the screen keeps asking. */
export function isRunActive(status: EvalRunStatus | undefined): boolean {
  return status === "QUEUED" || status === "RUNNING";
}

export function listEvalSets(): Promise<EvalSetListResponse> {
  return apiFetch<EvalSetListResponse>("/eval/sets");
}

/** Multipart, because the vignettes are a file; `apiFetch` leaves the type to the browser. */
export function uploadEvalSet(name: string, file: File): Promise<EvalSet> {
  const body = new FormData();
  body.append("name", name);
  body.append("file", file);
  return apiFetch<EvalSet>("/eval/sets", { method: "POST", body });
}

export function listEvalRuns(): Promise<EvalRunListResponse> {
  return apiFetch<EvalRunListResponse>("/eval/runs");
}

export function readEvalRun(id: string): Promise<EvalRun> {
  return apiFetch<EvalRun>(`/eval/runs/${id}`);
}

export function startEvalRun(setId: string): Promise<EvalRun> {
  return apiFetch<EvalRun>("/eval/runs", {
    method: "POST",
    body: JSON.stringify({ set_id: setId }),
  });
}

export function downloadEvalExport(id: string, format: EvalExportFormat): Promise<Blob> {
  return apiFetchBlob(`/eval/runs/${id}/export?format=${format}`);
}
