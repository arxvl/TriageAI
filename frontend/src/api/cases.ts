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
import type { UserRole } from "./auth";
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
 * How often the Case Review screen re-reads one case (P06 §6.2).
 *
 * Thirty seconds is what W-04's live "waiting X min of Y min" asks for. The
 * waiting time is re-read rather than counted locally, for the reason the queue
 * gives: one clock measures every case (FR-30).
 */
export const CASE_POLL_INTERVAL_MS = 30_000;

/**
 * The faster interval while something on the case is still running.
 *
 * A case in `SUBMITTED`/`PROCESSING`, or one whose suggested actions are still
 * `PENDING`, is expected to change within seconds, and the screen shows a
 * loading row until it does (FR-77, IR-22).
 */
export const CASE_PENDING_POLL_INTERVAL_MS = 5_000;

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
  | "queued"
  | "deidentify"
  | "screen"
  | "extract"
  | "retrieve"
  | "generate"
  | "done"
  | "failed";

/**
 * How far the suggested actions for one case have got (FR-77, ADR-18).
 *
 * Separate from the case status, and deliberately so: the category is settled and
 * the case is already awaiting review while the actions are still `PENDING`. A
 * `FAILED` value means the baseline actions are shown on their own — nothing
 * about the case is wrong, so the screen says one quiet line and never an error
 * dialog.
 */
export type ActionsStatus = "PENDING" | "READY" | "FAILED" | "NOT_APPLICABLE";

/**
 * The polling response while a case is being processed (IR-22).
 *
 * `pipeline_stage` is null for a case with no pipeline job — every case recorded
 * before the pipeline existed. `actions_status` is null until a recommendation
 * exists, because there is nothing for the actions job to be about before then.
 */
export interface CaseStatusOut {
  status: CaseStatus;
  category: VTLCategory | null;
  has_red_flag: boolean;
  pipeline_stage: PipelineStage | null;
  actions_status: ActionsStatus | null;
  /** ISO-8601 UTC. */
  updated_at: string;
}

/**
 * How often the Case Review screen asks how far a run has got (IR-22).
 *
 * Only while the case is `SUBMITTED` or `PROCESSING`, which is after a case is
 * entered or after Retry (P07 §7.1). Faster than the 5-second case re-read
 * because it is the progress the reviewer is watching.
 */
export const CASE_STATUS_POLL_INTERVAL_MS = 2_000;

/** How far the newest pipeline run on a case has got (IR-22). */
export async function readCaseStatus(caseId: string): Promise<CaseStatusOut> {
  return apiFetch<CaseStatusOut>(`/cases/${caseId}/status`);
}

/* --- The Case Review screen (W-04..W-07, P06 §6.1) ---------------------- */

/** Where one suggested action came from. Shown as a tag on every row (IR-23). */
export type ActionSource = "BASELINE" | "AI" | "REVIEWER";

/** What a reviewer did with one action when finalizing the list (FR-76). */
export type ActionStatus = "SUGGESTED" | "KEPT" | "EDITED" | "REMOVED" | "ADDED";

export type ConfidenceLevel = "HIGH" | "MEDIUM" | "LOW";

export type DecisionDirection = "UP" | "DOWN" | "SAME" | "NONE";

/**
 * Why a reviewer moved the category away from the recommendation (FR-33).
 *
 * A fixed list, not free text: these codes are the data behind the disagreement
 * analysis. `reason_text` carries the detail and is required for OTHER.
 */
export type AdjustReason =
  | "CONDITION_DIFFERS_ON_ARRIVAL"
  | "SIGN_NOT_CAPTURED"
  | "RECOMMENDATION_TOO_LOW"
  | "RECOMMENDATION_TOO_HIGH"
  | "OTHER";

