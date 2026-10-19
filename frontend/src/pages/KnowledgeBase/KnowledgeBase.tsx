/**
 * W-08 Knowledge Base (FR-49..FR-56, NFR-08, BR-04, DR-05, ADR-14, ADR-18 ·
 * UC-13, UC-14).
 *
 * One screen, two jobs, and the split between them is the point of the phase:
 *
 * 1. **An administrator curates.** Writing a draft, editing it, submitting it
 *    for review and retiring live content is curation work (FR-49, FR-51).
 * 2. **A KB approver decides.** Approving an entry or a red-flag rule is behind
 *    `can_approve_kb`, a permission only a Veterinary Reviewer may hold
 *    (BR-04, FR-52). The controls are hidden from everyone else and the server
 *    refuses the request whatever this screen shows (SR-05).
 *
 * Three behaviours matter more than the layout:
 *
 * - **Approval is not publication.** `POST /approve` answers 202 with a
 *   `KB_INDEX` job: the entry stays `PENDING_REVIEW` until that job indexes it
 *   and publishes version N+1. So the panel polls the entry while indexing runs
 *   and shows the reason code if it fails, with the entry still awaiting review
 *   (FR-53, ADR-08).
 * - **The counts describe the whole knowledge base**, not the filtered rows, so
 *   switching tabs never moves the numbers beside them — the same contract as
 *   the Triage Queue's counters (FR-39).
 * - **An active entry is never edited in place.** The editor opens for a draft
 *   only; a change to live content is a new draft that goes through approval
 *   again (ADR-14).
 *
 * Nothing on this screen touches a case, an owner description or an owner
 * reference: the knowledge base holds curated clinical content only (DR-04).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiErrorCode, isApiError } from "../../api/errors";
import {
  approveEntry,
  approveRedFlagRule,
  createEntry,
  KB_INDEX_POLL_INTERVAL_MS,
  listComplaints,
  listEntries,
  listRedFlagRules,
  readEntry,
  rejectEntry,
  retireEntry,
  retireRedFlagRule,
  submitEntry,
  updateEntry,
  type KBEntryDetail,
  type KBEntryKind,
  type KBEntryStatus,
} from "../../api/kb";
import { useAuth } from "../../hooks/useAuth";
import { useToast } from "../../hooks/useToast";
import { strings } from "../../i18n/strings";
import {
  entryFormFrom,
  toEntryCreateRequest,
  toEntryUpdateRequest,
  type KBEntryFormValues,
} from "../../lib/kbValidation";
import type { ServerFieldError } from "./catalogue";
import { EntryDetail } from "./EntryDetail";
import { EntryEditor } from "./EntryEditor";
import { EntryList } from "./EntryList";
import styles from "./KnowledgeBase.module.css";
import { RedFlagRulesTable } from "./RedFlagRulesTable";
import { RejectDialog } from "./RejectDialog";
import { RetireDialog } from "./RetireDialog";
import { VersionHistoryDrawer } from "./VersionHistoryDrawer";

const copy = strings.knowledgeBase;

/** Which half of the screen is showing: the catalogue, or the rules (NFR-08). */
type View = "ENTRIES" | "RULES";

/** What the right-hand panel is doing. `NEW` has no entry selected. */
type PanelMode = "VIEW" | "EDIT" | "NEW";

