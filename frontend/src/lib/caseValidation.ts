/**
 * The client half of the intake form's validation (FR-04, IR-05).
 *
 * Every limit here mirrors `CaseCreate` in the backend's `app/schemas/case.py`,
 * and every message is the sentence the backend's
 * `app/core/validation_messages.py` would return for the same failure. The
 * server still decides — this exists for two reasons the server cannot cover:
 *
 * 1. It answers without a round trip, so a typo is corrected in place.
 * 2. It reports **every** invalid field at once. The API reports only the first
 *    (`_first_validation_message`), and FR-04 asks for field-level errors.
 *
 * Error keys are the API's field names (`weight_kg`, not `weightKg`), so a
 * `field` off an `ApiError` drops straight into the same map.
 */
import type { AgeUnit, CaseCreateRequest, IntakeChannel, Sex, SpeciesInput } from "../api/cases";
import { strings } from "../i18n/strings";

// Mirrors the module-level constants in `app/schemas/case.py`.
export const DESCRIPTION_MIN_LENGTH = 20;
export const DESCRIPTION_MAX_LENGTH = 2_000;

// Mirrors the `Field(max_length=...)` declarations on `CaseCreate`.
export const PET_NAME_MAX_LENGTH = 60;
export const BREED_MAX_LENGTH = 60;
export const OWNER_NAME_MAX_LENGTH = 80;
export const CONTACT_NUMBER_MAX_LENGTH = 30;

export const AGE_MIN = 0;
export const AGE_MAX = 40;
export const WEIGHT_MIN = 0.1;
export const WEIGHT_MAX = 120;

/**
 * The one "Sex and neuter status" control on W-03, which stands for the two API
 * fields `sex` and `neutered`. `toCaseCreateRequest` splits it.
 */
export type SexNeuterChoice =
  "UNKNOWN" | "MALE_INTACT" | "MALE_NEUTERED" | "FEMALE_INTACT" | "FEMALE_SPAYED";

const SEX_NEUTER: Record<SexNeuterChoice, { sex: Sex; neutered?: boolean }> = {
  // No `neutered` at all: nobody said, and guessing `false` would be a claim.
  UNKNOWN: { sex: "UNKNOWN" },
  MALE_INTACT: { sex: "MALE", neutered: false },
  MALE_NEUTERED: { sex: "MALE", neutered: true },
  FEMALE_INTACT: { sex: "FEMALE", neutered: false },
  FEMALE_SPAYED: { sex: "FEMALE", neutered: true },
};

/**
 * What the form holds while it is being filled in.
 *
 * Numbers are kept as the raw string the user typed, so "4,2" survives long
 * enough to be reported as a mistake instead of silently becoming 4 or NaN.
 * `species` starts null because nothing is pre-selected; the wireframe's "Cat"
 * is sample data, and FR-01 makes species a required choice.
 */
export interface CaseFormValues {
  species: SpeciesInput | null;
  petName: string;
  ageValue: string;
  ageUnit: AgeUnit;
  sexNeuter: SexNeuterChoice;
  breed: string;
  weightKg: string;
  intakeChannel: IntakeChannel;
  description: string;
  ownerName: string;
  contactNumber: string;
}

/** A form with a species chosen, which is the only shape that can be submitted. */
export type SubmittableCaseForm = CaseFormValues & { species: SpeciesInput };

/** The API field names an error can be attached to. */
export const CASE_FIELDS = [
  "species",
  "description",
  "intake_channel",
  "pet_name",
  "age_value",
  "age_unit",
  "sex",
  "neutered",
  "breed",
  "weight_kg",
  "owner_name",
  "contact_number",
] as const;

export type CaseField = (typeof CASE_FIELDS)[number];

export type CaseFieldErrors = Partial<Record<CaseField, string>>;

/** The blank form. Age in years and a walk-in are the clinic's common case. */
export function emptyCaseForm(): CaseFormValues {
  return {
    species: null,
    petName: "",
    ageValue: "",
    ageUnit: "YEARS",
    sexNeuter: "UNKNOWN",
    breed: "",
    weightKg: "",
    // Matches `DEFAULT_INTAKE_CHANNEL` in the backend's `case_service.py`.
    intakeChannel: "WALK_IN",
    description: "",
    ownerName: "",
    contactNumber: "",
  };
}

