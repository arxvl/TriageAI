/**
 * W-02 (FR-29, FR-30, FR-36, FR-39, IR-03, IR-22).
 *
 * The fixture is the wireframe's sample data, which is the useful shape: a RED
 * case whose target is 0, a case with no category at all, an overdue YELLOW, and
 * one still in the pipeline. Every number a row shows comes from the response, so
 * none of these assertions depend on the wall clock.
 *
 * The 900 px card layout (W-11) is CSS, which jsdom does not apply. What is
 * asserted here is the thing the layout needs — a `data-label` on every cell; the
 * layout itself is checked by hand at 768 px.
 */
import { fireEvent, screen, waitFor, within, act } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QUEUE_POLL_INTERVAL_MS, type CaseListResponse, type CaseQueueItem } from "../../api/cases";
import { strings } from "../../i18n/strings";
import { makeUser, renderWithAuth, stubFetch } from "../../test/testUtils";
import { TriageQueue } from "./TriageQueue";

const copy = strings.queue;

/** Fictitious cases, as every fixture in this project is (CLAUDE.md §9). */
const RED_CASE: CaseQueueItem = {
  id: "00000000-0000-4000-8000-000000000141",
  case_no: "C-0141",
  status: "AWAITING_REVIEW",
  created_at: "2026-10-01T01:42:00Z",
  species: "DOG",
  pet_name: "Bantay",
  age_value: 8,
  age_unit: "YEARS",
  breed: null,
  primary_complaint_code: "DYSPNEA",
  primary_complaint_name: "Difficulty breathing",
  category: "RED",
  recommended_category: "RED",
  confirmed_category: null,
  decision_type: null,
  waiting_minutes: 1,
  target_minutes: 0,
  // The API is right; the screen still does not call a RED case overdue.
  is_overdue: true,
  has_red_flag: true,
};

const MANUAL_CASE: CaseQueueItem = {
  id: "00000000-0000-4000-8000-000000000140",
  case_no: "C-0140",
  status: "MANUAL_TRIAGE_REQUIRED",
  created_at: "2026-10-01T01:20:00Z",
  species: "CAT",
  pet_name: "Kiko",
  age_value: 6,
  age_unit: "YEARS",
  breed: null,
  primary_complaint_code: null,
  primary_complaint_name: null,
  category: null,
  recommended_category: null,
  confirmed_category: null,
  decision_type: null,
  waiting_minutes: 22,
  target_minutes: null,
  is_overdue: false,
  has_red_flag: false,
};

const OVERDUE_CASE: CaseQueueItem = {
  id: "00000000-0000-4000-8000-000000000138",
  case_no: "C-0138",
  status: "CONFIRMED",
  created_at: "2026-10-01T00:31:00Z",
  species: "DOG",
  pet_name: "Choco",
  age_value: 2,
  age_unit: "YEARS",
  breed: null,
  primary_complaint_code: "VOMITING",
  primary_complaint_name: "Repeated vomiting with lethargy",
  category: "YELLOW",
  recommended_category: "YELLOW",
  confirmed_category: "YELLOW",
  decision_type: "CONFIRM",
  waiting_minutes: 64,
  target_minutes: 60,
  is_overdue: true,
  has_red_flag: false,
};

const PROCESSING_CASE: CaseQueueItem = {
  id: "00000000-0000-4000-8000-000000000143",
  case_no: "C-0143",
  status: "PROCESSING",
  created_at: "2026-10-01T02:00:00Z",
  species: "CAT",
  pet_name: null,
  age_value: null,
  age_unit: null,
  breed: null,
  primary_complaint_code: null,
  primary_complaint_name: null,
  category: null,
  recommended_category: null,
  confirmed_category: null,
  decision_type: null,
  waiting_minutes: 0,
  target_minutes: null,
  is_overdue: false,
  has_red_flag: false,
};

function queueResponse(items: CaseQueueItem[] = []): CaseListResponse {
  return {
    items,
    counts: {
      by_category: { RED: 1, ORANGE: 0, YELLOW: 1, GREEN: 0, BLUE: 0 },
      manual_count: 1,
      awaiting_review_count: 1,
      total: 4,
    },
    generated_at: "2026-10-01T01:43:00Z",
  };
}

const FULL_QUEUE = [RED_CASE, MANUAL_CASE, OVERDUE_CASE, PROCESSING_CASE];

function renderQueue() {
  return renderWithAuth(
    <Routes>
      <Route path="/queue" element={<TriageQueue />} />
      <Route path="/cases/new" element={<p>new case screen</p>} />
      <Route path="/cases/:caseId" element={<p>case detail screen</p>} />
    </Routes>,
    { route: "/queue", user: makeUser({ role: "VETERINARY_REVIEWER" }) },
  );
}