/** One row of the W-04 action checklist (FR-73, IR-23). */
export interface SuggestedAction {
  text: string;
  /** `references[].rank` values, which is how a row sits beside its passage. */
  cited_ranks: number[];
  source: ActionSource;
  /** A decision settled on a category this action was not generated for (FR-78). */
  is_outdated: boolean;
}

/**
 * The two action layers for one case (FR-71..FR-79, ADR-18).
 *
 * `baseline` is always present — it is read from the knowledge base for the
 * case's current category, so it survives a failed actions job and follows a
 * reviewer who changes the category. `tailored` is best effort and is empty for
 * a caller who is not a Veterinary Reviewer (FR-79).
 */
export interface CaseActions {
  status: ActionsStatus | null;
  generated_for_category: VTLCategory | null;
  baseline: string[];
  tailored: SuggestedAction[];
  rejected_count: number;
  /** A decision settled on a category these were not generated for (FR-78). */
  is_outdated: boolean;
  /** Plain-language line for a failed actions job; null unless `status` is FAILED (FR-77). */
  failure_message: string | null;
}

/** The W-04 header: who the patient is and how long they have waited. */
export interface CaseHeader {
  case_no: string;
  species: Species;
  pet_name: string | null;
  age_value: number | null;
  age_unit: AgeUnit | null;
  sex: Sex;
  neutered: boolean | null;
  breed: string | null;
  weight_kg: number | null;
  intake_channel: IntakeChannel;
  /** ISO-8601 UTC; rendered in Asia/Manila (DR-03). */
  created_at: string;
  created_by_name: string | null;
  closed_at: string | null;
  waiting_minutes: number;
  /** Null for a case with no category, which has no target (FR-30). */
  target_minutes: number | null;
  is_overdue: boolean;
}

/**
 * Panel 1: what the owner said, and what the pipeline actually read.
 *
 * Evidence offsets index into `deidentified_text`, not `text`. When `differs` is
 * true the panel shows that text instead and says so, because a highlight
 * positioned against the wrong string would mark the wrong words (ADR-10).
 * `deidentified_text` is null for a case with no extraction.
 */
export interface CaseDescription {
  text: string;
  deidentified_text: string | null;
  differs: boolean;
}

/**
 * One highlight, as offsets into `CaseDescription.deidentified_text` (FR-13).
 *
 * `found: false` with null offsets means the stored span no longer matches. The
 * span is still returned, so the panel can show the quoted evidence as text
 * beside the value rather than silently showing less than the extraction claimed.
 */
export interface EvidenceSpan {
  field: string;
  text: string;
  start: number | null;
  end: number | null;
  found: boolean;
}

export interface ExtractedComplaint {
  code: string;
  name: string | null;
  is_primary: boolean;
}

/**
 * Panel 2: the extracted information. A reviewer can correct it before deciding
 * (P07 §7.2); a correction is a new version, never an edit (ADR-14).
 */
export interface CaseExtraction {
  id: string;
  version: number;
  is_corrected: boolean;
  /** Who made the correction; null for the pipeline's own version. */
  corrected_by_name: string | null;
  species: Species | null;
  presenting_complaints: ExtractedComplaint[];
  onset_duration: string | null;
  frequency_severity: string | null;
  associated_signs: string[];
  negated_findings: string[];
  exposure_history: string | null;
  relevant_history: string | null;
  red_flags: string[];
  /** Rendered as "Ask the owner" on W-04. */
  missing_information: string[];
  evidence_spans: EvidenceSpan[];
  created_at: string;
}

/**
 * A red-flag rule that raised the category (FR-23, IR-03).
 *
 * The notice names the `label`; the `code` is kept so the rule stays
 * identifiable when the label is later edited.
 */
export interface SafetyFloorRule {
  code: string;
  label: string | null;
}

/** Panel 3: the recommendation after the deterministic safety validator. */
export interface CaseRecommendation {
  id: string;
  version: number;
  category: VTLCategory;
  target_minutes: number;
  rationale: string;
  confidence: ConfidenceLevel;
  safety_floor_applied: boolean;
  safety_floor_rules: SafetyFloorRule[];
  /** Codes the screen renders as plain language (FR-24). */
  low_confidence_reasons: string[];
  created_at: string;
}

