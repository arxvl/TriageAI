/**
 * The W-08 editor: writing a knowledge-base entry (FR-49, FR-50, IR-05, ADR-18).
 *
 * Administrator-only, and open for a draft or a new entry only — an active entry
 * is never edited in place (ADR-14). Four things it insists on:
 *
 * 1. **The citation is required, all four fields.** FR-50 allows no entry
 *    without the title, publisher, URL and access date of its source, and the
 *    server checks the stored row again on submit.
 * 2. **The content is written, not copied.** The helper under the field says so
 *    in W-08's own words, and the counter shows what the server will count.
 * 3. **The kind decides the shape.** A clinical entry is filed under a
 *    presenting complaint and is 50–1,500 words; a baseline action set belongs
 *    to one VTL category and is 3–6 imperative lines (ADR-18, P08 §8.2b).
 * 4. **Every problem is reported at once**, beside the field it belongs to, and
 *    Submit moves focus to the first one (IR-05, NFR-21).
 *
 * The drug, dose and diagnosis boundary on a baseline action line is the
 * server's and is not mirrored here (CLAUDE.md §8): a line it refuses comes
 * back as a 422 and is shown against the content field.
 */
import { useId, useState, type ReactNode } from "react";

import type { Species, VTLCategory } from "../../api/cases";
import type { ComplaintOption, KBEntryKind, RedFlagRuleOut } from "../../api/kb";
import { strings } from "../../i18n/strings";
import {
  ACTIONS_MAX_LINES,
  ACTIONS_MIN_LINES,
  CONTENT_MAX_WORDS,
  CONTENT_MIN_WORDS,
  actionLines,
  asKBEntryField,
  countWords,
  emptyEntryForm,
  firstInvalidField,
  validateEntryForm,
  type KBEntryFieldErrors,
  type KBEntryFormValues,
} from "../../lib/kbValidation";
import { URGENCY_ORDER } from "../../lib/vtl";
import type { ServerFieldError } from "./catalogue";
import styles from "./KnowledgeBase.module.css";

const copy = strings.knowledgeBase;
const editorCopy = copy.editor;

const SPECIES_OPTIONS: readonly Species[] = ["DOG", "CAT"];

