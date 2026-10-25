import { describe, expect, it } from "vitest";

import { makeRun, makeTarget, TARGETS } from "../../test/evalFixtures";
import {
  configLine,
  exportFileName,
  fill,
  formatValue,
  isMockRun,
  latencyTargetText,
  latencyValueText,
  progressPercent,
  runNumbers,
  shortId,
  targetText,
} from "./runFormat";

const target = (key: string) => TARGETS.find((entry) => entry.key === key)!;

describe("how a target is written", () => {
  it("writes a score to two decimals and its target with the comparison", () => {
    expect(formatValue(target("macro_f1"))).toBe("0.84");
    expect(targetText(target("macro_f1"))).toBe("target ≥ 0.70");
  });

  it("writes the under-triage fraction as a percentage", () => {
    expect(formatValue(target("under_triage_rate"))).toBe("7.5%");
    expect(targetText(target("under_triage_rate"))).toBe("target ≤ 10%");
  });

  it("shows n/a, not 0, for a value that could not be computed", () => {
    expect(formatValue(makeTarget({ value: null, status: "n/a" }))).toBe("n/a");
  });

  it("joins the two latency percentiles into one value and one target", () => {
    const p50 = target("latency_p50");
    const p95 = target("latency_p95");
    expect(latencyValueText(p50, p95)).toBe("8.4 / 16.9 s");
    expect(latencyTargetText(p50, p95)).toBe("target ≤ 10 / 20 s");
  });

  it("reads n/a when neither latency percentile exists", () => {
    const missing = (key: string) => makeTarget({ key, value: null, status: "n/a", unit: "s" });
    expect(latencyValueText(missing("latency_p50"), missing("latency_p95"))).toBe("n/a");
    expect(latencyValueText(undefined, undefined)).toBe("n/a");
  });
});

describe("the run's own facts", () => {
  it("is a mock run only when the API says every stage was a mock", () => {
    expect(isMockRun(makeRun({ fully_mocked: true }))).toBe(true);
    expect(isMockRun(makeRun({ fully_mocked: false }))).toBe(false);
    // A queued run has no snapshot yet; nothing is claimed either way.
    expect(isMockRun(makeRun({ fully_mocked: null }))).toBe(false);
    expect(isMockRun(undefined)).toBe(false);
  });

  it("numbers runs from the oldest, whatever order the API lists them in", () => {
    const older = makeRun({ id: "older", created_at: "2026-10-01T00:00:00Z" });
    const newer = makeRun({ id: "newer", created_at: "2026-10-02T00:00:00Z" });

    const numbers = runNumbers([newer, older]);

    expect(numbers.get("older")).toBe(1);
    expect(numbers.get("newer")).toBe(2);
  });

  it("builds the configuration line from the run's own snapshot (NFR-23)", () => {
    expect(configLine(makeRun())).toBe(
      "Model: model-x · Prompt v1.3 · KB 22222222 · temperature 0 · top-k 5",
    );
  });

  it("says the temperature was the provider's own when none was sent", () => {
    const run = makeRun({
      config: { model_id: "m", prompt_version: "p", temperature: null, top_k: 5 },
    });
    expect(configLine(run)).toContain("temperature provider default");
  });

  it("has no configuration line before a run has recorded one", () => {
    expect(configLine(undefined)).toBeNull();
    expect(configLine(makeRun({ config: null }))).toBeNull();
  });

  it("names the download like the server's own Content-Disposition", () => {
    expect(exportFileName("11111111-aaaa-4000-8000-0000000000f1", "csv")).toBe(
      "evaluation-run-11111111.csv",
    );
    expect(shortId("abcdefghijkl")).toBe("abcdefgh");
  });
});

describe("small helpers", () => {
  it("rounds progress and survives an empty set", () => {
    expect(progressPercent(40, 80)).toBe(50);
    expect(progressPercent(80, 80)).toBe(100);
    expect(progressPercent(0, 0)).toBe(0);
    expect(progressPercent(9, 3)).toBe(100);
  });

  it("fills every occurrence of a placeholder", () => {
    expect(fill("{a} and {a} and {b}", { a: "x", b: 2 })).toBe("x and x and 2");
  });
});
