/**
 * The per-case audit route (FR-42, FR-43, FR-45, FR-46 · W-07).
 *
 * Two rules sit behind the three tests that are not about rendering:
 *
 * - every role may read the trail, Intake Staff and administrators included, so a
 *   later tightening of the route has to break a test to happen (FR-45);
 * - the page never calls `GET /cases/{id}`, because that request acknowledges the
 *   case's red-flag alerts (§6.1) and the queue's banner would vanish for a
 *   reviewer who had not opened the case.
 */
import { screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuditTimeline as AuditTimelineData } from "../../api/cases";
import { strings } from "../../i18n/strings";
import { errorBody, makeUserWithRole, renderWithAuth, stubFetch } from "../../test/testUtils";
import { CaseAudit } from "./CaseAudit";

const copy = strings.caseAudit;

const CASE_ID = "00000000-0000-4000-8000-000000000137";

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

function renderAudit(
  options: {
    role?: "INTAKE_STAFF" | "VETERINARY_REVIEWER" | "ADMINISTRATOR";
    status?: number;
    body?: unknown;
  } = {},
) {
  const mock = stubFetch({
    [`/cases/${CASE_ID}/audit`]: { status: options.status, body: options.body ?? TIMELINE },
  });

  const rendered = renderWithAuth(
    <Routes>
      <Route path="/cases/:caseId/audit" element={<CaseAudit />} />
    </Routes>,
    {
      user: makeUserWithRole(options.role ?? "VETERINARY_REVIEWER"),
      route: `/cases/${CASE_ID}/audit`,
    },
  );

  return { ...rendered, mock };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CaseAudit", () => {
  it("shows the timeline, its intervals, and the append-only caption", async () => {
    renderAudit();

    expect(await screen.findByText("Case created")).toBeInTheDocument();
    expect(screen.getByText("Decision: Adjusted Yellow → Green")).toBeInTheDocument();
    expect(screen.getByText("10 s")).toBeInTheDocument();
    expect(screen.getByText("8 min 28 s")).toBeInTheDocument();
    expect(screen.getByText(copy.appendOnly)).toBeInTheDocument();
  });

  it("offers the way back to the case", async () => {
    renderAudit();
    await screen.findByText("Case created");

    expect(screen.getByRole("link", { name: copy.backToCase })).toHaveAttribute(
      "href",
      `/cases/${CASE_ID}`,
    );
  });

  // The case number comes from W-04's cache entry, which a direct visit does not
  // have. The heading falls back rather than the page refusing to render.
  it("falls back to a heading without a case number when the case is not cached", async () => {
    renderAudit();
    expect(await screen.findByRole("heading", { name: copy.titleFallback })).toBeInTheDocument();
  });

  // FR-45: the trail is readable by every role.
  it.each(["INTAKE_STAFF", "ADMINISTRATOR"] as const)("is readable by %s", async (role) => {
    renderAudit({ role });
    expect(await screen.findByText("Case created")).toBeInTheDocument();
  });

  it("never reads the case itself, which would acknowledge its red-flag alerts", async () => {
    const { mock } = renderAudit();
    await screen.findByText("Case created");

    const urls = mock.mock.calls.map(([input]) => String(input));
    expect(urls).toHaveLength(1);
    expect(urls[0]).toContain(`/cases/${CASE_ID}/audit`);
  });

  it("says which failure it was, rather than one sentence for all of them", async () => {
    const { unmount } = renderAudit({
      status: 404,
      body: errorBody("NOT_FOUND", "No such case."),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.errors.notFound);
    unmount();
    vi.unstubAllGlobals();

    renderAudit({ status: 403, body: errorBody("FORBIDDEN", "Not allowed.") });
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.errors.forbidden);
  });

  it("falls back to the general sentence on anything else", async () => {
    renderAudit({ status: 500, body: errorBody("INTERNAL_ERROR", "Boom.") });
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(copy.errors.unexpected),
    );
  });
});
