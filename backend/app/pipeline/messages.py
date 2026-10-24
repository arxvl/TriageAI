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

from app.pipeline.orchestrator import ActionsFailureReason, FailureReason

__all__ = [
    "ACTIONS_FALLBACK_MESSAGE",
    "BASELINE_ONLY",
    "FALLBACK_MESSAGE",
    "REGENERATION_FALLBACK_MESSAGE",
    "SAFE_TO_TRIAGE",
    "STILL_NEEDS_DECISION",
    "actions_failure_message",
    "failure_message",
    "regeneration_failure_message",
]

SAFE_TO_TRIAGE = "The case is safe to triage; no data was lost."

FALLBACK_MESSAGE = f"AI processing could not be completed for this case. {SAFE_TO_TRIAGE}"

# What a reviewer needs to hear when a *regeneration* fails instead: nothing was
# lost, the correction was saved, and the recommendation they were looking at is
# still there to decide on (P07 §7.2, NFR-09).
STILL_NEEDS_DECISION = (
    "Your correction was saved and the previous recommendation is unchanged. "
    "It still needs your decision; you can save again to try once more."
)

REGENERATION_FALLBACK_MESSAGE = (
    f"A new recommendation could not be made after the correction. {STILL_NEEDS_DECISION}"
)

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


def _head(code: str, attempts: int | None, failed_at: datetime | None, tz: str) -> str | None:
    """The sentence before the closing line: what stopped, how often, and when."""
    head = _MESSAGES.get(code)
    if head is None:
        return None

    if attempts is not None and attempts >= 1 and code in _REPORTS_ATTEMPTS:
        head += f" after {attempts} attempt{'' if attempts == 1 else 's'}"
    if failed_at is not None:
        head += f" ({failed_at.astimezone(ZoneInfo(tz)).strftime('%H:%M:%S')})"
    return head


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
    head = _head(code, attempts, failed_at, tz)
    if head is None:
        return FALLBACK_MESSAGE
    return f"{head}. {SAFE_TO_TRIAGE}"


def regeneration_failure_message(
    code: str,
    *,
    attempts: int | None = None,
    failed_at: datetime | None = None,
    tz: str = "Asia/Manila",
) -> str:
    """The sentence for a failed regeneration (P07 §7.2).

    The same reason codes and the same opening as `failure_message`, with a
    different close: the case is not waiting for manual triage, it is waiting for
    a decision on the recommendation it already has.
    """
    head = _head(code, attempts, failed_at, tz)
    if head is None:
        return REGENERATION_FALLBACK_MESSAGE
    return f"{head}. {STILL_NEEDS_DECISION}"


# What a reviewer needs to hear when the *suggested actions* could not be made
# (P07 §7.2b, FR-77, ADR-18 §3): the case-specific list is missing, nothing else
# is. The baseline set is read from the knowledge base and is on screen, and the
# category and any decision are exactly as they were.
BASELINE_ONLY = "The baseline actions are shown; the category and your decision are unchanged."

ACTIONS_FALLBACK_MESSAGE = f"Case-specific suggestions could not be made. {BASELINE_ONLY}"

_ACTIONS_MESSAGES: dict[str, str] = {
    ActionsFailureReason.ACTIONS_TIMEOUT: (
        "The language model did not respond with suggested actions"
    ),
    ActionsFailureReason.ACTIONS_UNAVAILABLE: (
        "The language model could not be reached for suggested actions"
    ),
    ActionsFailureReason.ACTIONS_INVALID_OUTPUT: (
        "The language model’s suggested actions could not be read"
    ),
    ActionsFailureReason.ACTIONS_ALL_REJECTED: (
        "None of the suggested actions passed the safety checks"
    ),
    ActionsFailureReason.ACTIONS_INPUT_UNUSABLE: (
        "The stored extraction could not be read to suggest actions"
    ),
    ActionsFailureReason.ACTIONS_UNEXPECTED_ERROR: (
        "An unexpected error stopped the suggested actions"
    ),
}


def actions_failure_message(
    code: str,
    *,
    failed_at: datetime | None = None,
    tz: str = "Asia/Manila",
) -> str:
    """The sentence for one suggested-actions reason code.

    "The language model did not respond with suggested actions (09:20:41). The
    baseline actions are shown; the category and your decision are unchanged."

    No attempt count: the actions stage is called once, by design (ADR-18 §3).
    An unrecognised code gets `ACTIONS_FALLBACK_MESSAGE`, as `failure_message`
    does, and for the same reason. Never carries action text (SR-17).
    """
    head = _ACTIONS_MESSAGES.get(code)
    if head is None:
        return ACTIONS_FALLBACK_MESSAGE
    if failed_at is not None:
        head += f" ({failed_at.astimezone(ZoneInfo(tz)).strftime('%H:%M:%S')})"
    return f"{head}. {BASELINE_ONLY}"
