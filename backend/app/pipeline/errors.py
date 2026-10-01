"""Failures the pipeline can raise (CLAUDE.md §8, P05 §5.1 task 3).

These are plain exceptions. They deliberately do **not** subclass
`app.core.errors.AppError`: nothing here is ever rendered to a browser. The
pipeline runs in a background worker, not in a request (ADR-08), so the only
caller is the orchestrator, which maps any of them to the failure path — the case
moves to `MANUAL_TRIAGE_REQUIRED` with a reason code, and the case is never lost
and never left in `PROCESSING` (NFR-09, ADR-08).

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


class ExtractionFailed(PipelineError):
    """The extraction stage could not produce an `ExtractionOutput`."""


class RetrievalFailed(PipelineError):
    """The retrieval stage could not produce passages."""


class GenerationFailed(PipelineError):
    """The generation stage could not produce a `DraftRecommendation`."""