export function EntryEditor({
  values: initialValues,
  kind,
  redFlagCodes: initialCodes,
  complaints,
  rules,
  isSaving,
  serverError,
  onSave,
  onSubmit,
  onCancel,
}: {
  /** The stored draft being edited, or undefined for a new entry. */
  values: KBEntryFormValues | undefined;
  kind: KBEntryKind;
  redFlagCodes: readonly string[];
  complaints: readonly ComplaintOption[];
  rules: readonly RedFlagRuleOut[];
  isSaving: boolean;
  /** A 422 the server answered with, keyed to one of this form's fields. */
  serverError: ServerFieldError | null;
  onSave: (values: KBEntryFormValues, codes: string[]) => void;
  onSubmit: (values: KBEntryFormValues, codes: string[]) => void;
  onCancel: () => void;
}) {
  const fieldId = useId();
  const [values, setValues] = useState<KBEntryFormValues>(initialValues ?? emptyEntryForm(kind));
  const [codes, setCodes] = useState<string[]>([...initialCodes]);
  const [errors, setErrors] = useState<KBEntryFieldErrors>({});

  const isActionSet = values.kind === "URGENCY_ACTIONS";
  // The server's message, merged in so a field shows whichever problem is
  // current: the client found it, or the server answered with it.
  const serverField = asKBEntryField(serverError?.field);
  const shown: KBEntryFieldErrors =
    serverField === null || serverError === null
      ? errors
      : { ...errors, [serverField]: serverError.message };

  function set<K extends keyof KBEntryFormValues>(key: K, value: KBEntryFormValues[K]) {
    setValues((previous) => ({ ...previous, [key]: value }));
  }

  function toggleSpecies(species: Species) {
    setValues((previous) => ({
      ...previous,
      species: previous.species.includes(species)
        ? previous.species.filter((name) => name !== species)
        : [...previous.species, species],
    }));
  }

  function toggleCode(code: string) {
    setCodes((previous) =>
      previous.includes(code) ? previous.filter((name) => name !== code) : [...previous, code],
    );
  }

  /** Validate, then hand the form over — or focus the first problem (IR-05). */
  function attempt(action: (values: KBEntryFormValues, codes: string[]) => void) {
    const found = validateEntryForm(values);
    setErrors(found);

    const first = firstInvalidField(found);
    if (first !== null) {
      document.getElementById(`${fieldId}-${first}`)?.focus();
      return;
    }
    action(values, codes);
  }

  return (
    <form
      className={styles.editor}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        attempt(onSubmit);
      }}
    >
      <h2 className={styles.detailTitle}>
        {initialValues === undefined ? editorCopy.headingNew : editorCopy.headingEdit}
      </h2>
      <p className={styles.note}>{copy.kinds[values.kind]}</p>

      <Field
        id={`${fieldId}-title`}
        label={editorCopy.titleLabel}
        error={shown.title}
        errorId={`${fieldId}-title-error`}
      >
        <input
          id={`${fieldId}-title`}
          className={styles.input}
          type="text"
          value={values.title}
          aria-invalid={shown.title !== undefined}
          aria-describedby={shown.title === undefined ? undefined : `${fieldId}-title-error`}
          onChange={(event) => set("title", event.target.value)}
        />
      </Field>

      {isActionSet ? (
        <Field
          id={`${fieldId}-urgency_category`}
          label={editorCopy.urgencyCategoryLabel}
          error={shown.urgency_category}
          errorId={`${fieldId}-urgency_category-error`}
        >
          <select
            id={`${fieldId}-urgency_category`}
            className={styles.select}
            value={values.urgencyCategory}
            aria-invalid={shown.urgency_category !== undefined}
            onChange={(event) => set("urgencyCategory", event.target.value as VTLCategory | "")}
          >
            <option value="">{editorCopy.urgencyCategoryPlaceholder}</option>
            {URGENCY_ORDER.map((category) => (
              <option key={category} value={category}>
                {/* The code and the name together, never the colour alone (IR-03). */}
                {`${strings.vtl.codes[category]} · ${strings.vtl.labels[category]}`}
              </option>
            ))}
          </select>
        </Field>
      ) : (
        <Field
          id={`${fieldId}-complaint_code`}
          label={editorCopy.complaintLabel}
          error={shown.complaint_code}
          errorId={`${fieldId}-complaint_code-error`}
        >
          <select
            id={`${fieldId}-complaint_code`}
            className={styles.select}
            value={values.complaintCode}
            aria-invalid={shown.complaint_code !== undefined}
            onChange={(event) => set("complaintCode", event.target.value)}
          >
            <option value="">{editorCopy.complaintPlaceholder}</option>
            {complaints.map((option) => (
              <option key={option.code} value={option.code}>
                {option.name}
              </option>
            ))}
          </select>
        </Field>
      )}

      <fieldset className={styles.fieldset}>
        <legend className={styles.fieldLabel}>{editorCopy.speciesLabel}</legend>
        <div className={styles.checkboxRow}>
          {SPECIES_OPTIONS.map((species, index) => (
            <label key={species} className={styles.checkbox}>
              <input
                // The first box carries the field's id, so focusing the field
                // after a failed submit lands inside the group (IR-05).
                id={index === 0 ? `${fieldId}-species` : undefined}
                type="checkbox"
                checked={values.species.includes(species)}
                onChange={() => toggleSpecies(species)}
              />
              {copy.species[species]}
            </label>
          ))}
        </div>
        <FieldError id={`${fieldId}-species-error`} message={shown.species} />
      </fieldset>

      <Field
        id={`${fieldId}-content`}
        label={editorCopy.contentLabel}
        error={shown.content}
        errorId={`${fieldId}-content-error`}
      >
        <p className={styles.helper} id={`${fieldId}-content-helper`}>
          {isActionSet ? editorCopy.actionsHelper : editorCopy.contentHelper}
        </p>
        <textarea
          id={`${fieldId}-content`}
          className={styles.textarea}
          rows={isActionSet ? 7 : 12}
          value={values.content}
          aria-invalid={shown.content !== undefined}
          aria-describedby={`${fieldId}-content-helper ${fieldId}-content-counter`}
          onChange={(event) => set("content", event.target.value)}
        />
        {/* Not a live region: a count that announced every keystroke would make
            the field unusable with a screen reader (NFR-21). */}
        <p className={styles.counter} id={`${fieldId}-content-counter`} aria-live="off">
          {counterText(values)}
        </p>
      </Field>

      {!isActionSet && (
        <fieldset className={styles.fieldset}>
          <legend className={styles.fieldLabel}>{editorCopy.redFlagsLabel}</legend>
          <p className={styles.helper}>{editorCopy.redFlagsHint}</p>
          {rules.length === 0 ? (
            <p className={styles.note}>{editorCopy.redFlagsEmpty}</p>
          ) : (
            <div className={styles.checkboxColumn}>
              {rules.map((rule) => (
                <label key={rule.id} className={styles.checkbox}>
                  <input
                    type="checkbox"
                    checked={codes.includes(rule.code)}
                    onChange={() => toggleCode(rule.code)}
                  />
                  {`${rule.label} · ${strings.vtl.codes[rule.min_category]} ${
                    copy.detail.minimumSuffix
                  }`}
                </label>
              ))}
            </div>
          )}
        </fieldset>
      )}

      <fieldset className={styles.fieldset}>
        <legend className={styles.fieldLabel}>{editorCopy.citationLegend}</legend>

        <Field
          id={`${fieldId}-source_title`}
          label={editorCopy.sourceTitleLabel}
          error={shown.source_title}
          errorId={`${fieldId}-source_title-error`}
        >
          <input
            id={`${fieldId}-source_title`}
            className={styles.input}
            type="text"
            value={values.sourceTitle}
            aria-invalid={shown.source_title !== undefined}
            onChange={(event) => set("sourceTitle", event.target.value)}
          />
        </Field>

        <Field
          id={`${fieldId}-source_publisher`}
          label={editorCopy.sourcePublisherLabel}
          error={shown.source_publisher}
          errorId={`${fieldId}-source_publisher-error`}
        >
          <input
            id={`${fieldId}-source_publisher`}
            className={styles.input}
            type="text"
            value={values.sourcePublisher}
            aria-invalid={shown.source_publisher !== undefined}
            onChange={(event) => set("sourcePublisher", event.target.value)}
          />
        </Field>

        <Field
          id={`${fieldId}-source_url`}
          label={editorCopy.sourceUrlLabel}
          error={shown.source_url}
          errorId={`${fieldId}-source_url-error`}
        >
          <input
            id={`${fieldId}-source_url`}
            className={styles.input}
            type="url"
            value={values.sourceUrl}
            aria-invalid={shown.source_url !== undefined}
            onChange={(event) => set("sourceUrl", event.target.value)}
          />
        </Field>

        <Field
          id={`${fieldId}-access_date`}
          label={editorCopy.accessDateLabel}
          error={shown.access_date}
          errorId={`${fieldId}-access_date-error`}
        >
          <input
            id={`${fieldId}-access_date`}
            className={styles.input}
            type="date"
            value={values.accessDate}
            aria-invalid={shown.access_date !== undefined}
            onChange={(event) => set("accessDate", event.target.value)}
          />
        </Field>
      </fieldset>

      <div className={styles.actions}>
        <button
          type="button"
          className={styles.secondary}
          disabled={isSaving}
          onClick={() => attempt(onSave)}
        >
          {editorCopy.saveDraft}
        </button>
        <button type="submit" className={styles.primary} disabled={isSaving}>
          {editorCopy.submitForReview}
        </button>
        <button type="button" className={styles.link} disabled={isSaving} onClick={onCancel}>
          {editorCopy.cancel}
        </button>
      </div>
    </form>
  );
}