/** The last path `apiFetch` asked for, which is where the filters show up. */
function lastRequestUrl(mock: ReturnType<typeof stubFetch>): string {
  const call = mock.mock.calls.at(-1);
  return String(call?.[0]);
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("TriageQueue rows", () => {
  beforeEach(() => {
    stubFetch({ "/cases": { body: queueResponse(FULL_QUEUE) } });
  });

  it("renders the rows in the order the server returned them (FR-29)", async () => {
    renderQueue();

    const rows = await screen.findAllByRole("row");
    // Row 0 is the header.
    expect(within(rows[1]).getByText("C-0141")).toBeInTheDocument();
    expect(within(rows[2]).getByText("C-0140")).toBeInTheDocument();
    expect(within(rows[3]).getByText("C-0138")).toBeInTheDocument();
    expect(within(rows[4]).getByText("C-0143")).toBeInTheDocument();
  });

  it("shows the badge, patient, complaint and arrival time for a case", async () => {
    renderQueue();

    const row = (await screen.findByText("C-0141")).closest("tr");
    expect(row).not.toBeNull();
    const cells = within(row as HTMLElement);

    // Scoped to the Urgency cell: "Immediate" is RED's target time *and* what
    // the waiting cell says for a target of 0, so it is on the row twice.
    const urgency = within(
      (row as HTMLElement).querySelector('[data-label="Urgency"]') as HTMLElement,
    );
    expect(urgency.getByText(strings.vtl.codes.RED)).toBeInTheDocument();
    expect(urgency.getByText(strings.vtl.targets.RED)).toBeInTheDocument();

    expect(cells.getByText("Dog · Bantay · 8 y")).toBeInTheDocument();
    expect(cells.getByText("Difficulty breathing")).toBeInTheDocument();
    // 01:42 UTC is 09:42 in Asia/Manila.
    expect(cells.getByText("09:42")).toBeInTheDocument();
  });

  it("marks a case the pipeline flagged (FR-12)", async () => {
    renderQueue();

    const row = (await screen.findByText("C-0141")).closest("tr") as HTMLElement;
    expect(within(row).getByText(copy.redFlag)).toBeInTheDocument();
  });

  it("labels an AI recommendation as pending until a reviewer decides (FR-36)", async () => {
    renderQueue();

    const row = (await screen.findByText("C-0141")).closest("tr") as HTMLElement;
    expect(within(row).getByText(strings.statusChip.awaitingReview)).toBeInTheDocument();
  });

  it("tints and labels a case past its target (FR-30)", async () => {
    renderQueue();

    const row = (await screen.findByText("C-0138")).closest("tr") as HTMLElement;
    expect(row.className).toContain("overdue");
    expect(within(row).getByText(/64 \/ 60 min · overdue/)).toBeInTheDocument();
  });

  // RED's target is 0, so the API reports it overdue a minute after arrival. The
  // queue says "Immediate" instead, or the word would be on every RED row.
  it("does not label a RED case overdue, but still shows how long it has waited", async () => {
    renderQueue();

    const row = (await screen.findByText("C-0141")).closest("tr") as HTMLElement;
    expect(row.className).not.toContain("overdue");
    expect(within(row).queryByText(new RegExp(copy.overdueSuffix))).not.toBeInTheDocument();
    // FR-29 asks for the elapsed time against the target, and RED's target is 0.
    expect(within(row).getByText("1 / 0 min")).toBeInTheDocument();
  });

  it("shows no target for a case that has no category", async () => {
    renderQueue();

    const row = (await screen.findByText("C-0140")).closest("tr") as HTMLElement;
    expect(
      within(row).getByText(copy.waitingNoTarget.replace("{waiting}", "22")),
    ).toBeInTheDocument();
    expect(within(row).getByText(strings.vtl.codes.MANUAL)).toBeInTheDocument();
  });

  it("explains a case still in the pipeline rather than leaving the row blank", async () => {
    renderQueue();

    const row = (await screen.findByText("C-0143")).closest("tr") as HTMLElement;
    expect(within(row).getByText(strings.vtl.noCategory)).toBeInTheDocument();
    expect(within(row).getByText(strings.statusChip.processing)).toBeInTheDocument();
  });

  // W-11: the card layout prints this attribute as each field's name.
  it("labels every cell, which is what the narrow layout needs", async () => {
    renderQueue();
    await screen.findByText("C-0141");

    const cells = Array.from(document.querySelectorAll("tbody td"));
    expect(cells.length).toBeGreaterThan(0);
    for (const cell of cells) {
      expect(cell.getAttribute("data-label")).toBeTruthy();
    }
  });

  it("opens the case a row points at", async () => {
    renderQueue();

    fireEvent.click(await screen.findByText("C-0141"));

    expect(await screen.findByText("case detail screen")).toBeInTheDocument();
  });

  it("goes to the intake form from New Case", async () => {
    renderQueue();

    fireEvent.click(await screen.findByRole("button", { name: copy.newCase }));

    expect(await screen.findByText("new case screen")).toBeInTheDocument();
  });
});

describe("TriageQueue counters and filters", () => {
  it("shows the counts for the whole open queue (W-02)", async () => {
    stubFetch({ "/cases": { body: queueResponse(FULL_QUEUE) } });
    renderQueue();

    const counters = await screen.findByRole("group", { name: copy.countersLabel });
    expect(within(counters).getByRole("button", { name: /RED/ })).toHaveTextContent("1");
    expect(within(counters).getByRole("button", { name: /MANUAL/ })).toHaveTextContent("1");
    // Scoped: "Awaiting review" is also one of the status filter's options.
    expect(within(counters).getByText(copy.awaitingReviewCaption).closest("p")).toHaveTextContent(
      "1",
    );
  });

  it("applies a category filter when a counter is pressed, and clears it again", async () => {
    const fetchMock = stubFetch({ "/cases": { body: queueResponse(FULL_QUEUE) } });
    renderQueue();

    const redTile = await screen.findByRole("button", { name: /RED/ });
    fireEvent.click(redTile);

    await waitFor(() => expect(lastRequestUrl(fetchMock)).toContain("category=RED"));
    expect(redTile).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(redTile);

    await waitFor(() => expect(lastRequestUrl(fetchMock)).not.toContain("category="));
  });

  it("sends the species filter the dropdown chose (FR-39)", async () => {
    const fetchMock = stubFetch({ "/cases": { body: queueResponse(FULL_QUEUE) } });
    renderQueue();

    fireEvent.change(await screen.findByLabelText(copy.speciesFilterLabel), {
      target: { value: "CAT" },
    });

    await waitFor(() => expect(lastRequestUrl(fetchMock)).toContain("species=CAT"));
  });

  it("sends a date range as calendar dates", async () => {
    const fetchMock = stubFetch({ "/cases": { body: queueResponse(FULL_QUEUE) } });
    renderQueue();

    fireEvent.change(await screen.findByLabelText(copy.dateFilterLabel), {
      target: { value: "TODAY" },
    });

    await waitFor(() => expect(lastRequestUrl(fetchMock)).toMatch(/date_from=\d{4}-\d{2}-\d{2}/));
  });

  it("searches once the typing stops", async () => {
    const fetchMock = stubFetch({ "/cases": { body: queueResponse(FULL_QUEUE) } });
    renderQueue();

    const search = await screen.findByLabelText(copy.searchLabel);
    fireEvent.change(search, { target: { value: "C-014" } });

    await waitFor(() => expect(lastRequestUrl(fetchMock)).toContain("q=C-014"));
  });

  it("offers a way out when filters hide everything", async () => {
    const fetchMock = stubFetch({ "/cases": { body: queueResponse([]) } });
    renderQueue();

    fireEvent.change(await screen.findByLabelText(copy.speciesFilterLabel), {
      target: { value: "CAT" },
    });

    fireEvent.click(await screen.findByRole("button", { name: copy.clearFilters }));

    await waitFor(() => expect(lastRequestUrl(fetchMock)).not.toContain("species="));
    expect(screen.getByText(copy.empty)).toBeInTheDocument();
  });

  it("says the queue is empty rather than showing an empty table", async () => {
    stubFetch({ "/cases": { body: queueResponse([]) } });
    renderQueue();

    expect(await screen.findByText(copy.empty)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("reports a failure instead of looking like an empty queue", async () => {
    stubFetch({ "/cases": { status: 500 } });
    renderQueue();

    expect(await screen.findByRole("alert")).toHaveTextContent(copy.errors.unexpected);
  });
});

/**
 * IR-22: the queue refreshes itself at most every 15 s, and stops asking while
 * the tab is in the background.
 */
describe("TriageQueue polling", () => {
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

  it("refetches on its own every 15 seconds", async () => {
    vi.useFakeTimers();
    const fetchMock = stubFetch({ "/cases": { body: queueResponse(FULL_QUEUE) } });
    renderQueue();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(QUEUE_POLL_INTERVAL_MS);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("stops asking while the tab is hidden, and resumes when it comes back", async () => {
    vi.useFakeTimers();
    const fetchMock = stubFetch({ "/cases": { body: queueResponse(FULL_QUEUE) } });
    renderQueue();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    setVisibility("hidden");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(QUEUE_POLL_INTERVAL_MS * 3);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    setVisibility("visible");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
