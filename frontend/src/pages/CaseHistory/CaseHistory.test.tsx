/**
 * W-07 Case History (FR-44, FR-45, FR-46, IR-03, IR-04).
 *
 * The fixture is the wireframe's own sample: a YELLOW case adjusted to GREEN, a
 * BLUE case confirmed as BLUE, and a case triaged by hand with no AI category.
 * `is_disagreement` comes from the server, so the screen is tested only on
 * showing it, never on working it out.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AuditTimeline as AuditTimelineData,
  CaseHistoryItem,
  CaseHistoryResponse,
} from "../../api/cases";
import { strings } from "../../i18n/strings";
import { makeUserWithRole, renderWithAuth } from "../../test/testUtils";
import { CaseHistory } from "./CaseHistory";

const copy = strings.caseHistory;

const ADJUSTED_CASE: CaseHistoryItem = {
  id: "00000000-0000-4000-8000-000000000137",
  case_no: "C-0137",
  status: "CLOSED",
  created_at: "2026-10-01T00:50:00Z",
  species: "DOG",
  pet_name: "Max",
  primary_complaint_code: "LIMPING",
  primary_complaint_name: "Limping",
  ai_category: "YELLOW",
  final_category: "GREEN",
  decision_type: "ADJUST",
  is_disagreement: true,
};

const CONFIRMED_CASE: CaseHistoryItem = {
  id: "00000000-0000-4000-8000-000000000136",
  case_no: "C-0136",
  status: "CONFIRMED",
  created_at: "2026-10-01T00:12:00Z",
  species: "DOG",
  pet_name: "Whitey",
  primary_complaint_code: null,
  primary_complaint_name: null,
  ai_category: "BLUE",
  final_category: "BLUE",
  decision_type: "CONFIRM",
  is_disagreement: false,
};

const MANUAL_CASE: CaseHistoryItem = {
  id: "00000000-0000-4000-8000-000000000133",
  case_no: "C-0133",
  status: "MANUALLY_TRIAGED",
  created_at: "2026-09-30T08:00:00Z",
  species: "DOG",
  pet_name: "Tiger",
  primary_complaint_code: null,
  primary_complaint_name: null,
  ai_category: null,
  final_category: "YELLOW",
  decision_type: "MANUAL",
  is_disagreement: false,
};

const TIMELINE: AuditTimelineData = {
  items: [
    {
      ts: "2026-10-01T00:50:02Z",
      actor_name: "J. Cruz",
      actor_role: "INTAKE_STAFF",
      action: "CASE_CREATED",
      label: "Case created",
      details: "channel: walk-in",
    },
    {
      ts: "2026-10-01T00:58:40Z",
      actor_name: "Reviewer Demo",
      actor_role: "VETERINARY_REVIEWER",
      action: "DECISION_RECORDED",
      label: "Decision: Adjusted Yellow → Green",
      details: null,
    },
  ],
  submission_to_recommendation_s: 10,
  recommendation_to_decision_s: 508,
  append_only: true,
};

const COMPLAINTS = [
  { code: "LIMPING", name: "Limping" },
  { code: "VOMITING", name: "Repeated vomiting" },
];

function historyResponse(
  items: CaseHistoryItem[],
  overrides: Partial<CaseHistoryResponse> = {},
): CaseHistoryResponse {
  return { items, total: items.length, page: 1, limit: 25, ...overrides };
}

type Responder = (url: URL) => { status?: number; body: unknown };

/**
 * A `fetch` that answers by route and keeps every URL it was asked for.
 *
 * Not `stubFetch`: the history answer has to depend on the query (page 2 differs
 * from page 1), and the three routes share a prefix.
 */
