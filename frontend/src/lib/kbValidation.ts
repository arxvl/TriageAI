/**
 * The client half of the W-08 editor's validation (FR-49, FR-50, IR-05).
 *
 * Every limit mirrors `content_problem` and `KBEntryCreate` in the backend's
 * `app/schemas/kb.py`, and the server still decides. This exists for the two
 * reasons `lib/caseValidation.ts` gives: it answers without a round trip, and it
 * reports every invalid field at once where the API reports only the first.
 *
 * One boundary is deliberately **not** mirrored. The drug, dose and diagnosis
 * block list that screens each line of a baseline action set lives in
 * `app/pipeline/action_validator.py` and stays there (CLAUDE.md §8): a second
 * copy in the browser would be a second definition of the AI safety boundary,
 * and the one that matters is the server's. A line it refuses comes back as a
 * 422 and is shown as written.
 *
 * Error keys are the API's field names (`source_title`, not `sourceTitle`), so a
 * `field` off an `ApiError` drops straight into the same map.
 */
import type { KBEntryCreateRequest, KBEntryKind, KBEntryUpdateRequest } from "../api/kb";
import type { Species, VTLCategory } from "../api/cases";
import { strings } from "../i18n/strings";

// Mirrors the module-level constants in `app/schemas/kb.py`.
export const CONTENT_MIN_WORDS = 50;
export const CONTENT_MAX_WORDS = 1_500;
export const ACTIONS_MIN_LINES = 3;
export const ACTIONS_MAX_LINES = 6;

export const TITLE_MAX_LENGTH = 300;
export const SOURCE_TITLE_MAX_LENGTH = 300;
export const SOURCE_PUBLISHER_MAX_LENGTH = 300;
export const SOURCE_URL_MAX_LENGTH = 1_000;

/** The API field names an error can be attached to. */
export const KB_ENTRY_FIELDS = [
  "title",
  "complaint_code",
  "urgency_category",
  "species",
  "content",
  "source_title",
  "source_publisher",
  "source_url",
  "access_date",
  "red_flag_codes",
] as const;

export type KBEntryField = (typeof KB_ENTRY_FIELDS)[number];

export type KBEntryFieldErrors = Partial<Record<KBEntryField, string>>;

/**
 * What the editor holds while an entry is being written.
 *
 * `kind` is fixed once the form opens: an entry does not change from clinical
 * content into a baseline action set, which is why the API's `KBEntryUpdate`
 * has no `kind` either (ADR-18).
 */
export interface KBEntryFormValues {
  kind: KBEntryKind;
  title: string;
  complaintCode: string;
  urgencyCategory: VTLCategory | "";
  species: Species[];
  content: string;
  sourceTitle: string;
  sourcePublisher: string;
  sourceUrl: string;
  /** `YYYY-MM-DD`, as the date input gives it and the API reads it. */
  accessDate: string;
}

/** A blank clinical entry. Both species, which is the common case for a draft. */
export function emptyEntryForm(kind: KBEntryKind = "COMPLAINT"): KBEntryFormValues {
  return {
    kind,
    title: "",
    complaintCode: "",
    urgencyCategory: "",
    species: ["DOG", "CAT"],
    content: "",
    sourceTitle: "",
    sourcePublisher: "",
    sourceUrl: "",
    accessDate: "",
  };
}

/** How many words the content holds. The mirror of `word_count` on the server. */
export function countWords(text: string): number {
  return text.split(/\s+/).filter((word) => word !== "").length;
}

/**
 * The actions a baseline set holds: its non-empty lines.
 *
 * The mirror of `action_lines` in `app/pipeline/action_validator.py`, so the
 * counter beside the field counts what the server will count.
 */
