/**
 * The `/kb` endpoints: entries, their workflow, versions and red-flag rules
 * (FR-49..FR-56, NFR-08, BR-04).
 *
 * Field names match the API's own schemas verbatim — snake_case, no mapping
 * layer, the rule `api/cases.ts` follows.
 *
 * Three things in these types are the workflow itself, not shapes:
 *
 * - **`approveEntry` answers 202, not 200.** The entry is still
 *   `PENDING_REVIEW` and `job_id` names the `KB_INDEX` job that will index it
 *   and publish version N+1. It becomes `ACTIVE` when that job succeeds, so the
 *   screen reads `indexing` back rather than assuming (FR-52, FR-53, ADR-08).
 * - **`version_no` is set only by an action that published a version.**
 *   Retiring an entry and approving or retiring a rule do; submitting does not
 *   (FR-54).
 * - **`warning` is a consequence nothing refused.** Retiring the last baseline
 *   action set for a category leaves it with no baseline actions until a
 *   replacement is approved, and only the person retiring it is in a position
 *   to notice (FR-72).
 *
 * `Species` and `VTLCategory` are imported rather than redeclared: the knowledge
 * base and a case speak about the same five categories and the same two species
 * (CLAUDE.md §6).
 */
import type { Species, VTLCategory } from "./cases";
import { apiFetch } from "./client";

export type KBEntryStatus = "DRAFT" | "PENDING_REVIEW" | "ACTIVE" | "RETIRED";

/** `COMPLAINT` is retrievable clinical content; `URGENCY_ACTIONS` is one
 * category's baseline staff actions, looked up by category (ADR-18). */
export type KBEntryKind = "COMPLAINT" | "URGENCY_ACTIONS";

export type JobStatus = "QUEUED" | "RUNNING" | "DONE" | "FAILED";

/**
 * How often the screen re-reads an entry whose indexing is still running.
 *
 * Used only while `indexing.status` is `QUEUED` or `RUNNING`: indexing one entry
 * takes seconds, and the approver is watching the panel when it does
 * (FR-53, IR-22).
 */
export const KB_INDEX_POLL_INTERVAL_MS = 3_000;

export interface SourceCitation {
  title: string | null;
  publisher: string | null;
  url: string | null;
  /** ISO calendar date, as the API sends it. */
  access_date: string | null;
}

/**
 * What happened the last time this entry was indexed (FR-53).
 *
 * `error` is the job's reason code, never a model response or a traceback
 * (CLAUDE.md §9). `null` for an entry that has never been approved.
 */
export interface IndexingState {
  status: JobStatus;
  error: string | null;
  queued_at: string;
}

export interface KBEntrySummary {
  id: string;
  slug: string | null;
  kind: KBEntryKind;
  title: string;
  complaint_code: string | null;
  urgency_category: VTLCategory | null;
  species: Species[];
  status: KBEntryStatus;
  word_count: number;
  source_title: string | null;
}

export interface KBEntryDetail {
  id: string;
  slug: string | null;
  kind: KBEntryKind;
  title: string;
  complaint_code: string | null;
  urgency_category: VTLCategory | null;
  species: Species[];
  content: string;
  word_count: number;
  status: KBEntryStatus;
  source: SourceCitation;
  red_flag_codes: string[];
  created_by_name: string | null;
  approved_by_name: string | null;
  approved_at: string | null;
  /** The approver's rejection text, for the author to act on (FR-51). */
  review_comments: string | null;
  revises_entry_id: string | null;
  indexing: IndexingState | null;
}

/**
 * The entry list plus the tab counters.
 *
 * The counts always describe the whole knowledge base, so switching tabs or
 * filtering by kind never moves the numbers — the same contract as the queue's
 * counters (FR-39).
 */
export interface KBEntryListResponse {
  items: KBEntrySummary[];
  counts: Record<KBEntryStatus, number>;
  published_version_no: number | null;
  active_entry_count: number;
}

export interface KBEntryActionResult {
  id: string;
  status: KBEntryStatus;
  version_no: number | null;
  job_id: string | null;
  warning: string | null;
}

export interface KBVersionSummary {
  id: string;
  version_no: number;
  published_at: string | null;
  published_by_name: string | null;
  note: string | null;
  entry_count: number;
}

export interface KBVersionDetail extends KBVersionSummary {
  entries: KBEntrySummary[];
}

/**
 * One red-flag rule (FR-12, FR-23, NFR-08).
 *
 * `is_active` is the answer the pipeline's `get_active_rules` would give for
 * this rule in the running environment, so the table cannot imply that an
 * unapproved placeholder is screening cases.
 */
