/**
 * W-03 Case Intake (FR-01, FR-02, FR-04, FR-07, FR-18 · UC-02).
 *
 * Three rules shape this screen more than the layout does:
 *
 * 1. **Dogs and cats only.** "Other species" is a button the form offers and then
 *    refuses: it shows the manual-triage message and disables Submit (FR-02). The
 *    server answers `SPECIES_OUT_OF_SCOPE` if a request gets through anyway.
 * 2. **Nothing the user typed is ever thrown away.** Every value lives in one
 *    state object, and an error only adds a message beside a field (FR-04).
 * 3. **The owner's name and number are not part of the case.** They go in their
 *    own box, with their own caption, and the server stores them in a separate
 *    table that no pipeline reads (FR-07, DR-04).
 *
 * Validation runs here as well as on the server, because the API reports only the
 * first failure it finds while FR-04 asks for field-level errors; the limits and
 * the wording both come from `lib/caseValidation.ts`, which mirrors the server.
 *
 * All text is English and comes from `i18n/strings.ts` or
 * `content/redFlagSigns.ts` (FR-18, NFR-27, ADR-16).
 */
import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { createCase, type AgeUnit, type IntakeChannel, type SpeciesInput } from "../../api/cases";
import { ApiErrorCode, isApiError } from "../../api/errors";
import { SegmentedControl } from "../../components/SegmentedControl";
import { redFlagPanel } from "../../content/redFlagSigns";
import { useToast } from "../../hooks/useToast";
import { strings } from "../../i18n/strings";
import {
  asCaseField,
  DESCRIPTION_MAX_LENGTH,
  emptyCaseForm,
  toCaseCreateRequest,
  validateCaseForm,
  type CaseField,
  type CaseFieldErrors,
  type CaseFormValues,
  type SexNeuterChoice,
} from "../../lib/caseValidation";
import styles from "./CaseIntake.module.css";

const copy = strings.caseIntake;

const DESCRIPTION_HELPER_ID = "description-helper";
const SPECIES_NOTICE_ID = "species-notice";
const FORM_ERROR_ID = "case-intake-error";
const PROCESSING_ID = "case-intake-processing";

/**
 * How long the "Processing…" notice stays before the queue takes over (FR-06).
 *
 * A deliberate pause, not a wait for anything: the 202 has already arrived and the
 * pipeline runs in the background (ADR-08). Without it the notice would exist for
 * one microtask and nobody would read it — and what it tells the user is the thing
 * the queue cannot, that *this* case is the one now being worked on.
 */
const PROCESSING_NOTICE_MS = 900;

const SPECIES_OPTIONS: readonly { value: SpeciesInput; label: string }[] = [
  { value: "DOG", label: copy.species.DOG },
  { value: "CAT", label: copy.species.CAT },
  { value: "OTHER", label: copy.species.OTHER },
];

const INTAKE_CHANNEL_OPTIONS: readonly { value: IntakeChannel; label: string }[] = [
  { value: "WALK_IN", label: copy.intakeChannels.WALK_IN },
  { value: "PHONE", label: copy.intakeChannels.PHONE },
  { value: "MESSAGE", label: copy.intakeChannels.MESSAGE },
];

const AGE_UNIT_OPTIONS: readonly { value: AgeUnit; label: string }[] = [
  { value: "YEARS", label: copy.ageUnits.YEARS },
  { value: "MONTHS", label: copy.ageUnits.MONTHS },
];

/** One control for the API's `sex` and `neutered`, as W-03 draws it. */
const SEX_OPTIONS: readonly { value: SexNeuterChoice; label: string }[] = [
  { value: "UNKNOWN", label: copy.sexOptions.UNKNOWN },
  { value: "MALE_INTACT", label: copy.sexOptions.MALE_INTACT },
  { value: "MALE_NEUTERED", label: copy.sexOptions.MALE_NEUTERED },
  { value: "FEMALE_INTACT", label: copy.sexOptions.FEMALE_INTACT },
  { value: "FEMALE_SPAYED", label: copy.sexOptions.FEMALE_SPAYED },
];

/** Which API field each input owns, so editing one clears its own message. */
const FIELD_OF_INPUT: Record<keyof CaseFormValues, CaseField> = {
  species: "species",
  petName: "pet_name",
  ageValue: "age_value",
  ageUnit: "age_unit",
  sexNeuter: "sex",
  breed: "breed",
  weightKg: "weight_kg",
  intakeChannel: "intake_channel",
  description: "description",
  ownerName: "owner_name",
  contactNumber: "contact_number",
};

