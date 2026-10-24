/**
 * W-04 Case Review (FR-13, FR-31, FR-32, FR-36, FR-71..FR-79, IR-03, IR-04,
 * IR-06, IR-08).
 *
 * The fixture is the wireframe's sample case: C-0142, a male cat straining with
 * no urine, recommended ORANGE with the safety floor applied, three baseline
 * actions and three AI-suggested ones. Everything it asserts is a rule the
 * screen must not lose:
 *
 * - the AI label is on screen until a human decides, and gone afterwards (IR-04);
 * - the safety floor says so, and names the rule (FR-23);
 * - a user without `can_decide` gets no decision controls at all (BR-01, BR-02);
 * - the baseline actions survive every state of the actions job (FR-72, FR-77);
 * - unfinalized model suggestions never reach Intake Staff (FR-79);
 * - a decision records what the reviewer did to the action list (FR-76).
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CaseDetail, CaseReference, SuggestedAction, VTLCategory } from "../../api/cases";
import { strings } from "../../i18n/strings";
import { URGENCY_ORDER } from "../../lib/vtl";
import { errorBody, makeUser, renderWithAuth, stubFetch } from "../../test/testUtils";
import { CaseReview } from "./CaseReview";

const copy = strings.caseReview;

const CASE_ID = "00000000-0000-4000-8000-000000000142";

/** The de-identified text the extraction read, and the case text here. */
const DESCRIPTION =
  "Since this morning he keeps going to the litter box and cries, but nothing comes out. " +
  "He also vomited twice.";

const BASELINE_ACTIONS: readonly string[] = [
  "Alert the veterinarian now and move the patient to the treatment area.",
  "Recheck breathing effort and demeanour every few minutes while waiting.",
  "Keep the carrier covered and handling to a minimum to limit stress.",
];

const TAILORED_ACTIONS: readonly SuggestedAction[] = [
  {
    text: "Ask the owner when the cat last passed any urine.",
    cited_ranks: [1],
    source: "AI",
    is_outdated: false,
  },
  {
    text: "Check for a firm, painful bladder when the veterinarian examines.",
    cited_ranks: [1],
    source: "AI",
    is_outdated: false,
  },
];

/** Long enough that the panel has to truncate it (300 characters). */
const LONG_PASSAGE = `Male cats that strain without passing urine may have a blockage. ${"x".repeat(
  300,
)} END`;

const REFERENCES: readonly CaseReference[] = [
  {
    rank: 1,
    entry_title: "Feline lower urinary tract disease",
    source_title: "Merck Veterinary Manual",
    source_url: "https://example.invalid/flutd",
    passage_text: LONG_PASSAGE,
    score: 0.81,
    is_cited: true,
  },
  {
    rank: 2,
    entry_title: "Urinary discriminators",
    source_title: "Veterinary Triage List",
    source_url: null,
    passage_text: "Inability to urinate is listed among the higher-urgency discriminators.",
    score: 0.64,
    is_cited: false,
  },
];

/** The offsets of `fragment`, so a fixture cannot count characters wrong. */
function spanOf(field: string, fragment: string) {
  const start = DESCRIPTION.indexOf(fragment);
  expect(start).toBeGreaterThanOrEqual(0);
  return { field, text: fragment, start, end: start + fragment.length, found: true };
}

/** Fictitious, as every fixture in this project is (CLAUDE.md §9). */
function makeCaseDetail(overrides: Partial<CaseDetail> = {}): CaseDetail {
  return {
    id: CASE_ID,
    case_no: "C-0142",
    status: "AWAITING_REVIEW",
    species: "CAT",
    category: "ORANGE",
    recommended_category: "ORANGE",
    confirmed_category: null,
    has_red_flag: true,
    created_at: "2026-10-01T01:36:00Z",

    actions: {
      status: "READY",
      generated_for_category: "ORANGE",
      baseline: [...BASELINE_ACTIONS],
      tailored: [...TAILORED_ACTIONS],
      rejected_count: 1,
      is_outdated: false,
      failure_message: null,
    },

    header: {
      case_no: "C-0142",
      species: "CAT",
      pet_name: "Mingming",
      age_value: 3,
      age_unit: "YEARS",
      sex: "MALE",
      neutered: false,
      breed: null,
      weight_kg: 4.2,
      intake_channel: "PHONE",
      created_at: "2026-10-01T01:36:00Z",
      created_by_name: "J. Cruz",
      closed_at: null,
      waiting_minutes: 6,
      target_minutes: 15,
      is_overdue: false,
    },

    description: { text: DESCRIPTION, deidentified_text: DESCRIPTION, differs: false },

    extraction: {
      id: "00000000-0000-4000-8000-0000000000e1",
      version: 1,
      is_corrected: false,
      corrected_by_name: null,
      species: "CAT",
      presenting_complaints: [
        { code: "URINARY_STRAINING", name: "Straining or inability to urinate", is_primary: true },
        { code: "VOMITING", name: "Vomiting", is_primary: false },
      ],
      onset_duration: "Since this morning (< 24 h)",
      frequency_severity: "Repeated attempts; vomited 2 times",
      associated_signs: ["Vocalizing (crying)"],
      negated_findings: [],
      exposure_history: null,
      relevant_history: null,
      red_flags: ["Male cat producing no urine"],
      missing_information: ["Appetite", "Water intake", "Previous episodes"],
      evidence_spans: [
        spanOf("onset_duration", "Since this morning"),
        spanOf("associated_signs", "cries"),
      ],
      created_at: "2026-10-01T01:36:09Z",
    },

    recommendation: {
      id: "00000000-0000-4000-8000-0000000000r1",
      version: 1,
      category: "ORANGE",
      target_minutes: 15,
      rationale:
        "The owner reports repeated straining with no urine since this morning in a male cat.",
      confidence: "MEDIUM",
      safety_floor_applied: true,
      safety_floor_rules: [{ code: "MALE_CAT_NO_URINE", label: "male cat, no urine" }],
      low_confidence_reasons: ["LOW_RETRIEVAL_SCORE"],
      created_at: "2026-10-01T01:36:14Z",
    },

    references: [...REFERENCES],

    configuration: {
      model_id: "mock",
      prompt_version: "mock-0",
      kb_version_no: 7,
      generated_at: "2026-10-01T01:36:14Z",
      latency_ms: 9200,
    },

    alerts: [
      {
        rule_code: "MALE_CAT_NO_URINE",
        rule_label: "male cat producing no urine",
        min_category: "ORANGE",
        created_at: "2026-10-01T01:36:01Z",
        acknowledged_at: "2026-10-01T01:42:00Z",
      },
    ],

    decision: null,
    notes: [],
    permissions: {
      can_decide: true,
      can_regenerate: false,
      can_regenerate_actions: false,
      can_retry: false,
      can_close: false,
    },
    failure: null,
    recommendation_versions: [
      { version: 1, category: "ORANGE", created_at: "2026-10-01T01:36:14Z", is_current: true },
    ],
    regeneration_failure: null,

    ...overrides,
  };
}

/** A case a reviewer has already confirmed. */
function confirmedCase(): CaseDetail {
  return makeCaseDetail({
    status: "CONFIRMED",
    confirmed_category: "ORANGE",
    decision: {
      id: "00000000-0000-4000-8000-0000000000d1",
      type: "CONFIRM",
      final_category: "ORANGE",
      target_minutes: 15,
      reason_code: null,
      reason_text: null,
      direction: "SAME",
      decided_by_name: "Reviewer Demo",
      decided_at: "2026-10-01T01:44:00Z",
      amends_id: null,
      status: "CONFIRMED",
    },
  });
}

/** A case the pipeline gave up on: no recommendation, and a reason why (W-06). */
/** What the server writes for `LLM_TIMEOUT` (backend `pipeline/messages.py`). */
const FAILURE_MESSAGE =
  "The language model did not respond after 2 attempts (09:20:41). " +
  "The case is safe to triage; no data was lost.";

function manualTriageCase(overrides: Partial<CaseDetail> = {}): CaseDetail {
  return makeCaseDetail({
    status: "MANUAL_TRIAGE_REQUIRED",
    category: null,
    recommended_category: null,
    extraction: null,
    recommendation: null,
    references: [],
    configuration: null,
    actions: {
      status: null,
      generated_for_category: null,
      baseline: [],
      tailored: [],
      rejected_count: 0,
      is_outdated: false,
      failure_message: null,
    },
    failure: {
      reason_code: "LLM_TIMEOUT",
      message: FAILURE_MESSAGE,
      failed_at: "2026-10-01T01:20:41Z",
    },
    permissions: {
      can_decide: true,
      can_regenerate: false,
      can_regenerate_actions: false,
      can_retry: true,
      can_close: false,
    },
    recommendation_versions: [],
    ...overrides,
  });
}