export function KnowledgeBase() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const { showToast } = useToast();

  const isAdministrator = user?.role === "ADMINISTRATOR";
  // A permission, not a role (BR-04). An administrator never holds it.
  const canApprove = user?.can_approve_kb === true;

  const [view, setView] = useState<View>("ENTRIES");
  // An approver comes here to clear the review queue; an administrator comes to
  // carry on writing. Both can reach every tab.
  const [status, setStatus] = useState<KBEntryStatus>(canApprove ? "PENDING_REVIEW" : "DRAFT");
  const [kind, setKind] = useState<KBEntryKind | "">("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<PanelMode>("VIEW");
  const [newKind, setNewKind] = useState<KBEntryKind>("COMPLAINT");
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [dialog, setDialog] = useState<"reject" | "retire" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<ServerFieldError | null>(null);
  const [retireWarning, setRetireWarning] = useState<string | null>(null);

  const entries = useQuery({
    queryKey: ["kb", "entries", { status, kind }],
    queryFn: () => listEntries(kind === "" ? { status } : { status, kind }),
    // Keep the previous rows on screen while a tab change is in flight, so the
    // list does not blink empty between two valid states.
    placeholderData: (previous) => previous,
  });

  // The fixed complaint list and the rules are reference data for the whole
  // screen: the editor offers them, and the detail panel names them.
  const complaints = useQuery({ queryKey: ["kb", "complaints"], queryFn: listComplaints });
  const rules = useQuery({ queryKey: ["kb", "rules"], queryFn: listRedFlagRules });

  const entry = useQuery({
    queryKey: ["kb", "entry", selectedId],
    queryFn: () => readEntry(selectedId ?? ""),
    enabled: selectedId !== null,
    refetchInterval: (query) => indexingPollInterval(query.state.data),
    // IR-22: a backgrounded tab stops asking. The default, written out because
    // the requirement rests on it.
    refetchIntervalInBackground: false,
  });

  function clearErrors() {
    setActionError(null);
    setFieldError(null);
  }

  /** Everything the screen reads is derived from one of these three queries. */
  function invalidateCatalogue() {
    void queryClient.invalidateQueries({ queryKey: ["kb"] });
  }

  /**
   * What went wrong with an action, and whether it is worth calling an error.
   *
   * A 409 means the entry moved on while this screen was reading it — someone
   * else approved or submitted it — so the answer is to re-read rather than to
   * re-send. A 422 names the control it is about and belongs beside it (IR-05).
   */
  function handleActionError(error: unknown, fallback: string) {
    clearErrors();
    if (isApiError(error)) {
      if (error.code === ApiErrorCode.invalidTransition) {
        invalidateCatalogue();
        setActionError(copy.errors.conflict);
        return;
      }
      if (error.code === ApiErrorCode.validationError && error.field !== null) {
        setFieldError({ field: error.field, message: error.message });
        // With the editor closed there is no field to put it beside, and the
        // sentence still has to be read: submitting a draft whose citation is
        // incomplete is refused from the detail panel too (FR-50, IR-05).
        if (mode === "VIEW") {
          setActionError(error.message);
        }
        return;
      }
      if (error.code === ApiErrorCode.notFound) {
        setActionError(copy.errors.notFound);
        return;
      }
      if (error.code === ApiErrorCode.forbidden) {
        setActionError(copy.errors.forbidden);
        return;
      }
    }
    setActionError(fallback);
  }

  const save = useMutation({
    mutationFn: ({ values, codes }: { values: KBEntryFormValues; codes: string[] }) =>
      mode === "NEW" || selectedId === null
        ? createEntry(toEntryCreateRequest(values, codes))
        : updateEntry(selectedId, toEntryUpdateRequest(values, codes)),
    onSuccess: (saved) => {
      invalidateCatalogue();
      clearErrors();
      setSelectedId(saved.id);
      setMode("VIEW");
      // A new draft is on the Draft tab, wherever the list was.
      setStatus(saved.status);
      showToast(copy.toasts.draftSaved);
    },
    onError: (error: unknown) => handleActionError(error, copy.errors.saveFailed),
  });

  /**
   * Save the draft from the editor, then submit it.
   *
   * Two requests, in this order, because the server checks the *stored* row on
   * submit: an entry whose citation was only ever typed into this form would be
   * refused (FR-50).
   */
  const submit = useMutation({
    mutationFn: async ({ values, codes }: { values: KBEntryFormValues; codes: string[] }) => {
      const saved =
        mode === "NEW" || selectedId === null
          ? await createEntry(toEntryCreateRequest(values, codes))
          : await updateEntry(selectedId, toEntryUpdateRequest(values, codes));
      await submitEntry(saved.id);
      return saved;
    },
    onSuccess: (result) => {
      invalidateCatalogue();
      clearErrors();
      setSelectedId(result.id);
      setMode("VIEW");
      setStatus("PENDING_REVIEW");
      showToast(copy.toasts.submitted);
    },
    onError: (error: unknown) => handleActionError(error, copy.errors.saveFailed),
  });

  /** A stored draft that is already complete needs no save first (FR-51). */
  const submitStored = useMutation({
    mutationFn: (entryId: string) => submitEntry(entryId),
    onSuccess: () => {
      invalidateCatalogue();
      clearErrors();
      setStatus("PENDING_REVIEW");
      showToast(copy.toasts.submitted);
    },
    onError: (error: unknown) => handleActionError(error, copy.errors.saveFailed),
  });

  const approve = useMutation({
    mutationFn: (entryId: string) => approveEntry(entryId),
    onSuccess: () => {
      invalidateCatalogue();
      clearErrors();
      // Not "published": the entry becomes ACTIVE when the KB_INDEX job
      // succeeds, and the panel reports that from `indexing` (FR-53).
      showToast(copy.toasts.approved);
    },
    onError: (error: unknown) => handleActionError(error, copy.errors.actionFailed),
  });

  const reject = useMutation({
    mutationFn: ({ entryId, comments }: { entryId: string; comments: string }) =>
      rejectEntry(entryId, comments),
    onSuccess: () => {
      invalidateCatalogue();
      clearErrors();
      setDialog(null);
      showToast(copy.toasts.rejected);
    },
    onError: (error: unknown) => handleActionError(error, copy.errors.actionFailed),
  });

  const retire = useMutation({
    mutationFn: (entryId: string) => retireEntry(entryId),
    onSuccess: (result) => {
      invalidateCatalogue();
      clearErrors();
      setDialog(null);
      // The consequence nothing refused: a category with no baseline actions
      // until a replacement is approved (FR-72, P08 §8.2b).
      setRetireWarning(result.warning);
      showToast(copy.toasts.retired.replace("{version}", String(result.version_no ?? "")));
    },
    onError: (error: unknown) => handleActionError(error, copy.errors.actionFailed),
  });

  const ruleAction = useMutation({
    mutationFn: ({ ruleId, action }: { ruleId: string; action: "APPROVE" | "RETIRE" }) =>
      action === "APPROVE" ? approveRedFlagRule(ruleId) : retireRedFlagRule(ruleId),
    onSuccess: (result, variables) => {
      invalidateCatalogue();
      clearErrors();
      const template =
        variables.action === "APPROVE" ? copy.toasts.ruleApproved : copy.toasts.ruleRetired;
      showToast(template.replace("{version}", String(result.version_no ?? "")));
    },
    onError: (error: unknown) => handleActionError(error, copy.errors.actionFailed),
  });

  function selectEntry(entryId: string) {
    clearErrors();
    setRetireWarning(null);
    setSelectedId(entryId);
    setMode("VIEW");
  }

  function startNewEntry(entryKind: KBEntryKind) {
    clearErrors();
    setRetireWarning(null);
    setNewKind(entryKind);
    setSelectedId(null);
    setMode("NEW");
  }

  const detail = entry.data;
  const nextVersionNo = (entries.data?.published_version_no ?? 0) + 1;
  const isBusy =
    save.isPending ||
    submit.isPending ||
    submitStored.isPending ||
    approve.isPending ||
    retire.isPending;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>{copy.title}</h1>
        <div className={styles.headerRight}>
          <span className={styles.versionLine}>{versionLine(entries.data)}</span>
          <button
            type="button"
            className={styles.historyButton}
            aria-expanded={isHistoryOpen}
            onClick={() => setIsHistoryOpen((open) => !open)}
          >
            {copy.versions.open}
          </button>
        </div>
      </div>

      <div className={styles.views} role="group" aria-label={copy.viewsLabel}>
        <ViewTab
          label={copy.viewEntries}
          isActive={view === "ENTRIES"}
          onPick={() => setView("ENTRIES")}
        />
        <ViewTab
          label={copy.viewRules}
          isActive={view === "RULES"}
          onPick={() => setView("RULES")}
        />
      </div>

      {isHistoryOpen && <VersionHistoryDrawer onClose={() => setIsHistoryOpen(false)} />}

      {actionError !== null && (
        <p className={styles.error} role="alert">
          {actionError}
        </p>
      )}

      {view === "RULES" ? (
        <RedFlagRulesTable
          rules={rules.data}
          isPending={rules.isPending}
          isError={rules.isError}
          canApprove={canApprove}
          isBusy={ruleAction.isPending}
          onApprove={(ruleId) => ruleAction.mutate({ ruleId, action: "APPROVE" })}
          onRetire={(ruleId) => ruleAction.mutate({ ruleId, action: "RETIRE" })}
        />
      ) : (
        <div className={styles.columns}>
          <EntryList
            data={entries.data}
            isPending={entries.isPending}
            isError={entries.isError}
            status={status}
            kind={kind}
            complaints={complaints.data ?? []}
            selectedId={selectedId}
            canCreate={isAdministrator === true}
            onPickStatus={(next) => {
              clearErrors();
              setStatus(next);
            }}
            onPickKind={setKind}
            onSelect={selectEntry}
            onCreate={startNewEntry}
          />

          <div className={styles.panel}>
            {mode === "NEW" || (mode === "EDIT" && detail !== undefined) ? (
              <EntryEditor
                key={mode === "NEW" ? `new-${newKind}` : detail?.id}
                values={mode === "NEW" || detail === undefined ? undefined : entryFormFrom(detail)}
                kind={mode === "NEW" ? newKind : detail?.kind ?? "COMPLAINT"}
                redFlagCodes={mode === "NEW" ? [] : detail?.red_flag_codes ?? []}
                complaints={complaints.data ?? []}
                rules={rules.data ?? []}
                isSaving={save.isPending || submit.isPending}
                serverError={fieldError}
                onSave={(values, codes) => save.mutate({ values, codes })}
                onSubmit={(values, codes) => submit.mutate({ values, codes })}
                onCancel={() => {
                  clearErrors();
                  setMode("VIEW");
                }}
              />
            ) : (
              <EntryDetail
                entry={detail}
                isPending={entry.isPending && selectedId !== null}
                rules={rules.data ?? []}
                complaints={complaints.data ?? []}
                isAdministrator={isAdministrator === true}
                canApprove={canApprove}
                isBusy={isBusy}
                nextVersionNo={nextVersionNo}
                retireWarning={retireWarning}
                onEdit={() => {
                  clearErrors();
                  setMode("EDIT");
                }}
                onSubmit={() => {
                  clearErrors();
                  if (detail !== undefined) {
                    submitStored.mutate(detail.id);
                  }
                }}
                onApprove={() => {
                  if (detail !== undefined) {
                    approve.mutate(detail.id);
                  }
                }}
                onReject={() => setDialog("reject")}
                onRetire={() => setDialog("retire")}
              />
            )}
          </div>
        </div>
      )}

      {dialog === "reject" && detail !== undefined && (
        <RejectDialog
          isBusy={reject.isPending}
          onCancel={() => setDialog(null)}
          onReject={(comments) => reject.mutate({ entryId: detail.id, comments })}
        />
      )}

      {dialog === "retire" && detail !== undefined && (
        <RetireDialog
          title={detail.title}
          isBusy={retire.isPending}
          onCancel={() => setDialog(null)}
          onRetire={() => retire.mutate(detail.id)}
        />
      )}
    </div>
  );
}

