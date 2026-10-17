/**
 * W-04 Case Review, where a reviewer decides (FR-13, FR-31, FR-32, FR-36,
 * FR-71..FR-79, IR-03, IR-04, IR-06, IR-08 · UC-05).
 *
 * Four things shape this screen more than its layout does:
 *
 * 1. **The panel order is the safety argument.** Owner's description, then the
 *    extraction, then the recommendation (ADR-15). The reviewer meets the
 *    evidence before the conclusion, which is the structural defence against
 *    automation bias — so the three are never reordered, and the response that
 *    feeds them lists them in the same order for the same reason.
 * 2. **Nothing reads as settled until a human says so.** While the case is
 *    `AWAITING_REVIEW` the header carries the IR-04 sentence verbatim, and the
 *    model's own suggestions stay marked as needing approval (FR-75). Once a
 *    decision exists the chip becomes a `StatusChip` and the caveats go.
 * 3. **The server decides who may decide.** `permissions.can_decide` is used to
 *    hide controls, never to allow them; `require_role` and `ReviewService`
 *    refuse the request whatever this screen shows (SR-05, BR-02).
 * 4. **Waiting time is read, not computed.** It comes from the response, like
 *    the queue's, so one clock measures every case (FR-30). "Live" is therefore
 *    a 30-second refetch rather than a local timer — which also picks up the
 *    suggested actions finishing.
 *
 * This subphase wires one decision, CONFIRM. Adjust (W-05), manual triage
 * (W-06), notes and close are the next subphase, and the audit timeline (W-07)
 * the one after; their four controls are on the bar, disabled, so the bar's
 * layout and tab order do not change under the user when they arrive.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  CASE_PENDING_POLL_INTERVAL_MS,
  CASE_POLL_INTERVAL_MS,
  readCase,
  recordDecision,
  type CaseAlert,
  type CaseDetail,
  type CaseStatus,
  type VTLCategory,
} from "../../api/cases";
import { ApiErrorCode, isApiError } from "../../api/errors";
import { RedFlagBanner, type QueueRedFlagAlert } from "../../components/RedFlagBanner";
import { StatusChip } from "../../components/StatusChip";
import { useToast } from "../../hooks/useToast";
import { strings } from "../../i18n/strings";
import {
  addedRow,
  initialChecklist,
  keptCount,
  toFinalActions,
  type ChecklistRow,
} from "../../lib/actionChecklist";
import { formatArrivalTime, formatDisplayTime } from "../../lib/datetime";
import { isOverdueForDisplay } from "../../lib/vtl";
import { ActionChecklist } from "./ActionChecklist";
import styles from "./CaseReview.module.css";
import { ConfirmDialog } from "./ConfirmDialog";
import { DescriptionPanel } from "./DescriptionPanel";
import { ExtractionPanel } from "./ExtractionPanel";
import { RecommendationPanel } from "./RecommendationPanel";

const copy = strings.caseReview;

/** The statuses a reviewer has already decided on (CLAUDE.md §6). */
const DECIDED_STATUSES: readonly CaseStatus[] = [
  "CONFIRMED",
  "ADJUSTED",
  "MANUALLY_TRIAGED",
  "CLOSED",
];

export function CaseReview() {
  const { caseId = "" } = useParams<{ caseId: string }>();

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["cases", "detail", caseId],
    queryFn: () => readCase(caseId),
    refetchInterval: (query) => pollInterval(query.state.data),
    // IR-22, as on the queue: a backgrounded tab stops asking. The default,
    // written out because the requirement rests on it.
    refetchIntervalInBackground: false,
  });

  if (isPending) {
    return <p className={styles.notice}>{copy.loading}</p>;
  }

  if (data === undefined) {
    return (
      <p className={styles.error} role="alert">
        {loadErrorText(error)}
      </p>
    );
  }

  // Keyed on the case so moving between two cases rebuilds the checklist rather
  // than carrying one case's edits into another.
  return <CaseReviewScreen key={data.id} detail={data} onStale={() => void refetch()} />;
}

/**
 * How soon to re-read the case.
 *
 * Thirty seconds is what W-04's live waiting time asks for. A case still in the
 * pipeline, or whose suggested actions have not arrived, is expected to change
 * within seconds and shows a loading row until it does; a closed case is not
 * expected to change at all.
 */