function renderCase(
  detail: CaseDetail,
  options: {
    role?: "INTAKE_STAFF" | "VETERINARY_REVIEWER" | "ADMINISTRATOR";
    decision?: unknown;
    /** Extra or replacement routes, matched before the two defaults. */
    routes?: Record<string, { status?: number; body?: unknown }>;
  } = {},
) {
  // Order matters twice over. `stubFetch` matches on the first key the URL
  // contains and every path here contains `/cases/{id}`, so the subroutes go in
  // first and the case itself last. And a key is only defaulted when `routes`
  // did not supply it — spreading over it would silently shadow a route a test
  // asked for.
  const routes: Record<string, { status?: number; body?: unknown }> = {
    ...(options.routes ?? {}),
  };
  if (!("/decision" in routes)) {
    routes["/decision"] = { body: options.decision ?? confirmedCase().decision };
  }
  routes[`/cases/${CASE_ID}`] = { body: detail };

  const mock = stubFetch(routes);

  const result = renderWithAuth(
    <Routes>
      <Route path="/cases/:caseId" element={<CaseReview />} />
      <Route path="/queue" element={<p>triage queue</p>} />
    </Routes>,
    {
      route: `/cases/${CASE_ID}`,
      user: makeUser({ role: options.role ?? "VETERINARY_REVIEWER" }),
    },
  );

  return { ...result, mock };
}

/**
 * The body the decision was posted with.
 *
 * Found by path rather than taken from the last call: recording a decision
 * invalidates the case, so a GET follows it.
 */
function decisionBody(mock: ReturnType<typeof stubFetch>): Record<string, unknown> {
  const call = mock.mock.calls.filter((entry) => String(entry[0]).includes("/decision")).at(-1);
  expect(call).toBeDefined();
  return JSON.parse(String(call?.[1]?.body)) as Record<string, unknown>;
}

/** The body posted to a path, or undefined if nothing was. */
function postedBody(
  mock: ReturnType<typeof stubFetch>,
  path: string,
): Record<string, unknown> | undefined {
  const call = mock.mock.calls.filter((entry) => String(entry[0]).includes(path)).at(-1);
  if (call === undefined) {
    return undefined;
  }
  return JSON.parse(String(call[1]?.body)) as Record<string, unknown>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CaseReview header and panels", () => {
  it("names the patient, the arrival and the live waiting time", async () => {
    renderCase(makeCaseDetail());

    expect(
      await screen.findByRole("heading", { name: /C-0142 · Cat · Mingming · 3 y · Male, intact/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/recorded by J\. Cruz/)).toBeInTheDocument();
    expect(screen.getByText("waiting 6 min of 15 min")).toBeInTheDocument();
  });

  // IR-04: the one sentence that must stay on screen until a human decides.
  it("shows the AI label before a decision", async () => {
    renderCase(makeCaseDetail());

    expect(await screen.findByText(copy.aiPendingChip)).toBeInTheDocument();
  });

  it("replaces the AI label with the status once the case is decided", async () => {
    renderCase(confirmedCase());

    expect(await screen.findByText(strings.statusChip.confirmed)).toBeInTheDocument();
    expect(screen.queryByText(copy.aiPendingChip)).not.toBeInTheDocument();
  });

  it("announces the red flag by rule label, with no link back to this case", async () => {
    renderCase(makeCaseDetail());

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("male cat producing no urine");
    expect(within(banner).queryByRole("link")).not.toBeInTheDocument();
  });

  it("keeps the panels in the order ADR-15 sets", async () => {
    renderCase(makeCaseDetail());

    const headings = await screen.findAllByRole("heading", { level: 2 });
    expect(headings.map((heading) => heading.textContent)).toEqual([
      copy.descriptionTitle,
      copy.extractionTitle,
      copy.recommendationTitle,
    ]);
  });
});

describe("CaseReview panel 1 — the owner's description", () => {
  it("highlights the evidence the extraction used (FR-13)", async () => {
    const { container } = renderCase(makeCaseDetail());

    await screen.findByText(copy.descriptionTitle);
    const marks = container.querySelectorAll("mark");
    expect(Array.from(marks).map((mark) => mark.textContent)).toEqual([
      "Since this morning",
      "cries",
    ]);
    expect(marks[0]).toHaveAttribute("title", copy.fields.onset_duration);
  });

  // ADR-10: the offsets index into the de-identified text, so that is the text
  // shown when the two differ — a highlight over the original would mark the
  // wrong words.
  it("shows the de-identified text, and says so, when it differs", async () => {
    renderCase(
      makeCaseDetail({
        description: {
          text: "Maria said he keeps going to the litter box.",
          deidentified_text: DESCRIPTION,
          differs: true,
        },
      }),
    );

    expect(await screen.findByText(copy.deidentifiedNote)).toBeInTheDocument();
    expect(screen.queryByText(/Maria/)).not.toBeInTheDocument();
  });

  it("lists evidence the stored text no longer contains, rather than dropping it", async () => {
    const detail = makeCaseDetail();
    renderCase({
      ...detail,
      extraction: {
        ...detail.extraction!,
        evidence_spans: [
          {
            field: "relevant_history",
            text: "fine last night",
            start: null,
            end: null,
            found: false,
          },
        ],
      },
    });

    expect(await screen.findByText(copy.unmatchedEvidenceTitle)).toBeInTheDocument();
    expect(screen.getByText(/fine last night/)).toBeInTheDocument();
  });

  it("renders the description unhighlighted when there is no extraction", async () => {
    const { container } = renderCase(makeCaseDetail({ extraction: null }));

    await screen.findByText(copy.descriptionTitle);
    expect(container.querySelectorAll("mark")).toHaveLength(0);
    expect(screen.getByText(DESCRIPTION)).toBeInTheDocument();
  });
});

describe("CaseReview panel 2 — the extraction", () => {
  it("shows the extracted values, with the primary complaint marked", async () => {
    renderCase(makeCaseDetail());

    expect(await screen.findByText("Straining or inability to urinate")).toBeInTheDocument();
    expect(screen.getByText(copy.primaryMarker)).toBeInTheDocument();
    expect(screen.getByText("Since this morning (< 24 h)")).toBeInTheDocument();
  });

  it("shows the red flags and the questions to ask the owner", async () => {
    renderCase(makeCaseDetail());

    expect(await screen.findByText("Male cat producing no urine")).toBeInTheDocument();
    expect(screen.getByText(copy.fields.missing_information)).toBeInTheDocument();
    expect(screen.getByText(/Appetite · Water intake · Previous episodes/)).toBeInTheDocument();
  });

  it("reads an empty value as 'None stated' rather than dropping the row", async () => {
    renderCase(makeCaseDetail());

    await screen.findByText(copy.fields.negated_findings);
    expect(screen.getAllByText(copy.emptyValue).length).toBeGreaterThan(0);
  });

  it("says so when there is no extraction at all", async () => {
    renderCase(makeCaseDetail({ extraction: null }));

    expect(await screen.findByText(copy.extractionUnavailable)).toBeInTheDocument();
  });

  // Without `can_regenerate` the panel is a record: nothing to press.
  it("is read-only, with no Save and regenerate button, when regenerating is not allowed", async () => {
    renderCase(makeCaseDetail());

    await screen.findByText(copy.fields.onset_duration);
    expect(screen.queryByRole("button", { name: copy.saveAndRegenerate })).not.toBeInTheDocument();
    expect(screen.queryByText(copy.editHint)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: copy.editField.replace("{field}", copy.fields.onset_duration),
      }),
    ).not.toBeInTheDocument();
  });
});

const COMPLAINT_OPTIONS = [
  { code: "URINARY_STRAINING", name: "Straining or inability to urinate" },
  { code: "VOMITING", name: "Vomiting" },
  { code: "COLLAPSE", name: "Collapse" },
];

function regenerable(overrides: Partial<CaseDetail> = {}): CaseDetail {
  return makeCaseDetail({
    permissions: {
      can_decide: true,
      can_regenerate: true,
      can_regenerate_actions: false,
      can_retry: false,
      can_close: false,
    },
    ...overrides,
  });
}

