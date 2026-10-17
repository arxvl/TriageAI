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
  { text: "Ask the owner when the cat last passed any urine.", cited_ranks: [1], source: "AI" },
  {
    text: "Check for a firm, painful bladder when the veterinarian examines.",
    cited_ranks: [1],
    source: "AI",
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
    permissions: { can_decide: true, can_regenerate: false, can_close: false },

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

function renderCase(
  detail: CaseDetail,
  options: {
    role?: "INTAKE_STAFF" | "VETERINARY_REVIEWER" | "ADMINISTRATOR";
    decision?: unknown;
  } = {},
) {
  // `/decision` first: `stubFetch` matches on the first key the URL contains.
  const mock = stubFetch({
    "/decision": { body: options.decision ?? confirmedCase().decision },
    [`/cases/${CASE_ID}`]: { body: detail },
  });

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

  // Correcting a value and regenerating from it is P07.
  it("offers 'Save and regenerate' disabled, with the P07 tooltip", async () => {
    renderCase(makeCaseDetail());

    const button = await screen.findByRole("button", { name: copy.saveAndRegenerate });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", copy.availableInP07);
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

  it("reads a missing recommendation as a case to triage by hand, not an error", async () => {
    renderCase(
      makeCaseDetail({
        status: "MANUAL_TRIAGE_REQUIRED",
        category: null,
        recommended_category: null,
        recommendation: null,
        references: [],
        configuration: null,
      }),
    );

    expect(await screen.findByText(copy.recommendationUnavailable)).toBeInTheDocument();
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
        permissions: { can_decide: false, can_regenerate: false, can_close: false },
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
  it("offers the five controls, with only Confirm wired in this subphase", async () => {
    renderCase(makeCaseDetail());

    expect(await screen.findByRole("button", { name: "Confirm Orange" })).toBeEnabled();
    for (const label of [
      copy.decisionBar.adjust,
      copy.decisionBar.manual,
      copy.decisionBar.addNote,
      copy.decisionBar.viewAudit,
    ]) {
      const button = screen.getByRole("button", { name: label });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("title", copy.availableNextStep);
    }
  });

  it("always shows the decision-support disclaimer (IR-06, BR-10)", async () => {
    renderCase(makeCaseDetail());

    expect(await screen.findByText(copy.decisionBar.disclaimer)).toBeInTheDocument();
  });

  // BR-01, BR-02: Intake Staff and administrators may read a case, never decide one.
  it("hides the decision buttons and says the case is read-only for Intake Staff", async () => {
    renderCase(
      makeCaseDetail({
        permissions: { can_decide: false, can_regenerate: false, can_close: false },
      }),
      { role: "INTAKE_STAFF" },
    );

    expect(await screen.findByText(copy.decisionBar.readOnly)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Confirm/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.decisionBar.adjust })).not.toBeInTheDocument();
    // The disclaimer stays: the category on screen is still not a diagnosis.
    expect(screen.getByText(copy.decisionBar.disclaimer)).toBeInTheDocument();
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
