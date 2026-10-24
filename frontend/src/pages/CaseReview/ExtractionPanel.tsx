/**
 * W-04 panel 2: the clinical detail the extraction read, which a Veterinary
 * Reviewer can correct (FR-09, FR-27, FR-31 · UC-09).
 *
 * For a reviewer on a case that is awaiting review (`can_regenerate`) every value
 * is a button: click it, change it, and "Save and regenerate" turns on. The
 * button stays off until something differs from the stored extraction, and only
 * the fields that differ are sent. A correction is a new version on the server;
 * this panel never edits the one it is showing (ADR-14).
 *
 * Everyone else sees the same grid read-only, with no button — there is nothing
 * for them to press.
 *
 * Two rows are not like the others. Red flags are shown in the danger colour
 * *and* as bold text, so the emphasis survives without colour (NFR-21). "Ask the
 * owner" is `missing_information`, renamed: to a reviewer it is not a gap in the
 * data, it is the next question to ask.
 *
 * A row with nothing in it still renders, reading "None stated". An absent value
 * and a value the extraction positively denied are different findings, and a grid
 * that quietly dropped its empty rows would make the two look the same.
 *
 * **Drafts survive the page's polling.** The editor is keyed to the extraction's
 * id, so a background re-read of the same version leaves what is half typed
 * alone, and a new version (the regeneration's) starts a fresh draft.
 */
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import type { CaseExtraction, ExtractionCorrection } from "../../api/cases";
import { listComplaints } from "../../api/kb";
import { strings } from "../../i18n/strings";
import styles from "./CaseReview.module.css";

const copy = strings.caseReview;

const TEXT_FIELDS = [
  "onset_duration",
  "frequency_severity",
  "exposure_history",
  "relevant_history",
] as const;
const LIST_FIELDS = [
  "associated_signs",
  "negated_findings",
  "red_flags",
  "missing_information",
] as const;

type TextField = (typeof TEXT_FIELDS)[number];
type ListField = (typeof LIST_FIELDS)[number];
type EditableField = TextField | ListField | "presenting_complaints";

/** The server's limit on one free-text value (`EXTRACTION_VALUE_MAX_LENGTH`). */
const TEXT_MAX_LENGTH = 300;

interface ComplaintChoice {
  code: string;
  is_primary: boolean;
}

/** What the reviewer has typed so far. Lists are kept as text, one item per line. */
interface Draft {
  texts: Record<TextField, string>;
  lists: Record<ListField, string>;
  complaints: ComplaintChoice[];
}

export function ExtractionPanel({
  extraction,
  canEdit,
  isSaving,
  error,
  onSave,
}: {
  extraction: CaseExtraction | null;
  /** `permissions.can_regenerate`: a hint for the screen; the server decides. */
  canEdit: boolean;
  isSaving: boolean;
  error: string | null;
  onSave: (correction: ExtractionCorrection) => void;
}) {
  const isEditable = canEdit && extraction !== null;

  return (
    <section className={`${styles.panel} ${styles.panelExtraction}`}>
      <h2 className={styles.panelTitle}>
        {copy.extractionTitle}
        {isEditable && <span className={styles.panelHint}>{copy.editHint}</span>}
      </h2>

      {extraction === null ? (
        <p className={styles.muted}>{copy.extractionUnavailable}</p>
      ) : isEditable ? (
        <EditableRows
          key={extraction.id}
          extraction={extraction}
          isSaving={isSaving}
          error={error}
          onSave={onSave}
        />
      ) : (
        <Rows extraction={extraction} />
      )}

      {extraction !== null && extraction.is_corrected && (
        <p className={styles.footnote}>
          {(extraction.corrected_by_name === null
            ? copy.correctedByUnknown
            : copy.correctedBy.replace("{name}", extraction.corrected_by_name)
          ).replace("{version}", String(extraction.version))}
        </p>
      )}
    </section>
  );
}

// --- Read-only ------------------------------------------------------------