/**
 * A plain decimal, or null when the text is not one.
 *
 * Deliberately strict about what a number looks like: "4,2" (a comma decimal,
 * which is how it is written locally) and "4.2 kg" both come back null so the
 * form can say "Enter the weight as a number, e.g. 4.2." A leading minus parses,
 * so a negative value is reported as out of range rather than as not a number —
 * the same wording the server would use.
 */
export function parseDecimalInput(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return null;
  }
  if (!/^-?(?:\d+\.?\d*|\.\d+)$/.test(trimmed)) {
    return null;
  }
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

/** The server's `field` value, if it names an input this form has. */
export function asCaseField(field: string | null | undefined): CaseField | null {
  if (field === null || field === undefined) {
    return null;
  }
  return (CASE_FIELDS as readonly string[]).includes(field) ? (field as CaseField) : null;
}

/**
 * Every field-level problem in the form, keyed by API field name.
 *
 * An empty object means the form may be sent. Optional fields that were left
 * blank are never an error; only a value that was entered and is wrong.
 */
export function validateCaseForm(values: CaseFormValues): CaseFieldErrors {
  const messages = strings.caseIntake.errors;
  const errors: CaseFieldErrors = {};

  if (values.species === null) {
    errors.species = messages.species;
  } else if (values.species === "OTHER") {
    // Normally unreachable: choosing it disables Submit (FR-02). Kept so this
    // function never reports a form as valid that the server would refuse.
    errors.species = messages.speciesOutOfScope;
  }

  // Trimmed before measuring, exactly as `_trim_description` does on the server,
  // so twenty spaces is not a description (FR-05).
  const description = values.description.trim();
  if (description === "") {
    errors.description = messages.descriptionMissing;
  } else if (description.length < DESCRIPTION_MIN_LENGTH) {
    errors.description = messages.descriptionTooShort;
  } else if (description.length > DESCRIPTION_MAX_LENGTH) {
    errors.description = messages.descriptionTooLong;
  }

  if (values.petName.trim().length > PET_NAME_MAX_LENGTH) {
    errors.pet_name = messages.petNameTooLong;
  }
  if (values.breed.trim().length > BREED_MAX_LENGTH) {
    errors.breed = messages.breedTooLong;
  }
  if (values.ownerName.trim().length > OWNER_NAME_MAX_LENGTH) {
    errors.owner_name = messages.ownerNameTooLong;
  }
  if (values.contactNumber.trim().length > CONTACT_NUMBER_MAX_LENGTH) {
    errors.contact_number = messages.contactNumberTooLong;
  }

  if (values.ageValue.trim() !== "") {
    const age = parseDecimalInput(values.ageValue);
    if (age === null) {
      errors.age_value = messages.ageNotANumber;
    } else if (age < AGE_MIN || age > AGE_MAX) {
      errors.age_value = messages.ageOutOfRange;
    }
  }

  if (values.weightKg.trim() !== "") {
    const weight = parseDecimalInput(values.weightKg);
    if (weight === null) {
      errors.weight_kg = messages.weightNotANumber;
    } else if (weight < WEIGHT_MIN || weight > WEIGHT_MAX) {
      errors.weight_kg = messages.weightOutOfRange;
    }
  }

  return errors;
}

/**
 * The request body for a validated form.
 *
 * A blank optional field is left out of the JSON rather than sent as "" or null:
 * the server reads an absent field as "not given", and sending an empty string
 * would store one.
 */
export function toCaseCreateRequest(values: SubmittableCaseForm): CaseCreateRequest {
  const { sex, neutered } = SEX_NEUTER[values.sexNeuter];
  const age = parseDecimalInput(values.ageValue);
  const weight = parseDecimalInput(values.weightKg);

  const request: CaseCreateRequest = {
    species: values.species,
    description: values.description.trim(),
    intake_channel: values.intakeChannel,
    sex,
  };

  if (neutered !== undefined) {
    request.neutered = neutered;
  }
  if (values.petName.trim() !== "") {
    request.pet_name = values.petName.trim();
  }
  if (values.breed.trim() !== "") {
    request.breed = values.breed.trim();
  }
  if (age !== null) {
    request.age_value = age;
    request.age_unit = values.ageUnit;
  }
  if (weight !== null) {
    request.weight_kg = weight;
  }
  if (values.ownerName.trim() !== "") {
    request.owner_name = values.ownerName.trim();
  }
  if (values.contactNumber.trim() !== "") {
    request.contact_number = values.contactNumber.trim();
  }

  return request;
}
