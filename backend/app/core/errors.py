"""Application errors and the single response envelope for every 4xx and 5xx.

Every error response has the same shape (P03 task 8, IR-05):

    {"error": {"code": "INVALID_CREDENTIALS", "message": "..."}}

`AppError` and its subclasses are plain exceptions with no web framework in
sight, so services can raise them without importing FastAPI (CLAUDE.md §7).
`register_error_handlers` is the only part that touches FastAPI, and it imports
it inside the function so that `import app.core.errors` stays framework-free.

A validation error carries one extra key, `field`, naming the input it belongs
to so the form can show the message beside it rather than at the top of the page
(IR-05, FR-04):

    {"error": {"code": "VALIDATION_ERROR",
               "message": "Enter the weight as a number, e.g. 4.2.",
               "field": "weight_kg"}}

Messages here are user-facing: plain language, no stack traces, no technical
codes in the prose (IR-05). The per-field wording lives in
`core/validation_messages.py`.
"""

import logging
from typing import TYPE_CHECKING, Any

from app.core.validation_messages import field_from_location, plain_message

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# One message for every cause of a failed login, so the API cannot be used to
# discover which e-mail addresses have accounts (SR-03, ADR-11).
GENERIC_LOGIN_FAILURE_MESSAGE = "Incorrect username or password."


def error_body(code: str, message: str, field: str | None = None) -> dict[str, dict[str, str]]:
    """The one response envelope. `field` is omitted unless there is one."""
    error: dict[str, str] = {"code": code, "message": message}
    if field is not None:
        error["field"] = field
    return {"error": error}


class AppError(Exception):
    """An error with a stable code and a message that may reach the user."""

    code = "INTERNAL_ERROR"
    status_code = 500
    message = "Something went wrong. Please try again."

    def __init__(self, message: str | None = None) -> None:
        if message is not None:
            self.message = message
        super().__init__(self.message)

    def body(self) -> dict[str, dict[str, str]]:
        return error_body(self.code, self.message)


class NotAuthenticated(AppError):
    code = "NOT_AUTHENTICATED"
    status_code = 401
    message = "Please sign in to continue."


class InvalidCredentials(AppError):
    code = "INVALID_CREDENTIALS"
    status_code = 401
    message = GENERIC_LOGIN_FAILURE_MESSAGE


class AccountLocked(AppError):
    code = "ACCOUNT_LOCKED"
    status_code = 423
    message = "This account is temporarily locked."


class Forbidden(AppError):
    code = "FORBIDDEN"
    status_code = 403
    message = "You do not have permission to do that."


class PasswordChangeRequired(AppError):
    code = "PASSWORD_CHANGE_REQUIRED"
    status_code = 403
    message = "Please change your temporary password before continuing."


class CurrentPasswordIncorrect(AppError):
    code = "CURRENT_PASSWORD_INCORRECT"
    status_code = 400
    message = "The current password is incorrect."


class WeakPassword(AppError):
    code = "WEAK_PASSWORD"
    status_code = 400
    message = "The new password does not meet the password policy."


class SpeciesOutOfScope(AppError):
    """FR-02, BR-06: dogs and cats only; anything else is triaged by hand.

    A 422 rather than a 400: the request is well formed, and the species field is
    the one the form should point at.
    """

    code = "SPECIES_OUT_OF_SCOPE"
    status_code = 422
    message = "Other species are not processed by the AI and must be triaged manually."


class CaseNotFound(AppError):
    code = "NOT_FOUND"
    status_code = 404
    message = "That case could not be found."


class InvalidCaseTransition(AppError):
    """409: the case is not in a state where this action is allowed.

    A conflict, not a validation failure: the request is well formed and would
    have been correct a moment ago or on another case. The reviewer's screen is
    simply out of date — someone else decided first, or the case has been closed
    — so the client should re-read the case rather than fix a field (FR-32,
    FR-34, FR-38).
    """

    code = "INVALID_TRANSITION"
    status_code = 409
    message = "This case is no longer in a state where that action is allowed."


class AmendmentRequired(AppError):
    """409: the case is already decided, so a change must be an amendment.

    A finalized decision is never edited and never silently replaced (FR-48,
    ADR-12). Recording a different one means sending `amends_id`, which keeps
    the original row and the reason it was superseded.
    """

    code = "AMENDMENT_REQUIRED"
    status_code = 409
    message = (
        "This case has already been decided. Record a correction as an amendment, "
        "which keeps the original decision and its reason."
    )


class InvalidDecision(AppError):
    """422: the decision is well formed but its fields do not agree.

    Whether a decision needs a category, a reason code or a note depends on its
    type, and a cross-field rule has no Pydantic error type to key wording on —
    so these are raised by `ReviewService` instead, and carry the field the form
    should point at, exactly as a Pydantic failure would (IR-05, FR-33, FR-34).
    """

    code = "VALIDATION_ERROR"
    status_code = 422
    message = "Some of the information you entered is not valid."

    def __init__(self, message: str | None = None, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)

    def body(self) -> dict[str, dict[str, str]]:
        return error_body(self.code, self.message, self.field)


class InvalidCorrection(AppError):
    """422: an extraction correction is well formed but cannot be accepted.

    The cross-field rules — a complaint code the clinic does not have, no primary
    complaint, nothing actually changed — have no Pydantic error type to key
    wording on, so `ReviewService` raises them with the field the panel should
    point at (IR-05, FR-27).
    """

    code = "VALIDATION_ERROR"
    status_code = 422
    message = "Some of the information you entered is not valid."

    def __init__(self, message: str | None = None, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)

    def body(self) -> dict[str, dict[str, str]]:
        return error_body(self.code, self.message, self.field)


