/**
 * W-04's suggested-action checklist (FR-71..FR-79, IR-23, ADR-18).
 *
 * The actions are triage handling and nothing else — escalate, prepare, monitor,
 * what to ask the owner, how to move the patient. Never a medication, a dose, or
 * a treatment protocol (BR-09). The deterministic action validator is what
 * enforces that server-side (FR-74); this screen's job is to make the difference
 * between the two layers impossible to miss:
 *
 * - **Baseline** rows come from the knowledge base for this urgency category and
 *   are always present, including when the actions job failed. They are curated
 *   content, so they carry no "requires approval" caveat.
 * - **AI-suggested** rows were written by the model for this case. They sit under
 *   the FR-75 heading, in a dashed box, with the passage that supports them —
 *   and they stay marked that way until a reviewer finalizes the list.
 *
 * Three states the panel must never dramatise (FR-77). `PENDING` is a loading
 * row, because the category is already settled and the reviewer can decide
 * without waiting. `FAILED` is a single quiet line: nothing about the case is
 * wrong, the baseline actions are intact, and an error dialog here would block a
 * decision over a missing nicety. `NOT_APPLICABLE` is simply no tailored layer.
 *
 * Editing is available only to a reviewer on an undecided case (FR-79). For
 * everyone else — Intake Staff, an administrator, a case already decided — the
 * list is read-only, and the server has already withheld the unfinalized
 * tailored rows from non-reviewers, so there is nothing here to hide.
 */
import { useState } from "react";

import type { ActionsStatus, ActionSource, SuggestedAction, VTLCategory } from "../../api/cases";
import { strings } from "../../i18n/strings";
import { statusOf, type ChecklistRow } from "../../lib/actionChecklist";
import styles from "./CaseReview.module.css";

const copy = strings.caseReview.actions;

export interface ActionChecklistProps {
  rows: readonly ChecklistRow[];
  status: ActionsStatus | null;
  /** The category the actions are for, used only in the panel's intro line. */
  category: VTLCategory | null;
  rejectedCount: number;
  /** FR-79: the controls exist only for a reviewer on an undecided case. */
  isEditable: boolean;
  /**
   * Tailored rows suggested for a category the case no longer has (FR-78). Shown
   * greyed and read-only, and not part of `rows`, so they cannot be recorded as
   * kept by accident.
   */
  outdated: readonly SuggestedAction[];
  /** The category the outdated rows were suggested for. */
  outdatedCategory: VTLCategory | null;
  /** The server's plain-language line for a failed actions job (FR-77). */
  failureMessage: string | null;
  /** `permissions.can_regenerate_actions`: a reviewer, a recommendation, no job running. */
  canRegenerate: boolean;
  isRegenerating: boolean;
  onRegenerate: () => void;
  onToggle: (key: string) => void;
  onEdit: (key: string, text: string) => void;
  onAdd: (text: string) => void;
}

export function ActionChecklist({
  rows,
  status,
  category,
  rejectedCount,
  isEditable,
  outdated,
  outdatedCategory,
  failureMessage,
  canRegenerate,
  isRegenerating,
  onRegenerate,
  onToggle,
  onEdit,
  onAdd,
}: ActionChecklistProps) {
  const baseline = rows.filter((row) => row.source === "BASELINE");
  const tailored = rows.filter((row) => row.source !== "BASELINE");
  const categoryName = category === null ? "" : strings.vtl.names[category];
  const outdatedName = outdatedCategory === null ? "" : strings.vtl.names[outdatedCategory];
  // The button is offered when there is something to replace: rows suggested for
  // another category, or a job that failed. Not on a current, healthy list.
  const wantsRegeneration = outdated.length > 0 || status === "FAILED";

  return (
    <section className={styles.actions}>
      <h3 className={styles.sectionTitle}>{copy.title}</h3>
      <p className={styles.actionsIntro}>
        {(isEditable ? copy.intro : copy.introReadOnly).replace("{category}", categoryName)}
      </p>

      {baseline.map((row) => (
        <ActionRow
          key={row.key}
          row={row}
          isEditable={isEditable}
          onToggle={onToggle}
          onEdit={onEdit}
        />
      ))}

      {/* FR-75. The heading is the approval caveat, so it belongs to the rows
          that need one and disappears with them once the list is finalized. */}
      {isEditable && tailored.length > 0 && (
        <p className={styles.aiActionsHeading}>{copy.aiHeading}</p>
      )}

      {tailored.map((row) => (
        <ActionRow
          key={row.key}
          row={row}
          isEditable={isEditable}
          onToggle={onToggle}
          onEdit={onEdit}
        />
      ))}

      {/* FR-78. The rows stay visible so the reviewer can compare, but they are
          greyed, carry no checkbox, and are not in the list a decision records. */}
      {outdated.length > 0 && (
        <div>
          <p className={styles.aiActionsHeading}>
            {copy.outdatedNote.replace("{category}", outdatedName)}
          </p>
          {outdated.map((action, index) => (
            <div
              key={`outdated-${index}`}
              className={`${styles.action} ${styles.actionOutdated}`}
              data-outdated="true"
              title={copy.outdatedTitle}
            >
              <span className={styles.actionText}>
                {action.text}
                <Citation ranks={action.cited_ranks} />
              </span>
              <span className={styles.actionSource} title={copy.sourceTitles[action.source]}>
                {sourceLabel(action.source)}
              </span>
            </div>
          ))}
        </div>
      )}

      {status === "PENDING" && <p className={styles.actionsIntro}>{copy.pending}</p>}

      {/* One line, never a dialog: the baseline actions are what matter and they
          are already on screen (FR-77). The wording comes from the server, which
          knows which reason code stopped the job. */}
      {status === "FAILED" && (
        <p className={styles.actionsIntro}>{failureMessage ?? copy.failed}</p>
      )}

      {canRegenerate && wantsRegeneration && (
        <button
          type="button"
          className={`${styles.button} ${styles.buttonSmall}`}
          aria-label={copy.regenerateLabel.replace("{category}", categoryName)}
          disabled={isRegenerating}
          onClick={onRegenerate}
        >
          {isRegenerating ? copy.regenerating : copy.regenerate}
        </button>
      )}

      {rows.length === 0 && status !== "PENDING" && (
        <p className={styles.actionsIntro}>{copy.empty}</p>
      )}

      {rejectedCount > 0 && (
        <p className={styles.actionsIntro}>
          {rejectedCount === 1
            ? copy.rejectedOne
            : copy.rejectedMany.replace("{count}", String(rejectedCount))}
        </p>
      )}

      {isEditable && <AddAction onAdd={onAdd} />}
    </section>
  );
}

