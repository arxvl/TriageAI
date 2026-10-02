import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createCase } from "../../api/cases";
import { ApiError } from "../../api/errors";
import { redFlagPanel } from "../../content/redFlagSigns";
import { strings } from "../../i18n/strings";
import { makeUser, renderWithAuth } from "../../test/testUtils";
import { CaseIntake } from "./CaseIntake";

vi.mock("../../api/cases", () => ({ createCase: vi.fn() }));

const createCaseMock = vi.mocked(createCase);
const copy = strings.caseIntake;

/** Long enough to pass the 20-character floor (FR-01). Fictitious (CLAUDE.md §9). */
const DESCRIPTION =
  "Since this morning he keeps going to the litter box and cries, but nothing comes out.";

const DESCRIPTION_LABEL = /description of the problem/;

/** What a 202 answers with: the case exists, the pipeline has not finished (FR-06). */
const CREATED = {
  id: "00000000-0000-4000-8000-000000000010",
  case_no: "C-0007",
  status: "SUBMITTED",
} as const;

const expectedNotice = copy.processingNotice.replace("{caseNo}", CREATED.case_no);

function renderIntake() {
  return renderWithAuth(
    <Routes>
      <Route path="/cases/new" element={<CaseIntake />} />
      <Route path="/queue" element={<p>triage queue</p>} />
    </Routes>,
    { user: makeUser(), route: "/cases/new" },
  );
}

function chooseSpecies(label: string) {
  fireEvent.click(screen.getByRole("radio", { name: label }));
}

function typeIn(label: RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: copy.submit }));
}

/**
 * The text a control points at with `aria-describedby`.
 *
 * IR-05 asks for the message to appear *next to* the field, so the test checks the
 * association rather than only that the sentence is somewhere on the page.
 */
function describedTextFor(label: RegExp): string {
  const control = screen.getByLabelText(label);
  const ids = control.getAttribute("aria-describedby");
  if (ids === null) {
    return "";
  }
  return ids
    .split(" ")
    .map((id) => document.getElementById(id)?.textContent ?? "")
    .join(" ");
}

beforeEach(() => {
  createCaseMock.mockReset();
});

describe("CaseIntake content (W-03, FR-18)", () => {
  it("instructs staff to enter the description in English (FR-18, ADR-16)", () => {
    renderIntake();

    expect(screen.getByText(copy.descriptionHelper)).toBeInTheDocument();
  });

  it("ties that instruction to the description field for screen readers (IR-07)", () => {
    renderIntake();

    expect(describedTextFor(DESCRIPTION_LABEL)).toContain("Enter the description in English.");
  });

  it("says the owner reference is kept out of AI processing (FR-07, DR-04)", () => {
    renderIntake();

    expect(screen.getByText(copy.ownerReferenceTitle)).toBeInTheDocument();
    expect(screen.getByText(/stored separately and never sent to AI services/)).toBeInTheDocument();
  });

  it("lists the red-flag signs and says the list is not final yet", () => {
    renderIntake();

    for (const sign of redFlagPanel.signs) {
      expect(screen.getByText(sign)).toBeInTheDocument();
    }
    expect(screen.getByText(redFlagPanel.caption)).toBeInTheDocument();
  });
});

describe("CaseIntake character counter (W-03)", () => {
  it("starts at zero against the limit", () => {
    renderIntake();

    expect(screen.getByText("0 / 2,000")).toBeInTheDocument();
  });

  it("follows what the user types", () => {
    renderIntake();

    typeIn(DESCRIPTION_LABEL, "Vomited twice");

    expect(screen.getByText("13 / 2,000")).toBeInTheDocument();
  });

  it("keeps counting past the limit instead of truncating the text (FR-04)", () => {
    renderIntake();

    typeIn(DESCRIPTION_LABEL, "a".repeat(2001));

    expect(screen.getByText("2,001 / 2,000")).toBeInTheDocument();
  });
});