function stubApi(history: Responder, audit: unknown = TIMELINE) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    let stub: { status?: number; body: unknown };
    if (url.pathname.endsWith("/audit")) {
      stub = { body: audit };
    } else if (url.pathname.endsWith("/cases/complaints")) {
      stub = { body: COMPLAINTS };
    } else if (url.pathname.endsWith("/cases") && url.searchParams.get("scope") === "history") {
      stub = history(url);
    } else {
      stub = { status: 404, body: {} };
    }
    const status = stub.status ?? 200;
    return { ok: status < 300, status, json: async () => stub.body } as Response;
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function requested(mock: ReturnType<typeof stubApi>): URL[] {
  return mock.mock.calls.map((call) => new URL(String(call[0]), "http://localhost"));
}

/** The query string as a plain object (`URLSearchParams` is not iterable under this tsconfig). */
function paramsOf(url: URL): Record<string, string> {
  const params: Record<string, string> = {};
  url.searchParams.forEach((value, key) => {
    params[key] = value;
  });
  return params;
}

function historyRequests(mock: ReturnType<typeof stubApi>): URL[] {
  return requested(mock).filter((url) => url.searchParams.get("scope") === "history");
}

const THREE_CASES = () => ({ body: historyResponse([ADJUSTED_CASE, CONFIRMED_CASE, MANUAL_CASE]) });

function renderHistory(role: Parameters<typeof makeUserWithRole>[0] = "VETERINARY_REVIEWER") {
  return renderWithAuth(
    <Routes>
      <Route path="/history" element={<CaseHistory />} />
      <Route path="/cases/:caseId" element={<p>case detail screen</p>} />
    </Routes>,
    { route: "/history", user: makeUserWithRole(role) },
  );
}

function rowOf(caseNo: string): HTMLElement {
  return screen.getByText(caseNo).closest("tr") as HTMLElement;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CaseHistory results", () => {
  it("puts the AI category and the final category side by side, by name (IR-03)", async () => {
    stubApi(THREE_CASES);
    renderHistory();

    await screen.findByText("C-0137");
    const row = rowOf("C-0137");
    const ai = within(row.querySelector(`[data-label="${copy.columns.ai}"]`) as HTMLElement);
    const final = within(row.querySelector(`[data-label="${copy.columns.final}"]`) as HTMLElement);

    expect(ai.getByText(strings.vtl.codes.YELLOW)).toBeInTheDocument();
    expect(ai.getByText(strings.vtl.targets.YELLOW)).toBeInTheDocument();
    expect(final.getByText(strings.vtl.codes.GREEN)).toBeInTheDocument();
    expect(final.getByText(strings.vtl.targets.GREEN)).toBeInTheDocument();
  });

  it("marks a row where the AI and the final category differ, and only that row", async () => {
    stubApi(THREE_CASES);
    renderHistory();

    await screen.findByText("C-0137");

    expect(within(rowOf("C-0137")).getByText(copy.disagreementMarker)).toBeInTheDocument();
    expect(within(rowOf("C-0136")).queryByText(copy.disagreementMarker)).not.toBeInTheDocument();
    expect(within(rowOf("C-0133")).queryByText(copy.disagreementMarker)).not.toBeInTheDocument();
  });

  it("shows a dash, readable by a screen reader, where there is no AI category", async () => {
    stubApi(THREE_CASES);
    renderHistory();

    await screen.findByText("C-0133");
    const ai = within(
      rowOf("C-0133").querySelector(`[data-label="${copy.columns.ai}"]`) as HTMLElement,
    );

    expect(ai.getByText(strings.queue.notAvailable)).toBeInTheDocument();
    expect(ai.getByText(copy.noAiCategory)).toBeInTheDocument();
  });

  it("shows the arrival in the clinic's timezone and the patient", async () => {
    stubApi(THREE_CASES);
    renderHistory();

    await screen.findByText("C-0137");
    // 00:50 UTC on 1 Oct is 08:50 in Asia/Manila.
    expect(within(rowOf("C-0137")).getByText("1 Oct 2026 08:50")).toBeInTheDocument();
    expect(within(rowOf("C-0137")).getByText("Dog · Max")).toBeInTheDocument();
  });

  it("includes a closed case, with its status", async () => {
    stubApi(THREE_CASES);
    renderHistory();

    await screen.findByText("C-0137");
    expect(within(rowOf("C-0137")).getByText(strings.statusChip.closed)).toBeInTheDocument();
  });

  it("says so when there are no cases, and when the filters match none", async () => {
    const mock = stubApi(() => ({ body: historyResponse([]) }));
    renderHistory();

    expect(await screen.findByText(copy.empty)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(copy.speciesLabel), { target: { value: "CAT" } });
    fireEvent.click(screen.getByRole("button", { name: copy.search }));

    expect(await screen.findByText(copy.emptyFiltered)).toBeInTheDocument();
    expect(historyRequests(mock)).toHaveLength(2);
  });

  it("reports a failed load", async () => {
    stubApi(() => ({ status: 500, body: { error: { code: "INTERNAL_ERROR", message: "x" } } }));
    renderHistory();

    expect(await screen.findByRole("alert")).toHaveTextContent(copy.errors.unexpected);
  });
});

