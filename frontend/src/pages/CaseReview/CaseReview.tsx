/**
 * W-04 Case Review, where a reviewer decides (FR-13, FR-31..FR-38, FR-48,
 * FR-71..FR-79, IR-03, IR-04, IR-06, IR-08 · UC-05..UC-08).
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
 * 3. **The server decides who may decide.** `permissions.can_decide` and
 *    `can_close` are used to hide controls, never to allow them; `require_role`
 *    and `ReviewService` refuse the request whatever this screen shows (SR-05,
 *    BR-02).
 * 4. **Waiting time is read, not computed.** It comes from the response, like
 *    the queue's, so one clock measures every case (FR-30). "Live" is therefore
 *    a 30-second refetch rather than a local timer — which also picks up the
 *    suggested actions finishing.
 *
 * The screen has **two modes**, not two routes. In the usual one, panel 3 is the
 * recommendation. In manual-triage mode it is `ManualTriagePanel` instead, which
 * is how W-06 is drawn: the reviewer chooses the category while still reading the
 * owner's description beside it. Manual mode is on when the pipeline gave up
 * (`MANUAL_TRIAGE_REQUIRED`) or when a reviewer asks for it — FR-34 and ADR-15 §4
 * both require the second, and the banner says which of the two it is.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  CASE_PENDING_POLL_INTERVAL_MS,
  CASE_POLL_INTERVAL_MS,
  addCaseNote,
  closeCase,
  readCase,
  recordDecision,
  type CaseAlert,
  type CaseDetail,
  type CaseStatus,
  type DecisionRequest,
  type VTLCategory,
} from "../../api/cases";
import { ApiErrorCode, isApiError } from "../../api/errors";
import { RedFlagBanner, type QueueRedFlagAlert } from "../../components/RedFlagBanner";
import { StatusChip } from "../../components/StatusChip";
import { useAuth } from "../../hooks/useAuth";
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
import { AdjustDialog } from "./AdjustDialog";
import styles from "./CaseReview.module.css";
import { CloseDialog } from "./CloseDialog";
import { ConfirmDialog } from "./ConfirmDialog";
import { DescriptionPanel } from "./DescriptionPanel";
import { ExtractionPanel } from "./ExtractionPanel";
import { ManualTriagePanel } from "./ManualTriagePanel";
import { NoteDialog } from "./NoteDialog";
import { RecommendationPanel } from "./RecommendationPanel";

const copy = strings.caseReview;

/** The statuses a reviewer has already decided on (CLAUDE.md §6). */
const DECIDED_STATUSES: readonly CaseStatus[] = [
  "CONFIRMED",
  "ADJUSTED",
  "MANUALLY_TRIAGED",
  "CLOSED",
];

/** Which of the four dialogs is open; only ever one at a time. */
type OpenDialog = "confirm" | "adjust" | "note" | "close" | null;

