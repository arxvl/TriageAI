/**
 * The audit timeline panel (FR-42, FR-43, FR-45, FR-46, ADR-12).
 *
 * The fixture is W-07's own sample case, C-0137: created at 08:50, recommended
 * YELLOW, adjusted to GREEN eight minutes later, noted and closed. Each assertion
 * is a rule the panel must not lose — the order is the record, the pipeline is not
 * a person, and the append-only guarantee is stated rather than implied.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AuditTimeline as AuditTimelineData, AuditTimelineItem } from "../api/cases";
import { strings } from "../i18n/strings";
import { AuditTimeline } from "./AuditTimeline";

const copy = strings.caseAudit;

/** 08:50:02 Asia/Manila is 00:50:02 UTC (CLAUDE.md §7). */
const ITEMS: readonly AuditTimelineItem[] = [
  {
    ts: "2026-10-01T00:50:02Z",
    actor_name: "J. Cruz",
    actor_role: "INTAKE_STAFF",
    action: "CASE_CREATED",
    label: "Case created",
    details: "channel: walk-in",
  },
  {
    ts: "2026-10-01T00:50:03Z",
    actor_name: null,
    actor_role: null,
    action: "REDFLAG_SCREENED",
    label: "Red-flag pre-screen",
    details: "No red flags found",
  },
  {
    ts: "2026-10-01T00:50:12Z",
    actor_name: null,
    actor_role: null,
    action: "RECOMMENDATION_STORED",
    label: "Recommendation v1: YELLOW",
    details: "Confidence Medium · KB version 7 · 2 references",
  },
  {
    ts: "2026-10-01T00:58:40Z",
    actor_name: "Reviewer Demo",
    actor_role: "VETERINARY_REVIEWER",
    action: "DECISION_RECORDED",
    label: "Decision: Adjusted Yellow → Green",
    details: "Yellow → Green (down-triage)",
  },
];

function makeTimeline(overrides: Partial<AuditTimelineData> = {}): AuditTimelineData {
  return {
    items: [...ITEMS],
    submission_to_recommendation_s: 10,
    recommendation_to_decision_s: 508,
    append_only: true,
    ...overrides,
  };
}

describe("AuditTimeline", () => {
  it("names the case it belongs to, and falls back without one", () => {
    const { unmount } = render(<AuditTimeline timeline={makeTimeline()} caseNo="C-0137" />);
    expect(screen.getByRole("heading", { name: "Audit timeline – C-0137" })).toBeInTheDocument();
    unmount();

    render(<AuditTimeline timeline={makeTimeline()} />);
    expect(screen.getByRole("heading", { name: copy.titleFallback })).toBeInTheDocument();
  });

  // FR-45: the order is what the record says, so it is a list and not a heap.
  it("lists every entry in the order the server sent them", () => {
    const { container } = render(<AuditTimeline timeline={makeTimeline()} caseNo="C-0137" />);

    // `data-action` marks the entries, as against the day heading between them.
    const entries = Array.from(
      container.querySelectorAll("[data-action]"),
      (item) => item.textContent ?? "",
    );

    expect(entries).toHaveLength(ITEMS.length);
    expect(entries[0]).toContain("08:50:02");
    expect(entries[0]).toContain("Case created");
    expect(entries[0]).toContain("channel: walk-in");
    expect(entries[1]).toContain("Red-flag pre-screen");
    expect(entries[2]).toContain("Recommendation v1: YELLOW");
    expect(entries[3]).toContain("Decision: Adjusted Yellow → Green");
  });

  it("names a human actor with their role, and the pipeline as the system (ADR-12)", () => {
    render(<AuditTimeline timeline={makeTimeline()} caseNo="C-0137" />);

    expect(screen.getByText("Reviewer Demo (Veterinary Reviewer)")).toBeInTheDocument();
    expect(screen.getByText("J. Cruz (Intake Staff)")).toBeInTheDocument();
    // Two pipeline entries, neither of them attributed to a person.
    expect(screen.getAllByText(copy.actorSystem)).toHaveLength(2);
  });

  // FR-46, as W-07 prints the two figures.
  it("shows both intervals, and a dash for one the case has not reached", () => {
    const { unmount } = render(<AuditTimeline timeline={makeTimeline()} caseNo="C-0137" />);
    expect(screen.getByText("10 s")).toBeInTheDocument();
    expect(screen.getByText("8 min 28 s")).toBeInTheDocument();
    unmount();

    render(
      <AuditTimeline
        timeline={makeTimeline({ recommendation_to_decision_s: null })}
        caseNo="C-0137"
      />,
    );
    expect(screen.getByText(copy.intervalNotAvailable)).toBeInTheDocument();
  });

  // FR-43, ADR-12.
  it("states that the entries cannot be edited or deleted", () => {
    render(<AuditTimeline timeline={makeTimeline()} caseNo="C-0137" />);
    expect(screen.getByText(copy.appendOnly)).toBeInTheDocument();
  });

  it("names the day whenever it changes, so a case closed overnight still reads right", () => {
    const overnight = makeTimeline({
      items: [
        ITEMS[0],
        {
          ts: "2026-10-01T23:30:00Z",
          actor_name: "Reviewer Demo",
          actor_role: "VETERINARY_REVIEWER",
          action: "CASE_CLOSED",
          label: "Case closed",
          details: "Seen by veterinarian",
        },
      ],
    });

    render(<AuditTimeline timeline={overnight} caseNo="C-0137" />);
    expect(screen.getByText("1 Oct 2026")).toBeInTheDocument();
    expect(screen.getByText("2 Oct 2026")).toBeInTheDocument();
  });

  it("names the day once for a case that stays within it", () => {
    render(<AuditTimeline timeline={makeTimeline()} caseNo="C-0137" />);
    expect(screen.getAllByText("1 Oct 2026")).toHaveLength(1);
  });

  it("still states the guarantee when there is nothing to show", () => {
    render(<AuditTimeline timeline={makeTimeline({ items: [] })} caseNo="C-0137" />);

    expect(screen.getByText(copy.empty)).toBeInTheDocument();
    expect(screen.getByText(copy.appendOnly)).toBeInTheDocument();
    expect(screen.queryByLabelText(copy.eventsLabel)).not.toBeInTheDocument();
  });
});