describe("CaseHistory filters", () => {
  it("asks for the first page of everything before any filter is set", async () => {
    const mock = stubApi(THREE_CASES);
    renderHistory();
    await screen.findByText("C-0137");

    const [first] = historyRequests(mock);
    expect(paramsOf(first)).toEqual({
      scope: "history",
      page: "1",
      limit: "25",
    });
  });

  it("sends exactly the chosen filters when Search is pressed, and leaves blanks out", async () => {
    const mock = stubApi(THREE_CASES);
    renderHistory();
    await screen.findByText("C-0137");
    // The complaint list arrives separately; wait for it before choosing from it.
    await screen.findByRole("option", { name: "Limping" });

    fireEvent.change(screen.getByLabelText(copy.caseNoLabel), { target: { value: " C-0137 " } });
    fireEvent.change(screen.getByLabelText(copy.dateFromLabel), {
      target: { value: "2026-10-01" },
    });
    fireEvent.change(screen.getByLabelText(copy.dateToLabel), { target: { value: "2026-10-31" } });
    fireEvent.change(screen.getByLabelText(copy.speciesLabel), { target: { value: "DOG" } });
    fireEvent.change(screen.getByLabelText(copy.complaintLabel), { target: { value: "LIMPING" } });
    fireEvent.change(screen.getByLabelText(copy.aiCategoryLabel), { target: { value: "YELLOW" } });
    fireEvent.change(screen.getByLabelText(copy.finalCategoryLabel), {
      target: { value: "GREEN" },
    });
    fireEvent.change(screen.getByLabelText(copy.statusLabel), { target: { value: "CLOSED" } });

    // Nothing is sent until Search: editing the bar is not a request.
    expect(historyRequests(mock)).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: copy.search }));

    await waitFor(() => expect(historyRequests(mock)).toHaveLength(2));
    expect(paramsOf(historyRequests(mock)[1])).toEqual({
      scope: "history",
      page: "1",
      limit: "25",
      case_no: "C-0137",
      date_from: "2026-10-01",
      date_to: "2026-10-31",
      species: "DOG",
      complaint_code: "LIMPING",
      ai_category: "YELLOW",
      final_category: "GREEN",
      status: "CLOSED",
    });
  });

  it("sends disagreement=true for the AI ≠ final box, and nothing when it is clear", async () => {
    const mock = stubApi(THREE_CASES);
    renderHistory();
    await screen.findByText("C-0137");

    fireEvent.click(screen.getByLabelText(copy.disagreementLabel));
    fireEvent.click(screen.getByRole("button", { name: copy.search }));
    await waitFor(() => expect(historyRequests(mock)).toHaveLength(2));
    expect(historyRequests(mock)[1].searchParams.get("disagreement")).toBe("true");

    fireEvent.click(screen.getByLabelText(copy.disagreementLabel));
    fireEvent.click(screen.getByRole("button", { name: copy.search }));
    await waitFor(() => expect(historyRequests(mock)).toHaveLength(3));
    expect(historyRequests(mock)[2].searchParams.has("disagreement")).toBe(false);
  });

  it("offers the complaint list the server returned", async () => {
    stubApi(THREE_CASES);
    renderHistory();

    expect(await screen.findByRole("option", { name: "Repeated vomiting" })).toBeInTheDocument();
  });

  it("clears every control and searches again", async () => {
    const mock = stubApi(THREE_CASES);
    renderHistory();
    await screen.findByText("C-0137");

    fireEvent.change(screen.getByLabelText(copy.caseNoLabel), { target: { value: "C-9" } });
    fireEvent.click(screen.getByLabelText(copy.disagreementLabel));
    fireEvent.click(screen.getByRole("button", { name: copy.search }));
    await waitFor(() => expect(historyRequests(mock)).toHaveLength(2));

    fireEvent.click(screen.getByRole("button", { name: copy.clear }));

    expect(screen.getByLabelText(copy.caseNoLabel)).toHaveValue("");
    expect(screen.getByLabelText(copy.disagreementLabel)).not.toBeChecked();
    await waitFor(() => expect(historyRequests(mock)).toHaveLength(3));
    expect(Object.keys(paramsOf(historyRequests(mock)[2])).sort()).toEqual([
      "limit",
      "page",
      "scope",
    ]);
  });

  it("refuses an end date before the start date without asking the server", async () => {
    const mock = stubApi(THREE_CASES);
    renderHistory();
    await screen.findByText("C-0137");

    fireEvent.change(screen.getByLabelText(copy.dateFromLabel), {
      target: { value: "2026-10-12" },
    });
    fireEvent.change(screen.getByLabelText(copy.dateToLabel), { target: { value: "2026-10-11" } });

    expect(screen.getByRole("alert")).toHaveTextContent(copy.errors.badRange);
    const search = screen.getByRole("button", { name: copy.search });
    expect(search).toBeDisabled();
    fireEvent.click(search);
    expect(historyRequests(mock)).toHaveLength(1);
  });
});

