/**
 * W-10 Evaluation Console (FR-64..FR-69, NFR-14, NFR-16, NFR-17, IR-22 · UC-15).
 *
 * What the screen must not lose:
 *
 * - a persistent "MOCK MODE" banner whenever the selected run used only mock
 *   stages, and none otherwise (ADR-17);
 * - the cards, the confusion matrix and the under-triaged list for a finished
 *   run, and a progress bar instead while it runs;
 * - a run that is waiting is re-read, a settled one is not, and a hidden tab
 *   stops asking (IR-22);
 * - Start is blocked while a run is in progress, and exports open only when the
 *   run has finished (FR-69).
 *
 * All data here is fictitious (CLAUDE.md §9).
 */
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EVAL_RUN_POLL_INTERVAL_MS, type EvalRun, type EvalSet } from "../../api/eval";
import { strings } from "../../i18n/strings";
import { makeRun, makeSet } from "../../test/evalFixtures";
import { errorBody, makeUser, renderWithAuth } from "../../test/testUtils";
import { Evaluation } from "./Evaluation";

const copy = strings.evaluation;

const OLDER = makeRun({
  id: "11111111-aaaa-4000-8000-0000000000f1",
  created_at: "2026-10-20T02:00:00Z",
});
const NEWER = makeRun({
  id: "33333333-cccc-4000-8000-0000000000f2",
  created_at: "2026-10-21T02:00:00Z",
  fully_mocked: false,
});

interface Stubbed {
  status?: number;
  body?: unknown;
}

interface World {
  sets: EvalSet[];
  runs: EvalRun[];
  /** Answer for a request the default routing does not cover. */
  override?: (method: string, path: string) => Stubbed | undefined;
}

/** Answer by method and path, because `/eval/runs` is a prefix of the other routes. */
function stubApi(world: World) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input)).pathname.replace("/api/v1", "");
    const query = new URL(String(input)).search;
    const method = init?.method ?? "GET";

    let stub: Stubbed | undefined = world.override?.(method, path + query);
    if (stub === undefined) {
      const detail = /^\/eval\/runs\/([^/]+)$/.exec(path);
      if (method === "GET" && path === "/eval/sets") {
        stub = { body: { items: world.sets, total: world.sets.length } };
      } else if (method === "GET" && path === "/eval/runs") {
        stub = { body: { items: world.runs } };
      } else if (method === "GET" && /^\/eval\/runs\/[^/]+\/export$/.test(path)) {
        stub = { body: "external_id,predicted_category\n" };
      } else if (method === "GET" && detail !== null) {
        const run = world.runs.find((entry) => entry.id === detail[1]);
        stub = run === undefined ? { status: 404 } : { body: run };
      } else {
        stub = { status: 404 };
      }
    }
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

function callsTo(mock: ReturnType<typeof stubApi>, method: string, fragment: string) {
  return mock.mock.calls.filter(
    ([input, init]) => (init?.method ?? "GET") === method && String(input).includes(fragment),
  );
}

/** Detail reads only: `/eval/runs/<id>`, not the list and not the export. */
function detailReads(mock: ReturnType<typeof stubApi>) {
  return mock.mock.calls.filter(([input, init]) => {
    const path = new URL(String(input)).pathname;
    return (init?.method ?? "GET") === "GET" && /\/eval\/runs\/[^/]+$/.test(path);
  });
}

function renderConsole() {
  return renderWithAuth(<Evaluation />, {
    user: makeUser({ role: "ADMINISTRATOR", full_name: "System Administrator" }),
    route: "/admin/evaluation",
  });
}

