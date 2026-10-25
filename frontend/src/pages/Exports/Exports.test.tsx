/**
 * Exports (FR-47, BR-08, SR-12 · UC-16).
 *
 * What the screen must not lose: the BR-08 statement, a date range that is
 * checked before anything is requested, one download per file with the range
 * sent as `from`/`to`, and a visible failure instead of a silent one.
 *
 * All data is fictitious (CLAUDE.md §9).
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { exportPath } from "../../api/exports";
import { strings } from "../../i18n/strings";
import { errorBody, makeUser, renderWithAuth } from "../../test/testUtils";
import { Exports } from "./Exports";

const copy = strings.exports;

interface Stub {
  status?: number;
  body?: unknown;
}

function stubApi(respond: (path: string) => Stub = () => ({ body: "case_no\n" })) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    const stub = respond(url.pathname.replace("/api/v1", "") + url.search);
    const status = stub.status ?? 200;
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => stub.body ?? {},
      blob: async () => new Blob([String(stub.body ?? "")]),
    } as Response;
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function requestedPaths(mock: ReturnType<typeof stubApi>): string[] {
  return mock.mock.calls.map(([input]) => {
    const url = new URL(String(input));
    return url.pathname.replace("/api/v1", "") + url.search;
  });
}

function renderPage() {
  return renderWithAuth(<Exports />, {
    user: makeUser({ role: "ADMINISTRATOR", full_name: "System Administrator" }),
    route: "/admin/exports",
  });
}

function setDate(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

let downloads: string[];

beforeEach(() => {
  downloads = [];
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:fake"),
  });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    downloads.push(this.download);
  });
});

afterEach(() => {
  Reflect.deleteProperty(URL, "createObjectURL");
  Reflect.deleteProperty(URL, "revokeObjectURL");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("the page", () => {
  it("states that exports are de-identified and for academic evaluation only (BR-08)", () => {
    stubApi();
    renderPage();

    expect(screen.getByText(copy.note)).toBeInTheDocument();
    expect(copy.note).toBe("Exports are de-identified and for academic evaluation only (BR-08).");
  });

  it("offers a date range and both downloads", () => {
    stubApi();
    renderPage();

    expect(screen.getByLabelText(copy.fromLabel)).toBeInTheDocument();
    expect(screen.getByLabelText(copy.toLabel)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.cases.button })).toBeEnabled();
    expect(screen.getByRole("button", { name: copy.audit.button })).toBeEnabled();
  });
});

describe("exportPath", () => {
  it("leaves out an empty side of the range", () => {
    expect(exportPath("audit", { from: "", to: "" })).toBe("/exports/audit");
    expect(exportPath("audit", { from: "2026-03-01", to: "" })).toBe(
      "/exports/audit?from=2026-03-01",
    );
  });

  it("asks for csv on the cases export", () => {
    expect(exportPath("cases", { from: "2026-03-01", to: "2026-03-31" })).toBe(
      "/exports/cases?from=2026-03-01&to=2026-03-31&format=csv",
    );
  });
});

describe("downloading", () => {
  it("sends the chosen range with the cases request and saves the file", async () => {
    const mock = stubApi();
    renderPage();
    setDate(copy.fromLabel, "2026-03-01");
    setDate(copy.toLabel, "2026-03-31");

    fireEvent.click(screen.getByRole("button", { name: copy.cases.button }));

    await waitFor(() =>
      expect(downloads).toEqual(["triageai-cases-export-2026-03-01_2026-03-31.csv"]),
    );
    expect(requestedPaths(mock)).toEqual([
      "/exports/cases?from=2026-03-01&to=2026-03-31&format=csv",
    ]);
  });

  it("requests the audit export without a range when none is chosen", async () => {
    const mock = stubApi();
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: copy.audit.button }));

    await waitFor(() => expect(downloads).toEqual(["triageai-audit-export.csv"]));
    expect(requestedPaths(mock)).toEqual(["/exports/audit"]);
  });

  it("confirms with a toast", async () => {
    stubApi();
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: copy.cases.button }));

    expect(await screen.findByText(copy.done.replace("{kind}", "cases"))).toBeInTheDocument();
  });

  it("disables both buttons while a download is under way", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        await gate;
        return { ok: true, status: 200, blob: async () => new Blob(["x"]) } as Response;
      }),
    );
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: copy.cases.button }));

    expect(await screen.findByRole("button", { name: copy.exporting })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.audit.button })).toBeDisabled();
    release();
    await waitFor(() => expect(downloads).toHaveLength(1));
  });
});

describe("the range check", () => {
  it("explains a start after the end and requests nothing", () => {
    const mock = stubApi();
    renderPage();
    setDate(copy.fromLabel, "2026-03-31");
    setDate(copy.toLabel, "2026-03-01");

    expect(screen.getByText(copy.rangeInvalid)).toBeInTheDocument();
    expect(screen.getByLabelText(copy.toLabel)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: copy.cases.button })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.audit.button })).toBeDisabled();
    expect(mock).not.toHaveBeenCalled();
  });

  it("accepts the same day on both sides", () => {
    stubApi();
    renderPage();
    setDate(copy.fromLabel, "2026-03-01");
    setDate(copy.toLabel, "2026-03-01");

    expect(screen.queryByText(copy.rangeInvalid)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.cases.button })).toBeEnabled();
  });
});

describe("failures", () => {
  it("shows an alert and saves nothing when the download fails", async () => {
    stubApi(() => ({ status: 500 }));
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: copy.cases.button }));

    expect(await screen.findByRole("alert")).toHaveTextContent(copy.errors.failed);
    expect(downloads).toEqual([]);
  });

  it("explains a refusal for lack of permission", async () => {
    stubApi(() => ({ status: 403, body: errorBody("FORBIDDEN", "Not allowed.") }));
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: copy.audit.button }));

    expect(await screen.findByRole("alert")).toHaveTextContent(copy.errors.forbidden);
    expect(downloads).toEqual([]);
  });

  it("shows the server's message for an invalid range", async () => {
    stubApi(() => ({
      status: 422,
      body: errorBody("VALIDATION_ERROR", "The start date must be on or before the end date."),
    }));
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: copy.cases.button }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The start date must be on or before the end date.",
    );
  });

  it("clears the failure on the next attempt", async () => {
    let fail = true;
    stubApi(() => (fail ? { status: 500 } : { body: "ok" }));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: copy.cases.button }));
    await screen.findByRole("alert");

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: copy.cases.button }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });
});
