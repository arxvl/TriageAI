/**
 * W-08 Knowledge Base (FR-49..FR-56, NFR-08, BR-04, IR-03, IR-08 · UC-13, UC-14).
 *
 * The fixture is the wireframe's sample: a feline urinary entry awaiting review,
 * with version 7 published and 18 active entries. What it asserts is the set of
 * rules the screen must not lose:
 *
 * - the approve and reject controls exist for a KB approver and for nobody else
 *   — not an administrator, not a reviewer without the permission (BR-04, FR-52);
 * - a rejection cannot be sent without comments (FR-51);
 * - the citation is required and the content bound is enforced before the
 *   request is made (FR-50);
 * - an approval names the version it would publish, and reports indexing rather
 *   than claiming the entry is live (FR-53, FR-54);
 * - retiring is confirmed first and its warning is shown (FR-72, IR-08);
 * - every minimum category is shown with its name, never colour alone (IR-03).
 *
 * All data here is fictitious (CLAUDE.md §9).
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type {
  KBEntryDetail,
  KBEntryListResponse,
  KBEntryStatus,
  KBEntrySummary,
  RedFlagRuleOut,
} from "../../api/kb";
import type { UserRole } from "../../api/auth";
import { strings } from "../../i18n/strings";
import { errorBody, makeUser, renderWithAuth, stubFetch } from "../../test/testUtils";
import { KnowledgeBase } from "./KnowledgeBase";

const copy = strings.knowledgeBase;

const ENTRY_ID = "00000000-0000-4000-8000-0000000000e1";
const ACTION_SET_ID = "00000000-0000-4000-8000-0000000000e2";

const COMPLAINTS = [
  { code: "URINARY_OBSTRUCTION", name: "Straining to urinate or unable to urinate" },
  { code: "LETHARGY", name: "Lethargy" },
];

const RULES: RedFlagRuleOut[] = [
  {
    id: "00000000-0000-4000-8000-0000000000r1",
    code: "MALE_CAT_NO_URINE",
    label: "Male cat producing no urine",
    min_category: "ORANGE",
    species: ["CAT"],
    phrases_ref: "MALE_CAT_NO_URINE",
    is_placeholder: true,
    approved_by_name: null,
    approved_at: null,
    retired_at: null,
    is_active: false,
  },
  {
    id: "00000000-0000-4000-8000-0000000000r2",
    code: "COLLAPSE_UNRESPONSIVE",
    label: "Collapsed or unresponsive",
    min_category: "RED",
    species: ["DOG", "CAT"],
    phrases_ref: "COLLAPSE_UNRESPONSIVE",
    is_placeholder: false,
    approved_by_name: "Dr. A. Rivera",
    approved_at: "2026-10-12T01:30:00Z",
    retired_at: null,
    is_active: true,
  },
];

const VERSIONS = [
  {
    id: "00000000-0000-4000-8000-0000000000v7",
    version_no: 7,
    published_at: "2026-10-12T01:30:00Z",
    published_by_name: "Dr. A. Rivera",
    note: null,
    entry_count: 18,
  },
];

/** Over the 50-word floor the server applies to a clinical entry (FR-50). */
const CONTENT =
  "Male cats that repeatedly strain in the litter box and pass little or no urine may have a " +
  "urethral blockage. The condition can worsen within hours and should be assessed promptly by " +
  "a veterinarian, who will decide what examination the patient needs on arrival at the clinic. " +
  "Owners often report frequent trips to the litter box with crying and very little result.";

function makeEntry(overrides: Partial<KBEntryDetail> = {}): KBEntryDetail {
  return {
    id: ENTRY_ID,
    slug: "urinary-straining-cat",
    kind: "COMPLAINT",
    title: "Straining or inability to urinate - cats",
    complaint_code: "URINARY_OBSTRUCTION",
    urgency_category: null,
    species: ["CAT"],
    content: CONTENT,
    word_count: 63,
    status: "PENDING_REVIEW",
    source: {
      title: "Feline Lower Urinary Tract Disease",
      publisher: "Fixture Veterinary Manual",
      url: "https://example.invalid/flutd",
      access_date: "2026-10-12",
    },
    red_flag_codes: ["MALE_CAT_NO_URINE"],
    created_by_name: "An Administrator",
    approved_by_name: null,
    approved_at: null,
    review_comments: null,
    revises_entry_id: null,
    indexing: null,
    ...overrides,
  };
}