/**
 * One retrieved passage, in rank order (FR-31).
 *
 * The source fields are the copies stored with the recommendation, so an old
 * case shows the passage as it read at the time (ADR-14).
 */
export interface CaseReference {
  rank: number;
  entry_title: string;
  source_title: string | null;
  source_url: string | null;
  passage_text: string;
  score: number | null;
  is_cited: boolean;
}

/** The provenance footnote under panel 3 (FR-26, NFR-23). */
export interface CaseConfiguration {
  model_id: string;
  prompt_version: string;
  kb_version_no: number | null;
  generated_at: string;
  latency_ms: number | null;
}

/**
 * One red-flag alert on a case (FR-12).
 *
 * Carries the rule's label, never the text that matched it: that is a substring
 * of the owner's description (DR-04). `acknowledged_at` is stamped the first
 * time a Veterinary Reviewer opens the case, which clears the W-02 banner.
 */
export interface CaseAlert {
  rule_code: string;
  rule_label: string | null;
  min_category: VTLCategory;
  created_at: string;
  acknowledged_at: string | null;
}

/**
 * Why the pipeline gave up on this case, and when (NFR-09, W-06).
 *
 * Null unless the case is `MANUAL_TRIAGE_REQUIRED` — the one status that means
 * the pipeline stopped and nobody has decided yet. `reason_code` is a stable
 * code and is never shown; `message` is the sentence the server wrote for it
 * (`backend/app/pipeline/messages.py`), including the time in the clinic's zone,
 * so this build holds no list of codes and an unknown one still reads as a
 * sentence (IR-05, P07 §7.1).
 */
export interface CaseFailure {
  reason_code: string;
  message: string;
  /** ISO-8601 UTC. */
  failed_at: string;
}

/** The latest decision on a case, or the one just recorded (FR-36). */
export interface CaseDecision {
  id: string;
  type: DecisionType;
  final_category: VTLCategory;
  target_minutes: number;
  reason_code: AdjustReason | null;
  reason_text: string | null;
  direction: DecisionDirection;
  decided_by_name: string | null;
  decided_at: string;
  amends_id: string | null;
  status: CaseStatus;
}

export interface CaseNote {
  id: string;
  text: string;
  author_name: string | null;
  created_at: string;
}

/**
 * What this caller may do with this case, as the server sees it.
 *
 * For hiding controls, never for allowing them: the server refuses the request
 * whatever these say (SR-05, BR-02). `can_regenerate` is true for a reviewer on
 * a case that is awaiting review: a correction is refused once a decision exists
 * and while a regeneration is already running (P07 §7.2). `can_retry` is true for
 * a reviewer on a case that is waiting on a failed run (P07 §7.1).
 */
export interface CasePermissions {
  can_decide: boolean;
  can_regenerate: boolean;
  /** The "Regenerate suggestions" button: a recommendation exists and no actions job is running. */
  can_regenerate_actions: boolean;
  can_retry: boolean;
  can_close: boolean;
}

/** One entry of the version switcher under panel 3 (FR-27). */
export interface RecommendationVersion {
  version: number;
  category: VTLCategory;
  created_at: string;
  /** Only the current version can be decided on. */
  is_current: boolean;
}

/**
 * One stored recommendation version, read-only (FR-27, ADR-14).
 *
 * What the switcher shows for an older version: the recommendation as it was,
 * the passages it cited, the configuration that produced it, and the extraction
 * version it was made from.
 */
export interface RecommendationVersionDetail {
  recommendation: CaseRecommendation;
  references: CaseReference[];
  configuration: CaseConfiguration;
  extraction_version: number;
  is_current: boolean;
}