describe("CaseHistory paging", () => {
  const pageOf = (url: URL) => {
    const page = Number(url.searchParams.get("page"));
    return {
      body: historyResponse(page === 1 ? [ADJUSTED_CASE] : [CONFIRMED_CASE], {
        total: 60,
        page,
        limit: 25,
      }),
    };
  };

  it("shows where the page sits and cannot go back from the first one", async () => {
    stubApi(pageOf);
    renderHistory();

    const pager = await screen.findByRole("navigation", { name: copy.paginationLabel });
    expect(within(pager).getByText("Page 1 of 3")).toBeInTheDocument();
    expect(within(pager).getByText("1–1 of 60")).toBeInTheDocument();
    expect(within(pager).getByRole("button", { name: copy.previous })).toBeDisabled();
    expect(within(pager).getByRole("button", { name: copy.next })).toBeEnabled();
  });

  it("asks for the next page and shows its rows", async () => {
    const mock = stubApi(pageOf);
    renderHistory();
    const pager = await screen.findByRole("navigation", { name: copy.paginationLabel });

    fireEvent.click(within(pager).getByRole("button", { name: copy.next }));

    expect(await screen.findByText("C-0136")).toBeInTheDocument();
    const last = historyRequests(mock).at(-1) as URL;
    expect(last.searchParams.get("page")).toBe("2");
    expect(screen.queryByText("C-0137")).not.toBeInTheDocument();
  });

  it("goes back to page 1 when a new search is made", async () => {
    const mock = stubApi(pageOf);
    renderHistory();
    const pager = await screen.findByRole("navigation", { name: copy.paginationLabel });
    fireEvent.click(within(pager).getByRole("button", { name: copy.next }));
    await screen.findByText("C-0136");

    fireEvent.change(screen.getByLabelText(copy.speciesLabel), { target: { value: "CAT" } });
    fireEvent.click(screen.getByRole("button", { name: copy.search }));

    await waitFor(() => {
      const last = historyRequests(mock).at(-1) as URL;
      expect(last.searchParams.get("species")).toBe("CAT");
      expect(last.searchParams.get("page")).toBe("1");
    });
  });

  it("disables Next on the last page", async () => {
    stubApi((url) => ({
      body: historyResponse([CONFIRMED_CASE], {
        total: 26,
        page: Number(url.searchParams.get("page")),
      }),
    }));
    renderHistory();
    const pager = await screen.findByRole("navigation", { name: copy.paginationLabel });
    fireEvent.click(within(pager).getByRole("button", { name: copy.next }));

    await screen.findByText("Page 2 of 2");
    expect(within(pager).getByRole("button", { name: copy.next })).toBeDisabled();
  });
});