function summaryOf(entry: KBEntryDetail): KBEntrySummary {
  return {
    id: entry.id,
    slug: entry.slug,
    kind: entry.kind,
    title: entry.title,
    complaint_code: entry.complaint_code,
    urgency_category: entry.urgency_category,
    species: entry.species,
    status: entry.status,
    word_count: entry.word_count,
    source_title: entry.source.title,
  };
}

function listOf(entries: KBEntryDetail[]): KBEntryListResponse {
  return {
    items: entries.map(summaryOf),
    counts: { DRAFT: 3, PENDING_REVIEW: 2, ACTIVE: 18, RETIRED: 1 },
    published_version_no: 7,
    active_entry_count: 18,
  };
}

/**
 * Mount the screen over stubbed routes.
 *
 * Order matters, because `stubFetch` matches on the first key the URL contains
 * and every entry path contains `/kb/entries`:
 *
 * 1. the action subroutes, which a test may override;
 * 2. the entry being read, `/kb/entries/{id}`;
 * 3. the catalogue, keyed on `status=` — the list request always carries the
 *    tab, so this key cannot catch anything else;
 * 4. `/kb/entries` with no query string at all, which is the POST that creates
 *    an entry and answers with the created draft.
 */
function renderKb(
  options: {
    role?: UserRole;
    canApproveKb?: boolean;
    entries?: KBEntryDetail[];
    detail?: KBEntryDetail;
    /** What `POST /kb/entries` answers with. */
    created?: KBEntryDetail;
    routes?: Record<string, { status?: number; body?: unknown }>;
  } = {},
) {
  const entries = options.entries ?? [makeEntry()];
  const detail = options.detail ?? entries[0];

  const routes: Record<string, { status?: number; body?: unknown }> = {
    ...(options.routes ?? {}),
  };
  if (!(`/kb/entries/${detail.id}` in routes)) {
    routes[`/kb/entries/${detail.id}`] = { body: detail };
  }
  routes["status="] = { body: listOf(entries) };
  routes["/kb/entries"] = { status: 201, body: options.created ?? detail };
  routes["/kb/complaints"] = { body: COMPLAINTS };
  routes["/kb/red-flag-rules"] = { body: RULES };
  routes["/kb/versions"] = { body: VERSIONS };

  const mock = stubFetch(routes);
  const view = renderWithAuth(<KnowledgeBase />, {
    user: makeUser({
      role: options.role ?? "VETERINARY_REVIEWER",
      can_approve_kb: options.canApproveKb ?? options.role !== "ADMINISTRATOR",
      full_name: "Dr. A. Rivera",
    }),
    route: "/kb",
  });

  return { ...view, mock };
}

/** Open the entry in the right-hand panel, as a curator or approver would. */
async function openEntry(title: string) {
  const link = await screen.findByRole("button", { name: title });
  fireEvent.click(link);
}

function requestsTo(mock: ReturnType<typeof stubFetch>, fragment: string) {
  return mock.mock.calls.filter((call) => String(call[0]).includes(fragment));
}