/**
 * One case, everything the Case Review screen shows (FR-31, W-04).
 *
 * The panel order is ADR-15's: description, then extraction, then
 * recommendation. The reviewer reaches the AI's answer after the evidence they
 * can check it against, which is the structural defence against automation bias
 * — so a screen built from this must not reorder the three.
 *
 * `extraction`, `recommendation`, `configuration` and `decision` are null when
 * the case has not got that far. W-04 and W-06 read those nulls as "not
 * available", never as an error.
 */
export interface CaseDetail {
  id: string;
  case_no: string;
  status: CaseStatus;
  species: Species;
  /** The category on display: the confirmed one if there is one (FR-29). */
  category: VTLCategory | null;
  recommended_category: VTLCategory | null;
  confirmed_category: VTLCategory | null;
  has_red_flag: boolean;
  created_at: string;
  actions: CaseActions;

  header: CaseHeader;
  description: CaseDescription;
  extraction: CaseExtraction | null;
  recommendation: CaseRecommendation | null;
  references: CaseReference[];
  configuration: CaseConfiguration | null;
  alerts: CaseAlert[];
  decision: CaseDecision | null;
  notes: CaseNote[];
  permissions: CasePermissions;
  /** The failure the case is sitting on, for W-06's banner. */
  failure: CaseFailure | null;
  /** Every recommendation version, oldest first (FR-27). */
  recommendation_versions: RecommendationVersion[];
  /**
   * The last regeneration failed and the previous recommendation is still the
   * current one (P07 §7.2). Same shape as `failure`; the wording is different.
   */
  regeneration_failure: CaseFailure | null;
}

/** One row of the action list a reviewer finalizes with their decision (FR-76). */
export interface FinalActionInput {
  text: string;
  source: ActionSource;
  status: ActionStatus;
  /** The suggestion this came from; omitted for an action the reviewer wrote. */
  suggestion_id?: string;
}

/**
 * A decision on one case (FR-32, FR-33, FR-34).
 *
 * `final_category` is omitted for a CONFIRM: the point of confirming is that
 * the recommendation's category stands, and the server takes it from there.
 *
 * Omitting `final_actions` is not the same as sending `[]`. Omitted means the
 * reviewer did not touch the checklist, and the server records the list they
 * were shown as kept; `[]` means they removed everything.
 */
export interface DecisionRequest {
  type: DecisionType;
  final_category?: VTLCategory;
  reason_code?: AdjustReason;
  reason_text?: string;
  note?: string;
  /** Set to record a correction; the original decision is kept (FR-48). */
  amends_id?: string;
  final_actions?: FinalActionInput[];
}

/** What closing a case returns (FR-38). */
export interface CaseClosed {
  id: string;
  case_no: string;
  status: CaseStatus;
  closed_at: string;
}

/**
 * One row of the per-case audit timeline (FR-42, FR-45, W-07).
 *
 * `action` is the stable code, so a translated interface can substitute its own
 * wording (NFR-27); `label` and `details` are the sentence the server composed.
 * `actor_name` and `actor_role` are null for the pipeline's own entries — the
 * pipeline is not a person (ADR-12).
 */
export interface AuditTimelineItem {
  ts: string;
  actor_name: string | null;
  actor_role: UserRole | null;
  action: string;
  label: string;
  details: string | null;
}

/**
 * The timeline for one case, with the FR-46 intervals in seconds.
 *
 * Either interval may be null: a case with no recommendation has no first one,
 * an undecided case no second. Both are measured to the *first* recommendation
 * and the *first* decision, so a regeneration or an amendment does not reopen
 * them.
 */
export interface AuditTimeline {
  items: AuditTimelineItem[];
  submission_to_recommendation_s: number | null;
  recommendation_to_decision_s: number | null;
  /** A property of the database, which W-07 states as fact (FR-43, ADR-12). */
  append_only: boolean;
}