/** The W-08 header line, or what stands in for it before the first approval. */
function versionLine(
  data: { published_version_no: number | null; active_entry_count: number } | undefined,
): string {
  if (data === undefined) {
    return "";
  }
  const count = String(data.active_entry_count);
  if (data.published_version_no === null) {
    return copy.publishedVersionNone.replace("{count}", count);
  }
  return copy.publishedVersion
    .replace("{version}", String(data.published_version_no))
    .replace("{count}", count);
}

/**
 * How soon to re-read the selected entry.
 *
 * Only while its indexing job is still running: approving enqueues the job and
 * the approver is watching the panel when it finishes (FR-53). An entry that is
 * not being indexed never polls.
 */
function indexingPollInterval(detail: KBEntryDetail | undefined): number | false {
  if (detail?.indexing === undefined || detail.indexing === null) {
    return false;
  }
  return detail.indexing.status === "QUEUED" || detail.indexing.status === "RUNNING"
    ? KB_INDEX_POLL_INTERVAL_MS
    : false;
}

function ViewTab({
  label,
  isActive,
  onPick,
}: {
  label: string;
  isActive: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      className={isActive ? `${styles.viewTab} ${styles.viewTabActive}` : styles.viewTab}
      aria-pressed={isActive}
      onClick={onPick}
    >
      {label}
    </button>
  );
}