/** A 422's message and the control the server named for it (IR-05). */
interface FieldError {
  field: string;
  message: string;
}

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
  const { user } = useAuth();

  const isReviewer = user?.role === "VETERINARY_REVIEWER";

  const isDecided = DECIDED_STATUSES.includes(detail.status);
  // FR-79: the checklist is editable only for a reviewer, and only while the
  // list is still theirs to finalize.
  const isChecklistEditable = detail.permissions.can_decide && !isDecided;

  const [rows, setRows] = useChecklist(detail.actions);
  const [openDialog, setOpenDialog] = useState<OpenDialog>(null);
  const [isManualChosen, setIsManualChosen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<FieldError | null>(null);

  // The picker replaces panel 3 only for someone who can actually use it. A case
  // the pipeline gave up on still opens read-only for intake staff and
  // administrators, where `RecommendationPanel` says so in words (BR-02).
  const isManualMode =
    detail.permissions.can_decide &&
    !isDecided &&
    (detail.status === "MANUAL_TRIAGE_REQUIRED" || isManualChosen);

  function clearErrors() {
    setActionError(null);
    setFieldError(null);
  }

  /**
   * What went wrong with a decision, and whether it is worth calling an error.
   *
   * A 409 is not: the case moved on while this screen was reading it, so the
   * answer is to re-read rather than to re-send (FR-32, FR-48). A 422 names the
   * control it is about, and belongs beside it (IR-05).
   */
  function handleDecisionError(error: unknown) {
    clearErrors();
    if (isApiError(error)) {
      if (
        error.code === ApiErrorCode.invalidTransition ||
        error.code === ApiErrorCode.amendmentRequired
      ) {
        onStale();
        setActionError(copy.errors.conflict);
        return;
      }
      if (error.code === ApiErrorCode.validationError && error.field !== null) {
        setFieldError({ field: error.field, message: error.message });
        return;
      }
    }
    setActionError(copy.errors.decisionFailed);
  }

  // One mutation for all three decision types: they are one endpoint, one
  // transition check and one audit entry, and splitting them here would invite
  // three different answers to the same 409.
  const decision = useMutation({
    mutationFn: (payload: DecisionRequest) => recordDecision(detail.id, payload),
    onSuccess: (recorded) => {
      void queryClient.invalidateQueries({ queryKey: ["cases"] });
      showToast(decisionToast(detail, recorded.type, recorded.final_category));
      void navigate("/queue");
    },
    onError: handleDecisionError,
  });

  // A note is the one action that does not end the review: the reviewer writes
  // down what they saw and carries on reading the case (FR-37).
  const note = useMutation({
    mutationFn: (text: string) => addCaseNote(detail.id, text),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["cases"] });
      showToast(copy.noteAddedToast);
      setOpenDialog(null);
      clearErrors();
    },
    onError: () => setActionError(copy.errors.noteFailed),
  });

  const close = useMutation({
    mutationFn: () => closeCase(detail.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["cases"] });
      showToast(copy.closedToast.replace("{caseNo}", detail.case_no));
      void navigate("/queue");
    },
    onError: (error: unknown) => {
      clearErrors();
      if (isApiError(error) && error.code === ApiErrorCode.invalidTransition) {
        onStale();
        setActionError(copy.errors.closeConflict);
        return;
      }
      setActionError(copy.errors.closeFailed);
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

  function openDialogWith(which: OpenDialog) {
    clearErrors();
    setOpenDialog(which);
  }

  return (
    <div className={styles.page}>
      <Header detail={detail} isDecided={isDecided} />

      {/* The deterministic pre-screen's own finding, by rule label only (DR-04). */}
      <RedFlagBanner alerts={detail.alerts.map(toBannerAlert)} />

      {isManualMode && <ManualTriageBanner detail={detail} isByChoice={isManualChosen} />}

      <div className={styles.panels}>
        <DescriptionPanel description={detail.description} extraction={detail.extraction} />
        <ExtractionPanel extraction={detail.extraction} />

        {isManualMode ? (
          <ManualTriagePanel
            isSaving={decision.isPending}
            error={actionError}
            fieldError={fieldError}
            onSubmit={(values) => {
              clearErrors();
              decision.mutate({
                type: "MANUAL",
                final_category: values.final_category,
                note: values.note,
                // `final_actions` omitted on purpose — see ManualTriagePanel.
              });
            }}
            // Nothing to go back to on a case the pipeline gave up on.
            onCancel={
              detail.status === "MANUAL_TRIAGE_REQUIRED"
                ? null
                : () => {
                    clearErrors();
                    setIsManualChosen(false);
                  }
            }
          />
        ) : (
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
        )}
      </div>

      <NotesPanel notes={detail.notes} />

      <DecisionBar
        detail={detail}
        isDecided={isDecided}
        isManualMode={isManualMode}
        isReviewer={isReviewer}
        onConfirm={() => openDialogWith("confirm")}
        onAdjust={() => openDialogWith("adjust")}
        onManual={() => {
          clearErrors();
          setIsManualChosen(true);
        }}
        onAddNote={() => openDialogWith("note")}
        onClose={() => openDialogWith("close")}
      />

      {openDialog === "confirm" && detail.recommendation !== null && (
        <ConfirmDialog
          category={detail.recommendation.category}
          actionCount={keptCount(rows)}
          isSaving={decision.isPending}
          error={actionError}
          onConfirm={() => {
            clearErrors();
            decision.mutate({ type: "CONFIRM", final_actions: toFinalActions(rows) });
          }}
          onClose={() => {
            setOpenDialog(null);
            clearErrors();
          }}
        />
      )}

      {openDialog === "adjust" && detail.recommendation !== null && (
        <AdjustDialog
          recommended={detail.recommendation.category}
          isSaving={decision.isPending}
          error={actionError}
          fieldError={fieldError}
          onSubmit={(values) => {
            clearErrors();
            // `final_actions` omitted on purpose. The checklist on screen was
            // prepared for the recommended category and an adjustment moves away
            // from it, so those rows are not what this decision accepts. The
            // server reads the new category's baseline live and drops the now
            // outdated tailored suggestions (FR-78, ADR-18 §6).
            decision.mutate({ type: "ADJUST", ...values });
          }}
          onClose={() => {
            setOpenDialog(null);
            clearErrors();
          }}
        />
      )}

      {openDialog === "note" && (
        <NoteDialog
          isSaving={note.isPending}
          error={actionError}
          onSubmit={(text) => {
            clearErrors();
            note.mutate(text);
          }}
          onClose={() => {
            setOpenDialog(null);
            clearErrors();
          }}
        />
      )}

      {openDialog === "close" && (
        <CloseDialog
          caseNo={detail.case_no}
          isSaving={close.isPending}
          error={actionError}
          onConfirm={() => {
            clearErrors();
            close.mutate();
          }}
          onClose={() => {
            setOpenDialog(null);
            clearErrors();
          }}
        />
      )}
    </div>
  );
}

