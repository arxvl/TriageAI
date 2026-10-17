/**
 * W-05: changing the category, with a reason (FR-33, BR-03, IR-08, ADR-15 §4).
 *
 * ADR-15 §4 puts it plainly: disagreement must be cheap, and never silent. So
 * this dialog is deliberately easy to reach and deliberately impossible to
 * submit empty — Save stays disabled until the reviewer has chosen a category
 * that is actually different and said why, which is the same pair of rules the
 * server enforces (`ReviewService._resolve_category`, `_require_reason`) and the
 * database's own check constraint. The screen is the first of the three, never
 * the only one.
 *
 * Three things it says out loud:
 *
 * - **Which way the category moved.** "Orange → Red (up-triage)" is the
 *   direction the decision will be stored with, computed here from
 *   `URGENCY_ORDER` so the summary and the stored value cannot drift apart.
 * - **That the record is permanent.** The decision is append-only; a correction
 *   is a new row, never an edit (FR-48, ADR-12).
 * - **That the action list follows the new category.** The checklist on W-04 was
 *   prepared for the *recommended* category, and an adjustment by definition
 *   moves away from it, so those rows are not what this decision accepts
 *   (FR-78). The request omits `final_actions` and the server reads the new
 *   category's baseline live — see `onSubmit`'s caller.
 *
 * Presentational, like `ConfirmDialog`: the page owns the request, because the
 * page is what has to refetch and navigate afterwards. `fieldError` is the
 * server's 422 placed beside the control it names (IR-05).
 */
import { useState } from "react";

import type { AdjustReason, VTLCategory } from "../../api/cases";
import { Dialog, DialogActions } from "../../components/Dialog";
import { strings } from "../../i18n/strings";
import { directionOf } from "../../lib/vtl";
import styles from "./CaseReview.module.css";
import { CategoryOptions } from "./CategoryOptions";

const copy = strings.caseReview.adjustDialog;

/** The dropdown's order, which is the order FR-33 and the enum list them in. */
const REASON_ORDER: readonly AdjustReason[] = [
  "CONDITION_DIFFERS_ON_ARRIVAL",
  "SIGN_NOT_CAPTURED",
  "RECOMMENDATION_TOO_LOW",
  "RECOMMENDATION_TOO_HIGH",
  "OTHER",
];

export interface AdjustValues {
  final_category: VTLCategory;
  reason_code: AdjustReason;
  reason_text?: string;
}

export function AdjustDialog({
  recommended,
  isSaving,
  error,
  fieldError,
  onSubmit,
  onClose,
}: {
  /** The category being moved away from; its row is marked "current". */
  recommended: VTLCategory;
  isSaving: boolean;
  /** A message from the failed attempt that belongs to no single control. */
  error: string | null;
  /** A 422's message, keyed by the field the server named. */
  fieldError: { field: string; message: string } | null;
  onSubmit: (values: AdjustValues) => void;
  onClose: () => void;
}) {
  const [category, setCategory] = useState<VTLCategory | null>(null);
  const [reason, setReason] = useState<AdjustReason | "">("");
  const [details, setDetails] = useState("");

  const trimmedDetails = details.trim();
  // `OTHER` says nothing on its own, so the server requires the detail with it.
  const needsDetails = reason === "OTHER";
  const canSave =
    category !== null &&
    category !== recommended &&
    reason !== "" &&
    (!needsDetails || trimmedDetails !== "");

  function handleSubmit() {
    // The two narrowing checks come before `canSave`, not after: TypeScript
    // already narrows `reason` through that alias, so testing it afterwards is
    // code it can prove unreachable.
    if (category === null || reason === "" || !canSave) {
      return;
    }
    onSubmit({
      final_category: category,
      reason_code: reason,
      // Omitted rather than sent empty, as the intake form does: the server
      // treats a blank string as absent anyway, and "" is not a detail.
      ...(trimmedDetails === "" ? {} : { reason_text: trimmedDetails }),
    });
  }

  return (
    <Dialog title={copy.title} isBusy={isSaving} onClose={onClose}>
      <p className={styles.dialogText}>
        {copy.intro.replace("{category}", strings.vtl.names[recommended])}
      </p>

      <CategoryOptions
        name="adjust-category"
        legend={copy.categoryLegend}
        value={category}
        disabled={isSaving}
        note={(option) => strings.vtl.targets[option]}
        hint={(option) => {
          if (option === recommended) {
            return copy.currentMarker;
          }
          // Only on the row actually chosen: labelling all four would tell the
          // reviewer which way each option moves before they have decided, which
          // is a nudge, not information.
          if (option !== category) {
            return null;
          }
          return directionOf(recommended, option) === "UP" ? copy.upTriage : copy.downTriage;
        }}
        onChange={setCategory}
      />
      <FieldError fieldError={fieldError} field="final_category" />

      <label className={styles.field}>
        <span className={styles.sectionTitle}>{copy.reasonLabel}</span>
        <select
          className={styles.select}
          value={reason}
          disabled={isSaving}
          onChange={(event) => setReason(event.target.value as AdjustReason | "")}
        >
          <option value="">{copy.reasonPlaceholder}</option>
          {REASON_ORDER.map((code) => (
            <option key={code} value={code}>
              {strings.caseReview.adjustReasons[code]}
            </option>
          ))}
        </select>
      </label>
      <FieldError fieldError={fieldError} field="reason_code" />

      <label className={styles.field}>
        <span className={styles.sectionTitle}>
          {needsDetails ? copy.detailsLabelRequired : copy.detailsLabel}
        </span>
        <textarea
          className={styles.textarea}
          rows={3}
          value={details}
          disabled={isSaving}
          onChange={(event) => setDetails(event.target.value)}
        />
      </label>
      <FieldError fieldError={fieldError} field="reason_text" />

      {category !== null && category !== recommended && (
        <p className={styles.summaryBanner}>
          {copy.summary
            .replace("{from}", strings.vtl.names[recommended])
            .replace("{to}", strings.vtl.names[category])
            .replace(
              "{direction}",
              (directionOf(recommended, category) === "UP"
                ? copy.upTriage
                : copy.downTriage
              ).toLowerCase(),
            )}{" "}
          {copy.permanentNotice}
        </p>
      )}

      <p className={styles.dialogNotice}>{copy.actionsNotice}</p>

      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      <DialogActions>
        <button type="button" className={styles.button} disabled={isSaving} onClick={onClose}>
          {copy.cancel}
        </button>
        <button
          type="button"
          className={`${styles.button} ${styles.buttonPrimary}`}
          disabled={isSaving || !canSave}
          onClick={handleSubmit}
        >
          {isSaving ? copy.submitting : copy.submit}
        </button>
      </DialogActions>
    </Dialog>
  );
}

/** The server's message for one control, or nothing (IR-05). */
function FieldError({
  fieldError,
  field,
}: {
  fieldError: { field: string; message: string } | null;
  field: string;
}) {
  if (fieldError === null || fieldError.field !== field) {
    return null;
  }
  return (
    <p className={styles.error} role="alert">
      {fieldError.message}
    </p>
  );
}
