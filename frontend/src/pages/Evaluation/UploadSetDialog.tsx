/**
 * Uploading a vignette set (FR-64 · W-10 "Upload vignettes").
 *
 * The server validates every row and refuses the whole file if any is wrong, so
 * nothing is half-imported. This dialog lists the refused rows by line number,
 * counting the header as line 1, so the file can be fixed and sent again.
 *
 * A set whose file names a knowledge-base entry that does not exist is still
 * imported (the relevance judgement is left out). That is a warning, not an
 * error, so the dialog stays open on the list of unknown slugs rather than
 * closing on success and hiding it.
 *
 * Vignette text is never echoed: a refusal names rows and fields, not content.
 */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { uploadEvalSet, type EvalSet } from "../../api/eval";
import { ApiErrorCode, isApiError, type ApiErrorRow } from "../../api/errors";
import { Dialog, DialogActions } from "../../components/Dialog";
import { useToast } from "../../hooks/useToast";
import { strings } from "../../i18n/strings";
import styles from "./Evaluation.module.css";
import { fill } from "./runFormat";

const copy = strings.evaluation.uploadDialog;

function describeRow(row: ApiErrorRow): string {
  if (row.row === 0) {
    return fill(copy.file, { message: row.message });
  }
  return row.field === null
    ? fill(copy.row, { row: row.row, message: row.message })
    : fill(copy.rowField, { row: row.row, field: row.field, message: row.message });
}

export function UploadSetDialog({
  onUploaded,
  onClose,
}: {
  /** Called once the set is stored, whether or not there are warnings to read. */
  onUploaded: (set: EvalSet) => void;
  onClose: () => void;
}) {
  const { showToast } = useToast();

  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [rowErrors, setRowErrors] = useState<ApiErrorRow[]>([]);
  const [imported, setImported] = useState<EvalSet | null>(null);

  const upload = useMutation({
    mutationFn: ({ setName, vignettes }: { setName: string; vignettes: File }) =>
      uploadEvalSet(setName, vignettes),
    onSuccess: (set) => {
      showToast(copy.toast);
      onUploaded(set);
      if (set.warnings.length === 0) {
        onClose();
      } else {
        setImported(set);
      }
    },
    onError: (error) => {
      setNameError(null);
      setFailure(null);
      setRowErrors([]);
      if (!isApiError(error)) {
        setFailure(strings.evaluation.errors.uploadFailed);
      } else if (error.code === ApiErrorCode.evaluationNameInUse) {
        setNameError(copy.nameInUse);
      } else if (error.code === ApiErrorCode.validationError && error.rows.length > 0) {
        setRowErrors(error.rows);
      } else if (error.code === ApiErrorCode.validationError) {
        setFailure(error.message);
      } else if (error.code === ApiErrorCode.forbidden) {
        setFailure(strings.evaluation.errors.forbidden);
      } else {
        setFailure(strings.evaluation.errors.uploadFailed);
      }
    },
  });

  function handleSubmit() {
    const setName = name.trim();
    setNameError(setName === "" ? copy.nameMissing : null);
    setFileError(file === null ? copy.fileMissing : null);
    setFailure(null);
    setRowErrors([]);
    if (setName === "" || file === null) {
      return;
    }
    upload.mutate({ setName, vignettes: file });
  }

  if (imported !== null) {
    return (
      <Dialog title={copy.title} onClose={onClose}>
        <p>{fill(copy.imported, { count: imported.vignette_count })}</p>
        <p className={styles.warningText}>{copy.warningsHeading}</p>
        <ul className={styles.messageList}>
          {imported.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
        <DialogActions>
          <button type="button" className={styles.primary} onClick={onClose}>
            {copy.close}
          </button>
        </DialogActions>
      </Dialog>
    );
  }

  const isBusy = upload.isPending;

  return (
    <Dialog title={copy.title} isBusy={isBusy} onClose={onClose}>
      <div className={styles.field}>
        <label className={styles.label} htmlFor="eval-set-name">
          {copy.nameLabel}
        </label>
        <input
          id="eval-set-name"
          className={styles.input}
          type="text"
          autoComplete="off"
          value={name}
          aria-invalid={nameError !== null}
          onChange={(event) => setName(event.target.value)}
        />
        <p className={styles.fieldError}>{nameError ?? ""}</p>
      </div>

      <div className={styles.field}>
        <label className={styles.label} htmlFor="eval-set-file">
          {copy.fileLabel}
        </label>
        <input
          id="eval-set-file"
          className={styles.input}
          type="file"
          accept=".csv,text/csv"
          aria-invalid={fileError !== null}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <span className={styles.helper}>{copy.fileHelp}</span>
        <p className={styles.fieldError}>{fileError ?? ""}</p>
      </div>

      {failure !== null ? (
        <p className={styles.error} role="alert">
          {failure}
        </p>
      ) : null}

      {rowErrors.length > 0 ? (
        <div className={styles.error} role="alert">
          <p className={styles.errorHeading}>{copy.rowsHeading}</p>
          <ul className={styles.messageList}>
            {rowErrors.map((row, index) => (
              <li key={`${row.row}-${row.field ?? ""}-${index}`}>{describeRow(row)}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <DialogActions>
        <button type="button" className={styles.secondary} disabled={isBusy} onClick={onClose}>
          {copy.cancel}
        </button>
        <button type="button" className={styles.primary} disabled={isBusy} onClick={handleSubmit}>
          {isBusy ? copy.submitting : copy.submit}
        </button>
      </DialogActions>
    </Dialog>
  );
}