function ActionRow({
  row,
  isEditable,
  onToggle,
  onEdit,
}: {
  row: ChecklistRow;
  isEditable: boolean;
  onToggle: (key: string) => void;
  onEdit: (key: string, text: string) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const isRemoved = !row.isKept;
  const isAi = row.source === "AI";

  const className = [
    styles.action,
    isAi ? styles.actionAi : null,
    isRemoved ? styles.actionRemoved : null,
  ]
    .filter((name) => name !== null)
    .join(" ");

  if (draft !== null) {
    return (
      <div className={className}>
        <div className={styles.actionEdit}>
          <label className="visuallyHidden" htmlFor={`action-${row.key}`}>
            {copy.editLabel}
          </label>
          <input
            id={`action-${row.key}`}
            className={styles.actionInput}
            type="text"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button
            type="button"
            className={`${styles.button} ${styles.buttonSmall}`}
            onClick={() => {
              onEdit(row.key, draft);
              setDraft(null);
            }}
          >
            {copy.editSave}
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.buttonSmall}`}
            onClick={() => setDraft(null)}
          >
            {copy.editCancel}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={className} data-status={statusOf(row)}>
      {isEditable ? (
        <label className={styles.actionText}>
          <input
            type="checkbox"
            checked={row.isKept}
            aria-label={`${copy.keepLabel}: ${row.text}`}
            onChange={() => onToggle(row.key)}
          />{" "}
          {row.text}
          <Citation ranks={row.citedRanks} />
        </label>
      ) : (
        <span className={styles.actionText}>
          {row.text}
          <Citation ranks={row.citedRanks} />
        </span>
      )}

      <span className={styles.actionSource} title={copy.sourceTitles[row.source]}>
        {sourceLabel(row.source)}
      </span>

      {isEditable && (
        <span className={styles.actionTools}>
          <button
            type="button"
            className={styles.inlineButton}
            aria-label={`${copy.editLabel}: ${row.text}`}
            onClick={() => setDraft(row.text)}
          >
            {copy.edit}
          </button>
          <button
            type="button"
            className={styles.inlineButton}
            aria-label={`${isRemoved ? copy.restoreLabel : copy.removeLabel}: ${row.text}`}
            onClick={() => onToggle(row.key)}
          >
            {isRemoved ? copy.restore : copy.remove}
          </button>
        </span>
      )}
    </div>
  );
}

/** "[1]", the rank of the passage supporting this action (FR-74, IR-23). */
function Citation({ ranks }: { ranks: readonly number[] }) {
  if (ranks.length === 0) {
    return null;
  }

  const text = ranks.map((rank) => `[${rank}]`).join(" ");
  return (
    <span className={styles.actionCitation} title={copy.citationLabel.replace("{ranks}", text)}>
      {" "}
      {text}
    </span>
  );
}

function AddAction({ onAdd }: { onAdd: (text: string) => void }) {
  const [text, setText] = useState("");

  function submit() {
    if (text.trim() === "") {
      return;
    }
    onAdd(text.trim());
    setText("");
  }

  return (
    <div>
      <div className={styles.addRow}>
        <label className="visuallyHidden" htmlFor="add-action">
          {copy.addLabel}
        </label>
        <input
          id="add-action"
          className={styles.actionInput}
          type="text"
          value={text}
          placeholder={copy.addPlaceholder}
          aria-describedby="add-action-helper"
          onChange={(event) => setText(event.target.value)}
          // Enter adds the action rather than submitting anything: this input
          // sits on a page whose only form is the decision itself.
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              submit();
            }
          }}
        />
        <button
          type="button"
          className={`${styles.button} ${styles.buttonSmall}`}
          disabled={text.trim() === ""}
          onClick={submit}
        >
          {copy.add}
        </button>
      </div>
      <p id="add-action-helper" className={styles.actionsIntro}>
        {copy.addHelper}
      </p>
    </div>
  );
}

function sourceLabel(source: ActionSource): string {
  return copy.sources[source];
}