describe("CaseIntake other species (FR-02, BR-06)", () => {
  it("says nothing about manual triage until the choice is made", () => {
    renderIntake();

    expect(screen.queryByText(copy.errors.speciesOutOfScope)).not.toBeInTheDocument();
  });

  it("shows the manual-triage message and disables submission", () => {
    renderIntake();

    chooseSpecies(copy.species.OTHER);

    expect(screen.getByText(copy.errors.speciesOutOfScope)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.submit })).toBeDisabled();
  });

  it("never sends the case, even with everything else filled in", () => {
    renderIntake();

    typeIn(DESCRIPTION_LABEL, DESCRIPTION);
    chooseSpecies(copy.species.OTHER);
    submit();

    expect(createCaseMock).not.toHaveBeenCalled();
  });

  it("re-enables submission once a dog or cat is chosen", () => {
    renderIntake();

    chooseSpecies(copy.species.OTHER);
    chooseSpecies(copy.species.DOG);

    expect(screen.queryByText(copy.errors.speciesOutOfScope)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.submit })).toBeEnabled();
  });
});

describe("CaseIntake client-side validation (FR-04, IR-05)", () => {
  it("asks for a species when none was chosen, without calling the API", () => {
    renderIntake();

    typeIn(DESCRIPTION_LABEL, DESCRIPTION);
    submit();

    expect(screen.getByText(copy.errors.species)).toBeInTheDocument();
    expect(createCaseMock).not.toHaveBeenCalled();
  });

  it("puts the short-description message beside the description", () => {
    renderIntake();

    chooseSpecies(copy.species.CAT);
    typeIn(DESCRIPTION_LABEL, "Vomited twice");
    submit();

    expect(describedTextFor(DESCRIPTION_LABEL)).toContain(
      "The description must be at least 20 characters.",
    );
    expect(createCaseMock).not.toHaveBeenCalled();
  });

  it("uses the server's own wording for a weight that is not a number", () => {
    renderIntake();

    chooseSpecies(copy.species.CAT);
    typeIn(DESCRIPTION_LABEL, DESCRIPTION);
    typeIn(/^Body weight/, "4,2");
    submit();

    expect(describedTextFor(/^Body weight/)).toContain("Enter the weight as a number, e.g. 4.2.");
    expect(createCaseMock).not.toHaveBeenCalled();
  });

  it("reports an over-long pet name and an out-of-range age together", () => {
    renderIntake();

    chooseSpecies(copy.species.CAT);
    typeIn(DESCRIPTION_LABEL, DESCRIPTION);
    typeIn(/^Pet name/, "a".repeat(61));
    typeIn(/^Age \(optional\)/, "99");
    submit();

    expect(describedTextFor(/^Pet name/)).toContain("at most 60 characters");
    expect(describedTextFor(/^Age \(optional\)/)).toContain("Enter an age between 0 and 40.");
  });

  it("keeps everything the user entered after a refused submission (FR-04)", () => {
    renderIntake();

    chooseSpecies(copy.species.CAT);
    typeIn(/^Pet name/, "Mingming");
    typeIn(/^Breed/, "Puspin");
    typeIn(DESCRIPTION_LABEL, "Vomited twice");
    submit();

    expect(screen.getByLabelText(/^Pet name/)).toHaveValue("Mingming");
    expect(screen.getByLabelText(/^Breed/)).toHaveValue("Puspin");
    expect(screen.getByLabelText(DESCRIPTION_LABEL)).toHaveValue("Vomited twice");
    expect(screen.getByRole("radio", { name: copy.species.CAT })).toBeChecked();
  });

  it("retires a message once the field is corrected", () => {
    renderIntake();

    chooseSpecies(copy.species.CAT);
    typeIn(DESCRIPTION_LABEL, "Vomited twice");
    submit();
    expect(screen.getByText(copy.errors.descriptionTooShort)).toBeInTheDocument();

    typeIn(DESCRIPTION_LABEL, DESCRIPTION);

    expect(screen.queryByText(copy.errors.descriptionTooShort)).not.toBeInTheDocument();
  });
});