/** A correction accepted by the server: the 202 for `PATCH /cases/{id}/extraction`. */
const ACCEPTED = {
  status: 202,
  body: {
    id: CASE_ID,
    case_no: "C-0142",
    status: "PROCESSING",
    extraction_version: 2,
    changed_fields: ["onset_duration"],
  },
};

function renderRegenerable(
  detail: CaseDetail = regenerable(),
  routes: Record<string, { status?: number; body?: unknown }> = {},
) {
  return renderCase(detail, {
    routes: { "/extraction": ACCEPTED, "/kb/complaints": { body: COMPLAINT_OPTIONS }, ...routes },
  });
}

function editButton(label: string) {
  return screen.getByRole("button", { name: copy.editField.replace("{field}", label) });
}

/** Opens a field's editor, types into it, and closes the editor again. */
function editField(label: string, value: string) {
  fireEvent.click(editButton(label));
  fireEvent.change(screen.getByRole("textbox", { name: label }), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: copy.editDone }));
}

function savedCorrection(mock: ReturnType<typeof stubFetch>) {
  const call = mock.mock.calls.find((entry) => String(entry[0]).includes("/extraction"));
  return call === undefined
    ? undefined
    : {
        method: call[1]?.method,
        body: JSON.parse(String(call[1]?.body)) as Record<string, unknown>,
      };
}

describe("CaseReview panel 2 — correcting the extraction (P07 §7.2, FR-27)", () => {
  it("invites a correction and keeps Save and regenerate off until something changes", async () => {
    renderRegenerable();

    const button = await screen.findByRole("button", { name: copy.saveAndRegenerate });
    expect(screen.getByText(copy.editHint)).toBeInTheDocument();
    expect(screen.getByText(copy.enabledAfterCorrection)).toBeInTheDocument();
    expect(button).toBeDisabled();
  });

  it("turns the button on for a change and off again when the change is undone", async () => {
    renderRegenerable();
    await screen.findByText(copy.fields.onset_duration);

    editField(copy.fields.onset_duration, "Since yesterday evening");
    expect(screen.getByRole("button", { name: copy.saveAndRegenerate })).toBeEnabled();
    expect(screen.getByText(`(${copy.editedMarker})`)).toBeInTheDocument();

    editField(copy.fields.onset_duration, "Since this morning (< 24 h)");
    expect(screen.getByRole("button", { name: copy.saveAndRegenerate })).toBeDisabled();
  });

  it("sends only the fields that changed", async () => {
    const { mock } = renderRegenerable();
    await screen.findByText(copy.fields.onset_duration);

    editField(copy.fields.onset_duration, "  Since yesterday evening ");
    fireEvent.click(editButton(copy.fields.red_flags));
    fireEvent.change(screen.getByRole("textbox", { name: copy.fields.red_flags }), {
      target: { value: "Male cat producing no urine\nCollapsed at the litter box\n\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: copy.saveAndRegenerate }));

    await waitFor(() => expect(savedCorrection(mock)).toBeDefined());
    expect(savedCorrection(mock)).toEqual({
      method: "PATCH",
      body: {
        onset_duration: "Since yesterday evening",
        red_flags: ["Male cat producing no urine", "Collapsed at the litter box"],
      },
    });
  });

  it("sends a cleared text value as null", async () => {
    const { mock } = renderRegenerable();
    await screen.findByText(copy.fields.onset_duration);

    editField(copy.fields.onset_duration, "   ");
    fireEvent.click(screen.getByRole("button", { name: copy.saveAndRegenerate }));

    await waitFor(() => expect(savedCorrection(mock)).toBeDefined());
    expect(savedCorrection(mock)?.body).toEqual({ onset_duration: null });
  });

  it("chooses complaints from the list with exactly one primary", async () => {
    const { mock } = renderRegenerable();
    await screen.findByText(copy.fields.onset_duration);

    fireEvent.click(editButton(copy.fields.presenting_complaints));
    // The list loads from the knowledge-base complaints endpoint.
    const collapse = await screen.findByRole("checkbox", { name: /Collapse/ });
    fireEvent.click(collapse);
    fireEvent.click(
      screen.getByRole("radio", { name: copy.primaryFor.replace("{complaint}", "Collapse") }),
    );
    fireEvent.click(screen.getByRole("button", { name: copy.saveAndRegenerate }));

    await waitFor(() => expect(savedCorrection(mock)).toBeDefined());
    expect(savedCorrection(mock)?.body).toEqual({
      presenting_complaints: [
        { code: "URINARY_STRAINING", is_primary: false },
        { code: "VOMITING", is_primary: false },
        { code: "COLLAPSE", is_primary: true },
      ],
    });
  });

  it("hands the primary mark on when the primary complaint is unchecked", async () => {
    const { mock } = renderRegenerable();
    await screen.findByText(copy.fields.onset_duration);

    fireEvent.click(editButton(copy.fields.presenting_complaints));
    fireEvent.click(await screen.findByRole("checkbox", { name: /Straining or inability/ }));
    fireEvent.click(screen.getByRole("button", { name: copy.saveAndRegenerate }));

    await waitFor(() => expect(savedCorrection(mock)).toBeDefined());
    expect(savedCorrection(mock)?.body).toEqual({
      presenting_complaints: [{ code: "VOMITING", is_primary: true }],
    });
  });

  it("shows the server's wording when a value is refused", async () => {
    renderRegenerable(regenerable(), {
      "/extraction": {
        status: 422,
        body: errorBody(
          "VALIDATION_ERROR",
          "Mark exactly one complaint as primary.",
          "presenting_complaints",
        ),
      },
    });
    await screen.findByText(copy.fields.onset_duration);

    editField(copy.fields.onset_duration, "Since yesterday");
    fireEvent.click(screen.getByRole("button", { name: copy.saveAndRegenerate }));

    expect(await screen.findByText("Mark exactly one complaint as primary.")).toBeInTheDocument();
  });

  it("refreshes and explains when the case can no longer be corrected", async () => {
    renderRegenerable(regenerable(), {
      "/extraction": {
        status: 409,
        body: errorBody("INVALID_TRANSITION", "This case has already been decided."),
      },
    });
    await screen.findByText(copy.fields.onset_duration);

    editField(copy.fields.onset_duration, "Since yesterday");
    fireEvent.click(screen.getByRole("button", { name: copy.saveAndRegenerate }));

    expect(await screen.findByText(copy.errors.correctionConflict)).toBeInTheDocument();
  });

  it("shows a quiet error when the correction cannot be sent", async () => {
    renderRegenerable(regenerable(), { "/extraction": { status: 500 } });
    await screen.findByText(copy.fields.onset_duration);

    editField(copy.fields.onset_duration, "Since yesterday");
    fireEvent.click(screen.getByRole("button", { name: copy.saveAndRegenerate }));

    expect(await screen.findByText(copy.errors.correctionFailed)).toBeInTheDocument();
  });

  it("says who corrected a corrected version", async () => {
    const detail = regenerable();
    renderRegenerable({
      ...detail,
      extraction: detail.extraction && {
        ...detail.extraction,
        version: 2,
        is_corrected: true,
        corrected_by_name: "Reviewer Demo",
      },
    });

    expect(await screen.findByText("Version 2 – corrected by Reviewer Demo.")).toBeInTheDocument();
  });
});

const REGENERATING_STATUS = {
  body: {
    status: "PROCESSING",
    category: "ORANGE",
    has_red_flag: true,
    pipeline_stage: "generate",
    actions_status: "READY",
    updated_at: "2026-10-01T01:50:00Z",
  },
};

describe("CaseReview while a correction is being regenerated (FR-27)", () => {
  it("shows the regeneration progress, not the first-run wording", async () => {
    renderCase(regenerable({ status: "PROCESSING" }), {
      routes: { "/status": REGENERATING_STATUS },
    });

    expect(await screen.findByText(copy.processing.regeneratingTitle)).toBeInTheDocument();
    expect(
      await screen.findByText(copy.processing.regeneratingStages.generate),
    ).toBeInTheDocument();
    expect(screen.queryByText(copy.processing.title)).not.toBeInTheDocument();
  });

  it("offers no decision and no further correction while it runs", async () => {
    renderCase(
      makeCaseDetail({
        status: "PROCESSING",
        permissions: {
          can_decide: true,
          can_regenerate: false,
          can_regenerate_actions: false,
          can_retry: false,
          can_close: false,
        },
      }),
      { routes: { "/status": REGENERATING_STATUS } },
    );

    await screen.findByText(copy.processing.regeneratingTitle);
    expect(screen.getByRole("button", { name: /^Confirm/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.decisionBar.adjust })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.decisionBar.manual })).toBeDisabled();
    expect(screen.queryByRole("button", { name: copy.saveAndRegenerate })).not.toBeInTheDocument();
  });

  it("uses the first-run wording for a case with no recommendation yet", async () => {
    renderCase(manualTriageCase({ status: "SUBMITTED", failure: null }), {
      routes: { "/status": REGENERATING_STATUS },
    });

    expect(await screen.findByText(copy.processing.title)).toBeInTheDocument();
  });

  it("shows why the last regeneration failed and keeps the previous recommendation", async () => {
    renderCase(
      regenerable({
        regeneration_failure: {
          reason_code: "LLM_TIMEOUT",
          message:
            "The language model did not respond after 2 attempts (09:20:41). " +
            "Your correction was saved and the previous recommendation is unchanged.",
          failed_at: "2026-10-01T01:20:41Z",
        },
      }),
    );

    expect(await screen.findByText(/Your correction was saved/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(copy.regenerationFailedTitle))).toBeInTheDocument();
    expect(screen.getByText("ORANGE")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Confirm/ })).toBeEnabled();
  });
});

