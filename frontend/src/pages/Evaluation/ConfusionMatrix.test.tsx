/**
 * The W-10 confusion matrix and under-triaged list (FR-66, NFR-14, IR-03).
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CONFUSION_MATRIX, METRICS } from "../../test/evalFixtures";
import { ConfusionMatrix } from "./ConfusionMatrix";
import { UnderTriagedList } from "./UnderTriagedList";

const LABELS = METRICS.classification.labels;

describe("the confusion matrix", () => {
  it("lays the five categories out in VTL order on both axes", () => {
    render(<ConfusionMatrix labels={LABELS} matrix={CONFUSION_MATRIX} />);

    const table = screen.getByRole("table");
    const columnHeaders = within(table).getAllByRole("columnheader").slice(1);
    expect(columnHeaders.map((header) => header.textContent?.replace("Predicted ", ""))).toEqual([
      "Red",
      "Orange",
      "Yellow",
      "Green",
      "Blue",
    ]);

    const rowHeaders = within(table).getAllByRole("rowheader");
    expect(rowHeaders.map((header) => header.textContent?.replace("Reference ", ""))).toEqual([
      "Red",
      "Orange",
      "Yellow",
      "Green",
      "Blue",
    ]);
  });

  it("puts every count in the cell for its reference row and predicted column", () => {
    render(<ConfusionMatrix labels={LABELS} matrix={CONFUSION_MATRIX} />);

    const rows = screen.getAllByRole("row").slice(1);
    const counts = rows.map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => Number(cell.textContent)),
    );

    expect(counts).toEqual(CONFUSION_MATRIX);
  });

  it("says which cells are under-triage, in words", () => {
    render(<ConfusionMatrix labels={LABELS} matrix={CONFUSION_MATRIX} />);

    expect(screen.getByText("Cells to the right of the diagonal are under-triaged.")).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: /rows: reference, columns: predicted/ }),
    ).toBeTruthy();
  });
});

describe("the under-triaged vignette list (NFR-14)", () => {
  const items = METRICS.classification.under_triaged;

  it("names each vignette with both categories as text, not colour alone", () => {
    render(<UnderTriagedList items={items.slice(0, 3)} />);

    const row = screen.getByText("V-017").closest("tr") as HTMLElement;
    expect(within(row).getByText(/^RED/)).toBeTruthy();
    expect(within(row).getByText(/^ORANGE/)).toBeTruthy();
    expect(within(row).getByText("Seizures")).toBeTruthy();
  });

  it("folds rows beyond the third into '+ N more' and opens them on request", () => {
    render(<UnderTriagedList items={items} />);

    expect(screen.queryByText("V-051")).toBeNull();
    expect(screen.getByText(/\+ 3 more/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Show all" }));

    // Nothing was dropped: all six vignettes are listed.
    for (const item of items) {
      expect(screen.getByText(item.external_id)).toBeTruthy();
    }
    expect(screen.queryByText(/\+ 3 more/)).toBeNull();
    expect(screen.getByRole("button", { name: "Show fewer" })).toBeTruthy();
  });

  it("offers no fold when the list is short", () => {
    render(<UnderTriagedList items={items.slice(0, 3)} />);

    expect(screen.queryByRole("button", { name: "Show all" })).toBeNull();
  });

  it("shows a dash for a vignette with no primary complaint", () => {
    render(<UnderTriagedList items={[items[3]]} />);

    const row = screen.getByText("V-051").closest("tr") as HTMLElement;
    expect(within(row).getAllByRole("cell").at(-1)?.textContent).toBe("—");
  });

  it("says so when nothing was under-triaged", () => {
    render(<UnderTriagedList items={[]} />);

    expect(screen.getByText("No under-triaged vignettes in this run.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
