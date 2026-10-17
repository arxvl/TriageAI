/**
 * W-06, the manual-triage panel's own rules (FR-34, NFR-09).
 *
 * Two things are load-bearing here. The note is required, because a category
 * assigned by hand with no stated basis is the one record in this system nobody
 * could check afterwards — and `ReviewService._resolve_category` refuses the
 * request without it, so a Save that looked possible would only waste a round
 * trip. And every option carries its discriminators in words, because a reviewer
 * placing a case by hand has no recommendation to lean on and colour alone tells
 * them nothing (IR-03, NFR-21).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { VTL_DISCRIMINATORS, vtlReference } from "../../content/vtlReference";
import { strings } from "../../i18n/strings";
import { URGENCY_ORDER } from "../../lib/vtl";
import { ManualTriagePanel } from "./ManualTriagePanel";

const copy = strings.caseReview.manualTriage;

function renderPanel(overrides: Partial<Parameters<typeof ManualTriagePanel>[0]> = {}): {
  onSubmit: ReturnType<typeof vi.fn>;
  onCancel: ReturnType<typeof vi.fn>;
} {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  render(
    <ManualTriagePanel
      isSaving={false}
      error={null}
      fieldError={null}
      onSubmit={onSubmit}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { onSubmit, onCancel };
}

function chooseCategory(category: string) {
  fireEvent.click(screen.getByRole("radio", { name: new RegExp(category, "i") }));
}

function saveButton() {
  return screen.getByRole("button", { name: copy.submit });
}

describe("ManualTriagePanel", () => {
  // FR-34: the note is required, and so the server says too.
  it("keeps Save disabled until both a category and a note are given", () => {
    renderPanel();

    expect(saveButton()).toBeDisabled();

    chooseCategory("ORANGE");
    expect(saveButton()).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Fast breathing reported; assess on arrival." },
    });
    expect(saveButton()).toBeEnabled();
  });

  it("does not accept whitespace as a note", () => {
    renderPanel();

    chooseCategory("RED");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "   " } });

    expect(saveButton()).toBeDisabled();
  });

  // IR-03, NFR-21: every option says in words what belongs in it.
  it("prints the example discriminators for all five categories", () => {
    renderPanel();

    for (const category of URGENCY_ORDER) {
      const row = screen.getByRole("radio", { name: new RegExp(category, "i") });
      expect(row.closest("label")).toHaveTextContent(VTL_DISCRIMINATORS[category]);
    }
  });

  // The examples must not read as a decision rule.
  it("says the examples are not a complete list and do not decide the category", () => {
    renderPanel();

    expect(screen.getByText(vtlReference.caption)).toBeInTheDocument();
  });

  it("says where the actions come from, and what the status will become", () => {
    renderPanel();

    expect(screen.getByText(copy.actionsNotice)).toBeInTheDocument();
    expect(screen.getByText(copy.statusNotice)).toBeInTheDocument();
  });

  it("submits the chosen category and the trimmed note", () => {
    const { onSubmit } = renderPanel();

    chooseCategory("YELLOW");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "  Recheck on arrival.  " } });
    fireEvent.click(saveButton());

    expect(onSubmit).toHaveBeenCalledWith({
      final_category: "YELLOW",
      note: "Recheck on arrival.",
    });
  });

  // A case the pipeline gave up on has no recommendation to go back to, so the
  // way out is the queue, not a Cancel that would leave an empty panel 3.
  it("offers no way out when there is nothing to go back to", () => {
    renderPanel({ onCancel: null });

    expect(screen.queryByRole("button", { name: copy.cancel })).not.toBeInTheDocument();
  });

  it("lets a reviewer who chose manual triage go back to the recommendation", () => {
    const { onCancel } = renderPanel();

    fireEvent.click(screen.getByRole("button", { name: copy.cancel }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("shows a field error from the server beside its own control", () => {
    renderPanel({
      fieldError: { field: "note", message: "Enter a note explaining the manual triage." },
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter a note explaining the manual triage.",
    );
  });
});