/** One case, for the Case Review screen (FR-31). */
export async function readCase(caseId: string): Promise<CaseDetail> {
  return apiFetch<CaseDetail>(`/cases/${caseId}`);
}

/** Confirm, adjust, or manually triage a case. Reviewers only (FR-35). */
export async function recordDecision(
  caseId: string,
  payload: DecisionRequest,
): Promise<CaseDecision> {
  return apiFetch<CaseDecision>(`/cases/${caseId}/decision`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** The 202 that follows a retry: the case is back to `SUBMITTED`. */
export interface CaseRetryAccepted {
  id: string;
  case_no: string;
  status: CaseStatus;
}

/** Run the AI pipeline again for a case it gave up on. Reviewers only (UC-08). */
export async function retryCase(caseId: string): Promise<CaseRetryAccepted> {
  return apiFetch<CaseRetryAccepted>(`/cases/${caseId}/retry`, { method: "POST" });
}

/** The 202 that follows a request for new suggested actions (FR-78). */
export interface ActionsRegenerationAccepted {
  id: string;
  case_no: string;
  /** The category the suggestions are being made for. */
  category: VTLCategory;
  /** The number of the set that will hold them; earlier sets are kept. */
  generation: number;
  actions_status: ActionsStatus;
}

/**
 * Suggest actions again for the category the case now has. Reviewers only.
 *
 * Changes no decision and no case status: the case keeps being what it was and
 * `actions_status` goes back to PENDING until the job lands.
 */
export async function regenerateActions(caseId: string): Promise<ActionsRegenerationAccepted> {
  return apiFetch<ActionsRegenerationAccepted>(`/cases/${caseId}/actions/regenerate`, {
    method: "POST",
  });
}

/**
 * The fields of a correction to the extracted information (UC-09, FR-27).
 *
 * Partial: only the fields present are changed, and a field sent as `null` or
 * `[]` is cleared deliberately. Species, signalment and the evidence spans are
 * not editable, and the server refuses a request that sends them.
 */
export interface ExtractionCorrection {
  presenting_complaints?: { code: string; is_primary: boolean }[];
  onset_duration?: string | null;
  frequency_severity?: string | null;
  associated_signs?: string[];
  negated_findings?: string[];
  exposure_history?: string | null;
  relevant_history?: string | null;
  red_flags?: string[];
  missing_information?: string[];
}

/** The 202 that follows a correction: the case is `PROCESSING` while it regenerates. */
export interface CorrectionAccepted {
  id: string;
  case_no: string;
  status: CaseStatus;
  extraction_version: number;
  /** Field names only, never values. Empty when an earlier failure was re-queued. */
  changed_fields: string[];
}

/** Correct the extracted information and regenerate. Reviewers only (FR-27). */
export async function correctExtraction(
  caseId: string,
  payload: ExtractionCorrection,
): Promise<CorrectionAccepted> {
  return apiFetch<CorrectionAccepted>(`/cases/${caseId}/extraction`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

/** One stored recommendation version, read-only (FR-27). */
export async function readRecommendationVersion(
  caseId: string,
  version: number,
): Promise<RecommendationVersionDetail> {
  return apiFetch<RecommendationVersionDetail>(`/cases/${caseId}/recommendations/${version}`);
}

/** Attach a clinical note to a case. Reviewers only (FR-37). */
export async function addCaseNote(caseId: string, text: string): Promise<CaseNote> {
  return apiFetch<CaseNote>(`/cases/${caseId}/notes`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

/** Close a case, removing it from the active queue. Reviewers only (FR-38). */
export async function closeCase(caseId: string): Promise<CaseClosed> {
  return apiFetch<CaseClosed>(`/cases/${caseId}/close`, { method: "POST" });
}

/** The chronological record of one case (FR-45, FR-46). */
export async function readCaseAudit(caseId: string): Promise<AuditTimeline> {
  return apiFetch<AuditTimeline>(`/cases/${caseId}/audit`);
}
