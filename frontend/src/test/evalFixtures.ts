/**
 * Fictitious evaluation runs for the W-10 tests (CLAUDE.md §9).
 *
 * The numbers are the ones W-10 draws, so a reader can check a card against the
 * wireframe: Macro-F1 0.84, Red+Orange recall 0.96, under-triage 7.5%,
 * Recall@5 0.86, MRR 0.74, latency 8.4 / 16.9 s.
 */
import type { EvalMetrics, EvalRun, EvalSet, EvalTarget } from "../api/eval";

export function makeTarget(overrides: Partial<EvalTarget> = {}): EvalTarget {
  return {
    key: "macro_f1",
    label: "Macro-F1",
    requirement: "NFR-16",
    comparison: "at_least",
    threshold: 0.7,
    unit: "",
    value: 0.84,
    status: "PASS",
    ...overrides,
  };
}

export const TARGETS: EvalTarget[] = [
  makeTarget(),
  makeTarget({
    key: "red_orange_recall",
    label: "Red + Orange recall",
    threshold: 0.9,
    value: 0.96,
  }),
  makeTarget({
    key: "under_triage_rate",
    label: "Under-triage rate",
    comparison: "at_most",
    threshold: 0.1,
    value: 0.075,
  }),
  makeTarget({
    key: "recall_at_k",
    label: "Recall@5",
    requirement: "NFR-17",
    threshold: 0.8,
    value: 0.86,
  }),
  makeTarget({ key: "mrr", label: "MRR", requirement: "NFR-17", threshold: 0.7, value: 0.74 }),
  makeTarget({
    key: "latency_p50",
    label: "Latency p50",
    requirement: "NFR-01",
    comparison: "at_most",
    threshold: 10,
    unit: "s",
    value: 8.4,
  }),
  makeTarget({
    key: "latency_p95",
    label: "Latency p95",
    requirement: "NFR-01",
    comparison: "at_most",
    threshold: 20,
    unit: "s",
    value: 16.9,
  }),
];

/** Rows are the reference category, columns the predicted one, RED to BLUE. */
export const CONFUSION_MATRIX = [
  [11, 1, 0, 0, 0],
  [1, 14, 1, 0, 0],
  [0, 2, 16, 2, 0],
  [0, 0, 2, 14, 2],
  [0, 0, 0, 2, 12],
];

export const METRICS: EvalMetrics = {
  counts: { total: 80, failed: 0, scored: 80 },
  classification: {
    labels: ["RED", "ORANGE", "YELLOW", "GREEN", "BLUE"],
    confusion_matrix: CONFUSION_MATRIX,
    under_triage_count: 6,
    under_triaged: [
      {
        external_id: "V-017",
        reference: "RED",
        predicted: "ORANGE",
        primary_complaint: "Seizures",
      },
      {
        external_id: "V-032",
        reference: "ORANGE",
        predicted: "YELLOW",
        primary_complaint: "Suspected toxin ingestion",
      },
      {
        external_id: "V-044",
        reference: "YELLOW",
        predicted: "GREEN",
        primary_complaint: "Diarrhea",
      },
      { external_id: "V-051", reference: "GREEN", predicted: "BLUE", primary_complaint: null },
      {
        external_id: "V-060",
        reference: "ORANGE",
        predicted: "GREEN",
        primary_complaint: "Limping",
      },
      {
        external_id: "V-071",
        reference: "YELLOW",
        predicted: "BLUE",
        primary_complaint: "Itching",
      },
    ],
  },
};

export function makeSet(overrides: Partial<EvalSet> = {}): EvalSet {
  return {
    id: "00000000-0000-4000-8000-0000000000e1",
    name: "Set v1",
    vignette_count: 80,
    imported_at: "2026-10-20T01:00:00Z",
    warnings: [],
    ...overrides,
  };
}

export function makeRun(overrides: Partial<EvalRun> = {}): EvalRun {
  return {
    id: "11111111-aaaa-4000-8000-0000000000f1",
    set_id: "00000000-0000-4000-8000-0000000000e1",
    set_name: "Set v1",
    status: "DONE",
    progress: { done: 80, total: 80 },
    kb_version_id: "22222222-bbbb-4000-8000-000000000001",
    fully_mocked: false,
    config: {
      model_id: "model-x",
      prompt_version: "v1.3",
      kb_version_id: "22222222-bbbb-4000-8000-000000000001",
      temperature: 0,
      top_k: 5,
      fully_mocked: false,
    },
    metrics: METRICS,
    targets: TARGETS,
    created_at: "2026-10-21T02:00:00Z",
    started_at: "2026-10-21T02:00:01Z",
    finished_at: "2026-10-21T02:05:00Z",
    ...overrides,
  };
}