function Rows({ extraction }: { extraction: CaseExtraction }) {
  return (
    <dl className={styles.grid}>
      <Row label={copy.fields.species}>
        {extraction.species === null ? null : strings.queue.species[extraction.species]}
      </Row>

      <Row label={copy.fields.presenting_complaints}>
        {complaintsDisplay(namesOf(extraction), extraction.presenting_complaints)}
      </Row>

      <Row label={copy.fields.onset_duration}>{extraction.onset_duration}</Row>
      <Row label={copy.fields.frequency_severity}>{extraction.frequency_severity}</Row>
      <Row label={copy.fields.associated_signs}>{joined(extraction.associated_signs)}</Row>
      <Row label={copy.fields.negated_findings}>{joined(extraction.negated_findings)}</Row>
      <Row label={copy.fields.exposure_history}>{extraction.exposure_history}</Row>
      <Row label={copy.fields.relevant_history}>{extraction.relevant_history}</Row>

      <Row label={copy.fields.red_flags}>{redFlagsDisplay(extraction.red_flags)}</Row>

      <Row label={copy.fields.missing_information}>{joined(extraction.missing_information)}</Row>
    </dl>
  );
}

/** One key and its value, or "None stated" where the extraction read nothing. */
function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className={styles.gridKey}>{label}</dt>
      <dd className={isEmpty(children) ? `${styles.gridValue} ${styles.muted}` : styles.gridValue}>
        {isEmpty(children) ? copy.emptyValue : children}
      </dd>
    </>
  );
}

// --- Editable -------------------------------------------------------------

function EditableRows({
  extraction,
  isSaving,
  error,
  onSave,
}: {
  extraction: CaseExtraction;
  isSaving: boolean;
  error: string | null;
  onSave: (correction: ExtractionCorrection) => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => draftFrom(extraction));
  const [editing, setEditing] = useState<EditableField | null>(null);
  const options = useQuery({ queryKey: ["kb", "complaints"], queryFn: listComplaints });

  // The extraction's own complaints are always offered, even if the list has not
  // loaded or no longer carries one of them.
  const names = namesOf(extraction);
  for (const option of options.data ?? []) {
    names.set(option.code, option.name);
  }

  const correction = correctionFrom(draft, extraction);
  const changed = new Set(Object.keys(correction));
  const hasChanges = changed.size > 0;

  function setText(field: TextField, value: string) {
    setDraft((previous) => ({ ...previous, texts: { ...previous.texts, [field]: value } }));
  }

  function setList(field: ListField, value: string) {
    setDraft((previous) => ({ ...previous, lists: { ...previous.lists, [field]: value } }));
  }

  function row(field: EditableField, label: string, display: ReactNode, editor: ReactNode) {
    return (
      <EditRow
        label={label}
        isEditing={editing === field}
        isEdited={changed.has(field)}
        display={display}
        editor={editor}
        onEdit={() => setEditing(field)}
        onDone={() => setEditing(null)}
      />
    );
  }

  function textRow(field: TextField) {
    const label = copy.fields[field];
    return row(
      field,
      label,
      draft.texts[field].trim(),
      <input
        type="text"
        className={styles.input}
        aria-label={label}
        value={draft.texts[field]}
        maxLength={TEXT_MAX_LENGTH}
        autoFocus
        onChange={(event) => setText(field, event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            setEditing(null);
          }
        }}
      />,
    );
  }

  function listRow(field: ListField) {
    const label = copy.fields[field];
    const items = linesOf(draft.lists[field]);
    return row(
      field,
      label,
      field === "red_flags" ? redFlagsDisplay(items) : joined(items),
      <>
        <textarea
          className={styles.textarea}
          aria-label={label}
          rows={3}
          value={draft.lists[field]}
          autoFocus
          onChange={(event) => setList(field, event.target.value)}
        />
        <span className={styles.editHelper}>{copy.editListHelper}</span>
      </>,
    );
  }

  return (
    <>
      <dl className={styles.grid}>
        <Row label={copy.fields.species}>
          {extraction.species === null ? null : strings.queue.species[extraction.species]}
        </Row>

        {row(
          "presenting_complaints",
          copy.fields.presenting_complaints,
          complaintsDisplay(names, draft.complaints),
          <ComplaintsEditor
            names={names}
            status={options.status}
            choices={draft.complaints}
            onChange={(complaints) => setDraft((previous) => ({ ...previous, complaints }))}
          />,
        )}

        {textRow("onset_duration")}
        {textRow("frequency_severity")}
        {listRow("associated_signs")}
        {listRow("negated_findings")}
        {textRow("exposure_history")}
        {textRow("relevant_history")}
        {listRow("red_flags")}
        {listRow("missing_information")}
      </dl>

      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      <div className={styles.addRow}>
        <button
          type="button"
          className={`${styles.button} ${styles.buttonSmall}`}
          disabled={!hasChanges || isSaving}
          onClick={() => onSave(correction)}
        >
          {isSaving ? copy.saving : copy.saveAndRegenerate}
        </button>
        {!hasChanges && <span className={styles.muted}>{copy.enabledAfterCorrection}</span>}
      </div>
    </>
  );
}