beforeEach(() => {
  document.cookie = "triageai_csrf=csrf-token-value; path=/";
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the console with finished runs", () => {
  it("lists the sets, numbers the runs from the oldest, and opens the newest", async () => {
    stubApi({ sets: [makeSet()], runs: [NEWER, OLDER] });
    renderConsole();

    expect(await screen.findByRole("option", { name: "Set v1 – 80 vignettes" })).toBeTruthy();
    expect(
      await screen.findByRole("heading", { name: "Run #2 · completed · 80 of 80 vignettes" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Show run #1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Show run #2" }).getAttribute("aria-current")).toBe(
      "true",
    );
  });

  it("shows the cards, the matrix and the under-triaged list for the selected run", async () => {
    stubApi({ sets: [makeSet()], runs: [NEWER] });
    renderConsole();

    const cards = await screen.findByRole("list", { name: copy.metrics.title });
    expect(within(cards).getByText("0.84")).toBeTruthy();
    expect(within(cards).getByText("8.4 / 16.9 s")).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Confusion matrix/ })).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Under-triaged vignettes/ })).toBeTruthy();
    expect(screen.getByText("V-017")).toBeTruthy();
  });

  it("writes the run's own configuration under the selector (NFR-23)", async () => {
    stubApi({ sets: [makeSet()], runs: [NEWER] });
    renderConsole();

    expect(
      await screen.findByText(
        "Model: model-x · Prompt v1.3 · KB 22222222 · temperature 0 · top-k 5",
      ),
    ).toBeTruthy();
  });

  it("switches to another run when its name is chosen", async () => {
    stubApi({ sets: [makeSet()], runs: [NEWER, OLDER] });
    renderConsole();
    await screen.findByRole("heading", { name: /Run #2/ });

    fireEvent.click(screen.getByRole("button", { name: "Show run #1" }));

    expect(
      await screen.findByRole("heading", { name: "Run #1 · completed · 80 of 80 vignettes" }),
    ).toBeTruthy();
  });

  it("notes vignettes that failed and were left out of the metrics", async () => {
    const run = makeRun({
      metrics: { ...NEWER.metrics!, counts: { total: 80, failed: 4, scored: 76 } },
    });
    stubApi({ sets: [makeSet()], runs: [run] });
    renderConsole();

    expect(
      await screen.findByText("4 vignette(s) failed and are excluded from the metrics."),
    ).toBeTruthy();
  });

  it("says a run that did not finish has no metrics", async () => {
    const failed = makeRun({ status: "FAILED", metrics: null, progress: { done: 12, total: 80 } });
    stubApi({ sets: [makeSet()], runs: [failed] });
    renderConsole();

    expect(await screen.findByText(copy.runs.failedRun)).toBeTruthy();
    expect(screen.queryByRole("list", { name: copy.metrics.title })).toBeNull();
    // A failed run can still be exported (FR-69).
    expect(screen.getByRole("button", { name: copy.export.csv }).hasAttribute("disabled")).toBe(
      false,
    );
  });

  it("reports a load failure in plain language", async () => {
    stubApi({
      sets: [],
      runs: [],
      override: (_method, path) => (path === "/eval/runs" ? { status: 500 } : undefined),
    });
    renderConsole();

    expect(await screen.findByRole("alert")).toHaveTextContent(copy.errors.unexpected);
  });

  it("invites a first upload and a first run when there is nothing yet", async () => {
    stubApi({ sets: [], runs: [] });
    renderConsole();

    expect(await screen.findByText(copy.noSets)).toBeTruthy();
    expect(screen.getByText(copy.runs.empty)).toBeTruthy();
    expect(screen.getByText(copy.configPending)).toBeTruthy();
    expect(screen.getByRole("button", { name: copy.start }).hasAttribute("disabled")).toBe(true);
  });
});

describe("the MOCK MODE banner (ADR-17)", () => {
  it("is shown, in words, for a run whose stages were all mocks", async () => {
    stubApi({ sets: [makeSet()], runs: [makeRun({ fully_mocked: true })] });
    renderConsole();

    const banner = await screen.findByText("MOCK MODE – results are not model results");
    expect(banner.getAttribute("role")).toBe("status");
  });

  it("is absent for a run that used a real stage", async () => {
    stubApi({ sets: [makeSet()], runs: [makeRun({ fully_mocked: false })] });
    renderConsole();
    await screen.findByRole("list", { name: copy.metrics.title });

    expect(screen.queryByText(copy.mockBanner)).toBeNull();
  });

  it("follows the run that is selected", async () => {
    const mocked = makeRun({
      id: "44444444-dddd-4000-8000-0000000000f3",
      created_at: "2026-10-22T02:00:00Z",
      fully_mocked: true,
    });
    stubApi({ sets: [makeSet()], runs: [OLDER, mocked] });
    renderConsole();
    await screen.findByText(copy.mockBanner);

    fireEvent.click(screen.getByRole("button", { name: "Show run #1" }));

    await waitFor(() => expect(screen.queryByText(copy.mockBanner)).toBeNull());
  });
});