const VERSION_ONE = {
  version: 1,
  category: "BLUE" as const,
  created_at: "2026-10-01T01:36:14Z",
  is_current: false,
};
const VERSION_TWO = {
  version: 2,
  category: "ORANGE" as const,
  created_at: "2026-10-01T01:52:00Z",
  is_current: true,
};

function regeneratedCase(): CaseDetail {
  const detail = makeCaseDetail();
  return makeCaseDetail({
    recommendation: detail.recommendation && { ...detail.recommendation, version: 2 },
    recommendation_versions: [VERSION_ONE, VERSION_TWO],
  });
}

const OLD_VERSION = {
  body: {
    recommendation: {
      id: "00000000-0000-4000-8000-0000000000r0",
      version: 1,
      category: "BLUE",
      target_minutes: 240,
      rationale: "The first reading was a routine complaint.",
      confidence: "HIGH",
      safety_floor_applied: false,
      safety_floor_rules: [],
      low_confidence_reasons: [],
      created_at: "2026-10-01T01:36:14Z",
    },
    references: [],
    configuration: {
      model_id: "mock",
      prompt_version: "mock-0",
      kb_version_no: 7,
      generated_at: "2026-10-01T01:36:14Z",
      latency_ms: null,
    },
    extraction_version: 1,
    is_current: false,
  },
};

describe("CaseReview recommendation versions (FR-27, ADR-14)", () => {
  it("notes that the recommendation was regenerated after a correction", async () => {
    renderCase(regeneratedCase());

    expect(
      await screen.findByText(
        "Version 2 – regenerated after correction (version 1 kept in audit).",
      ),
    ).toBeInTheDocument();
  });

  it("has no switcher and no note while there is only one version", async () => {
    renderCase(makeCaseDetail());

    await screen.findByText("ORANGE");
    expect(screen.queryByRole("group", { name: copy.versions.label })).not.toBeInTheDocument();
    expect(screen.queryByText(/regenerated after correction/)).not.toBeInTheDocument();
  });

  it("lists every version and marks the current one", async () => {
    renderCase(regeneratedCase());

    const group = await screen.findByRole("group", { name: copy.versions.label });
    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Version 1 · Blue",
      "Version 2 · Orange (current)",
    ]);
    expect(buttons[1]).toHaveAttribute("aria-pressed", "true");
    expect(buttons[0]).toHaveAttribute("aria-pressed", "false");
  });

  it("shows an older version read-only, and cannot be decided on", async () => {
    const { mock } = renderCase(regeneratedCase(), {
      routes: { "/recommendations/1": OLD_VERSION },
    });

    fireEvent.click(await screen.findByRole("button", { name: /^Version 1/ }));

    expect(
      await screen.findByText("The first reading was a routine complaint."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(copy.versions.viewingOlder.replace("{version}", "1")),
    ).toBeInTheDocument();
    expect(screen.getByText(copy.versions.madeFrom.replace("{version}", "1"))).toBeInTheDocument();
    // Decisions always apply to the latest version.
    expect(screen.getByRole("button", { name: /^Confirm/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.decisionBar.adjust })).toBeDisabled();
    // The checklist belongs to the current recommendation.
    expect(screen.queryByText(copy.actions.aiHeading)).not.toBeInTheDocument();
    expect(mock.mock.calls.some((entry) => String(entry[0]).endsWith("/recommendations/1"))).toBe(
      true,
    );
  });

  it("goes back to the current version", async () => {
    renderCase(regeneratedCase(), { routes: { "/recommendations/1": OLD_VERSION } });

    fireEvent.click(await screen.findByRole("button", { name: /^Version 1/ }));
    await screen.findByText("The first reading was a routine complaint.");
    fireEvent.click(screen.getByRole("button", { name: copy.versions.backToCurrent }));

    await waitFor(() =>
      expect(
        screen.queryByText("The first reading was a routine complaint."),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /^Confirm/ })).toBeEnabled();
  });

  it("says so when an older version cannot be loaded", async () => {
    renderCase(regeneratedCase(), { routes: { "/recommendations/1": { status: 500 } } });

    fireEvent.click(await screen.findByRole("button", { name: /^Version 1/ }));

    expect(await screen.findByText(copy.errors.versionFailed)).toBeInTheDocument();
  });
});

describe("CaseReview panel 3 — the recommendation", () => {
  it("shows the category with its name and target time (IR-03)", async () => {
    renderCase(makeCaseDetail());

    expect(await screen.findByText("ORANGE")).toBeInTheDocument();
    expect(screen.getByText("Very urgent · see within ≤ 15 min")).toBeInTheDocument();
  });

  // FR-23: a reviewer is entitled to know a rule raised the category, not the model.
  it("renders the safety-floor notice and names the rule", async () => {
    renderCase(makeCaseDetail());

    expect(
      await screen.findByText(/Safety floor applied: the red flag “male cat, no urine”/),
    ).toBeInTheDocument();
    expect(screen.getByText(/requires at least Orange/)).toBeInTheDocument();
  });

  it("leaves the notice out when no rule raised the category", async () => {
    const detail = makeCaseDetail();
    renderCase({
      ...detail,
      recommendation: {
        ...detail.recommendation!,
        safety_floor_applied: false,
        safety_floor_rules: [],
      },
    });

    await screen.findByText(copy.recommendationTitle);
    expect(screen.queryByText(/Safety floor applied/)).not.toBeInTheDocument();
  });

  it("states the confidence and its reasons in plain language (FR-24)", async () => {
    renderCase(makeCaseDetail());

    expect(await screen.findByText(/Medium/)).toBeInTheDocument();
    expect(screen.getByText(copy.lowConfidenceReasons.LOW_RETRIEVAL_SCORE)).toBeInTheDocument();
    // IR-05: a stored code is never shown to a clinician.
    expect(screen.queryByText(/LOW_RETRIEVAL_SCORE/)).not.toBeInTheDocument();
  });

  it("falls back to a sentence for a reason code it does not know", async () => {
    const detail = makeCaseDetail();
    renderCase({
      ...detail,
      recommendation: { ...detail.recommendation!, low_confidence_reasons: ["SOMETHING_NEW"] },
    });

    expect(await screen.findByText(copy.lowConfidenceFallback)).toBeInTheDocument();
  });

  it("marks the cited references and leaves the others unmarked (FR-22)", async () => {
    renderCase(makeCaseDetail());

    await screen.findByText(copy.referencesTitle);
    expect(screen.getAllByText(copy.citedMarker)).toHaveLength(1);
    expect(screen.getByText(/\[1\] Feline lower urinary tract disease/)).toBeInTheDocument();
    // An uncited passage stays on screen: what the model did not use is evidence too.
    expect(screen.getByText(/\[2\] Urinary discriminators/)).toBeInTheDocument();
  });

  it("truncates a long passage and reveals it on 'Show more'", async () => {
    renderCase(makeCaseDetail());

    const showMore = await screen.findByRole("button", { name: copy.showMore });
    expect(screen.queryByText(/END/)).not.toBeInTheDocument();

    fireEvent.click(showMore);

    expect(screen.getByText(/END/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.showLess })).toBeInTheDocument();
  });

  it("records what produced the recommendation (FR-26)", async () => {
    renderCase(makeCaseDetail());

    expect(
      await screen.findByText(/Model: mock · Prompt mock-0 · KB version 7/),
    ).toBeInTheDocument();
    expect(screen.getByText(/in 9\.2 s/)).toBeInTheDocument();
  });

  // A reviewer gets the W-06 picker in this panel's place; everyone else reads
  // the sentence, because manual triage is not theirs to do (BR-02).
  it("reads a missing recommendation as a case to triage by hand, not an error", async () => {
    renderCase(
      manualTriageCase({
        permissions: {
          can_decide: false,
          can_regenerate: false,
          can_regenerate_actions: false,
          can_retry: false,
          can_close: false,
        },
      }),
      { role: "INTAKE_STAFF" },
    );

    expect(await screen.findByText(copy.recommendationUnavailable)).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: copy.manualTriage.title }),
    ).not.toBeInTheDocument();
  });
});

