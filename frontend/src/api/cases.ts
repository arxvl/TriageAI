/**
 * The `/cases` endpoints (FR-01, FR-03, FR-07).
 *
 * Field names match the API's `CaseCreate` and `CaseCreated` verbatim —
 * snake_case, no mapping layer on either side, the same rule `auth.ts` follows.
 *
 * Two things the enums record rather than hide:
 *
 * - `SpeciesInput` is wider than `Species`. A case row is only ever DOG or CAT,
 *   but the W-03 control has a third button and FR-02 says choosing it must
 *   produce the manual-triage message. The request type carries OTHER; no
 *   response type does.
 * - There is no owner-reference field on any response. Owner name and contact
 *   number are accepted on the way in and returned by nothing (FR-07, DR-04).
 */
import { apiFetch } from "./client";

export type Species = "DOG" | "CAT";
/** What the species control on W-03 can submit. See the module docblock. */
export type SpeciesInput = Species | "OTHER";

export type AgeUnit = "MONTHS" | "YEARS";
export type Sex = "MALE" | "FEMALE" | "UNKNOWN";
export type IntakeChannel = "WALK_IN" | "PHONE" | "MESSAGE";

export type CaseStatus =
  | "SUBMITTED"
  | "PROCESSING"
  | "AWAITING_REVIEW"
  | "MANUAL_TRIAGE_REQUIRED"
  | "CONFIRMED"
  | "ADJUSTED"
  | "MANUALLY_TRIAGED"
  | "CLOSED";

export type VTLCategory = "RED" | "ORANGE" | "YELLOW" | "GREEN" | "BLUE";

/**
 * The Case Intake Form body (FR-01).
 *
 * Species and description are the only required fields. An omitted optional
 * field is left out of the JSON entirely rather than sent as null or "", which
 * is what `toCaseCreateRequest` in `lib/caseValidation.ts` produces.
 */
export interface CaseCreateRequest {
  species: SpeciesInput;
  description: string;

  intake_channel?: IntakeChannel;

  pet_name?: string;
  age_value?: number;
  age_unit?: AgeUnit;
  sex?: Sex;
  neutered?: boolean;
  breed?: string;
  weight_kg?: number;

  /** Stored in `owner_references` and returned by no endpoint (FR-07, DR-04). */
  owner_name?: string;
  contact_number?: string;
}

export interface CaseCreated {
  id: string;
  case_no: string;
  status: CaseStatus;
}

/**
 * Record a new case and start its triage (FR-01, FR-03, FR-06).
 *
 * Answers 202 Accepted: the case and its pipeline job are committed together and a
 * worker picks the job up within about half a second, so the recommendation does
 * not exist yet. The returned status is `SUBMITTED`; `getCaseStatus` reports the
 * rest (ADR-08, IR-22).
 *
 * Throws `ApiError`: `VALIDATION_ERROR` naming a field (FR-04), or
 * `SPECIES_OUT_OF_SCOPE` with no field for a species the AI does not process
 * (FR-02).
 */