/** One editable row: the value as a button, or its editor while it is open. */
function EditRow({
  label,
  isEditing,
  isEdited,
  display,
  editor,
  onEdit,
  onDone,
}: {
  label: string;
  isEditing: boolean;
  isEdited: boolean;
  display: ReactNode;
  editor: ReactNode;
  onEdit: () => void;
  onDone: () => void;
}) {
  return (
    <>
      <dt className={styles.gridKey}>{label}</dt>
      <dd className={styles.gridValue}>
        {isEditing ? (
          <div className={styles.editor}>
            {editor}
            <button type="button" className={styles.inlineButton} onClick={onDone}>
              {copy.editDone}
            </button>
          </div>
        ) : (
          <button
            type="button"
            className={styles.editValue}
            aria-label={copy.editField.replace("{field}", label)}
            onClick={onEdit}
          >
            <span className={isEmpty(display) ? styles.muted : undefined}>
              {isEmpty(display) ? copy.emptyValue : display}
            </span>
            {isEdited && <span className={styles.editedMarker}> ({copy.editedMarker})</span>}
          </button>
        )}
      </dd>
    </>
  );
}

/**
 * The complaint list as checkboxes with a primary radio (UC-09).
 *
 * Exactly one complaint is primary whenever there is any, and the handlers keep
 * it so: the first one chosen becomes primary, and unchecking the primary hands
 * it to the first that remains. The server enforces the same rule and names the
 * field if it is ever broken (IR-05).
 */
function ComplaintsEditor({
  names,
  status,
  choices,
  onChange,
}: {
  names: ReadonlyMap<string, string>;
  status: "pending" | "error" | "success";
  choices: ComplaintChoice[];
  onChange: (choices: ComplaintChoice[]) => void;
}) {
  function toggle(code: string, isChecked: boolean) {
    if (isChecked) {
      onChange([...choices, { code, is_primary: choices.length === 0 }]);
      return;
    }
    const remaining = choices.filter((choice) => choice.code !== code);
    const hasPrimary = remaining.some((choice) => choice.is_primary);
    onChange(
      remaining.map((choice, index) => ({
        ...choice,
        is_primary: hasPrimary ? choice.is_primary : index === 0,
      })),
    );
  }

  function makePrimary(code: string) {
    onChange(choices.map((choice) => ({ ...choice, is_primary: choice.code === code })));
  }

  return (
    <fieldset className={styles.complaintFieldset}>
      <legend className={styles.editHelper}>{copy.editComplaintsHelper}</legend>
      {status === "pending" && <p className={styles.muted}>{copy.complaintsLoading}</p>}
      {status === "error" && (
        <p className={styles.muted} role="status">
          {copy.complaintsUnavailable}
        </p>
      )}
      {[...names].map(([code, name]) => {
        const choice = choices.find((candidate) => candidate.code === code);
        return (
          <div key={code} className={styles.complaintOption}>
            <label>
              <input
                type="checkbox"
                checked={choice !== undefined}
                onChange={(event) => toggle(code, event.target.checked)}
              />{" "}
              {name}
            </label>
            <label className={styles.complaintPrimary}>
              <input
                type="radio"
                name="primary-complaint"
                aria-label={copy.primaryFor.replace("{complaint}", name)}
                checked={choice?.is_primary === true}
                disabled={choice === undefined}
                onChange={() => makePrimary(code)}
              />{" "}
              {copy.primaryMarker}
            </label>
          </div>
        );
      })}
    </fieldset>
  );
}