describe("CaseReview suggested actions", () => {
  // FR-72: the baseline list is read from the knowledge base for the case's
  // category, so it is there for every one of the five.
  it.each(URGENCY_ORDER)("renders the baseline actions for %s", async (category: VTLCategory) => {
    const detail = makeCaseDetail();
    renderCase({
      ...detail,
      category,
      recommended_category: category,
      recommendation: { ...detail.recommendation!, category },
      actions: { ...detail.actions, generated_for_category: category },
    });

    await screen.findByText(copy.actions.title);
    for (const action of BASELINE_ACTIONS) {
      expect(screen.getByText(action, { exact: false })).toBeInTheDocument();
    }
  });

  it("puts the AI-suggested actions under the approval heading (FR-75)", async () => {
    renderCase(makeCaseDetail());

    expect(await screen.findByText(copy.actions.aiHeading)).toBeInTheDocument();
    expect(screen.getByText(TAILORED_ACTIONS[0].text, { exact: false })).toBeInTheDocument();
    // The citation ties the row to the passage that supports it (IR-23).
    expect(screen.getAllByText("[1]").length).toBeGreaterThan(0);
  });

  it("drops the approval heading once the case is decided", async () => {
    renderCase(confirmedCase());

    await screen.findByText(copy.actions.title);
    expect(screen.queryByText(copy.actions.aiHeading)).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  // FR-79. The server sends Intake Staff an empty `tailored` list; the screen
  // must not invent a heading for it either.
  it("shows Intake Staff no unfinalized tailored actions", async () => {
    const detail = makeCaseDetail();
    renderCase(
      {
        ...detail,
        actions: { ...detail.actions, tailored: [], rejected_count: 0 },
        permissions: {
          can_decide: false,
          can_regenerate: false,
          can_regenerate_actions: false,
          can_retry: false,
          can_close: false,
        },
      },
      { role: "INTAKE_STAFF" },
    );

    await screen.findByText(copy.actions.title);
    expect(screen.getByText(BASELINE_ACTIONS[0], { exact: false })).toBeInTheDocument();
    expect(screen.queryByText(copy.actions.aiHeading)).not.toBeInTheDocument();
    expect(screen.queryByText(TAILORED_ACTIONS[0].text)).not.toBeInTheDocument();
  });

  it("shows a loading row while the suggestions are still being prepared", async () => {
    const detail = makeCaseDetail();
    renderCase({
      ...detail,
      actions: { ...detail.actions, status: "PENDING", tailored: [], rejected_count: 0 },
    });

    expect(await screen.findByText(copy.actions.pending)).toBeInTheDocument();
    expect(screen.getByText(BASELINE_ACTIONS[0], { exact: false })).toBeInTheDocument();
  });

  // FR-77: one quiet line, never an error dialog, and never a blocked decision.
  it("shows one quiet line when the suggestions failed, and still allows a decision", async () => {
    const detail = makeCaseDetail();
    renderCase({
      ...detail,
      actions: { ...detail.actions, status: "FAILED", tailored: [], rejected_count: 0 },
    });

    expect(await screen.findByText(copy.actions.failed)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm Orange" })).toBeEnabled();
    // The red-flag banner is the only alert on this screen.
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("says how many suggestions the safety check withheld (FR-74)", async () => {
    renderCase(makeCaseDetail());

    expect(await screen.findByText(copy.actions.rejectedOne)).toBeInTheDocument();
  });

  it("lets a reviewer edit a row's wording", async () => {
    renderCase(makeCaseDetail());

    const edit = await screen.findByRole("button", {
      name: `${copy.actions.editLabel}: ${BASELINE_ACTIONS[0]}`,
    });
    fireEvent.click(edit);

    const input = screen.getByLabelText(copy.actions.editLabel);
    fireEvent.change(input, { target: { value: "Alert the veterinarian now." } });
    fireEvent.click(screen.getByRole("button", { name: copy.actions.editSave }));

    expect(screen.getByText("Alert the veterinarian now.", { exact: false })).toBeInTheDocument();
  });

  it("lets a reviewer add an action of their own", async () => {
    renderCase(makeCaseDetail());

    const input = await screen.findByLabelText(copy.actions.addLabel);
    fireEvent.change(input, { target: { value: "Ask whether the cat has vomited again." } });
    fireEvent.click(screen.getByRole("button", { name: copy.actions.add }));

    expect(
      screen.getByText("Ask whether the cat has vomited again.", { exact: false }),
    ).toBeInTheDocument();
    expect(screen.getByText(copy.actions.sources.REVIEWER)).toBeInTheDocument();
  });
});

describe("CaseReview decision bar", () => {
  it("offers every decision control, and the audit timeline beside them", async () => {
    renderCase(makeCaseDetail());

    expect(await screen.findByRole("button", { name: "Confirm Orange" })).toBeEnabled();
    for (const label of [
      copy.decisionBar.adjust,
      copy.decisionBar.manual,
      copy.decisionBar.addNote,
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeEnabled();
    }

    // W-07, on its own route (§6.4).
    expect(screen.getByRole("link", { name: copy.decisionBar.viewAudit })).toHaveAttribute(
      "href",
      `/cases/${CASE_ID}/audit`,
    );
  });

  // FR-38: closing is offered only once a decision exists, which is what
  // `can_close` reports.
  it("offers Close case only when the server says the case may be closed", async () => {
    renderCase(makeCaseDetail());
    await screen.findByRole("button", { name: "Confirm Orange" });
    expect(screen.queryByRole("button", { name: copy.decisionBar.close })).not.toBeInTheDocument();
  });

  it("always shows the decision-support disclaimer (IR-06, BR-10)", async () => {
    renderCase(makeCaseDetail());

    expect(await screen.findByText(copy.decisionBar.disclaimer)).toBeInTheDocument();
  });

  // BR-01, BR-02: Intake Staff and administrators may read a case, never decide one.
  it("hides the decision buttons and says the case is read-only for Intake Staff", async () => {
    renderCase(
      makeCaseDetail({
        permissions: {
          can_decide: false,
          can_regenerate: false,
          can_regenerate_actions: false,
          can_retry: false,
          can_close: false,
        },
      }),
      { role: "INTAKE_STAFF" },
    );

    expect(await screen.findByText(copy.decisionBar.readOnly)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Confirm/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.decisionBar.adjust })).not.toBeInTheDocument();
    // The disclaimer stays: the category on screen is still not a diagnosis.
    expect(screen.getByText(copy.decisionBar.disclaimer)).toBeInTheDocument();
    // FR-45: read-only is about deciding, not about reading the record.
    expect(screen.getByRole("link", { name: copy.decisionBar.viewAudit })).toHaveAttribute(
      "href",
      `/cases/${CASE_ID}/audit`,
    );
  });

  it("shows the decision already recorded instead of offering Confirm again", async () => {
    renderCase(confirmedCase());

    expect(await screen.findByText(copy.decisionBar.decided)).toBeInTheDocument();
    expect(screen.getByText(/Orange · Reviewer Demo/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Confirm/ })).not.toBeInTheDocument();
  });
});

describe("CaseReview confirming a decision", () => {
  it("asks first, then records the decision and returns to the queue (IR-08)", async () => {
    const { mock } = renderCase(makeCaseDetail());

    fireEvent.click(await screen.findByRole("button", { name: "Confirm Orange" }));

    const dialog = screen.getByRole("dialog", { name: "Confirm Orange?" });
    expect(within(dialog).getByText(copy.confirmDialog.permanentNotice)).toBeInTheDocument();
    // Five actions: three baseline and two tailored, all still ticked.
    expect(within(dialog).getByText("5 actions will be recorded.")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: copy.confirmDialog.submit }));

    expect(await screen.findByText("triage queue")).toBeInTheDocument();
    const body = decisionBody(mock);
    expect(body.type).toBe("CONFIRM");
    // FR-32: the point of confirming is that the recommendation's category stands.
    expect(body).not.toHaveProperty("final_category");
  });

  it("records the whole action list with what the reviewer did to it (FR-76)", async () => {
    const { mock } = renderCase(makeCaseDetail());

    const remove = await screen.findByRole("button", {
      name: `${copy.actions.removeLabel}: ${TAILORED_ACTIONS[0].text}`,
    });
    fireEvent.click(remove);

    fireEvent.click(screen.getByRole("button", { name: "Confirm Orange" }));
    fireEvent.click(screen.getByRole("button", { name: copy.confirmDialog.submit }));

    await screen.findByText("triage queue");
    const actions = decisionBody(mock).final_actions as { text: string; status: string }[];
    expect(actions).toHaveLength(5);
    expect(actions.filter((action) => action.status === "KEPT")).toHaveLength(4);
    expect(actions.find((action) => action.text === TAILORED_ACTIONS[0].text)?.status).toBe(
      "REMOVED",
    );
  });

  it("closes on Cancel without recording anything", async () => {
    const { mock } = renderCase(makeCaseDetail());

    fireEvent.click(await screen.findByRole("button", { name: "Confirm Orange" }));
    fireEvent.click(screen.getByRole("button", { name: copy.confirmDialog.cancel }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mock.mock.calls.every((call) => !String(call[0]).includes("/decision"))).toBe(true);
  });

  // A 409 is not a field to fix: the screen was out of date (FR-32, FR-48).
  it("explains a decision someone else already made, and stays put", async () => {
    stubFetch({
      "/decision": {
        status: 409,
        body: errorBody("INVALID_TRANSITION", "This case is no longer in that state."),
      },
      [`/cases/${CASE_ID}`]: { body: makeCaseDetail() },
    });

    renderWithAuth(
      <Routes>
        <Route path="/cases/:caseId" element={<CaseReview />} />
        <Route path="/queue" element={<p>triage queue</p>} />
      </Routes>,
      { route: `/cases/${CASE_ID}`, user: makeUser({ role: "VETERINARY_REVIEWER" }) },
    );

    fireEvent.click(await screen.findByRole("button", { name: "Confirm Orange" }));
    fireEvent.click(screen.getByRole("button", { name: copy.confirmDialog.submit }));

    await waitFor(() => expect(screen.getByRole("dialog")).toHaveTextContent(copy.errors.conflict));
    expect(screen.queryByText("triage queue")).not.toBeInTheDocument();
  });

  it("reports any other failure beside the button that caused it", async () => {
    stubFetch({
      "/decision": { status: 500, body: errorBody("INTERNAL_ERROR", "Something went wrong.") },
      [`/cases/${CASE_ID}`]: { body: makeCaseDetail() },
    });

    renderWithAuth(
      <Routes>
        <Route path="/cases/:caseId" element={<CaseReview />} />
        <Route path="/queue" element={<p>triage queue</p>} />
      </Routes>,
      { route: `/cases/${CASE_ID}`, user: makeUser({ role: "VETERINARY_REVIEWER" }) },
    );

    fireEvent.click(await screen.findByRole("button", { name: "Confirm Orange" }));
    fireEvent.click(screen.getByRole("button", { name: copy.confirmDialog.submit }));

    await waitFor(() =>
      expect(screen.getByRole("dialog")).toHaveTextContent(copy.errors.decisionFailed),
    );
  });
});

describe("CaseReview adjusting a decision (W-05)", () => {
  it("records the new category and the reason, then returns to the queue", async () => {
    const { mock } = renderCase(makeCaseDetail(), {
      decision: { ...confirmedCase().decision, type: "ADJUST", final_category: "RED" },
    });

    fireEvent.click(await screen.findByRole("button", { name: copy.decisionBar.adjust }));

    const dialog = screen.getByRole("dialog", { name: copy.adjustDialog.title });
    fireEvent.click(within(dialog).getByRole("radio", { name: /RED/i }));
    fireEvent.change(within(dialog).getByRole("combobox"), {
      target: { value: "CONDITION_DIFFERS_ON_ARRIVAL" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: copy.adjustDialog.submit }));

    expect(await screen.findByText("triage queue")).toBeInTheDocument();
    const body = decisionBody(mock);
    expect(body.type).toBe("ADJUST");
    expect(body.final_category).toBe("RED");
    expect(body.reason_code).toBe("CONDITION_DIFFERS_ON_ARRIVAL");
  });

  // FR-78: the checklist on screen was prepared for the recommended category, so
  // it is not what this decision accepts. The server reads the new category's
  // baseline live when the key is absent (`_accepted_actions`).
  it("sends no action list, so the server prepares the new category's own", async () => {
    const { mock } = renderCase(makeCaseDetail(), {
      decision: { ...confirmedCase().decision, type: "ADJUST", final_category: "RED" },
    });

    fireEvent.click(await screen.findByRole("button", { name: copy.decisionBar.adjust }));
    fireEvent.click(screen.getByRole("radio", { name: /RED/i }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "SIGN_NOT_CAPTURED" } });
    fireEvent.click(screen.getByRole("button", { name: copy.adjustDialog.submit }));

    await screen.findByText("triage queue");
    expect(decisionBody(mock)).not.toHaveProperty("final_actions");
  });

  // IR-05: the server's 422 belongs beside the control it names.
  it("puts a rejected reason back beside the reason dropdown", async () => {
    renderCase(makeCaseDetail(), {
      routes: {
        "/decision": {
          status: 422,
          body: errorBody(
            "VALIDATION_ERROR",
            "Choose a reason for the change from the list.",
            "reason_code",
          ),
        },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: copy.decisionBar.adjust }));
    const dialog = screen.getByRole("dialog", { name: copy.adjustDialog.title });
    fireEvent.click(within(dialog).getByRole("radio", { name: /RED/i }));
    fireEvent.change(within(dialog).getByRole("combobox"), { target: { value: "OTHER" } });
    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: { value: "Looked worse on arrival." },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: copy.adjustDialog.submit }));

    await waitFor(() =>
      expect(screen.getByRole("dialog")).toHaveTextContent(
        "Choose a reason for the change from the list.",
      ),
    );
    expect(screen.queryByText("triage queue")).not.toBeInTheDocument();
  });

  it("closes on Cancel without recording anything", async () => {
    const { mock } = renderCase(makeCaseDetail());

    fireEvent.click(await screen.findByRole("button", { name: copy.decisionBar.adjust }));
    fireEvent.click(screen.getByRole("button", { name: copy.adjustDialog.cancel }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mock.mock.calls.every((call) => !String(call[0]).includes("/decision"))).toBe(true);
  });
});