export interface RedFlagRuleOut {
  id: string;
  code: string;
  label: string;
  min_category: VTLCategory;
  species: Species[];
  phrases_ref: string | null;
  is_placeholder: boolean;
  approved_by_name: string | null;
  approved_at: string | null;
  retired_at: string | null;
  is_active: boolean;
}

export interface RedFlagRuleActionResult {
  id: string;
  code: string;
  version_no: number | null;
}

/** One choice in the editor's presenting-complaint select (FR-10). */
export interface ComplaintOption {
  code: string;
  name: string;
}

/**
 * A new draft entry (FR-49, FR-50).
 *
 * The server forbids unknown fields and refuses a `complaint_code` on a
 * baseline action set or an `urgency_category` on a clinical entry, so an
 * omitted field is left out of the JSON entirely rather than sent as null.
 */
export interface KBEntryCreateRequest {
  kind: KBEntryKind;
  title: string;
  complaint_code?: string;
  urgency_category?: VTLCategory;
  species: Species[];
  content: string;
  source_title: string;
  source_publisher: string;
  source_url: string;
  /** ISO calendar date. */
  access_date: string;
  slug?: string;
  red_flag_codes?: string[];
}

/** An edit to a draft: only what is sent changes. */
export type KBEntryUpdateRequest = Partial<Omit<KBEntryCreateRequest, "kind" | "slug">>;

export interface KBEntryFilters {
  status?: KBEntryStatus;
  kind?: KBEntryKind;
}

/**
 * The W-08 catalogue (FR-51, P08 §8.3).
 *
 * An absent filter is left out of the query string rather than sent blank: the
 * server's `KBEntryFilters` forbids unknown and malformed parameters.
 */
export async function listEntries(filters: KBEntryFilters = {}): Promise<KBEntryListResponse> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") {
      params.set(key, value);
    }
  }

  const query = params.toString();
  return apiFetch<KBEntryListResponse>(query === "" ? "/kb/entries" : `/kb/entries?${query}`);
}

export async function readEntry(entryId: string): Promise<KBEntryDetail> {
  return apiFetch<KBEntryDetail>(`/kb/entries/${entryId}`);
}

export async function createEntry(payload: KBEntryCreateRequest): Promise<KBEntryDetail> {
  return apiFetch<KBEntryDetail>("/kb/entries", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateEntry(
  entryId: string,
  payload: KBEntryUpdateRequest,
): Promise<KBEntryDetail> {
  return apiFetch<KBEntryDetail>(`/kb/entries/${entryId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function submitEntry(entryId: string): Promise<KBEntryActionResult> {
  return apiFetch<KBEntryActionResult>(`/kb/entries/${entryId}/submit`, { method: "POST" });
}

/** Approve an entry. See the module docblock: this enqueues indexing (FR-53). */
export async function approveEntry(entryId: string): Promise<KBEntryActionResult> {
  return apiFetch<KBEntryActionResult>(`/kb/entries/${entryId}/approve`, { method: "POST" });
}

export async function rejectEntry(entryId: string, comments: string): Promise<KBEntryActionResult> {
  return apiFetch<KBEntryActionResult>(`/kb/entries/${entryId}/reject`, {
    method: "POST",
    body: JSON.stringify({ comments }),
  });
}

export async function retireEntry(entryId: string): Promise<KBEntryActionResult> {
  return apiFetch<KBEntryActionResult>(`/kb/entries/${entryId}/retire`, { method: "POST" });
}

export async function listVersions(): Promise<KBVersionSummary[]> {
  return apiFetch<KBVersionSummary[]>("/kb/versions");
}

export async function readVersion(versionId: string): Promise<KBVersionDetail> {
  return apiFetch<KBVersionDetail>(`/kb/versions/${versionId}`);
}

export async function listRedFlagRules(): Promise<RedFlagRuleOut[]> {
  return apiFetch<RedFlagRuleOut[]>("/kb/red-flag-rules");
}

export async function approveRedFlagRule(ruleId: string): Promise<RedFlagRuleActionResult> {
  return apiFetch<RedFlagRuleActionResult>(`/kb/red-flag-rules/${ruleId}/approve`, {
    method: "POST",
  });
}

export async function retireRedFlagRule(ruleId: string): Promise<RedFlagRuleActionResult> {
  return apiFetch<RedFlagRuleActionResult>(`/kb/red-flag-rules/${ruleId}/retire`, {
    method: "POST",
  });
}

export async function listComplaints(): Promise<ComplaintOption[]> {
  return apiFetch<ComplaintOption[]>("/kb/complaints");
}