// --- Draft <-> extraction -------------------------------------------------

function draftFrom(extraction: CaseExtraction): Draft {
  return {
    texts: {
      onset_duration: extraction.onset_duration ?? "",
      frequency_severity: extraction.frequency_severity ?? "",
      exposure_history: extraction.exposure_history ?? "",
      relevant_history: extraction.relevant_history ?? "",
    },
    lists: {
      associated_signs: extraction.associated_signs.join("\n"),
      negated_findings: extraction.negated_findings.join("\n"),
      red_flags: extraction.red_flags.join("\n"),
      missing_information: extraction.missing_information.join("\n"),
    },
    complaints: extraction.presenting_complaints.map(({ code, is_primary }) => ({
      code,
      is_primary,
    })),
  };
}

/**
 * Only the fields that differ from the stored extraction.
 *
 * Compared after trimming, so retyping a value the same way is not a correction,
 * and a cleared text field is sent as `null` — which the server reads as
 * "nothing stated" rather than leaving the old value in place.
 */
function correctionFrom(draft: Draft, extraction: CaseExtraction): ExtractionCorrection {
  const correction: ExtractionCorrection = {};

  for (const field of TEXT_FIELDS) {
    const value = draft.texts[field].trim();
    if (value !== (extraction[field] ?? "").trim()) {
      correction[field] = value === "" ? null : value;
    }
  }

  for (const field of LIST_FIELDS) {
    const items = linesOf(draft.lists[field]);
    if (!sameItems(items, extraction[field])) {
      correction[field] = items;
    }
  }

  if (!sameComplaints(draft.complaints, extraction.presenting_complaints)) {
    correction.presenting_complaints = draft.complaints;
  }

  return correction;
}

function linesOf(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

function sameItems(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

function sameComplaints(
  left: readonly ComplaintChoice[],
  right: readonly ComplaintChoice[],
): boolean {
  const key = (choice: ComplaintChoice) => `${choice.code}:${choice.is_primary ? 1 : 0}`;
  const a = left.map(key).sort();
  const b = right.map(key).sort();
  return sameItems(a, b);
}

// --- Display --------------------------------------------------------------

/** Display names by complaint code, for the complaints this extraction carries. */
function namesOf(extraction: CaseExtraction): Map<string, string> {
  return new Map(
    extraction.presenting_complaints.map((complaint) => [
      complaint.code,
      complaint.name ?? complaint.code,
    ]),
  );
}

/** The complaints with the primary marked. */
function complaintsDisplay(
  names: ReadonlyMap<string, string>,
  shown: readonly ComplaintChoice[],
): ReactNode {
  if (shown.length === 0) {
    return null;
  }
  return shown.map((complaint) => (
    <span key={complaint.code} className={styles.gridValue}>
      {names.get(complaint.code) ?? complaint.code}
      {complaint.is_primary && <b className={styles.primary}> {copy.primaryMarker}</b>}
      <br />
    </span>
  ));
}

function redFlagsDisplay(flags: readonly string[]): ReactNode {
  return flags.length === 0 ? null : <b className={styles.redFlagValue}>{joined(flags)}</b>;
}

function joined(values: readonly string[]): string | null {
  return values.length === 0 ? null : values.join(" · ");
}

function isEmpty(value: ReactNode): boolean {
  return value === null || value === undefined || value === "";
}