describe("CaseReview manual triage (W-06)", () => {
  // NFR-09: the case was never lost, and the banner says why and when.
  it("opens straight into the picker, with the failure reason and its time", async () => {
    renderCase(manualTriageCase());

    expect(
      await screen.findByRole("heading", { name: copy.manualTriage.title }),
    ).toBeInTheDocument();

    const banner = screen.getByText(copy.manualTriage.aiUnavailable, { exact: false });
    expect(banner).toHaveTextContent(FAILURE_MESSAGE);
    expect(banner).toHaveTextContent("09:20:41");
  });

  // IR-05: the code behind the sentence is never shown.
  it("never prints the reason code", async () => {
    renderCase(
      manualTriageCase({
        failure: {
          reason_code: "SOMETHING_NEW_IN_P08",
          message: "AI processing could not be completed for this case.",
          failed_at: "2026-10-01T01:20:41Z",
        },
      }),
    );

    expect(
      await screen.findByText("AI processing could not be completed", { exact: false }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/SOMETHING_NEW_IN_P08/)).not.toBeInTheDocument();
  });

  it("still says the case is safe when no failure was recorded", async () => {
    renderCase(manualTriageCase({ failure: null }));

    const banner = await screen.findByText(copy.manualTriage.aiUnavailable, { exact: false });
    expect(banner).toHaveTextContent(copy.manualTriage.safeToTriage);
  });

  // P07 §7.1, UC-08.
  it("posts a retry and re-reads the case", async () => {
    const { mock } = renderCase(manualTriageCase(), {
      routes: { "/retry": { status: 202, body: { id: CASE_ID, status: "SUBMITTED" } } },
    });

    const retry = await screen.findByRole("button", { name: copy.manualTriage.retry });
    expect(retry).toBeEnabled();
    fireEvent.click(retry);

    await waitFor(() => {
      const call = mock.mock.calls.find((entry) => String(entry[0]).includes("/retry"));
      expect(call?.[1]?.method).toBe("POST");
    });
    const reads = () =>
      mock.mock.calls.filter((entry) => String(entry[0]).endsWith(`/cases/${CASE_ID}`)).length;
    await waitFor(() => expect(reads()).toBeGreaterThan(1));
  });

  it("leaves Retry disabled when the server says it is not allowed", async () => {
    renderCase(
      manualTriageCase({
        permissions: {
          can_decide: true,
          can_regenerate: false,
          can_regenerate_actions: false,
          can_retry: false,
          can_close: false,
        },
      }),
    );

    expect(await screen.findByRole("button", { name: copy.manualTriage.retry })).toBeDisabled();
  });

  it("refreshes and explains when the retry is refused as out of date", async () => {
    renderCase(manualTriageCase(), {
      routes: {
        "/retry": {
          status: 409,
          body: errorBody("INVALID_TRANSITION", "This case is no longer in that state."),
        },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: copy.manualTriage.retry }));

    expect(await screen.findByText(copy.errors.retryConflict)).toBeInTheDocument();
  });

  it("shows a quiet error when the retry cannot be sent", async () => {
    renderCase(manualTriageCase(), { routes: { "/retry": { status: 500 } } });

    fireEvent.click(await screen.findByRole("button", { name: copy.manualTriage.retry }));

    expect(await screen.findByText(copy.errors.retryFailed)).toBeInTheDocument();
  });

  it("records the category and the note, then returns to the queue", async () => {
    const { mock } = renderCase(manualTriageCase(), {
      decision: {
        ...confirmedCase().decision,
        type: "MANUAL",
        final_category: "ORANGE",
        direction: "NONE",
        status: "MANUALLY_TRIAGED",
      },
    });

    await screen.findByRole("heading", { name: copy.manualTriage.title });
    fireEvent.click(screen.getByRole("radio", { name: /ORANGE/i }));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Fast breathing reported; assess on arrival." },
    });
    fireEvent.click(screen.getByRole("button", { name: copy.manualTriage.submit }));

    expect(await screen.findByText("triage queue")).toBeInTheDocument();
    const body = decisionBody(mock);
    expect(body.type).toBe("MANUAL");
    expect(body.final_category).toBe("ORANGE");
    expect(body.note).toBe("Fast breathing reported; assess on arrival.");
    // The baseline set belongs to the category being assigned, and the server
    // reads it (FR-72, ADR-18 §6).
    expect(body).not.toHaveProperty("final_actions");
  });

  // FR-34, ADR-15 §4: available at any time, not only after a failure.
  it("lets a reviewer choose manual triage on a case that has a recommendation", async () => {
    renderCase(makeCaseDetail());

    fireEvent.click(await screen.findByRole("button", { name: copy.decisionBar.manual }));

    expect(screen.getByRole("heading", { name: copy.manualTriage.title })).toBeInTheDocument();
    // "AI unavailable" would simply be untrue here.
    expect(screen.getByText(copy.manualTriage.byChoice)).toBeInTheDocument();
    expect(screen.queryByText(copy.manualTriage.aiUnavailable, { exact: false })).toBeNull();
  });

  it("goes back to the recommendation when the reviewer changes their mind", async () => {
    renderCase(makeCaseDetail());

    fireEvent.click(await screen.findByRole("button", { name: copy.decisionBar.manual }));
    fireEvent.click(screen.getByRole("button", { name: copy.manualTriage.cancel }));

    expect(screen.getByText(copy.recommendationTitle)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: copy.manualTriage.title })).toBeNull();
  });

  // IR-06's acceptance criterion names W-06 as well as W-04.
  it("keeps the decision-support disclaimer on screen in manual mode", async () => {
    renderCase(manualTriageCase());

    await screen.findByRole("heading", { name: copy.manualTriage.title });
    expect(screen.getByText(copy.decisionBar.disclaimer)).toBeInTheDocument();
  });

  // Neither Confirm nor Adjust means anything without a recommendation, and the
  // server refuses both from this status (`DECISION_FROM`).
  it("offers neither Confirm nor Adjust on a case with no recommendation", async () => {
    renderCase(manualTriageCase());

    await screen.findByRole("heading", { name: copy.manualTriage.title });
    expect(screen.getByRole("button", { name: /Confirm/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.decisionBar.adjust })).toBeDisabled();
  });
});

