/**
 * Pure helpers for the evaluation console (W-10): how a run's numbers are
 * written, and which run is which.
 *
 * Nothing here decides pass or fail. The API's `targets` already carry the
 * status for every SRS threshold (`backend/app/eval/targets.py`), so this only
 * turns values into the wording the cards show.
 */
import type { EvalExportFormat, EvalRun, EvalTarget } from "../../api/eval";
import { strings } from "../../i18n/strings";

const copy = strings.evaluation;

/** Characters of a UUID shown where the full id would only be noise. */
const SHORT_ID_LENGTH = 8;

/** The two latency targets share one card, as W-10 draws them. */
export const LATENCY_KEYS = { p50: "latency_p50", p95: "latency_p95" } as const;

/** Fill `{name}` placeholders in a resource string. */
export function fill(template: string, values: Record<string, string | number>): string {
  return Object.entries(values).reduce(
    (text, [name, value]) => text.split(`{${name}}`).join(String(value)),
    template,
  );
}

/** The leading characters of an id: enough to tell two runs apart on screen. */
export function shortId(id: string): string {
  return id.slice(0, SHORT_ID_LENGTH);
}

/** Every pipeline stage was a mock, so the numbers are not model results (ADR-17). */
export function isMockRun(run: EvalRun | undefined): boolean {
  return run?.fully_mocked === true;
}

/**
 * Number each run from the oldest, so "Run #3" keeps its number as newer runs
 * arrive. The API lists runs without promising an order.
 */
export function runNumbers(runs: readonly EvalRun[]): Map<string, number> {
  const oldestFirst = [...runs].sort((a, b) => a.created_at.localeCompare(b.created_at));
  return new Map(oldestFirst.map((run, index) => [run.id, index + 1]));
}

/** 0–100, for the progress bar; an empty set reads as no progress rather than NaN. */
export function progressPercent(done: number, total: number): number {
  if (total <= 0) {
    return 0;
  }
  return Math.min(100, Math.round((done / total) * 100));
}

function trimmed(value: number, digits: number): string {
  return Number(value.toFixed(digits)).toString();
}

function isRate(target: EvalTarget): boolean {
  return target.key === "under_triage_rate";
}

/** A measured value as the card writes it; null when it could not be computed. */
export function formatValue(target: EvalTarget): string {
  if (target.value === null) {
    return copy.metrics.valueUnavailable;
  }
  if (isRate(target)) {
    return `${trimmed(target.value * 100, 1)}%`;
  }
  if (target.unit === "s") {
    return trimmed(target.value, 1);
  }
  return target.value.toFixed(2);
}

/** A threshold the same way, so "7.5%" sits beside "target ≤ 10%". */
function formatThreshold(target: EvalTarget): string {
  if (isRate(target)) {
    return `${trimmed(target.threshold * 100, 1)}%`;
  }
  if (target.unit === "s") {
    return trimmed(target.threshold, 1);
  }
  return target.threshold.toFixed(2);
}

function comparisonSign(target: EvalTarget): string {
  return target.comparison === "at_least" ? copy.metrics.atLeast : copy.metrics.atMost;
}

/** "target ≥ 0.70" */
export function targetText(target: EvalTarget): string {
  return fill(copy.metrics.target, {
    comparison: comparisonSign(target),
    threshold: `${formatThreshold(target)}${target.unit === "s" ? " s" : ""}`,
  });
}

/** "8.4 / 16.9 s", or "n/a" when neither percentile exists. */
export function latencyValueText(p50: EvalTarget | undefined, p95: EvalTarget | undefined): string {
  if (p50 === undefined || p95 === undefined || (p50.value === null && p95.value === null)) {
    return copy.metrics.valueUnavailable;
  }
  return `${formatValue(p50)} / ${formatValue(p95)} s`;
}

/** "target ≤ 10 / 20 s" */
export function latencyTargetText(p50: EvalTarget, p95: EvalTarget): string {
  return fill(copy.metrics.target, {
    comparison: comparisonSign(p50),
    threshold: `${formatThreshold(p50)} / ${formatThreshold(p95)} s`,
  });
}

/**
 * The line under the set selector: what the run was configured with (NFR-23).
 * Null before any run exists, because the configuration is recorded by a run.
 */
export function configLine(run: EvalRun | undefined): string | null {
  const config = run?.config;
  if (config === null || config === undefined) {
    return null;
  }
  const unknown = copy.configUnknown;
  const kb = config.kb_version_id ?? run?.kb_version_id ?? null;
  const temperature = config.temperature;
  return fill(copy.configLine, {
    model: config.model_id ?? unknown,
    prompt: config.prompt_version ?? unknown,
    kb: kb === null ? unknown : shortId(kb),
    temperature:
      temperature === null || temperature === undefined || temperature === ""
        ? copy.temperatureDefault
        : String(temperature),
    topK: config.top_k ?? unknown,
  });
}

/** The download's name, matching the server's own `Content-Disposition`. */
export function exportFileName(runId: string, format: EvalExportFormat): string {
  return fill(copy.export.fileName, { id: shortId(runId), format });
}