/**
 * How to reach each field's control, in the order the screen reads.
 *
 * A refused submit moves focus to the first field with a problem, which is what
 * makes the message beside it reach a screen reader (IR-05, NFR-21).
 */
const FOCUS_ORDER: readonly { field: CaseField; selector: string }[] = [
  { field: "species", selector: 'input[name="species"]' },
  { field: "pet_name", selector: "#pet-name" },
  { field: "age_value", selector: "#age-value" },
  { field: "age_unit", selector: "#age-unit" },
  { field: "sex", selector: "#sex-neuter" },
  { field: "neutered", selector: "#sex-neuter" },
  { field: "breed", selector: "#breed" },
  { field: "weight_kg", selector: "#weight-kg" },
  { field: "intake_channel", selector: 'input[name="intake-channel"]' },
  { field: "description", selector: "#description" },
  { field: "owner_name", selector: "#owner-name" },
  { field: "contact_number", selector: "#contact-number" },
];

export function CaseIntake() {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const formRef = useRef<HTMLFormElement>(null);

  const [values, setValues] = useState<CaseFormValues>(emptyCaseForm);
  const [fieldErrors, setFieldErrors] = useState<CaseFieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  /**
   * The case number the server just assigned, while the pipeline has it (FR-06).
   *
   * Set on a 202 and never cleared: the screen's job is finished at that point and
   * the navigation to the queue follows, so the notice is what the user reads in
   * between rather than a state the form returns from.
   */
  const [processingCaseNo, setProcessingCaseNo] = useState<string | null>(null);

  const isOtherSpecies = values.species === "OTHER";

  function update<K extends keyof CaseFormValues>(key: K, value: CaseFormValues[K]) {
    setValues((previous) => ({ ...previous, [key]: value }));
    // Correcting a field retires its message; the value itself is never touched.
    setFieldErrors((previous) => {
      const field = FIELD_OF_INPUT[key];
      if (previous[field] === undefined) {
        return previous;
      }
      const next = { ...previous };
      delete next[field];
      return next;
    });
  }

  function focusFirstError(errors: CaseFieldErrors) {
    const first = FOCUS_ORDER.find((entry) => errors[entry.field] !== undefined);
    if (first === undefined) {
      return;
    }
    formRef.current?.querySelector<HTMLElement>(first.selector)?.focus();
  }

  function reportServerError(caught: unknown) {
    if (!isApiError(caught)) {
      setFormError(copy.errors.unexpected);
      return;
    }

    // FR-02. The server names no field for this one, because the field is the
    // species control itself.
    if (caught.code === ApiErrorCode.speciesOutOfScope) {
      const errors: CaseFieldErrors = { species: caught.message };
      setFieldErrors(errors);
      focusFirstError(errors);
      return;
    }

    const field = asCaseField(caught.field);
    if (caught.code === ApiErrorCode.validationError && field !== null) {
      const errors: CaseFieldErrors = { [field]: caught.message };
      setFieldErrors(errors);
      focusFirstError(errors);
      return;
    }

    // A validation error about no particular field still says something useful;
    // anything else stays generic so no internal detail reaches the user (IR-05).
    setFormError(
      caught.code === ApiErrorCode.validationError ? caught.message : copy.errors.unexpected,
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    const errors = validateCaseForm(values);
    if (Object.keys(errors).length > 0 || values.species === null) {
      setFieldErrors(errors);
      focusFirstError(errors);
      return;
    }

    setFieldErrors({});
    setIsSubmitting(true);
    try {
      const created = await createCase(toCaseCreateRequest({ ...values, species: values.species }));
      // 202: the case is recorded and a worker has the pipeline job (ADR-08). The
      // notice says so before the queue takes over, so submitting never looks like
      // nothing happened while the browser navigates.
      setProcessingCaseNo(created.case_no);
      showToast(copy.submittedToast.replace("{caseNo}", created.case_no));
      await new Promise((resolve) => setTimeout(resolve, PROCESSING_NOTICE_MS));
      await navigate("/queue");
    } catch (caught) {
      // Submitting is finished only on the failing path; on the successful one the
      // button stays disabled through the navigation, so one case cannot be
      // submitted twice.
      setIsSubmitting(false);
      reportServerError(caught);
    }
  }

  const speciesDescribedBy =
    [
      isOtherSpecies ? SPECIES_NOTICE_ID : null,
      !isOtherSpecies && fieldErrors.species !== undefined ? "species-error" : null,
    ]
      .filter((id) => id !== null)
      .join(" ") || undefined;

  const counter = copy.descriptionCounter
    .replace("{count}", values.description.length.toLocaleString("en-US"))
    .replace("{max}", DESCRIPTION_MAX_LENGTH.toLocaleString("en-US"));

  const descriptionDescribedBy = [
    DESCRIPTION_HELPER_ID,
    fieldErrors.description !== undefined ? "description-error" : null,
  ]
    .filter((id) => id !== null)
    .join(" ");

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>{copy.title}</h1>

      <div className={styles.row}>
        <form
          ref={formRef}
          className={styles.card}
          onSubmit={(event) => void handleSubmit(event)}
          noValidate
        >
          <SegmentedControl
            name="species"
            legend={copy.speciesLabel}
            options={SPECIES_OPTIONS}
            value={values.species}
            onChange={(value) => update("species", value)}
            describedBy={speciesDescribedBy}
            invalid={isOtherSpecies || fieldErrors.species !== undefined}
          />
          {isOtherSpecies ? (
            // FR-02: the same sentence the server would answer with, shown before
            // the user can send anything.
            <p id={SPECIES_NOTICE_ID} className={styles.notice}>
              {copy.errors.speciesOutOfScope}
            </p>
          ) : (
            fieldErrors.species !== undefined && (
              <p id="species-error" className={styles.fieldError}>
                {fieldErrors.species}
              </p>
            )
          )}

          <div className={styles.grid3}>
            <TextField
              id="pet-name"
              label={copy.petNameLabel}
              value={values.petName}
              error={fieldErrors.pet_name}
              onChange={(value) => update("petName", value)}
            />

            <div className={styles.field}>
              <Label htmlFor="age-value" optional>
                {copy.ageLabel}
              </Label>
              <div className={styles.ageRow}>
                <input
                  id="age-value"
                  className={`${controlClass(fieldErrors.age_value)} ${styles.ageValue}`}
                  type="text"
                  inputMode="decimal"
                  autoComplete="off"
                  value={values.ageValue}
                  aria-invalid={fieldErrors.age_value !== undefined}
                  aria-describedby={
                    fieldErrors.age_value === undefined ? undefined : "age-value-error"
                  }
                  onChange={(event) => update("ageValue", event.target.value)}
                />
                {/* The visible "Age" label belongs to the number; the unit still
                    needs a name of its own. */}
                <label className="visuallyHidden" htmlFor="age-unit">
                  {copy.ageUnitLabel}
                </label>
                <select
                  id="age-unit"
                  className={`${styles.input} ${styles.ageUnit}`}
                  value={values.ageUnit}
                  onChange={(event) => update("ageUnit", event.target.value as AgeUnit)}
                >
                  {AGE_UNIT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <FieldError id="age-value-error" message={fieldErrors.age_value} />
            </div>

            <div className={styles.field}>
              <Label htmlFor="sex-neuter" optional>
                {copy.sexLabel}
              </Label>
              <select
                id="sex-neuter"
                className={styles.input}
                value={values.sexNeuter}
                onChange={(event) => update("sexNeuter", event.target.value as SexNeuterChoice)}
              >
                {SEX_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            <TextField
              id="breed"
              label={copy.breedLabel}
              value={values.breed}
              error={fieldErrors.breed}
              onChange={(value) => update("breed", value)}
            />

            <TextField
              id="weight-kg"
              label={copy.weightLabel}
              value={values.weightKg}
              error={fieldErrors.weight_kg}
              inputMode="decimal"
              onChange={(value) => update("weightKg", value)}
            />

            <div className={styles.field}>
              <SegmentedControl
                name="intake-channel"
                legend={copy.intakeChannelLabel}
                options={INTAKE_CHANNEL_OPTIONS}
                value={values.intakeChannel}
                onChange={(value) => update("intakeChannel", value)}
              />
            </div>
          </div>

          <div className={styles.descriptionBlock}>
            <label className={styles.label} htmlFor="description">
              {copy.descriptionLabel}
            </label>
            <textarea
              id="description"
              className={
                fieldErrors.description === undefined ? styles.textarea : styles.textareaInvalid
              }
              value={values.description}
              aria-invalid={fieldErrors.description !== undefined}
              aria-describedby={descriptionDescribedBy}
              onChange={(event) => update("description", event.target.value)}
            />
            <div className={styles.helperRow}>
              {/* FR-18: staff translate at intake. No detection, no translation. */}
              <p id={DESCRIPTION_HELPER_ID} className={styles.helper}>
                {copy.descriptionHelper}
              </p>
              {/* Not a live region: it would read out on every keystroke. */}
              <p className={styles.counter} aria-hidden="true">
                {counter}
              </p>
            </div>
            <FieldError id="description-error" message={fieldErrors.description} />
          </div>

          <div className={styles.pane}>
            <p className={styles.paneTitle}>
              <strong>{copy.ownerReferenceTitle}</strong>{" "}
              <span className={styles.caption}>&ndash; {copy.ownerReferenceCaption}</span>
            </p>
            <div className={styles.grid2}>
              <TextField
                id="owner-name"
                label={copy.ownerNameLabel}
                optional={false}
                value={values.ownerName}
                error={fieldErrors.owner_name}
                onChange={(value) => update("ownerName", value)}
              />
              <TextField
                id="contact-number"
                label={copy.contactNumberLabel}
                optional={false}
                value={values.contactNumber}
                error={fieldErrors.contact_number}
                onChange={(value) => update("contactNumber", value)}
              />
            </div>
          </div>

          {/* Always rendered so the live region exists before the first failure. */}
          <p id={FORM_ERROR_ID} className={styles.formError} role="alert">
            {formError}
          </p>

          {processingCaseNo !== null && (
            <p id={PROCESSING_ID} className={styles.processing} role="status">
              {copy.processingNotice.replace("{caseNo}", processingCaseNo)}
            </p>
          )}

          <div className={styles.actions}>
            <button
              type="submit"
              className={styles.submit}
              disabled={isSubmitting || isOtherSpecies}
            >
              {isSubmitting ? copy.submitting : copy.submit}
            </button>
            <button type="button" className={styles.cancel} onClick={() => void navigate("/queue")}>
              {copy.cancel}
            </button>
            <span className={styles.latency}>{copy.latencyNote}</span>
          </div>
        </form>

        <aside className={styles.sidePane}>
          <h2 className={styles.paneHeading}>{redFlagPanel.heading}</h2>
          <ul className={styles.signs}>
            {redFlagPanel.signs.map((sign) => (
              <li key={sign}>{sign}</li>
            ))}
          </ul>
          <p className={styles.caption}>{redFlagPanel.caption}</p>

          <h2 className={styles.paneHeading}>{redFlagPanel.tipsHeading}</h2>
          <p className={styles.tips}>{redFlagPanel.tips}</p>
        </aside>
      </div>
    </div>
  );
}

function controlClass(error: string | undefined): string {
  return error === undefined ? styles.input : styles.inputInvalid;
}

function Label({
  htmlFor,
  optional,
  children,
}: {
  htmlFor: string;
  optional: boolean;
  children: ReactNode;
}) {
  return (
    <label className={styles.label} htmlFor={htmlFor}>
      {children}
      {optional && <span className={styles.optional}> {copy.optionalSuffix}</span>}
    </label>
  );
}

function FieldError({ id, message }: { id: string; message: string | undefined }) {
  if (message === undefined) {
    return null;
  }
  return (
    <p id={id} className={styles.fieldError}>
      {message}
    </p>
  );
}

/**
 * One free-text signalment or owner-reference input.
 *
 * No `maxLength`: capping the input would make the length limit unreachable and
 * silently swallow what someone pasted. FR-04 wants it reported, not truncated.
 */
function TextField({
  id,
  label,
  value,
  error,
  onChange,
  optional = true,
  inputMode,
}: {
  id: string;
  label: string;
  value: string;
  error: string | undefined;
  onChange: (value: string) => void;
  optional?: boolean;
  inputMode?: "text" | "decimal";
}) {
  const errorId = `${id}-error`;
  return (
    <div className={styles.field}>
      <Label htmlFor={id} optional={optional}>
        {label}
      </Label>
      <input
        id={id}
        className={controlClass(error)}
        type="text"
        inputMode={inputMode}
        autoComplete="off"
        value={value}
        aria-invalid={error !== undefined}
        aria-describedby={error === undefined ? undefined : errorId}
        onChange={(event) => onChange(event.target.value)}
      />
      <FieldError id={errorId} message={error} />
    </div>
  );
}