describe("CaseReview notes (FR-37)", () => {
  it("adds a note and shows it on the case without leaving the screen", async () => {
    const note = {
      id: "00000000-0000-4000-8000-0000000000n1",
      text: "Owner called back: the cat passed a small amount of urine.",
      author_name: "Reviewer Demo",
      created_at: "2026-10-01T02:10:00Z",
    };
    const { mock } = renderCase(makeCaseDetail({ notes: [note] }), {
      routes: { "/notes": { body: note } },
    });

    fireEvent.click(await screen.findByRole("button", { name: copy.decisionBar.addNote }));
    const dialog = screen.getByRole("dialog", { name: copy.noteDialog.title });
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: note.text } });
    fireEvent.click(within(dialog).getByRole("button", { name: copy.noteDialog.submit }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(postedBody(mock, "/notes")).toEqual({ text: note.text });
    // Still on the case: a note is not a decision.
    expect(screen.queryByText("triage queue")).not.toBeInTheDocument();
    expect(screen.getByText(note.text)).toBeInTheDocument();
    expect(screen.getByText(/Reviewer Demo/)).toBeInTheDocument();
  });

  it("will not save an empty note", async () => {
    renderCase(makeCaseDetail());

    fireEvent.click(await screen.findByRole("button", { name: copy.decisionBar.addNote }));

    expect(screen.getByRole("button", { name: copy.noteDialog.submit })).toBeDisabled();
  });

  // A note may be added at any status, a closed case included: the moment to
  // record an observation is when it is known (`ReviewService.add_note`).
  it("is available on a case that has already been decided", async () => {
    renderCase(confirmedCase());

    expect(await screen.findByRole("button", { name: copy.decisionBar.addNote })).toBeEnabled();
  });

  // A closed case is the one place `can_decide` is false for a reviewer, and a
  // note is not a decision — so the control survives the read-only bar.
  it("stays reachable for a reviewer on a closed case", async () => {
    renderCase({
      ...confirmedCase(),
      status: "CLOSED",
      permissions: {
        can_decide: false,
        can_regenerate: false,
        can_regenerate_actions: false,
        can_retry: false,
        can_close: false,
      },
    });

    expect(await screen.findByText(copy.decisionBar.readOnly)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.decisionBar.addNote })).toBeEnabled();
    // Still nothing that would decide the case.
    expect(screen.queryByRole("button", { name: /Confirm/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.decisionBar.adjust })).not.toBeInTheDocument();
  });
});

describe("CaseReview closing a case (FR-38)", () => {
  function closable(): CaseDetail {
    return {
      ...confirmedCase(),
      permissions: {
        can_decide: true,
        can_regenerate: false,
        can_regenerate_actions: false,
        can_retry: false,
        can_close: true,
      },
    };
  }

  // IR-08: closing cannot be undone, so it is asked about first.
  it("asks before closing, then closes and returns to the queue", async () => {
    const { mock } = renderCase(closable(), {
      routes: {
        "/close": {
          body: {
            id: CASE_ID,
            case_no: "C-0142",
            status: "CLOSED",
            closed_at: "2026-10-01T03:00:00Z",
          },
        },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: copy.decisionBar.close }));

    const dialog = screen.getByRole("dialog", { name: "Close case C-0142?" });
    expect(within(dialog).getByText(copy.closeDialog.permanentNotice)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: copy.closeDialog.submit }));

    expect(await screen.findByText("triage queue")).toBeInTheDocument();
    expect(mock.mock.calls.some((call) => String(call[0]).includes("/close"))).toBe(true);
  });

  it("closes the dialog on Cancel without closing the case", async () => {
    const { mock } = renderCase(closable());

    fireEvent.click(await screen.findByRole("button", { name: copy.decisionBar.close }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: copy.closeDialog.cancel }),
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mock.mock.calls.every((call) => !String(call[0]).includes("/close"))).toBe(true);
  });

  // A 409 here means someone else closed it: the screen was out of date.
  it("explains a case that was already closed, and stays put", async () => {
    renderCase(closable(), {
      routes: {
        "/close": {
          status: 409,
          body: errorBody("INVALID_TRANSITION", "This case is already closed."),
        },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: copy.decisionBar.close }));

    const dialog = screen.getByRole("dialog", { name: "Close case C-0142?" });
    fireEvent.click(within(dialog).getByRole("button", { name: copy.closeDialog.submit }));

    await waitFor(() =>
      expect(screen.getByRole("dialog")).toHaveTextContent(copy.errors.closeConflict),
    );
    expect(screen.queryByText("triage queue")).not.toBeInTheDocument();
  });
});

