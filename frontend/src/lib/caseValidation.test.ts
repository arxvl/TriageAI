import { describe, expect, it } from "vitest";

import { strings } from "../i18n/strings";
import {
  asCaseField,
  emptyCaseForm,
  parseDecimalInput,
  toCaseCreateRequest,
  validateCaseForm,
  type CaseFormValues,
  type SubmittableCaseForm,
} from "./caseValidation";

const messages = strings.caseIntake.errors;

/** A form that passes every check, so each test can break exactly one thing. */
function validForm(overrides: Partial<CaseFormValues> = {}): SubmittableCaseForm {
  return {
    ...emptyCaseForm(),
    species: "CAT",
    description: "Since this morning he keeps going to the litter box and cries.",
    ...overrides,
  } as SubmittableCaseForm;
}

describe("parseDecimalInput (IR-05)", () => {
  it.each(["4.2", "4", "0.1", "120", ".5", "4."])("reads %s as a number", (raw) => {
    expect(parseDecimalInput(raw)).not.toBeNull();
  });

  it("rejects a comma decimal, which is how it is written locally", () => {
    expect(parseDecimalInput("4,2")).toBeNull();
  });

  it("rejects a number with the unit typed after it", () => {
    expect(parseDecimalInput("4.2 kg")).toBeNull();
  });

  it.each(["", "   ", "abc", "4.2.3"])("rejects %j", (raw) => {
    expect(parseDecimalInput(raw)).toBeNull();
  });

  it("reads a negative number, so it is reported as out of range, not unreadable", () => {
    expect(parseDecimalInput("-3")).toBe(-3);
  });

  it("ignores surrounding spaces", () => {
    expect(parseDecimalInput("  4.2  ")).toBe(4.2);
  });
});

describe("validateCaseForm species (FR-01, FR-02)", () => {
  it("asks for a species when none is chosen", () => {
    expect(validateCaseForm(emptyCaseForm()).species).toBe(messages.species);
  });

  it("refuses a species outside dog and cat", () => {
    expect(validateCaseForm(validForm({ species: "OTHER" })).species).toBe(
      messages.speciesOutOfScope,
    );
  });

  it.each(["DOG", "CAT"] as const)("accepts %s", (species) => {
    expect(validateCaseForm(validForm({ species })).species).toBeUndefined();
  });
});

describe("validateCaseForm description (FR-01, FR-05)", () => {
  it("asks for a description when it is blank", () => {
    expect(validateCaseForm(validForm({ description: "" })).description).toBe(
      messages.descriptionMissing,
    );
  });

  it("treats whitespace as blank, the way the server trims before measuring", () => {
    expect(validateCaseForm(validForm({ description: " ".repeat(40) })).description).toBe(
      messages.descriptionMissing,
    );
  });

  it("refuses 19 characters and accepts 20", () => {
    expect(validateCaseForm(validForm({ description: "a".repeat(19) })).description).toBe(
      messages.descriptionTooShort,
    );
    expect(
      validateCaseForm(validForm({ description: "a".repeat(20) })).description,
    ).toBeUndefined();
  });

  it("accepts 2,000 characters and refuses 2,001", () => {
    expect(
      validateCaseForm(validForm({ description: "a".repeat(2000) })).description,
    ).toBeUndefined();
    expect(validateCaseForm(validForm({ description: "a".repeat(2001) })).description).toBe(
      messages.descriptionTooLong,
    );
  });
});

