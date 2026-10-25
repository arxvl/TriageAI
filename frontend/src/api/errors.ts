/**
 * The typed form of the API's single error envelope (backend `core/errors.py`):
 *
 *     {"error": {"code": "INVALID_CREDENTIALS", "message": "..."}}
 *
 * Branch on `code`, never on `status` alone: 401 covers both
 * `NOT_AUTHENTICATED` and `INVALID_CREDENTIALS`, and 403 covers `FORBIDDEN`,
 * `PASSWORD_CHANGE_REQUIRED` and `CSRF_FAILED`.
 *
 * A validation error carries one more key, `field`, naming the input the message
 * belongs to, so a form can show it beside that input rather than at the top of
 * the page (IR-05, FR-04).
 */

/**
 * The codes the frontend reacts to. The API may return others, so `ApiError.code`
 * stays a plain string and this is a lookup rather than a union.
 */
export const ApiErrorCode = {
  notAuthenticated: "NOT_AUTHENTICATED",
  invalidCredentials: "INVALID_CREDENTIALS",
  accountLocked: "ACCOUNT_LOCKED",
  forbidden: "FORBIDDEN",
  passwordChangeRequired: "PASSWORD_CHANGE_REQUIRED",
  csrfFailed: "CSRF_FAILED",
  currentPasswordIncorrect: "CURRENT_PASSWORD_INCORRECT",
  weakPassword: "WEAK_PASSWORD",
  validationError: "VALIDATION_ERROR",
  /** Dog and cat only; anything else is triaged by hand (FR-02, BR-06). */
  speciesOutOfScope: "SPECIES_OUT_OF_SCOPE",
  notFound: "NOT_FOUND",
  /**
   * 409: the case has moved on since the screen read it (FR-32, FR-34, FR-38).
   *
   * Not a field to fix. Someone else decided first, or the case has been closed,
   * so the answer is to re-read the case rather than to re-send the request.
   */
  invalidTransition: "INVALID_TRANSITION",
  /** 409: already decided, so a change has to carry `amends_id` (FR-48). */
  amendmentRequired: "AMENDMENT_REQUIRED",
  /** 409: the change would leave no active administrator (FR-60). */
  lastAdministrator: "LAST_ADMINISTRATOR",
  /** 409, with `field: "email"`: another account has this address (FR-60). */
  emailAlreadyInUse: "EMAIL_ALREADY_IN_USE",
  /** 409, with `field: "name"`: another vignette set has this name (FR-64). */
  evaluationNameInUse: "EVALUATION_NAME_IN_USE",
  /** 409: the run is still queued or running, so it has nothing to export (FR-69). */
  evaluationNotFinished: "EVALUATION_NOT_FINISHED",
  internalError: "INTERNAL_ERROR",
  /** Set by the client itself when the request never reached the API. */
  networkError: "NETWORK_ERROR",
} as const;

/**
 * One row of a file the server refused (FR-64). `row` is the line in the file,
 * counting the header as line 1; 0 means the file or the set name as a whole.
 */
export interface ApiErrorRow {
  row: number;
  field: string | null;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  /**
   * The input this message belongs to, or null when it belongs to no single one.
   *
   * Only validation errors carry it, and only ever one at a time: the server
   * reports the first failure it finds (`_first_validation_message`). A form
   * that wants every field checked at once has to do that itself.
   */
  readonly field: string | null;
  /**
   * The per-row problems of a refused file upload, in file order; empty for every
   * other error. Only the vignette import sends them (`InvalidVignetteFile`).
   */
  readonly rows: ApiErrorRow[];

  constructor(
    status: number,
    code: string,
    message: string,
    field: string | null = null,
    rows: ApiErrorRow[] = [],
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.field = field;
    this.rows = rows;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/** True when the error means "this session is no longer usable". */
export function isSessionEnded(error: unknown): boolean {
  if (!isApiError(error)) {
    return false;
  }
  // CSRF_FAILED belongs here too: the CSRF cookie is issued only at login and
  // never refreshed, so it expires 30 minutes after sign-in even while the
  // session cookie keeps sliding. From the user's side that is a dead session.
  return error.code === ApiErrorCode.notAuthenticated || error.code === ApiErrorCode.csrfFailed;
}