describe("the header and the tabs", () => {
  it("names the published version and the number of active entries", async () => {
    renderKb();

    expect(
      await screen.findByText(
        copy.publishedVersion.replace("{version}", "7").replace("{count}", "18"),
      ),
    ).toBeInTheDocument();
  });

  it("shows the server's counts on all four tabs", async () => {
    renderKb();

    for (const [status, count] of [
      ["DRAFT", 3],
      ["PENDING_REVIEW", 2],
      ["ACTIVE", 18],
      ["RETIRED", 1],
    ] as [KBEntryStatus, number][]) {
      const label = copy.tabLabel
        .replace("{label}", copy.tabs[status])
        .replace("{count}", String(count));
      expect(await screen.findByRole("tab", { name: label })).toBeInTheDocument();
    }
  });

  it("re-queries the catalogue when another tab is chosen", async () => {
    const { mock } = renderKb();
    const activeTab = await screen.findByRole("tab", {
      name: copy.tabLabel.replace("{label}", copy.tabs.ACTIVE).replace("{count}", "18"),
    });

    fireEvent.click(activeTab);

    await waitFor(() => {
      expect(mock.mock.calls.some((call) => String(call[0]).includes("status=ACTIVE"))).toBe(true);
    });
  });

  it("re-queries with the kind filter, so the action sets can be found alone", async () => {
    const { mock } = renderKb();
    const filter = await screen.findByLabelText(copy.kindFilterLabel);

    fireEvent.change(filter, { target: { value: "URGENCY_ACTIONS" } });

    await waitFor(() => {
      expect(mock.mock.calls.some((call) => String(call[0]).includes("kind=URGENCY_ACTIONS"))).toBe(
        true,
      );
    });
  });
});

describe("who may approve (BR-04, FR-52)", () => {
  it("offers approve and reject to a reviewer holding the KB permission", async () => {
    renderKb({ role: "VETERINARY_REVIEWER", canApproveKb: true });
    await openEntry(makeEntry().title);

    // The button names the version the approval would publish (FR-54).
    expect(
      await screen.findByRole("button", { name: copy.approve.replace("{version}", "8") }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.reject })).toBeInTheDocument();
    expect(screen.getByText(copy.approverOnlyNote)).toBeInTheDocument();
  });

  it("offers neither to a reviewer without the permission", async () => {
    renderKb({ role: "VETERINARY_REVIEWER", canApproveKb: false });
    await openEntry(makeEntry().title);

    await screen.findByText(copy.detail.contentHeading);
    expect(
      screen.queryByRole("button", { name: copy.approve.replace("{version}", "8") }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.reject })).not.toBeInTheDocument();
  });

  it("offers neither to an administrator, who curates but does not decide", async () => {
    renderKb({ role: "ADMINISTRATOR", canApproveKb: false });
    await openEntry(makeEntry().title);

    await screen.findByText(copy.detail.contentHeading);
    expect(
      screen.queryByRole("button", { name: copy.approve.replace("{version}", "8") }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.reject })).not.toBeInTheDocument();
  });

  it("gives the administrator the draft controls instead", async () => {
    const draft = makeEntry({ status: "DRAFT" });
    renderKb({ role: "ADMINISTRATOR", canApproveKb: false, entries: [draft], detail: draft });
    await openEntry(draft.title);

    expect(await screen.findByRole("button", { name: copy.editor.edit })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.editor.submitForReview })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.editor.newEntry })).toBeInTheDocument();
  });

  it("shows the server's reason when an incomplete draft cannot be submitted", async () => {
    // FR-50 is checked again on the stored row, because an imported draft never
    // passed through the request schema (P08 §8.2).
    const draft = makeEntry({
      status: "DRAFT",
      source: { title: null, publisher: null, url: null, access_date: null },
    });
    renderKb({
      role: "ADMINISTRATOR",
      canApproveKb: false,
      entries: [draft],
      detail: draft,
      routes: {
        "/submit": {
          status: 422,
          body: errorBody("VALIDATION_ERROR", "The source citation is incomplete.", "source_title"),
        },
      },
    });
    await openEntry(draft.title);

    fireEvent.click(await screen.findByRole("button", { name: copy.editor.submitForReview }));

    expect(await screen.findByText("The source citation is incomplete.")).toBeInTheDocument();
  });

  it("gives a reviewer no way to create an entry", async () => {
    renderKb({ role: "VETERINARY_REVIEWER", canApproveKb: true });

    await screen.findByText(makeEntry().title);
    expect(screen.queryByRole("button", { name: copy.editor.newEntry })).not.toBeInTheDocument();
  });
});

