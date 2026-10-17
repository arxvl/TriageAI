/**
 * W-05, the adjust dialog's own rules (FR-33, BR-03).
 *
 * What these assert is the client half of BR-03: an adjustment that does not say
 * what changed and why cannot be sent at all. `ReviewService` and a database
 * check constraint refuse one too, so a bug here costs the reviewer a round trip
 * rather than the record its reason — but the round trip is the point, because a
 * form that offers an impossible Save teaches people to ignore it.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { strings } from "../../i18n/strings";
import { AdjustDialog } from "./AdjustDialog";

const copy = strings.caseReview.adjustDialog;
const reasons = strings.caseReview.adjustReasons;

function renderDialog(overrides: Partial<Parameters<typeof AdjustDialog>[0]> = {}): {
  onSubmit: ReturnType<typeof vi.fn>;
} {
  const onSubmit = vi.fn();
  render(
    <AdjustDialog
      recommended="ORANGE"
      isSaving={false}
      error={null}
      fieldError={null}
      onSubmit={onSubmit}
      onClose={vi.fn()}
      {...overrides}
    />,
  );
  return { onSubmit };
}

/** Pick a category by its row, which is the whole label and not just the badge. */
function chooseCategory(category: string) {
  const row = screen.getByRole("radio", { name: new RegExp(category, "i") });
  fireEvent.click(row);
}

function saveButton() {
  return screen.getByRole("button", { name: copy.submit });
}

describe("AdjustDialog", () => {
  it("marks the recommendation's own row as the current category", () => {
    renderDialog();

    const current = screen.getByRole("radio", { name: /ORANGE/i });
    expect(current.closest("label")).toHaveTextContent(copy.currentMarker);
  });

  // BR-03. The reason codes are the data behind the disagreement analysis, so an
  // adjustment without one is not a record of anything.
  it("keeps Save disabled until a reason is chosen", () => {
    renderDialog();

    chooseCategory("RED");
    expect(saveButton()).toBeDisabled();

    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "CONDITION_DIFFERS_ON_ARRIVAL" },
    });
    expect(saveButton()).toBeEnabled();
  });

  // FR-33: adjusting to the recommended category is not a disagreement, and the
  // server rejects it. Nothing on screen should invite it.
  it("keeps Save disabled while the chosen category is still the recommended one", () => {
    renderDialog();

    chooseCategory("ORANGE");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "SIGN_NOT_CAPTURED" } });

    expect(saveButton()).toBeDisabled();
  });

  it("names the direction of the change, and which way round it goes", () => {
    renderDialog();

    chooseCategory("RED");
    expect(screen.getByText(/Change: Orange → Red \(up-triage\)/)).toBeInTheDocument();

    chooseCategory("BLUE");
    expect(screen.getByText(/Change: Orange → Blue \(down-triage\)/)).toBeInTheDocument();
  });

  it("says the change is recorded permanently, and that the actions follow the new category", () => {
    renderDialog();

    chooseCategory("RED");
    expect(screen.getByText(new RegExp(copy.permanentNotice))).toBeInTheDocument();
    expect(screen.getByText(copy.actionsNotice)).toBeInTheDocument();
  });

  // "Other" carries no meaning on its own, so the server requires the detail
  // with it (`_require_reason`).
  it("requires the details when the reason is Other", () => {
    renderDialog();

    chooseCategory("RED");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "OTHER" } });

    expect(screen.getByText(copy.detailsLabelRequired)).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Abdomen painful on arrival." },
    });
    expect(saveButton()).toBeEnabled();
  });

  it("submits the category, the reason code and the trimmed detail", () => {
    const { onSubmit } = renderDialog();

    chooseCategory("RED");
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "CONDITION_DIFFERS_ON_ARRIVAL" },
    });
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "  Weak and lying down.  " },
    });
    fireEvent.click(saveButton());

    expect(onSubmit).toHaveBeenCalledWith({
      final_category: "RED",
      reason_code: "CONDITION_DIFFERS_ON_ARRIVAL",
      reason_text: "Weak and lying down.",
    });
  });

  // An untouched optional textarea means "not given", not "the empty string".
  it("leaves the detail out entirely when nothing was typed", () => {
    const { onSubmit } = renderDialog();

    chooseCategory("YELLOW");
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "RECOMMENDATION_TOO_HIGH" },
    });
    fireEvent.click(saveButton());

    expect(onSubmit).toHaveBeenCalledWith({
      final_category: "YELLOW",
      reason_code: "RECOMMENDATION_TOO_HIGH",
    });
  });

  it("offers all five reasons from the fixed list", () => {
    renderDialog();

    for (const label of Object.values(reasons)) {
      expect(screen.getByRole("option", { name: label })).toBeInTheDocument();
    }
  });

  // IR-05: a 422 belongs beside the control the server named, not at the top.
  it("shows a field error from the server beside its own control", () => {
    renderDialog({
      fieldError: {
        field: "reason_code",
        message: "Choose a reason for the change from the list.",
      },
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Choose a reason for the change from the list.",
    );
  });
});
