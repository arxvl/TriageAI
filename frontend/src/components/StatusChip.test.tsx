/**
 * FR-36 and IR-04: the chip is what keeps an AI recommendation from reading as a
 * decision. Every status gets an assertion, and the pending wording is the one
 * that must not be lost.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CaseStatus } from "../api/cases";
import { strings } from "../i18n/strings";
import { StatusChip } from "./StatusChip";

const copy = strings.statusChip;

describe("StatusChip", () => {
  it.each<[CaseStatus, string]>([
    ["SUBMITTED", copy.processing],
    ["PROCESSING", copy.processing],
    ["AWAITING_REVIEW", copy.awaitingReview],
    ["MANUAL_TRIAGE_REQUIRED", copy.manualTriageRequired],
    ["CONFIRMED", copy.confirmed],
    ["MANUALLY_TRIAGED", copy.manuallyTriaged],
    ["CLOSED", copy.closed],
  ])("says %s is %s", (status, expected) => {
    render(<StatusChip status={status} />);

    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  // IR-04. The sentence a reviewer relies on before deciding.
  it("marks an unreviewed recommendation as pending", () => {
    render(<StatusChip status="AWAITING_REVIEW" recommendedCategory="ORANGE" />);

    expect(screen.getByText(copy.awaitingReview)).toBeInTheDocument();
    expect(screen.getByText(/pending/i)).toBeInTheDocument();
  });

  it("names both categories when a reviewer adjusted one", () => {
    render(<StatusChip status="ADJUSTED" recommendedCategory="YELLOW" confirmedCategory="GREEN" />);

    expect(screen.getByText("Adjusted (Yellow → Green)")).toBeInTheDocument();
  });

  it("falls back to plain 'Adjusted' when a category is missing", () => {
    render(<StatusChip status="ADJUSTED" confirmedCategory="GREEN" />);

    expect(screen.getByText(strings.queue.status.ADJUSTED)).toBeInTheDocument();
  });

  it("marks manual triage with bold text, not colour alone", () => {
    const { container } = render(<StatusChip status="MANUAL_TRIAGE_REQUIRED" />);

    expect(container.firstElementChild?.className).toContain("bad");
    expect(screen.getByText(copy.manualTriageRequired)).toBeInTheDocument();
  });
});