/** The confirmation message for the decision that was just recorded. */
function decisionToast(
  detail: CaseDetail,
  type: DecisionRequest["type"],
  finalCategory: VTLCategory,
): string {
  const name = strings.vtl.names[finalCategory];

  if (type === "ADJUST") {
    const from = detail.recommended_category;
    return copy.adjustedToast
      .replace("{caseNo}", detail.case_no)
      .replace("{from}", from === null ? strings.queue.notAvailable : strings.vtl.names[from])
      .replace("{to}", name);
  }

  const template = type === "MANUAL" ? copy.manuallyTriagedToast : copy.confirmedToast;
  return template.replace("{caseNo}", detail.case_no).replace("{category}", name);
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

/**
 * The W-06 banner (NFR-09, FR-34).
 *
 * Two wordings, because the two ways into manual triage are not the same thing.
 * The pipeline having given up is news, and the banner says why and when so the
 * reviewer knows the case was not lost. A reviewer who *chose* manual triage on a
 * case with a sound recommendation already knows why they are here, and telling
 * them "AI unavailable" would simply be untrue.
 *
 * The reason arrives as a code and is never shown as one: an unrecognised code
 * falls back to a general sentence rather than printing itself at a clinician
 * (IR-05).
 */
function ManualTriageBanner({ detail, isByChoice }: { detail: CaseDetail; isByChoice: boolean }) {
  const manual = copy.manualTriage;

  if (isByChoice && detail.status !== "MANUAL_TRIAGE_REQUIRED") {
    return <p className={styles.noticeBanner}>{manual.byChoice}</p>;
  }

  return (
    <div className={styles.warnBanner}>
      <span className={styles.warnIcon} aria-hidden="true">
        !
      </span>
      <span>
        {manual.aiUnavailable} {failureSentence(detail)} {manual.safeToTriage}
      </span>
      {/* P07 §7.1 adds POST /cases/{id}/retry and enables this. */}
      <button type="button" className={styles.button} disabled title={copy.availableInP07}>
        {manual.retry}
      </button>
    </div>
  );
}

/** "The language model did not respond in time. (09:20)", or nothing. */
function failureSentence(detail: CaseDetail): string {
  const failure = detail.failure;
  if (failure === null) {
    return "";
  }

  const reasons: Record<string, string> = copy.failureReasons;
  const reason = reasons[failure.reason_code] ?? copy.failureReasonFallback;
  const time = formatDisplayTime(failure.failed_at);

  return time === null
    ? reason
    : copy.manualTriage.failureDetail.replace("{reason}", reason).replace("{time}", time);
}

/**
 * The clinical notes on this case (FR-37, FR-45).
 *
 * Oldest first, as the server returns them, because they read as a running
 * account of the case. Nothing here is editable: a note cannot be corrected once
 * written, only followed by another one (FR-43).
 */
function NotesPanel({ notes }: { notes: CaseDetail["notes"] }) {
  if (notes.length === 0) {
    return null;
  }

  const notesCopy = copy.notes;

  return (
    <section className={`${styles.panel} ${styles.notesPanel}`}>
      <h2 className={styles.panelTitle}>{notesCopy.title}</h2>
      {notes.map((item) => {
        const time = formatDisplayTime(item.created_at) ?? "";
        const byline =
          item.author_name === null
            ? notesCopy.bylineUnknown.replace("{time}", time)
            : notesCopy.byline.replace("{name}", item.author_name).replace("{time}", time);

        return (
          <div key={item.id} className={styles.note}>
            <p className={styles.footnote}>{byline}</p>
            <p>{item.text}</p>
          </div>
        );
      })}
    </section>
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
 * The fixed decision bar (FR-32..FR-34, FR-37, FR-38, IR-06, BR-10).
 *
 * `can_decide` stays true on a case that is already decided, because FR-48
 * allows an amendment — but an amendment is not a confirmation, and P06 has no
 * screen for one. So the four deciding controls are offered while the case is
 * undecided, and the decision already taken is shown in their place afterwards,
 * alongside the two that still apply: a note can be added to a decided case, and
 * closing one is the whole point of `can_close`.
 */
function DecisionBar({
  detail,
  isDecided,
  isManualMode,
  isReviewer,
  onConfirm,
  onAdjust,
  onManual,
  onAddNote,
  onClose,
}: {
  detail: CaseDetail;
  isDecided: boolean;
  isManualMode: boolean;
  /** Used only to keep Add note reachable on a closed case; never to allow anything. */
  isReviewer: boolean;
  onConfirm: () => void;
  onAdjust: () => void;
  onManual: () => void;
  onAddNote: () => void;
  onClose: () => void;
}) {
  const bar = copy.decisionBar;

  if (!detail.permissions.can_decide) {
    return (
      <div className={styles.decisionBar}>
        <p className={styles.readOnlyNotice}>{bar.readOnly}</p>
        {/* A closed case is the one place `can_decide` is false for a reviewer
            (FR-38), and a note is not a decision: `ReviewService.add_note`
            accepts one at any status, because the time to write an observation
            down is when it is known rather than when the workflow permits it
            (FR-37). So the role is what gates this control, not the permission.
            Hiding only — the endpoint is reviewer-only whatever this shows
            (SR-05). */}
        {isReviewer && (
          <button type="button" className={styles.button} onClick={onAddNote}>
            {bar.addNote}
          </button>
        )}
        {/* Read-only is about deciding, not about reading the record: every role
            may open the trail, and an Intake Staff member who entered the case
            has as much reason to as anyone (FR-45). */}
        <ViewAuditLink caseId={detail.id} />
        <p className={styles.disclaimer}>{bar.disclaimer}</p>
      </div>
    );
  }

  const category: VTLCategory | null = detail.recommendation?.category ?? null;
  // Both speak about a recommendation — one accepts it, the other departs from
  // it — so both need one, and need nobody to have decided yet.
  const canDecideOnRecommendation =
    detail.status === "AWAITING_REVIEW" && category !== null && !isManualMode;

  return (
    <div className={styles.decisionBar}>
      {isDecided && detail.decision !== null ? (
        <p className={styles.decided}>
          <b>{bar.decided}</b> {decidedLine(detail)}
        </p>
      ) : (
        <>
          <button
            type="button"
            className={`${styles.button} ${styles.buttonPrimary}`}
            disabled={!canDecideOnRecommendation}
            onClick={onConfirm}
          >
            {bar.confirm.replace(
              "{category}",
              category === null ? strings.queue.notAvailable : strings.vtl.names[category],
            )}
          </button>

          <button
            type="button"
            className={styles.button}
            disabled={!canDecideOnRecommendation}
            onClick={onAdjust}
          >
            {bar.adjust}
          </button>

          {/* FR-34 and ADR-15 §4: available at any time, not only after a
              failure. Already on the screen when manual mode is on. */}
          <button
            type="button"
            className={styles.button}
            disabled={isManualMode}
            onClick={onManual}
          >
            {bar.manual}
          </button>
        </>
      )}

      <button type="button" className={styles.button} onClick={onAddNote}>
        {bar.addNote}
      </button>

      {detail.permissions.can_close && (
        <button type="button" className={styles.button} onClick={onClose}>
          {bar.close}
        </button>
      )}

      <ViewAuditLink caseId={detail.id} />

      <p className={styles.disclaimer}>{bar.disclaimer}</p>
    </div>
  );
}

/**
 * W-07's timeline, on its own route.
 *
 * A link and not a button: the record is a place, and a reviewer who wants it
 * beside the case should be able to open it in a second tab.
 */
function ViewAuditLink({ caseId }: { caseId: string }) {
  return (
    <Link className={`${styles.button} ${styles.buttonLink}`} to={`/cases/${caseId}/audit`}>
      {copy.decisionBar.viewAudit}
    </Link>
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