describe("CaseHistory audit timeline", () => {
  it("asks the reader to pick a case before anything is selected", async () => {
    stubApi(THREE_CASES);
    renderHistory();
    await screen.findByText("C-0137");

    expect(screen.getByText(copy.selectPrompt)).toBeInTheDocument();
  });

  it("shows the selected case's timeline with both intervals (FR-45, FR-46)", async () => {
    const mock = stubApi(THREE_CASES);
    renderHistory();
    await screen.findByText("C-0137");

    fireEvent.click(rowOf("C-0137"));

    const panel = await screen.findByRole("region", { name: "Audit timeline – C-0137" });
    expect(within(panel).getByText("Case created")).toBeInTheDocument();
    expect(
      within(panel).getByText(strings.caseAudit.submissionToRecommendation),
    ).toBeInTheDocument();
    expect(within(panel).getByText("10 s")).toBeInTheDocument();
    expect(within(panel).getByText(strings.caseAudit.recommendationToDecision)).toBeInTheDocument();
    expect(requested(mock).some((url) => url.pathname.endsWith(`/${ADJUSTED_CASE.id}/audit`))).toBe(
      true,
    );
  });

  // Reading a case as a reviewer acknowledges its red-flag alerts (FR-12), so
  // browsing the archive must never make that request.
  it("never reads the case itself, only its audit trail", async () => {
    const mock = stubApi(THREE_CASES);
    renderHistory();
    await screen.findByText("C-0137");

    fireEvent.click(screen.getByRole("button", { name: /Show the audit timeline for C-0137/ }));
    await screen.findByRole("region", { name: "Audit timeline – C-0137" });

    const detail = requested(mock).filter((url) =>
      url.pathname.endsWith(`/cases/${ADJUSTED_CASE.id}`),
    );
    expect(detail).toHaveLength(0);
  });

  it("switches to another case's timeline and links to the case", async () => {
    stubApi(THREE_CASES);
    renderHistory();
    await screen.findByText("C-0137");

    fireEvent.click(rowOf("C-0137"));
    await screen.findByRole("region", { name: "Audit timeline – C-0137" });
    fireEvent.click(rowOf("C-0136"));

    expect(
      await screen.findByRole("region", { name: "Audit timeline – C-0136" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.openCase })).toHaveAttribute(
      "href",
      `/cases/${CONFIRMED_CASE.id}`,
    );
    expect(rowOf("C-0136").className).toContain("selected");
  });
});

describe("CaseHistory access", () => {
  it.each(["INTAKE_STAFF", "VETERINARY_REVIEWER", "ADMINISTRATOR"] as const)(
    "lets %s search and read the timeline",
    async (role) => {
      stubApi(THREE_CASES);
      renderHistory(role);

      await screen.findByText("C-0137");
      fireEvent.click(rowOf("C-0137"));

      expect(
        await screen.findByRole("region", { name: "Audit timeline – C-0137" }),
      ).toBeInTheDocument();
    },
  );

  it("offers an administrator nothing that changes a case (BR-02)", async () => {
    stubApi(THREE_CASES);
    renderHistory("ADMINISTRATOR");
    await screen.findByText("C-0137");

    const buttons = screen.getAllByRole("button").map((button) => button.textContent ?? "");
    expect(buttons.join(" ")).not.toMatch(/confirm|adjust|close|retry|regenerate|note/i);
  });
});
