"""Failures the pipeline can raise (CLAUDE.md §8, P05 §5.1 task 3).

These are plain exceptions. They deliberately do **not** subclass
`app.core.errors.AppError`: nothing here is ever rendered to a browser. The
pipeline runs in a background worker, not in a request (ADR-08), so the only
caller is the orchestrator, which maps any of them to the failure path — the case
moves to `MANUAL_TRIAGE_REQUIRED` with a reason code, and the case is never lost
and never left in `PROCESSING` (NFR-09, ADR-08).

`ActionsFailed` is the one exception to that mapping: suggested actions are not
part of the triage decision, so the orchestrator records `actions_status =
failed` with a reason code, leaves the case in `AWAITING_REVIEW` and shows the
baseline actions on their own. It never routes the case to manual triage
(FR-77, ADR-18 §3).

The split is between *transport* failures of a provider (`LLMTimeout`,
`LLMUnavailable`, `LLMInvalidOutput`, raised by an `LLMProvider`) and *stage*
failures (`ExtractionFailed`, `RetrievalFailed`, `GenerationFailed`, raised by a
stage after it has exhausted its retries). Only `LLMInvalidOutput` is worth
retrying — a schema violation is often transient, a timeout under load is not —
and that retry decision belongs to the orchestrator, not here.

Messages are for the log and the job's `last_error`. They must never contain the
owner's description, a prompt or a model response (CLAUDE.md §9).
"""


class PipelineError(Exception):
    """Base for every pipeline failure."""


class LLMTimeout(PipelineError):
    """The provider did not answer within `timeout_s`."""


class LLMUnavailable(PipelineError):
    """The provider could not be reached, refused the request, or rate-limited it."""


class LLMInvalidOutput(PipelineError):
    """The provider answered, but not with JSON matching the requested schema."""


class DeidentificationFailed(PipelineError):
    """The de-identifier could not produce text that is safe to send onward.

    Raised by a de-identifier, and also what the orchestrator turns *any*
    exception from that stage into: the run fails closed and no later stage sees
    the description (IR-20, ADR-10).
    """


class ExtractionFailed(PipelineError):
    """The extraction stage could not produce an `ExtractionOutput`."""


class RetrievalFailed(PipelineError):
    """The retrieval stage could not produce passages."""


class GenerationFailed(PipelineError):
    """The generation stage could not produce a `DraftRecommendation`."""


class ActionsFailed(PipelineError):
    """The actions stage could not produce suggested actions.

    Non-blocking, unlike every other failure here: the recommendation is already
    stored and the case stays in `AWAITING_REVIEW` with its baseline actions
    (FR-77). Only `recommendations.actions_status` and `actions_error` change.
    """