export async function createCase(payload: CaseCreateRequest): Promise<CaseCreated> {
  return apiFetch<CaseCreated>("/cases", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export type DecisionType = "CONFIRM" | "ADJUST" | "MANUAL";

/**
 * The category filter on W-02: the five VTL categories plus manual triage.
 *
 * MANUAL is not a category. It selects the cases that reached
 * `MANUAL_TRIAGE_REQUIRED`, which have no category at all.
 */
export type QueueCategoryFilter = VTLCategory | "MANUAL";

/** How often the queue re-asks the server (IR-22, ADR-08). */
export const QUEUE_POLL_INTERVAL_MS = 15_000;

/**
 * One row of the Triage Queue (W-02), mirroring the API's `CaseQueueItem`.
 *
 * `category` is the one the row displays: the confirmed category if a reviewer
 * has decided, otherwise the AI's recommendation (FR-29). The two sources come
 * separately as well, because the status chip has to say *which* it is (FR-36,
 * IR-04).
 *
 * Everything from `waiting_minutes` down is derived by the server against a
 * single clock, so every row in one response is measured at the same instant.
 */
export interface CaseQueueItem {
  id: string;
  case_no: string;
  status: CaseStatus;
  /** ISO-8601 UTC; the screen shows it in the clinic's timezone. */
  created_at: string;

  species: Species;
  pet_name: string | null;
  age_value: number | null;
  age_unit: AgeUnit | null;
  breed: string | null;

  primary_complaint_code: string | null;
  primary_complaint_name: string | null;

  category: VTLCategory | null;
  recommended_category: VTLCategory | null;
  confirmed_category: VTLCategory | null;
  decision_type: DecisionType | null;

  waiting_minutes: number;
  /** Null for a case with no category, which therefore has no target. */
  target_minutes: number | null;
  is_overdue: boolean;
  has_red_flag: boolean;
}

/**
 * The counters above the W-02 table.
 *
 * They always describe the whole open queue, never the filtered rows, so the
 * numbers do not move when a filter is applied and a counter can be used to
 * apply one. `by_category` carries all five keys, zeros included.
 */
export interface CaseQueueCounts {
  by_category: Record<VTLCategory, number>;
  manual_count: number;
  awaiting_review_count: number;
  total: number;
}

/**
 * One entry in the W-02 red-flag banner (FR-12, NFR-05).
 *
 * Enough to recognise the patient and act, and no more: there is no field for the
 * text the rule matched, because that is a substring of the owner's description
 * and the banner is the most widely visible surface in the application (DR-04).
 *
 * `rule_label` is the clinic's own wording for the rule, not its code.
 */
export interface QueueRedFlagAlert {
  case_id: string;
  case_no: string;
  species: Species;
  pet_name: string | null;
  rule_code: string;
  rule_label: string;
  min_category: VTLCategory;
  /** ISO-8601 UTC. */
  created_at: string;
}

export interface CaseListResponse {
  items: CaseQueueItem[];
  counts: CaseQueueCounts;
  /**
   * The banner above the table. Part of this response rather than its own
   * endpoint, so the alerts and the rows a reviewer compares them against are read
   * at the same instant. Unfiltered, like the counters (FR-12).
   */
  red_flag_alerts: QueueRedFlagAlert[];
  /** Drives the "Updated N s ago" indicator (IR-22). */
  generated_at: string;
}

/** The W-02 search and filter bar (FR-39), as query parameters. */
export interface CaseQueueFilters {
  species?: Species;
  category?: QueueCategoryFilter;
  status?: CaseStatus;
  /** Inclusive calendar dates, `YYYY-MM-DD`, read in the clinic's timezone. */
  date_from?: string;
  date_to?: string;
  q?: string;
}

/**
 * The Triage Queue: open cases in urgency order, with the counters (FR-29, FR-39).
 *
 * An absent or empty filter is left out of the query string rather than sent
 * blank, because `CaseQueueFilters` on the server forbids unknown and malformed
 * parameters.
 */
export async function listCases(filters: CaseQueueFilters = {}): Promise<CaseListResponse> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") {
      params.set(key, value);
    }
  }

  const query = params.toString();
  return apiFetch<CaseListResponse>(query === "" ? "/cases" : `/cases?${query}`);
}

/**
 * How far the triage pipeline has got on one case (IR-22, ADR-08).
 *
 * `queued` is a job nobody has claimed yet; `done` and `failed` are the two
 * finished states. The five in between are the orchestrator's own steps, so a case
 * that is taking a long time says which stage it is in.
 */
export type PipelineStage =
  "queued" | "deidentify" | "screen" | "extract" | "retrieve" | "generate" | "done" | "failed";

/**
 * The polling response while a case is being processed (IR-22).
 *
 * `pipeline_stage` is null for a case with no pipeline job — every case recorded
 * before the pipeline existed.
 */
export interface CaseStatusOut {
  status: CaseStatus;
  category: VTLCategory | null;
  has_red_flag: boolean;
  pipeline_stage: PipelineStage | null;
  /** ISO-8601 UTC. */
  updated_at: string;
}

// `GET /cases/{id}/status` has no caller yet. The queue's own 15-second poll is
// what W-02 refreshes from (IR-22), and the per-case polling this response is for
// belongs to the Case Review screen in P06. The types above are the contract, kept
// here with the rest of the endpoint's shapes.