describe("rejecting (FR-51)", () => {
  it("sends nothing until a comment is written, then sends the comment", async () => {
    const { mock } = renderKb({ canApproveKb: true });
    await openEntry(makeEntry().title);
    fireEvent.click(await screen.findByRole("button", { name: copy.reject }));

    const dialog = await screen.findByRole("dialog");
    const send = within(dialog).getByRole("button", { name: copy.rejectDialog.submit });
    expect(send).toBeDisabled();

    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: { value: "Cite the source section this paragraph came from." },
    });
    expect(send).toBeEnabled();
    fireEvent.click(send);

    await waitFor(() => {
      expect(requestsTo(mock, "/reject").length).toBe(1);
    });
    const [, init] = requestsTo(mock, "/reject")[0];
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      comments: "Cite the source section this paragraph came from.",
    });
  });
});

describe("approving and indexing (FR-53)", () => {
  it("approves without claiming the entry is live", async () => {
    const { mock } = renderKb({
      canApproveKb: true,
      routes: {
        "/approve": {
          status: 202,
          body: { id: ENTRY_ID, status: "PENDING_REVIEW", version_no: null, job_id: "j1" },
        },
      },
    });
    await openEntry(makeEntry().title);

    fireEvent.click(
      await screen.findByRole("button", { name: copy.approve.replace("{version}", "8") }),
    );

    await waitFor(() => {
      expect(requestsTo(mock, "/approve").length).toBe(1);
    });
    expect(await screen.findByText(copy.toasts.approved)).toBeInTheDocument();
  });

  it("reports a failed indexing run with the entry still awaiting review", async () => {
    const failed = makeEntry({
      indexing: {
        status: "FAILED",
        error: "EMBEDDING_UNAVAILABLE",
        queued_at: "2026-10-12T02:00:00Z",
      },
    });
    renderKb({ canApproveKb: true, entries: [failed], detail: failed });
    await openEntry(failed.title);

    expect(await screen.findByText(copy.indexing.FAILED)).toBeInTheDocument();
    expect(
      screen.getByText(copy.indexing.reason.replace("{reason}", "EMBEDDING_UNAVAILABLE")),
    ).toBeInTheDocument();
    expect(screen.getByText(copy.indexing.stillPending)).toBeInTheDocument();
    expect(screen.getByText(copy.tabs.PENDING_REVIEW)).toBeInTheDocument();
  });
});

describe("retiring (FR-53, FR-54, FR-72, IR-08)", () => {
  it("confirms first and reports the fallback warning", async () => {
    const warning = "GREEN now has no baseline actions until a replacement is approved.";
    const active = makeEntry({
      id: ACTION_SET_ID,
      kind: "URGENCY_ACTIONS",
      title: "Suggested staff actions - Green",
      complaint_code: null,
      urgency_category: "GREEN",
      status: "ACTIVE",
      red_flag_codes: [],
    });
    const { mock } = renderKb({
      role: "ADMINISTRATOR",
      canApproveKb: false,
      entries: [active],
      detail: active,
      routes: {
        "/retire": {
          body: { id: active.id, status: "RETIRED", version_no: 8, job_id: null, warning },
        },
      },
    });
    await openEntry(active.title);

    fireEvent.click(await screen.findByRole("button", { name: copy.retire }));
    const dialog = await screen.findByRole("dialog");
    // Nothing is sent by opening the dialog.
    expect(requestsTo(mock, "/retire").length).toBe(0);

    fireEvent.click(within(dialog).getByRole("button", { name: copy.retireDialog.confirm }));

    await waitFor(() => {
      expect(requestsTo(mock, "/retire").length).toBe(1);
    });
    expect(await screen.findByText(warning)).toBeInTheDocument();
  });
});

