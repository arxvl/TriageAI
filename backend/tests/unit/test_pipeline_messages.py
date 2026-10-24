"""The plain-language wording behind each failure code (P07 §7.1 task 2, NFR-09).

The codes are a contract; the sentences are what a reviewer reads on W-06. These
tests keep the two in step: a code added to `FailureReason` without a sentence
fails here, not in front of a clinician.
"""

from datetime import UTC, datetime

import pytest

from app.pipeline.messages import FALLBACK_MESSAGE, SAFE_TO_TRIAGE, failure_message
from app.pipeline.orchestrator import FailureReason

# 01:20:41 UTC is 09:20:41 in Asia/Manila (UTC+8, no daylight saving).
FAILED_AT = datetime(2026, 10, 24, 1, 20, 41, tzinfo=UTC)

SHOWN_TO_REVIEWERS = [
    reason for reason in FailureReason if reason is not FailureReason.CASE_NOT_FOUND
]


def test_the_prompt_lists_exactly_these_codes() -> None:
    assert {reason.value for reason in SHOWN_TO_REVIEWERS} == {
        "LLM_TIMEOUT",
        "LLM_UNAVAILABLE",
        "LLM_INVALID_OUTPUT",
        "RETRIEVAL_FAILED",
        "GENERATION_FAILED",
        "DEIDENTIFICATION_FAILED",
        "INTERNAL_ERROR",
    }


@pytest.mark.parametrize("reason", SHOWN_TO_REVIEWERS, ids=lambda reason: reason.value)
def test_every_code_has_its_own_sentence_that_says_nothing_was_lost(reason: FailureReason) -> None:
    message = failure_message(reason.value)

    assert message != FALLBACK_MESSAGE
    assert message.endswith(SAFE_TO_TRIAGE)
    assert reason.value not in message
    assert "{" not in message and "}" not in message


def test_the_example_wording_from_the_prompt() -> None:
    assert failure_message("LLM_TIMEOUT", attempts=2, failed_at=FAILED_AT) == (
        "The language model did not respond after 2 attempts (09:20:41). "
        "The case is safe to triage; no data was lost."
    )


def test_one_attempt_is_singular() -> None:
    assert "after 1 attempt (" in failure_message(
        "LLM_INVALID_OUTPUT", attempts=1, failed_at=FAILED_AT
    )


def test_the_time_is_shown_in_the_clinic_zone_not_utc() -> None:
    assert "(09:20:41)" in failure_message("INTERNAL_ERROR", failed_at=FAILED_AT)
    assert "(01:20:41)" in failure_message("INTERNAL_ERROR", failed_at=FAILED_AT, tz="UTC")


def test_codes_that_are_not_model_calls_do_not_count_attempts() -> None:
    message = failure_message("RETRIEVAL_FAILED", attempts=3, failed_at=FAILED_AT)

    assert "attempt" not in message


def test_without_a_time_or_attempts_the_sentence_is_still_complete() -> None:
    assert failure_message("LLM_UNAVAILABLE") == (
        "The language model could not be reached. " + SAFE_TO_TRIAGE
    )


@pytest.mark.parametrize("code", ["", "EXTRACTION_TIMEOUT", "SOMETHING_NEW", "CASE_NOT_FOUND"])
def test_an_unrecognised_code_gets_the_general_sentence_never_the_code(code: str) -> None:
    message = failure_message(code, attempts=2, failed_at=FAILED_AT)

    assert message == FALLBACK_MESSAGE
    assert code not in message or code == ""


def test_the_deidentification_message_says_the_text_was_not_sent() -> None:
    assert "not sent" in failure_message("DEIDENTIFICATION_FAILED")
