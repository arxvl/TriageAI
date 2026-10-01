import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { strings } from "../i18n/strings";
import { RedFlagBanner, type QueueRedFlagAlert } from "./RedFlagBanner";

/** Fictitious, as every fixture in this project is (CLAUDE.md §9). */
const alert: QueueRedFlagAlert = {
  caseId: "00000000-0000-4000-8000-000000000042",
  caseNo: "C-0142",
  summary: "male cat producing no urine",
};

function renderBanner(alerts: readonly QueueRedFlagAlert[]) {
  return render(
    <MemoryRouter>
      <RedFlagBanner alerts={alerts} />
    </MemoryRouter>,
  );
}

describe("RedFlagBanner", () => {
  // P05 is what fills it; until then the screen must not reserve space for it.
  it("renders nothing while there are no alerts", () => {
    const { container } = renderBanner([]);

    expect(container).toBeEmptyDOMElement();
  });

  it("announces an alert and links to its case", () => {
    renderBanner([alert]);

    expect(screen.getByRole("alert")).toHaveTextContent("C-0142");
    expect(screen.getByRole("alert")).toHaveTextContent(alert.summary);
    expect(screen.getByRole("link", { name: strings.queue.redFlagOpenCase })).toHaveAttribute(
      "href",
      `/cases/${alert.caseId}`,
    );
  });

  it("lists every alert", () => {
    renderBanner([alert, { ...alert, caseId: "other-id", caseNo: "C-0143" }]);

    expect(screen.getAllByRole("link", { name: strings.queue.redFlagOpenCase })).toHaveLength(2);
  });
});
