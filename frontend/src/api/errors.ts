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
  internalError: "INTERNAL_ERROR",
  /** Set by the client itself when the request never reached the API. */
  networkError: "NETWORK_ERROR",
} as const;

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

  constructor(status: number, code: string, message: string, field: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.field = field;
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