describe("the editor (FR-49, FR-50)", () => {
  it("refuses to save without the citation or with content under the floor", async () => {
    const { mock } = renderKb({ role: "ADMINISTRATOR", canApproveKb: false });
    fireEvent.click(await screen.findByRole("button", { name: copy.editor.newEntry }));

    fireEvent.change(screen.getByLabelText(copy.editor.titleLabel), {
      target: { value: "A fictitious entry" },
    });
    fireEvent.change(screen.getByLabelText(copy.editor.complaintLabel), {
      target: { value: "LETHARGY" },
    });
    fireEvent.change(screen.getByLabelText(copy.editor.contentLabel), {
      target: { value: "Far too short." },
    });

    fireEvent.click(screen.getByRole("button", { name: copy.editor.saveDraft }));

    // One message per missing citation field, and the content bound (FR-50).
    expect(screen.getByText(copy.errors.sourceTitleMissing)).toBeInTheDocument();
    expect(screen.getByText(copy.errors.sourcePublisherMissing)).toBeInTheDocument();
    expect(screen.getByText(copy.errors.sourceUrlMissing)).toBeInTheDocument();
    expect(screen.getByText(copy.errors.accessDateMissing)).toBeInTheDocument();
    expect(
      screen.getByText(
        copy.errors.contentWordCount
          .replace("{min}", "50")
          .replace("{max}", "1,500")
          .replace("{count}", "3"),
      ),
    ).toBeInTheDocument();

    // Nothing was sent: the form is not valid.
    expect(
      mock.mock.calls.every(
        (call) => String((call[1] as RequestInit | undefined)?.method) !== "POST",
      ),
    ).toBe(true);
  });

  it("counts the words as they are typed, and carries W-08's helper", async () => {
    renderKb({ role: "ADMINISTRATOR", canApproveKb: false });
    fireEvent.click(await screen.findByRole("button", { name: copy.editor.newEntry }));

    expect(screen.getByText(copy.editor.contentHelper)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(copy.editor.contentLabel), {
      target: { value: "one two three four" },
    });

    expect(
      screen.getByText(
        copy.editor.contentCounter
          .replace("{count}", "4")
          .replace("{min}", "50")
          .replace("{max}", "1,500"),
      ),
    ).toBeInTheDocument();
  });

  it("asks a baseline action set for a category and counts its lines", async () => {
    renderKb({ role: "ADMINISTRATOR", canApproveKb: false });
    fireEvent.click(await screen.findByRole("button", { name: copy.editor.newActionSet }));

    expect(screen.getByLabelText(copy.editor.urgencyCategoryLabel)).toBeInTheDocument();
    expect(screen.queryByLabelText(copy.editor.complaintLabel)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(copy.editor.contentLabel), {
      target: { value: "Escalate now.\nMonitor breathing." },
    });

    expect(
      screen.getByText(
        copy.editor.actionsCounter
          .replace("{count}", "2")
          .replace("{min}", "3")
          .replace("{max}", "6"),
      ),
    ).toBeInTheDocument();
  });

  it("posts a complete entry, with the complaint and the chosen rule", async () => {
    const created = makeEntry({
      id: "00000000-0000-4000-8000-0000000000e9",
      slug: null,
      status: "DRAFT",
      title: "A fictitious entry about lethargy",
      complaint_code: "LETHARGY",
    });
    const { mock } = renderKb({ role: "ADMINISTRATOR", canApproveKb: false, created });
    fireEvent.click(await screen.findByRole("button", { name: copy.editor.newEntry }));

    fireEvent.change(screen.getByLabelText(copy.editor.titleLabel), {
      target: { value: "A fictitious entry about lethargy" },
    });
    fireEvent.change(screen.getByLabelText(copy.editor.complaintLabel), {
      target: { value: "LETHARGY" },
    });
    fireEvent.change(screen.getByLabelText(copy.editor.contentLabel), {
      target: { value: CONTENT },
    });
    fireEvent.change(screen.getByLabelText(copy.editor.sourceTitleLabel), {
      target: { value: "Fixture Source Title" },
    });
    fireEvent.change(screen.getByLabelText(copy.editor.sourcePublisherLabel), {
      target: { value: "Fixture Publisher" },
    });
    fireEvent.change(screen.getByLabelText(copy.editor.sourceUrlLabel), {
      target: { value: "https://example.invalid/fixture" },
    });
    fireEvent.change(screen.getByLabelText(copy.editor.accessDateLabel), {
      target: { value: "2026-10-12" },
    });
    fireEvent.click(screen.getByLabelText(/Male cat producing no urine/));

    fireEvent.click(screen.getByRole("button", { name: copy.editor.saveDraft }));

    await waitFor(() => {
      const posts = mock.mock.calls.filter(
        (call) => (call[1] as RequestInit | undefined)?.method === "POST",
      );
      expect(posts.length).toBe(1);
    });
    const post = mock.mock.calls.find(
      (call) => (call[1] as RequestInit | undefined)?.method === "POST",
    );
    const body = JSON.parse(String((post?.[1] as RequestInit).body)) as Record<string, unknown>;
    expect(body.complaint_code).toBe("LETHARGY");
    expect(body.red_flag_codes).toEqual(["MALE_CAT_NO_URINE"]);
    expect(body.source_publisher).toBe("Fixture Publisher");
  });
});