describe("CaseIntake server responses (IR-05)", () => {
  function fillValidForm() {
    chooseSpecies(copy.species.CAT);
    typeIn(DESCRIPTION_LABEL, DESCRIPTION);
  }

  it("places a validation error under the field the server named", async () => {
    createCaseMock.mockRejectedValue(
      new ApiError(422, "VALIDATION_ERROR", "Enter a weight between 0.1 and 120 kg.", "weight_kg"),
    );
    renderIntake();

    fillValidForm();
    typeIn(/^Body weight/, "5");
    submit();

    await waitFor(() => {
      expect(describedTextFor(/^Body weight/)).toContain("Enter a weight between 0.1 and 120 kg.");
    });
  });

  it("attaches an out-of-scope species to the species control, which it names no field for", async () => {
    createCaseMock.mockRejectedValue(
      new ApiError(422, "SPECIES_OUT_OF_SCOPE", copy.errors.speciesOutOfScope),
    );
    renderIntake();

    fillValidForm();
    submit();

    expect(await screen.findByText(copy.errors.speciesOutOfScope)).toBeInTheDocument();
  });

  it("keeps an unexpected failure generic, with no internal detail", async () => {
    createCaseMock.mockRejectedValue(
      new ApiError(500, "INTERNAL_ERROR", "sqlalchemy.exc.DBAPIError"),
    );
    renderIntake();

    fillValidForm();
    submit();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(copy.errors.unexpected);
    expect(alert).not.toHaveTextContent("sqlalchemy");
  });

  it("lets the user try again after a failure", async () => {
    createCaseMock.mockRejectedValue(new ApiError(0, "NETWORK_ERROR", "unreachable"));
    renderIntake();

    fillValidForm();
    submit();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: copy.submit })).toBeEnabled();
    });
  });
});

describe("CaseIntake submission (FR-01, FR-03, FR-07)", () => {
  it("sends only the fields that were filled in, with numbers as numbers", async () => {
    createCaseMock.mockResolvedValue({
      id: "00000000-0000-4000-8000-000000000010",
      case_no: "C-0007",
      status: "SUBMITTED",
    });
    renderIntake();

    chooseSpecies(copy.species.CAT);
    typeIn(/^Pet name/, "Mingming");
    typeIn(/^Age \(optional\)/, "3");
    typeIn(/^Body weight/, "4.2");
    typeIn(DESCRIPTION_LABEL, DESCRIPTION);
    typeIn(/^Owner name$/, "J. Cruz");
    typeIn(/^Contact number$/, "0917 000 0000");
    fireEvent.click(screen.getByRole("radio", { name: copy.intakeChannels.PHONE }));
    submit();

    await waitFor(() => {
      expect(createCaseMock).toHaveBeenCalledWith({
        species: "CAT",
        description: DESCRIPTION,
        intake_channel: "PHONE",
        sex: "UNKNOWN",
        pet_name: "Mingming",
        age_value: 3,
        age_unit: "YEARS",
        weight_kg: 4.2,
        owner_name: "J. Cruz",
        contact_number: "0917 000 0000",
      });
    });
  });

  it("confirms the case number the server assigned", async () => {
    createCaseMock.mockResolvedValue(CREATED);
    renderIntake();

    chooseSpecies(copy.species.DOG);
    typeIn(DESCRIPTION_LABEL, DESCRIPTION);
    submit();

    expect(await screen.findByText("Case C-0007 submitted")).toBeInTheDocument();
  });

  it("says the case is being processed, then moves to the queue (FR-06)", async () => {
    createCaseMock.mockResolvedValue(CREATED);
    renderIntake();

    chooseSpecies(copy.species.DOG);
    typeIn(DESCRIPTION_LABEL, DESCRIPTION);
    submit();

    // `role="status"`, not `alert`: this is progress, not something that should
    // interrupt what a screen reader is in the middle of (IR-07).
    expect(await screen.findByText(expectedNotice)).toBeInTheDocument();
    expect(screen.getByText(expectedNotice)).toHaveAttribute("role", "status");
    // Still on the form, so the notice is a state the user can actually read.
    expect(screen.queryByText("triage queue")).not.toBeInTheDocument();

    expect(await screen.findByText("triage queue")).toBeInTheDocument();
  });

  it("keeps submission disabled while the notice is up, so one case is sent once", async () => {
    createCaseMock.mockResolvedValue(CREATED);
    renderIntake();

    chooseSpecies(copy.species.DOG);
    typeIn(DESCRIPTION_LABEL, DESCRIPTION);
    submit();

    await screen.findByText(expectedNotice);

    expect(screen.getByRole("button", { name: copy.submitting })).toBeDisabled();
    // There is no "Submit for triage" control to press a second time.
    expect(screen.queryByRole("button", { name: copy.submit })).not.toBeInTheDocument();
    expect(createCaseMock).toHaveBeenCalledTimes(1);
  });
});
