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
 * Record a new case (FR-01, FR-03).
 *
 * Answers 201 today; P05 starts the pipeline on submission and it becomes 202
 * (FR-06). `apiFetch` treats both as success, so nothing here changes then.
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