describe("the red-flag rules tab (NFR-08, IR-03)", () => {
  it("marks a placeholder rule and never shows a category as colour alone", async () => {
    renderKb({ canApproveKb: true });

    fireEvent.click(await screen.findByRole("button", { name: copy.viewRules }));

    expect(await screen.findByText("Male cat producing no urine")).toBeInTheDocument();
    expect(screen.getByText(copy.rules.placeholderBadge)).toBeInTheDocument();
    // The code is text in the row, so the minimum category reads without colour.
    expect(screen.getByText(strings.vtl.codes.ORANGE)).toBeInTheDocument();
    expect(screen.getByText(copy.rules.notApproved)).toBeInTheDocument();
    expect(screen.getByText(copy.rules.screening)).toBeInTheDocument();
  });

  it("offers approve and retire to an approver only", async () => {
    renderKb({ canApproveKb: true });
    fireEvent.click(await screen.findByRole("button", { name: copy.viewRules }));

    expect(await screen.findByRole("button", { name: copy.rules.approve })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.rules.retire })).toBeInTheDocument();
  });

  it("offers an administrator the table without the two actions", async () => {
    renderKb({ role: "ADMINISTRATOR", canApproveKb: false });
    fireEvent.click(await screen.findByRole("button", { name: copy.viewRules }));

    expect(await screen.findByText("Male cat producing no urine")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.rules.approve })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.rules.retire })).not.toBeInTheDocument();
  });

  it("publishes a version when a rule is approved", async () => {
    const { mock } = renderKb({
      canApproveKb: true,
      routes: {
        "/approve": { body: { id: RULES[0].id, code: RULES[0].code, version_no: 8 } },
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: copy.viewRules }));
    fireEvent.click(await screen.findByRole("button", { name: copy.rules.approve }));

    await waitFor(() => {
      expect(requestsTo(mock, "/red-flag-rules/").length).toBeGreaterThan(0);
    });
    expect(
      await screen.findByText(copy.toasts.ruleApproved.replace("{version}", "8")),
    ).toBeInTheDocument();
  });
});

describe("the version history drawer (FR-54, DR-05)", () => {
  it("lists each version's number, publisher and entry count", async () => {
    renderKb({ canApproveKb: true });

    fireEvent.click(await screen.findByRole("button", { name: copy.versions.open }));

    const drawer = await screen.findByRole("region", { name: copy.versions.heading });
    expect(
      await within(drawer).findByText(copy.versions.label.replace("{version}", "7")),
    ).toBeInTheDocument();
    expect(
      within(drawer).getByText(copy.versions.publishedBy.replace("{name}", "Dr. A. Rivera")),
    ).toBeInTheDocument();
    expect(
      within(drawer).getByText(copy.versions.entryCount.replace("{count}", "18")),
    ).toBeInTheDocument();
  });
});

describe("the entry list", () => {
  it("shows the source title and the complaint's name, not its code", async () => {
    renderKb();

    expect(
      await screen.findByText("Straining to urinate or unable to urinate"),
    ).toBeInTheDocument();
    expect(screen.getByText("Feline Lower Urinary Tract Disease")).toBeInTheDocument();
  });

  it("reports a failed catalogue read rather than an empty knowledge base", async () => {
    stubFetch({ "/kb/entries": { status: 500 } });
    renderWithAuth(<KnowledgeBase />, {
      user: makeUser({ role: "ADMINISTRATOR" }),
      route: "/kb",
    });

    expect(await screen.findByText(copy.errors.unexpected)).toBeInTheDocument();
  });
});