/** "132 words (needs 50–1,500)", or the line count for a baseline action set. */
function counterText(values: KBEntryFormValues): string {
  if (values.kind === "URGENCY_ACTIONS") {
    return editorCopy.actionsCounter
      .replace("{count}", String(actionLines(values.content).length))
      .replace("{min}", String(ACTIONS_MIN_LINES))
      .replace("{max}", String(ACTIONS_MAX_LINES));
  }
  return editorCopy.contentCounter
    .replace("{count}", countWords(values.content).toLocaleString("en-US"))
    .replace("{min}", String(CONTENT_MIN_WORDS))
    .replace("{max}", CONTENT_MAX_WORDS.toLocaleString("en-US"));
}

function Field({
  id,
  label,
  error,
  errorId,
  children,
}: {
  id: string;
  label: string;
  error: string | undefined;
  errorId: string;
  children: ReactNode;
}) {
  return (
    <div className={styles.field}>
      <label className={styles.fieldLabel} htmlFor={id}>
        {label}
      </label>
      {children}
      <FieldError id={errorId} message={error} />
    </div>
  );
}

/**
 * The message under one control.
 *
 * Always rendered, even when empty, so the live region exists before the first
 * message arrives — the same reason the intake form's error paragraphs do.
 */
function FieldError({ id, message }: { id: string; message: string | undefined }) {
  return (
    <p className={styles.fieldError} id={id} role={message === undefined ? undefined : "alert"}>
      {message ?? ""}
    </p>
  );
}
