"""The pipeline error hierarchy (P05 §5.1 task 3).

Two things matter here. Every failure must be catchable as one `PipelineError`,
because the orchestrator's failure path is a single `except` that must not let a
case escape into `PROCESSING` forever (NFR-09, ADR-08). And none of them may be
an `AppError`: the pipeline runs in a background worker, and a pipeline failure
must never become an HTTP response body that could carry internal detail to a
browser (IR-05).
"""

import pytest

from app.core.errors import AppError
from app.pipeline.errors import (
    ExtractionFailed,
    GenerationFailed,
    LLMInvalidOutput,
    LLMTimeout,
    LLMUnavailable,
    PipelineError,
    RetrievalFailed,
)
from app.pipeline.registry import StageNotImplementedError, UnsafePipelineConfigError

PIPELINE_ERRORS = [
    LLMTimeout,
    LLMUnavailable,
    LLMInvalidOutput,
    ExtractionFailed,
    RetrievalFailed,
    GenerationFailed,
    StageNotImplementedError,
    UnsafePipelineConfigError,
]


@pytest.mark.parametrize("error", PIPELINE_ERRORS, ids=lambda e: e.__name__)
def test_every_error_is_a_pipeline_error(error: type[Exception]) -> None:
    assert issubclass(error, PipelineError)


@pytest.mark.parametrize("error", PIPELINE_ERRORS, ids=lambda e: e.__name__)
def test_no_pipeline_error_is_an_app_error(error: type[Exception]) -> None:
    assert not issubclass(error, AppError)


@pytest.mark.parametrize("error", PIPELINE_ERRORS, ids=lambda e: e.__name__)
def test_one_except_clause_catches_them_all(error: type[Exception]) -> None:
    with pytest.raises(PipelineError):
        raise error("fictitious failure")


def test_errors_named_by_the_phase_prompt_all_exist() -> None:
    """P05 §5.1 task 3 fixes the six runtime errors by name."""
    from app.pipeline import errors

    assert {name for name in vars(errors) if name.endswith(("Timeout", "Failed", "Output"))} >= {
        "LLMTimeout",
        "LLMInvalidOutput",
        "ExtractionFailed",
        "RetrievalFailed",
        "GenerationFailed",
    }
