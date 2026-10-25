/**
 * The W-10 metric cards (NFR-01, NFR-16, NFR-17, IR-03).
 *
 * What the cards must not lose: every threshold comes from the API's `targets`
 * (nothing is hard-coded), the result is written in words, and the two latency
 * targets share a card.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeTarget, TARGETS } from "../../test/evalFixtures";
import { MetricCards } from "./MetricCards";

function card(label: string): HTMLElement {
  return screen.getByText(label).closest("li") as HTMLElement;
}

describe("the metric cards", () => {
  it("shows six cards: five measures and one joint latency card", () => {
    render(<MetricCards targets={TARGETS} />);

    expect(screen.getAllByRole("listitem")).toHaveLength(6);
  });

  it("writes each value with its target and a result in words", () => {
    render(<MetricCards targets={TARGETS} />);

    const f1 = within(card("Macro-F1"));
    expect(f1.getByText("0.84")).toBeTruthy();
    expect(f1.getByText("target ≥ 0.70")).toBeTruthy();
    expect(f1.getByText("✓ target met")).toBeTruthy();

    const under = within(card("Under-triage rate"));
    expect(under.getByText("7.5%")).toBeTruthy();
    expect(under.getByText("target ≤ 10%")).toBeTruthy();
  });

  it("combines latency p50 and p95 in one card", () => {
    render(<MetricCards targets={TARGETS} />);

    const latency = within(card("Latency p50 / p95"));
    expect(latency.getByText("8.4 / 16.9 s")).toBeTruthy();
    expect(latency.getByText("target ≤ 10 / 20 s")).toBeTruthy();
    expect(screen.queryByText("Latency p50")).toBeNull();
  });

  it("reports a missed target as 'not met', in words and without hiding the value", () => {
    const missed = TARGETS.map((target) =>
      target.key === "mrr" ? { ...target, value: 0.55, status: "FAIL" as const } : target,
    );
    render(<MetricCards targets={missed} />);

    const mrr = within(card("MRR"));
    expect(mrr.getByText("0.55")).toBeTruthy();
    expect(mrr.getByText("✗ target not met")).toBeTruthy();
  });

  it("marks a metric that could not be computed as n/a, never as 0", () => {
    const unavailable = TARGETS.map((target) =>
      target.key === "recall_at_k" ? { ...target, value: null, status: "n/a" as const } : target,
    );
    render(<MetricCards targets={unavailable} />);

    const recall = within(card("Recall@5"));
    expect(recall.getByText("n/a")).toBeTruthy();
    expect(recall.getByText("n/a – not computed")).toBeTruthy();
    expect(recall.queryByText("0.00")).toBeNull();
  });

  it("calls the latency card met only when both percentiles are", () => {
    const slowTail = TARGETS.map((target) =>
      target.key === "latency_p95" ? { ...target, value: 24.2, status: "FAIL" as const } : target,
    );
    render(<MetricCards targets={slowTail} />);

    const latency = within(card("Latency p50 / p95"));
    expect(latency.getByText("8.4 / 24.2 s")).toBeTruthy();
    expect(latency.getByText("✗ target not met")).toBeTruthy();
  });

  it("draws a card for whatever targets the API sends, with no thresholds of its own", () => {
    render(
      <MetricCards targets={[makeTarget({ label: "Custom", threshold: 0.5, value: 0.51 })]} />,
    );

    expect(within(card("Custom")).getByText("target ≥ 0.50")).toBeTruthy();
  });
});