function pollInterval(detail: CaseDetail | undefined): number | false {
  if (detail === undefined) {
    return CASE_POLL_INTERVAL_MS;
  }
  if (detail.status === "CLOSED") {
    return false;
  }
  if (
    detail.status === "SUBMITTED" ||
    detail.status === "PROCESSING" ||
    detail.actions.status === "PENDING"
  ) {
    return CASE_PENDING_POLL_INTERVAL_MS;
  }
  return CASE_POLL_INTERVAL_MS;
}

function loadErrorText(error: unknown): string {
  if (isApiError(error)) {
    if (error.code === ApiErrorCode.notFound) {
      return copy.errors.notFound;
    }
    if (error.code === ApiErrorCode.forbidden) {
      return copy.errors.forbidden;
    }
  }
  return copy.errors.unexpected;
}

function CaseReviewScreen({ detail, onStale }: { detail: CaseDetail; onStale: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { showToast } = useToast();

  const isDecided = DECIDED_STATUSES.includes(detail.status);
  // FR-79: the checklist is editable only for a reviewer, and only while the
  // list is still theirs to finalize.
  const isChecklistEditable = detail.permissions.can_decide && !isDecided;

  const [rows, setRows] = useChecklist(detail.actions);
  const [isConfirming, setIsConfirming] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  const decision = useMutation({
    mutationFn: () =>
      recordDecision(detail.id, {
        type: "CONFIRM",
        // Omitted on purpose: the point of confirming is that the
        // recommendation's category stands, and the server takes it from there.
        final_actions: toFinalActions(rows),
      }),
    onSuccess: (recorded) => {
      void queryClient.invalidateQueries({ queryKey: ["cases"] });
      showToast(
        copy.confirmedToast
          .replace("{caseNo}", detail.case_no)
          .replace("{category}", strings.vtl.names[recorded.final_category]),
      );
      void navigate("/queue");
    },
    onError: (error: unknown) => {
      if (
        isApiError(error) &&
        (error.code === ApiErrorCode.invalidTransition ||
          error.code === ApiErrorCode.amendmentRequired)
      ) {
        // Not a failure to report as one: the case moved on. Re-read it, and
        // leave the dialog open with the explanation.
        onStale();
        setDecisionError(copy.errors.conflict);
        return;
      }
      setDecisionError(copy.errors.decisionFailed);
    },
  });

  function toggleRow(key: string) {
    setRows((previous) =>
      previous.map((row) => (row.key === key ? { ...row, isKept: !row.isKept } : row)),
    );
  }

  function editRow(key: string, text: string) {
    setRows((previous) => previous.map((row) => (row.key === key ? { ...row, text } : row)));
  }

  function addRow(text: string) {
    setRows((previous) => [...previous, addedRow(`added-${previous.length}`, text)]);
  }

  return (
    <div className={styles.page}>
      <Header detail={detail} isDecided={isDecided} />

      {/* The deterministic pre-screen's own finding, by rule label only (DR-04). */}
      <RedFlagBanner alerts={detail.alerts.map(toBannerAlert)} />

      <div className={styles.panels}>
        <DescriptionPanel description={detail.description} extraction={detail.extraction} />
        <ExtractionPanel extraction={detail.extraction} />
        <RecommendationPanel
          recommendation={detail.recommendation}
          references={detail.references}
          configuration={detail.configuration}
        >
          <ActionChecklist
            rows={rows}
            status={detail.actions.status}
            category={detail.actions.generated_for_category ?? detail.category}
            rejectedCount={detail.actions.rejected_count}
            isEditable={isChecklistEditable}
            onToggle={toggleRow}
            onEdit={editRow}
            onAdd={addRow}
          />
        </RecommendationPanel>
      </div>

      <DecisionBar
        detail={detail}
        isDecided={isDecided}
        onConfirm={() => {
          setDecisionError(null);
          setIsConfirming(true);
        }}
      />

      {isConfirming && detail.recommendation !== null && (
        <ConfirmDialog
          category={detail.recommendation.category}
          actionCount={keptCount(rows)}
          isSaving={decision.isPending}
          error={decisionError}
          onConfirm={() => decision.mutate()}
          onClose={() => {
            setIsConfirming(false);
            setDecisionError(null);
          }}
        />
      )}
    </div>
  );
}

/**
 * The action checklist's state, rebuilt when the actions themselves change.
 *
 * The suggested actions arrive *after* the category: the actions job runs
 * separately so it never delays triage (ADR-18 §3), and the screen polls until
 * it lands. So the checklist has to be rebuilt when the list it was built from
 * changes — and only then, because rebuilding on every poll would discard a
 * reviewer's ticks and edits every thirty seconds.
 *
 * The reset happens during render, not in an effect: this is React's own
 * "adjusting state when a prop changes" pattern, and it avoids the extra commit
 * — and the flash of a stale checklist — that an effect would cause.
 */
function useChecklist(
  actions: CaseDetail["actions"],
): [ChecklistRow[], (update: (previous: ChecklistRow[]) => ChecklistRow[]) => void] {
  const signature = [
    actions.status,
    actions.generated_for_category,
    actions.baseline.join("|"),
    actions.tailored.map((action) => action.text).join("|"),
  ].join("::");

  const [state, setState] = useState(() => ({
    signature,
    rows: initialChecklist(actions.baseline, actions.tailored),
  }));

  let rows = state.rows;
  if (state.signature !== signature) {
    rows = initialChecklist(actions.baseline, actions.tailored);
    setState({ signature, rows });
  }

  function update(updater: (previous: ChecklistRow[]) => ChecklistRow[]) {
    setState((previous) => ({ ...previous, rows: updater(previous.rows) }));
  }

  return [rows, update];
}

/**
 * The W-04 header: who the patient is, how long they have waited, and whether
 * anyone has accepted the category yet.
 */
function Header({ detail, isDecided }: { detail: CaseDetail; isDecided: boolean }) {
  return (
    <div className={styles.header}>
      <div>
        <Link className={styles.back} to="/queue">
          {copy.backToQueue}
        </Link>
        <h1 className={styles.title}>{patientLine(detail)}</h1>
        <p className={styles.subtitle}>
          {arrivalLine(detail)} · <Waiting detail={detail} />
        </p>
      </div>

      {/* IR-04, word for word, until a reviewer decides. */}
      {isDecided ? (
        <StatusChip
          status={detail.status}
          recommendedCategory={detail.recommended_category}
          confirmedCategory={detail.confirmed_category}
        />
      ) : (
        <span className={styles.aiChip}>{copy.aiPendingChip}</span>
      )}
    </div>
  );
}

/** "waiting 6 min of 15 min", from the server's clock (FR-30). */
function Waiting({ detail }: { detail: CaseDetail }) {
  const { header } = detail;
  const overdue = isOverdueForDisplay(detail.category, header.is_overdue);

  const text =
    header.target_minutes === null
      ? copy.waitingNoTarget.replace("{waiting}", String(header.waiting_minutes))
      : copy.waiting
          .replace("{waiting}", String(header.waiting_minutes))
          .replace("{target}", String(header.target_minutes));

  if (header.closed_at !== null) {
    return (
      <span className={styles.waiting}>
        {copy.closedAt.replace("{time}", formatDisplayTime(header.closed_at) ?? "")}
      </span>
    );
  }

  return (
    <b className={overdue ? `${styles.waiting} ${styles.overdueText}` : styles.waiting}>
      {text}
      {overdue && ` · ${copy.overdueSuffix}`}
    </b>
  );
}

/** "C-0142 · Cat · Mingming · 3 y · Male, intact", with whatever parts exist. */
function patientLine(detail: CaseDetail): string {
  const { header } = detail;
  const parts: string[] = [header.case_no, strings.queue.species[header.species]];

  if (header.pet_name !== null) {
    parts.push(header.pet_name);
  }
  if (header.age_value !== null && header.age_unit !== null) {
    const template = header.age_unit === "YEARS" ? strings.queue.ageYears : strings.queue.ageMonths;
    parts.push(template.replace("{value}", String(header.age_value)));
  }

  const sex = sexLine(header.sex, header.neutered);
  if (sex !== null) {
    parts.push(sex);
  }
  if (header.breed !== null) {
    parts.push(header.breed);
  }

  return parts.join(" · ");
}

/**
 * "Male, intact", the one W-03 control read back out.
 *
 * `sex` and `neutered` are two API fields and one fact to a reviewer, so they
 * are rejoined here using the intake form's own wording. An unknown sex says
 * only that, whatever `neutered` holds: "Unknown, neutered" would be a claim
 * about an animal nobody has examined.
 */
function sexLine(sex: CaseDetail["header"]["sex"], neutered: boolean | null): string | null {
  const options = strings.caseIntake.sexOptions;

  if (sex === "UNKNOWN") {
    return options.UNKNOWN;
  }
  if (neutered === null) {
    return sex === "MALE" ? "Male" : "Female";
  }
  if (sex === "MALE") {
    return neutered ? options.MALE_NEUTERED : options.MALE_INTACT;
  }
  return neutered ? options.FEMALE_SPAYED : options.FEMALE_INTACT;
}

/** "Arrived 09:36 by phone · recorded by J. Cruz". */
function arrivalLine(detail: CaseDetail): string {
  const { header } = detail;
  const time = formatArrivalTime(header.created_at) ?? strings.queue.notAvailable;
  const channel = strings.caseIntake.intakeChannels[header.intake_channel].toLowerCase();

  const template = header.created_by_name === null ? copy.arrivedByUnknown : copy.arrivedBy;

  return template
    .replace("{time}", time)
    .replace("{channel}", channel)
    .replace("{name}", header.created_by_name ?? "");
}

/**
 * One case alert as the banner's own shape.
 *
 * No `caseId`: the reviewer is already on the case, so a link to it would lead
 * nowhere. The sentence names the rule's label and nothing else — the words the
 * rule matched are a substring of the owner's description (DR-04).
 */
function toBannerAlert(alert: CaseAlert): QueueRedFlagAlert {
  const label = alert.rule_label;

  return {
    message:
      label === null || label === ""
        ? copy.redFlagDetectedUnlabelled
        : copy.redFlagDetected.replace("{rule}", label),
  };
}

/**
 * The fixed decision bar (FR-32, FR-34, FR-37, IR-06, BR-10).
 *
 * `can_decide` stays true on a case that is already decided, because FR-48
 * allows an amendment — but an amendment is not a confirmation, and this
 * subphase has no screen for one. So Confirm is offered while the case is
 * `AWAITING_REVIEW` and the decision already taken is shown in its place
 * afterwards.
 */
function DecisionBar({
  detail,
  isDecided,
  onConfirm,
}: {
  detail: CaseDetail;
  isDecided: boolean;
  onConfirm: () => void;
}) {
  const bar = copy.decisionBar;

  if (!detail.permissions.can_decide) {
    return (
      <div className={styles.decisionBar}>
        <p className={styles.readOnlyNotice}>{bar.readOnly}</p>
        <p className={styles.disclaimer}>{bar.disclaimer}</p>
      </div>
    );
  }

  const category: VTLCategory | null = detail.recommendation?.category ?? null;
  const canConfirm = detail.status === "AWAITING_REVIEW" && category !== null;

  return (
    <div className={styles.decisionBar}>
      {isDecided && detail.decision !== null ? (
        <p className={styles.decided}>
          <b>{bar.decided}</b> {decidedLine(detail)}
        </p>
      ) : (
        <button
          type="button"
          className={`${styles.button} ${styles.buttonPrimary}`}
          disabled={!canConfirm}
          onClick={onConfirm}
        >
          {bar.confirm.replace(
            "{category}",
            category === null ? strings.queue.notAvailable : strings.vtl.names[category],
          )}
        </button>
      )}

      {/* The next subphase wires these four; they are here now so the bar's
          layout and tab order do not change when they start working. */}
      <button type="button" className={styles.button} disabled title={copy.availableNextStep}>
        {bar.adjust}
      </button>
      <button type="button" className={styles.button} disabled title={copy.availableNextStep}>
        {bar.manual}
      </button>
      <button type="button" className={styles.button} disabled title={copy.availableNextStep}>
        {bar.addNote}
      </button>
      <button type="button" className={styles.button} disabled title={copy.availableNextStep}>
        {bar.viewAudit}
      </button>

      <p className={styles.disclaimer}>{bar.disclaimer}</p>
    </div>
  );
}

/** "Red · Reviewer Demo · 9:58 AM", the decision already on the case (FR-36). */
function decidedLine(detail: CaseDetail): string {
  const bar = copy.decisionBar;
  const decision = detail.decision;
  if (decision === null) {
    return "";
  }

  const category = strings.vtl.names[decision.final_category];
  const time = formatDisplayTime(decision.decided_at) ?? "";
  const template = decision.decided_by_name === null ? bar.decidedByUnknown : bar.decidedBy;

  return template
    .replace("{category}", category)
    .replace("{name}", decision.decided_by_name ?? "")
    .replace("{time}", time);
}