// BR-01, BR-02: the clinical core. Nobody but a Veterinary Reviewer gets any of
// these controls, whatever else the screen shows them.
describe("CaseReview decision controls and role", () => {
  for (const role of ["INTAKE_STAFF", "ADMINISTRATOR"] as const) {
    it(`offers no decision, note or close control to ${role}`, async () => {
      renderCase(
        manualTriageCase({
          permissions: {
            can_decide: false,
            can_regenerate: false,
            can_regenerate_actions: false,
            can_retry: false,
            can_close: false,
          },
        }),
        { role },
      );

      expect(await screen.findByText(copy.decisionBar.readOnly)).toBeInTheDocument();
      for (const label of [
        copy.decisionBar.adjust,
        copy.decisionBar.manual,
        copy.decisionBar.addNote,
        copy.decisionBar.close,
      ]) {
        expect(screen.queryByRole("button", { name: label })).not.toBeInTheDocument();
      }
      // And no way to assign a category by hand either.
      expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    });
  }
});

describe("CaseReview loading and failure", () => {
  it("says a case it cannot find is missing, not broken", async () => {
    stubFetch({
      [`/cases/${CASE_ID}`]: { status: 404, body: errorBody("NOT_FOUND", "No such case.") },
    });

    renderWithAuth(<Routes>{<Route path="/cases/:caseId" element={<CaseReview />} />}</Routes>, {
      route: `/cases/${CASE_ID}`,
      user: makeUser({ role: "VETERINARY_REVIEWER" }),
    });

    expect(await screen.findByText(copy.errors.notFound)).toBeInTheDocument();
  });
});

describe("CaseReview while a run is in progress (IR-22)", () => {
  it("names the stage the pipeline has reached", async () => {
    renderCase(manualTriageCase({ status: "SUBMITTED", failure: null }), {
      routes: {
        "/status": {
          body: {
            status: "PROCESSING",
            category: null,
            has_red_flag: false,
            pipeline_stage: "extract",
            actions_status: null,
            updated_at: "2026-10-01T01:21:00Z",
          },
        },
      },
    });

    expect(await screen.findByText(copy.processing.title)).toBeInTheDocument();
    expect(await screen.findByText(copy.processing.stages.extract)).toBeInTheDocument();
  });

  it("re-reads the case as soon as the status settles", async () => {
    const { mock } = renderCase(manualTriageCase({ status: "SUBMITTED", failure: null }), {
      routes: {
        "/status": {
          body: {
            status: "AWAITING_REVIEW",
            category: "ORANGE",
            has_red_flag: true,
            pipeline_stage: "done",
            actions_status: "PENDING",
            updated_at: "2026-10-01T01:21:00Z",
          },
        },
      },
    });

    await screen.findByText(copy.processing.title);
    const reads = () =>
      mock.mock.calls.filter((entry) => String(entry[0]).endsWith(`/cases/${CASE_ID}`)).length;
    await waitFor(() => expect(reads()).toBeGreaterThan(1));
  });

  it("shows no progress banner on a case that is not running", async () => {
    renderCase(makeCaseDetail());

    await screen.findByText("C-0142", { exact: false });
    expect(screen.queryByText(copy.processing.title)).not.toBeInTheDocument();
  });
});

// FR-78, P07 §7.2b: a decision on another category swaps the baseline set at once
// and leaves the tailored rows on screen, greyed, until new ones are asked for.
describe("CaseReview actions after the category changed", () => {
  const RED_BASELINE = [
    "Alert the veterinarian now.",
    "Prepare the treatment area for immediate assessment.",
  ];

  function adjustedToRed(overrides: Partial<CaseDetail["actions"]> = {}): CaseDetail {
    const base = confirmedCase();
    return makeCaseDetail({
      status: "ADJUSTED",
      category: "RED",
      confirmed_category: "RED",
      decision: { ...base.decision!, type: "ADJUST", final_category: "RED", status: "ADJUSTED" },
      permissions: {
        can_decide: true,
        can_regenerate: false,
        can_regenerate_actions: true,
        can_retry: false,
        can_close: true,
      },
      actions: {
        status: "READY",
        generated_for_category: "ORANGE",
        baseline: RED_BASELINE,
        tailored: TAILORED_ACTIONS.map((action) => ({ ...action, is_outdated: true })),
        rejected_count: 0,
        is_outdated: true,
        failure_message: null,
        ...overrides,
      },
    });
  }

  const regenerateButton = () =>
    screen.queryByRole("button", { name: new RegExp(copy.actions.regenerate, "i") });

  it("shows the new category's baseline and greys the old suggestions with a note", async () => {
    renderCase(adjustedToRed());

    await screen.findByText(RED_BASELINE[0], { exact: false });
    const note = copy.actions.outdatedNote.replace("{category}", strings.vtl.names.ORANGE);
    expect(screen.getByText(note)).toBeInTheDocument();
    for (const action of TAILORED_ACTIONS) {
      const row = screen.getByText(action.text, { exact: false }).closest("[data-outdated]");
      expect(row).not.toBeNull();
    }
  });

  it("gives the outdated rows no checkbox, so they cannot be kept", async () => {
    renderCase(adjustedToRed());

    await screen.findByText(RED_BASELINE[0], { exact: false });
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
  });

  it("asks the server for new suggestions and refreshes", async () => {
    const { mock } = renderCase(adjustedToRed(), {
      routes: {
        "/actions/regenerate": {
          status: 202,
          body: {
            id: CASE_ID,
            case_no: "C-0142",
            category: "RED",
            generation: 2,
            actions_status: "PENDING",
          },
        },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: /Regenerate suggestions/i }));

    await waitFor(() => {
      const post = mock.mock.calls.find((entry) =>
        String(entry[0]).endsWith(`/cases/${CASE_ID}/actions/regenerate`),
      );
      expect(post?.[1]?.method).toBe("POST");
    });
  });

  it("offers the button only when the server says it is allowed", async () => {
    const detail = adjustedToRed();
    renderCase({
      ...detail,
      permissions: { ...detail.permissions, can_regenerate_actions: false },
    });

    await screen.findByText(RED_BASELINE[0], { exact: false });
    expect(regenerateButton()).not.toBeInTheDocument();
  });

  it("offers no button on a current, healthy list", async () => {
    renderCase(
      makeCaseDetail({
        permissions: { ...makeCaseDetail().permissions, can_regenerate_actions: true },
      }),
    );

    await screen.findByText(copy.actions.title);
    expect(regenerateButton()).not.toBeInTheDocument();
  });

  it("shows the server's wording for a failed job and offers another try", async () => {
    const message =
      "The language model did not respond with suggested actions (09:20:41). " +
      "The baseline actions are shown; the category and your decision are unchanged.";
    renderCase(adjustedToRed({ status: "FAILED", failure_message: message }));

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(regenerateButton()).toBeInTheDocument();
  });

  it("falls back to the generic line when a failed job has no message", async () => {
    renderCase(adjustedToRed({ status: "FAILED", failure_message: null }));

    expect(await screen.findByText(copy.actions.failed)).toBeInTheDocument();
  });

  it("says so, and refreshes, when the server refuses with a conflict", async () => {
    renderCase(adjustedToRed(), {
      routes: {
        "/actions/regenerate": {
          status: 409,
          body: errorBody("INVALID_TRANSITION", "Suggested actions are already being prepared."),
        },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: /Regenerate suggestions/i }));

    expect(await screen.findByText(copy.errors.regenerateActionsConflict)).toBeInTheDocument();
  });

  it("shows the preparing line, and no button, while the new set is pending", async () => {
    renderCase(
      (() => {
        const detail = adjustedToRed({ status: "PENDING" });
        return {
          ...detail,
          permissions: { ...detail.permissions, can_regenerate_actions: false },
        };
      })(),
    );

    expect(await screen.findByText(copy.actions.pending)).toBeInTheDocument();
    expect(regenerateButton()).not.toBeInTheDocument();
  });
});