describe("a run in progress", () => {
  const running = makeRun({
    status: "RUNNING",
    progress: { done: 20, total: 80 },
    metrics: null,
    fully_mocked: true,
  });

  it("shows a progress bar and no metrics yet", async () => {
    stubApi({ sets: [makeSet()], runs: [running] });
    renderConsole();

    const bar = await screen.findByRole("progressbar", { name: copy.runs.progressLabel });
    expect(bar.getAttribute("aria-valuenow")).toBe("25");
    expect(bar.getAttribute("aria-valuetext")).toBe("20 of 80 vignettes");
    expect(screen.queryByRole("list", { name: copy.metrics.title })).toBeNull();
  });

  it("blocks Start and the exports until it has finished", async () => {
    stubApi({ sets: [makeSet()], runs: [running] });
    renderConsole();
    await screen.findByRole("progressbar");

    expect(screen.getByRole("button", { name: copy.start }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(copy.startBlockedRunning)).toBeTruthy();
    expect(screen.getByRole("button", { name: copy.export.csv }).hasAttribute("disabled")).toBe(
      true,
    );
    expect(screen.getByRole("button", { name: copy.export.json }).hasAttribute("disabled")).toBe(
      true,
    );
  });
});

describe("starting a run (FR-65)", () => {
  it("posts the chosen set, then opens the new run", async () => {
    const world: World = { sets: [makeSet()], runs: [OLDER] };
    const queued = makeRun({
      id: "55555555-eeee-4000-8000-0000000000f4",
      created_at: "2026-10-23T02:00:00Z",
      status: "QUEUED",
      progress: { done: 0, total: 80 },
      metrics: null,
      fully_mocked: null,
      config: null,
    });
    world.override = (method, path) => {
      if (method === "POST" && path === "/eval/runs") {
        world.runs.push(queued);
        return { status: 202, body: queued };
      }
      return undefined;
    };
    const mock = stubApi(world);
    renderConsole();
    await screen.findByRole("heading", { name: /Run #1/ });

    fireEvent.click(screen.getByRole("button", { name: copy.start }));

    expect(
      await screen.findByRole("heading", { name: "Run #2 · queued · 0 of 80 vignettes" }),
    ).toBeTruthy();
    const [post] = callsTo(mock, "POST", "/eval/runs");
    expect(JSON.parse(String(post[1]?.body))).toEqual({ set_id: world.sets[0].id });
    expect(screen.getByRole("progressbar")).toBeTruthy();
  });

  it("sends the set that was picked, not just the first", async () => {
    const second = makeSet({ id: "00000000-0000-4000-8000-0000000000e2", name: "Set v2" });
    const mock = stubApi({
      sets: [makeSet(), second],
      runs: [],
      override: (method, path) =>
        method === "POST" && path === "/eval/runs" ? { status: 500 } : undefined,
    });
    renderConsole();
    await screen.findByRole("option", { name: "Set v2 – 80 vignettes" });

    fireEvent.change(screen.getByLabelText(copy.setLabel), { target: { value: second.id } });
    fireEvent.click(screen.getByRole("button", { name: copy.start }));

    await waitFor(() => expect(callsTo(mock, "POST", "/eval/runs")).toHaveLength(1));
    expect(JSON.parse(String(callsTo(mock, "POST", "/eval/runs")[0][1]?.body))).toEqual({
      set_id: second.id,
    });
  });

  it("says so when the run could not be started", async () => {
    stubApi({
      sets: [makeSet()],
      runs: [],
      override: (method, path) =>
        method === "POST" && path === "/eval/runs"
          ? { status: 500, body: errorBody("INTERNAL_ERROR", "boom") }
          : undefined,
    });
    renderConsole();
    await screen.findByRole("option", { name: /Set v1/ });

    fireEvent.click(screen.getByRole("button", { name: copy.start }));

    expect(await screen.findByRole("alert")).toHaveTextContent(copy.errors.startFailed);
  });
});

describe("exporting a run (FR-69)", () => {
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
  });

  it.each([
    ["csv", copy.export.csv],
    ["json", copy.export.json],
  ])("downloads the %s export under the run's name", async (format, label) => {
    const mock = stubApi({ sets: [makeSet()], runs: [NEWER] });
    renderConsole();
    await screen.findByRole("list", { name: copy.metrics.title });

    fireEvent.click(screen.getByRole("button", { name: label }));

    await waitFor(() => expect(downloads).toEqual([`evaluation-run-33333333.${format}`]));
    const [call] = callsTo(mock, "GET", "/export");
    expect(String(call[0])).toContain(`/eval/runs/${NEWER.id}/export?format=${format}`);
  });

  it("explains a refusal because the run has not finished", async () => {
    stubApi({
      sets: [makeSet()],
      runs: [NEWER],
      override: (_method, path) =>
        path.includes("/export")
          ? { status: 409, body: errorBody("EVALUATION_NOT_FINISHED", "Not finished.") }
          : undefined,
    });
    renderConsole();
    await screen.findByRole("list", { name: copy.metrics.title });

    fireEvent.click(screen.getByRole("button", { name: copy.export.csv }));

    expect(await screen.findByRole("alert")).toHaveTextContent(copy.export.unavailable);
    expect(downloads).toEqual([]);
  });

  it("reports any other failure and downloads nothing", async () => {
    stubApi({
      sets: [makeSet()],
      runs: [NEWER],
      override: (_method, path) => (path.includes("/export") ? { status: 500 } : undefined),
    });
    renderConsole();
    await screen.findByRole("list", { name: copy.metrics.title });

    fireEvent.click(screen.getByRole("button", { name: copy.export.json }));

    expect(await screen.findByRole("alert")).toHaveTextContent(copy.export.failed);
    expect(downloads).toEqual([]);
  });
});

/** IR-22: a waiting run is re-read, a settled one is not, a hidden tab stops asking. */
describe("polling a run", () => {
  function setVisibility(state: "visible" | "hidden") {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => state,
    });
    // TanStack Query's focus manager listens on the window.
    window.dispatchEvent(new Event("visibilitychange"));
    document.dispatchEvent(new Event("visibilitychange"));
  }

  afterEach(() => {
    setVisibility("visible");
  });

  const running = makeRun({ status: "RUNNING", progress: { done: 10, total: 80 }, metrics: null });

  async function settle() {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
  }

  async function tick(ms: number) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  it("re-reads a running run on its interval, and stops once it is done", async () => {
    vi.useFakeTimers();
    const world: World = { sets: [makeSet()], runs: [running] };
    const mock = stubApi(world);
    renderConsole();
    await settle();
    expect(detailReads(mock)).toHaveLength(1);

    await tick(EVAL_RUN_POLL_INTERVAL_MS);
    expect(detailReads(mock)).toHaveLength(2);

    world.runs = [makeRun({ id: running.id, created_at: running.created_at })];
    await tick(EVAL_RUN_POLL_INTERVAL_MS);
    // The answer to that read still has to be parsed and rendered.
    await tick(50);
    const readsWhenDone = detailReads(mock).length;
    expect(screen.getByRole("list", { name: copy.metrics.title })).toBeTruthy();

    await tick(EVAL_RUN_POLL_INTERVAL_MS * 5);
    expect(detailReads(mock)).toHaveLength(readsWhenDone);
  });

  it("does not poll a run that has already finished", async () => {
    vi.useFakeTimers();
    const mock = stubApi({ sets: [makeSet()], runs: [NEWER] });
    renderConsole();
    await settle();
    const reads = mock.mock.calls.length;

    await tick(EVAL_RUN_POLL_INTERVAL_MS * 5);

    expect(mock.mock.calls).toHaveLength(reads);
  });

  it("stops asking while the tab is hidden, and resumes when it comes back", async () => {
    vi.useFakeTimers();
    const mock = stubApi({ sets: [makeSet()], runs: [running] });
    renderConsole();
    await settle();
    expect(detailReads(mock)).toHaveLength(1);

    setVisibility("hidden");
    await tick(EVAL_RUN_POLL_INTERVAL_MS * 3);
    expect(detailReads(mock)).toHaveLength(1);

    setVisibility("visible");
    await settle();
    expect(detailReads(mock).length).toBeGreaterThan(1);
  });
});