export function actionLines(content: string): string[] {
  return content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

/**
 * Why this content is not acceptable for an entry of this kind, or null.
 *
 * The bound depends on the kind, as it does on the server: a clinical entry is
 * 50–1,500 words, and a baseline action set is 3–6 imperative lines, which the
 * same word floor would reject (P08 §8.2b).
 */
export function contentProblem(content: string, kind: KBEntryKind): string | null {
  const messages = strings.knowledgeBase.errors;

  if (kind === "URGENCY_ACTIONS") {
    const lines = actionLines(content);
    if (lines.length < ACTIONS_MIN_LINES || lines.length > ACTIONS_MAX_LINES) {
      return messages.actionLineCount
        .replace("{min}", String(ACTIONS_MIN_LINES))
        .replace("{max}", String(ACTIONS_MAX_LINES))
        .replace("{count}", String(lines.length));
    }
    return null;
  }

  const words = countWords(content);
  if (words < CONTENT_MIN_WORDS || words > CONTENT_MAX_WORDS) {
    return messages.contentWordCount
      .replace("{min}", String(CONTENT_MIN_WORDS))
      .replace("{max}", CONTENT_MAX_WORDS.toLocaleString("en-US"))
      .replace("{count}", words.toLocaleString("en-US"));
  }
  return null;
}

/** The server's `field` value, if it names an input this form has. */
export function asKBEntryField(field: string | null | undefined): KBEntryField | null {
  if (field === null || field === undefined) {
    return null;
  }
  return (KB_ENTRY_FIELDS as readonly string[]).includes(field) ? (field as KBEntryField) : null;
}

/**
 * Every field-level problem in the editor, keyed by API field name.
 *
 * An empty object means the form may be sent. The four citation fields are all
 * required, whatever the kind: FR-50 allows no entry without the title,
 * publisher, URL and access date of the source it was written from.
 */
export function validateEntryForm(values: KBEntryFormValues): KBEntryFieldErrors {
  const messages = strings.knowledgeBase.errors;
  const errors: KBEntryFieldErrors = {};

  if (values.title.trim() === "") {
    errors.title = messages.titleMissing;
  } else if (values.title.trim().length > TITLE_MAX_LENGTH) {
    errors.title = messages.titleTooLong;
  }

  // Which of the two an entry needs is its kind, and the server's check
  // constraints state the same pairing (ADR-18).
  if (values.kind === "COMPLAINT") {
    if (values.complaintCode === "") {
      errors.complaint_code = messages.complaintMissing;
    }
  } else if (values.urgencyCategory === "") {
    errors.urgency_category = messages.urgencyCategoryMissing;
  }

  if (values.species.length === 0) {
    errors.species = messages.speciesMissing;
  }

  const content = values.content.trim();
  if (content === "") {
    errors.content = messages.contentMissing;
  } else {
    const problem = contentProblem(values.content, values.kind);
    if (problem !== null) {
      errors.content = problem;
    }
  }

  if (values.sourceTitle.trim() === "") {
    errors.source_title = messages.sourceTitleMissing;
  } else if (values.sourceTitle.trim().length > SOURCE_TITLE_MAX_LENGTH) {
    errors.source_title = messages.sourceTitleTooLong;
  }

  if (values.sourcePublisher.trim() === "") {
    errors.source_publisher = messages.sourcePublisherMissing;
  } else if (values.sourcePublisher.trim().length > SOURCE_PUBLISHER_MAX_LENGTH) {
    errors.source_publisher = messages.sourcePublisherTooLong;
  }

  if (values.sourceUrl.trim() === "") {
    errors.source_url = messages.sourceUrlMissing;
  } else if (values.sourceUrl.trim().length > SOURCE_URL_MAX_LENGTH) {
    errors.source_url = messages.sourceUrlTooLong;
  }

  if (values.accessDate.trim() === "") {
    errors.access_date = messages.accessDateMissing;
  }

  return errors;
}

/**
 * The first field with a problem, in the order the editor lays them out.
 *
 * Submit focuses it, so a message is never reported somewhere off screen
 * (IR-05, NFR-21).
 */
export function firstInvalidField(errors: KBEntryFieldErrors): KBEntryField | null {
  return KB_ENTRY_FIELDS.find((field) => errors[field] !== undefined) ?? null;
}

/**
 * The request body for a validated form.
 *
 * Only the field the kind allows is sent: the server forbids a `complaint_code`
 * on a baseline action set and an `urgency_category` on a clinical entry, so
 * sending the empty one would be a 422 rather than a no-op.
 */
export function toEntryCreateRequest(
  values: KBEntryFormValues,
  redFlagCodes: readonly string[] = [],
): KBEntryCreateRequest {
  const request: KBEntryCreateRequest = {
    kind: values.kind,
    title: values.title.trim(),
    species: [...values.species],
    content: values.content.trim(),
    source_title: values.sourceTitle.trim(),
    source_publisher: values.sourcePublisher.trim(),
    source_url: values.sourceUrl.trim(),
    access_date: values.accessDate,
  };

  if (values.kind === "COMPLAINT") {
    request.complaint_code = values.complaintCode;
    // Only a clinical entry explains a red-flag rule; a baseline action set is
    // the handling for a category, not for a sign (ADR-18).
    request.red_flag_codes = [...redFlagCodes];
  } else if (values.urgencyCategory !== "") {
    request.urgency_category = values.urgencyCategory;
  }

  return request;
}

/** The same body as a PATCH: every field, since the editor holds all of them. */
export function toEntryUpdateRequest(
  values: KBEntryFormValues,
  redFlagCodes: readonly string[] = [],
): KBEntryUpdateRequest {
  const body: KBEntryCreateRequest = toEntryCreateRequest(values, redFlagCodes);
  const update: KBEntryUpdateRequest = { ...body };
  // `kind` is not editable: an entry does not change from clinical content into
  // a baseline action set, and the API's `KBEntryUpdate` forbids the field.
  delete (update as { kind?: unknown }).kind;
  return update;
}

/** The form that matches an entry as it is stored, for editing a draft. */
export function entryFormFrom(entry: {
  kind: KBEntryKind;
  title: string;
  complaint_code: string | null;
  urgency_category: VTLCategory | null;
  species: Species[];
  content: string;
  source: {
    title: string | null;
    publisher: string | null;
    url: string | null;
    access_date: string | null;
  };
}): KBEntryFormValues {
  return {
    kind: entry.kind,
    title: entry.title,
    complaintCode: entry.complaint_code ?? "",
    urgencyCategory: entry.urgency_category ?? "",
    species: [...entry.species],
    content: entry.content,
    sourceTitle: entry.source.title ?? "",
    sourcePublisher: entry.source.publisher ?? "",
    sourceUrl: entry.source.url ?? "",
    accessDate: entry.source.access_date ?? "",
  };
}
