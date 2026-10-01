/**
 * The typed form of the API's single error envelope (backend `core/errors.py`):
 *
 *     {"error": {"code": "INVALID_CREDENTIALS", "message": "..."}}
 *
 * Branch on `code`, never on `status` alone: 401 covers both
 * `NOT_AUTHENTICATED` and `INVALID_CREDENTIALS`, and 403 covers `FORBIDDEN`,
 * `PASSWORD_CHANGE_REQUIRED` and `CSRF_FAILED`.
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
  internalError: "INTERNAL_ERROR",
  /** Set by the client itself when the request never reached the API. */
  networkError: "NETWORK_ERROR",
} as const;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
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