describe("validateCaseForm optional fields (FR-01, FR-04)", () => {
  it("leaves every optional field alone when all are blank", () => {
    expect(validateCaseForm(validForm())).toEqual({});
  });

  it("refuses a pet name over 60 characters", () => {
    expect(validateCaseForm(validForm({ petName: "a".repeat(61) })).pet_name).toBe(
      messages.petNameTooLong,
    );
    expect(validateCaseForm(validForm({ petName: "a".repeat(60) })).pet_name).toBeUndefined();
  });

  it("refuses a breed over 60 characters", () => {
    expect(validateCaseForm(validForm({ breed: "a".repeat(61) })).breed).toBe(
      messages.breedTooLong,
    );
  });

  it("refuses an owner name over 80 characters", () => {
    expect(validateCaseForm(validForm({ ownerName: "a".repeat(81) })).owner_name).toBe(
      messages.ownerNameTooLong,
    );
  });

  it("refuses a contact number over 30 characters", () => {
    expect(validateCaseForm(validForm({ contactNumber: "a".repeat(31) })).contact_number).toBe(
      messages.contactNumberTooLong,
    );
  });

  it("tells an unreadable age apart from one out of range", () => {
    expect(validateCaseForm(validForm({ ageValue: "three" })).age_value).toBe(
      messages.ageNotANumber,
    );
    expect(validateCaseForm(validForm({ ageValue: "41" })).age_value).toBe(messages.ageOutOfRange);
    expect(validateCaseForm(validForm({ ageValue: "-1" })).age_value).toBe(messages.ageOutOfRange);
    expect(validateCaseForm(validForm({ ageValue: "40" })).age_value).toBeUndefined();
    expect(validateCaseForm(validForm({ ageValue: "0" })).age_value).toBeUndefined();
  });

  it("tells an unreadable weight apart from one out of range", () => {
    expect(validateCaseForm(validForm({ weightKg: "4,2" })).weight_kg).toBe(
      messages.weightNotANumber,
    );
    expect(validateCaseForm(validForm({ weightKg: "0.05" })).weight_kg).toBe(
      messages.weightOutOfRange,
    );
    expect(validateCaseForm(validForm({ weightKg: "121" })).weight_kg).toBe(
      messages.weightOutOfRange,
    );
    expect(validateCaseForm(validForm({ weightKg: "0.1" })).weight_kg).toBeUndefined();
    expect(validateCaseForm(validForm({ weightKg: "120" })).weight_kg).toBeUndefined();
  });

  it("reports every bad field at once, because the server reports only the first", () => {
    const errors = validateCaseForm(
      validForm({ description: "too short", weightKg: "4,2", ageValue: "99" }),
    );

    expect(Object.keys(errors).sort()).toEqual(["age_value", "description", "weight_kg"]);
  });
});

describe("toCaseCreateRequest (FR-01, FR-07)", () => {
  it("sends only what was filled in", () => {
    expect(toCaseCreateRequest(validForm())).toEqual({
      species: "CAT",
      description: "Since this morning he keeps going to the litter box and cries.",
      intake_channel: "WALK_IN",
      sex: "UNKNOWN",
    });
  });

  it("omits neutered when the sex is unknown rather than guessing false", () => {
    expect(toCaseCreateRequest(validForm())).not.toHaveProperty("neutered");
  });

  it.each([
    ["MALE_INTACT", "MALE", false],
    ["MALE_NEUTERED", "MALE", true],
    ["FEMALE_INTACT", "FEMALE", false],
    ["FEMALE_SPAYED", "FEMALE", true],
  ] as const)("splits %s into sex and neutered", (choice, sex, neutered) => {
    const request = toCaseCreateRequest(validForm({ sexNeuter: choice }));

    expect(request.sex).toBe(sex);
    expect(request.neutered).toBe(neutered);
  });

  it("sends the age unit only alongside an age", () => {
    expect(toCaseCreateRequest(validForm({ ageUnit: "MONTHS" }))).not.toHaveProperty("age_unit");

    const request = toCaseCreateRequest(validForm({ ageValue: "8", ageUnit: "MONTHS" }));
    expect(request.age_value).toBe(8);
    expect(request.age_unit).toBe("MONTHS");
  });

  it("sends the weight as a number, not the typed text", () => {
    expect(toCaseCreateRequest(validForm({ weightKg: "4.2" })).weight_kg).toBe(4.2);
  });

  it("trims what it sends and drops fields left blank", () => {
    const request = toCaseCreateRequest(
      validForm({ petName: "  Mingming  ", breed: "   ", ownerName: " J. Cruz " }),
    );

    expect(request.pet_name).toBe("Mingming");
    expect(request).not.toHaveProperty("breed");
    expect(request.owner_name).toBe("J. Cruz");
  });

  it("carries the owner reference, which the server keeps out of the case (FR-07)", () => {
    const request = toCaseCreateRequest(
      validForm({ ownerName: "J. Cruz", contactNumber: "0917 000 0000" }),
    );

    expect(request.owner_name).toBe("J. Cruz");
    expect(request.contact_number).toBe("0917 000 0000");
  });
});

describe("asCaseField", () => {
  it("accepts a field the form has", () => {
    expect(asCaseField("weight_kg")).toBe("weight_kg");
  });

  it.each([null, undefined, "body", "unknown_field"])("rejects %j", (field) => {
    expect(asCaseField(field)).toBeNull();
  });
});
