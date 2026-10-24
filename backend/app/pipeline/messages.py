"""What a failure reason code means to a reviewer, in plain language (P07 §7.1, NFR-09).

The codes in `FailureReason` are the contract between the worker, `jobs.last_error`,
the audit log and the API. The sentences live here, on the server, so the W-06
banner, the audit timeline and any later report say the same thing and the client
carries no copy of the code list.

Every sentence says two things a clinician needs: what stopped, and that the case
is not lost. It never carries a model response, a prompt or anything from the
owner's description — only the code, the number of attempts and the time
(CLAUDE.md §9).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.pipeline.orchestrator import FailureReason

__all__ = ["FALLBACK_MESSAGE", "SAFE_TO_TRIAGE", "failure_message"]

SAFE_TO_TRIAGE = "The case is safe to triage; no data was lost."

FALLBACK_MESSAGE = f"AI processing could not be completed for this case. {SAFE_TO_TRIAGE}"

# The part of the sentence before the optional attempts and time. Codes whose
# cause is a model call say how many attempts were made; the others do not,
# because "after 1 attempt" adds nothing to a knowledge-base failure.
_MESSAGES: dict[str, str] = {
    FailureReason.LLM_TIMEOUT: "The language model did not respond",
    FailureReason.LLM_UNAVAILABLE: "The language model could not be reached",
    FailureReason.LLM_INVALID_OUTPUT: "The language model’s answer could not be read",
    FailureReason.RETRIEVAL_FAILED: "The knowledge base could not be searched",
    FailureReason.GENERATION_FAILED: "The step that recommends a category did not finish",
    FailureReason.DEIDENTIFICATION_FAILED: (
        "The description could not be de-identified, so it was not sent for AI processing"
    ),
    FailureReason.INTERNAL_ERROR: "An unexpected error stopped AI processing",
}

_REPORTS_ATTEMPTS = frozenset(
    {
        FailureReason.LLM_TIMEOUT,
        FailureReason.LLM_UNAVAILABLE,
        FailureReason.LLM_INVALID_OUTPUT,
    }
)


def failure_message(
    code: str,
    *,
    attempts: int | None = None,
    failed_at: datetime | None = None,
    tz: str = "Asia/Manila",
) -> str:
    """The sentence for one reason code.

    "The language model did not respond after 2 attempts (09:20:41). The case is
    safe to triage; no data was lost."

    An unrecognised code gets `FALLBACK_MESSAGE`: a code from a newer build, or one
    written by hand into the audit log, must still produce a banner and must never
    be printed at a clinician. `failed_at` is rendered in `tz`, the clinic's
    display zone; timestamps are stored in UTC (CLAUDE.md §7).
    """
    head = _MESSAGES.get(code)
    if head is None:
        return FALLBACK_MESSAGE

    if attempts is not None and attempts >= 1 and code in _REPORTS_ATTEMPTS:
        head += f" after {attempts} attempt{'' if attempts == 1 else 's'}"
    if failed_at is not None:
        head += f" ({failed_at.astimezone(ZoneInfo(tz)).strftime('%H:%M:%S')})"
    return f"{head}. {SAFE_TO_TRIAGE}"