class KBNotFound(AppError):
    """404 for anything under `/kb`: an entry, a rule, or a version.

    One class with a message per caller rather than three near-identical ones.
    The code is the same `NOT_FOUND` the rest of the API answers, so a client
    needs no new branch (IR-05).
    """

    code = "NOT_FOUND"
    status_code = 404
    message = "That knowledge-base record could not be found."


class InvalidKBTransition(AppError):
    """409: the entry or rule is not in a state where this action is allowed.

    The same conflict as `InvalidCaseTransition` and for the same reason: the
    request is well formed and would have been correct a moment ago — somebody
    else approved, rejected or retired first — so the client should re-read the
    entry rather than fix a field (FR-51, ADR-14).
    """

    code = "INVALID_TRANSITION"
    status_code = 409
    message = "This record is no longer in a state where that action is allowed."


class InvalidKBEntry(AppError):
    """422: the entry is well formed but incomplete or out of bounds.

    Raised by `KBService` for the FR-50 completeness rules, which are checked
    again on submit because an imported draft can be missing a citation that
    `KBEntryCreate` would have required (8.2). Carries the field the editor
    should point at, exactly as a Pydantic failure does (IR-05).
    """

    code = "VALIDATION_ERROR"
    status_code = 422
    message = "Some of the information in this entry is not valid."

    def __init__(self, message: str | None = None, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)

    def body(self) -> dict[str, dict[str, str]]:
        return error_body(self.code, self.message, self.field)


class VersionPublishConflict(AppError):
    """409: another knowledge-base version was published at the same instant.

    `kb_versions.version_no` is unique, which is what makes a version number
    mean something. Two publications racing for the same number is rare — one
    worker and a handful of administrators — and the honest answer is to say so
    and let the caller retry, rather than renumber silently (FR-54, DR-05).
    """

    code = "VERSION_PUBLISH_CONFLICT"
    status_code = 409
    message = (
        "Another knowledge-base version was published just now. "
        "Reload the knowledge base and try again."
    )


class UserNotFound(AppError):
    """404: no account has that id (FR-60)."""

    code = "NOT_FOUND"
    status_code = 404
    message = "That user account could not be found."


class LastAdministrator(AppError):
    """409: the change would leave the system with no active administrator.

    Nobody could then create accounts, unlock anybody, or reset a password, and
    only a database edit would recover it (FR-60). A conflict rather than a
    validation error: the same request is fine once a second administrator is
    active.
    """

    code = "LAST_ADMINISTRATOR"
    status_code = 409
    message = (
        "This is the only active administrator. Add or reactivate another "
        "administrator before changing this account."
    )


class EmailAlreadyInUse(AppError):
    """409: another account already uses this e-mail address."""

    code = "EMAIL_ALREADY_IN_USE"
    status_code = 409
    message = "Another account already uses that e-mail address."

    def body(self) -> dict[str, dict[str, str]]:
        return error_body(self.code, self.message, "email")


class InvalidUserUpdate(AppError):
    """422: the account fields contradict each other.

    Only the knowledge-base approval rule can do this today: the permission
    belongs to a Veterinary Reviewer and to nobody else (BR-04, FR-58). Checked
    in the service so the answer names the field instead of surfacing the
    database constraint.
    """

    code = "VALIDATION_ERROR"
    status_code = 422
    message = "Some of the information for this account is not valid."

    def __init__(self, message: str | None = None, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)

    def body(self) -> dict[str, dict[str, str]]:
        return error_body(self.code, self.message, self.field)


class CSRFFailed(AppError):
    code = "CSRF_FAILED"
    status_code = 403
    message = "Your session could not be verified. Please reload the page and try again."


def register_error_handlers(app: "FastAPI") -> None:
    """Install the handlers that render every error in the envelope above."""
    # Imported here, not at module scope: services import this module and must
    # stay free of FastAPI (CLAUDE.md §7).
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, error: AppError) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content=error.body())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        field, message = _first_validation_message(error.errors())
        return JSONResponse(
            status_code=422,
            content=error_body("VALIDATION_ERROR", message, field),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, error: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(error.status_code, "HTTP_ERROR")
        message = error.detail if isinstance(error.detail, str) else code
        return JSONResponse(status_code=error.status_code, content=error_body(code, message))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        # Log the cause for operators; never return it (IR-05, SR-09).
        logger.exception(
            "unhandled error", extra={"path": request.url.path, "method": request.method}
        )
        fallback = AppError()
        return JSONResponse(status_code=fallback.status_code, content=fallback.body())


_HTTP_STATUS_CODES = {
    401: "NOT_AUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    423: "ACCOUNT_LOCKED",
}


def _first_validation_message(errors: list[Any]) -> tuple[str | None, str]:
    """The field and the sentence for the first error Pydantic reported.

    Only the first is reported. A form that submits one field at a time needs no
    more, and a list of every simultaneous failure is how an error display turns
    into a wall of text (IR-05).

    A field with registered wording gets it. Anything else falls back to
    Pydantic's own message, prefixed with the field so the sentence still says
    where the problem is — worse wording, never a missing message.
    """
    if not errors:
        return None, "Some of the information you entered is not valid."

    first = errors[0]
    field = field_from_location(first.get("loc", ()))
    plain = plain_message(field, str(first.get("type", "")))
    if plain is not None:
        return field, plain

    fallback = first.get("msg", "is not valid")
    return field, f"{field}: {fallback}" if field else fallback
