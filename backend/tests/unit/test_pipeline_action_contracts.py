"""The action contracts match CLAUDE.md §8.1 and §8.2 exactly.

These are declarations of shape, so the test is about shape: a field renamed
here is a change to the stored `action_suggestions` rows and to what M6b must
return, and it has to be a deliberate change to the ADR first.
"""

import inspect
import uuid

import pytest
from pydantic import ValidationError

from app.models.enums import ActionSource, VTLCategory
from app.pipeline.errors import ActionsFailed, PipelineError
from app.pipeline.stages import ActionSuggester
from app.pipeline.types import ActionPlan, ExtractionOutput, Passage, SuggestedAction


def test_suggested_action_fields_match_the_contract() -> None:
    assert list(SuggestedAction.model_fields) == ["text", "cited_ranks", "source"]


def test_action_plan_fields_match_the_contract() -> None:
    assert list(ActionPlan.model_fields) == [
        "category",
        "baseline",
        "tailored",
        "rejected_count",
        "rejection_reasons",
    ]


def test_a_suggested_action_carries_its_source_and_citations() -> None:
    action = SuggestedAction(
        text="Prepare oxygen and alert the veterinarian.",
        cited_ranks=[1, 3],
        source=ActionSource.AI,
    )

    assert action.source is ActionSource.AI
    assert action.cited_ranks == [1, 3]


def test_a_suggested_action_requires_a_source() -> None:
    """Every row of the W-04 checklist shows where it came from (IR-23)."""
    with pytest.raises(ValidationError):
        SuggestedAction(text="Alert the veterinarian.", cited_ranks=[1])


def test_an_action_plan_keeps_baseline_and_tailored_apart() -> None:
    """Baseline is always present; tailored is best effort (FR-71, FR-72)."""
    plan = ActionPlan(
        category=VTLCategory.RED,
        baseline=["Move the patient to the treatment area now."],
        tailored=[],
        rejected_count=2,
        rejection_reasons=["CONTAINS_DOSE", "NO_VALID_CITATION"],
    )

    assert plan.baseline
    assert plan.tailored == []
    assert plan.rejected_count == 2


def test_actions_failed_is_a_pipeline_error() -> None:
    assert issubclass(ActionsFailed, PipelineError)


class StubActionSuggester:
    """The smallest thing that satisfies the port (CLAUDE.md §8.2)."""

    model_id = "mock"
    prompt_version = "mock-0"
    last_latency_ms = 0

    def suggest(
        self,
        extraction: ExtractionOutput,
        category: VTLCategory,
        passages: list[Passage],
        max_items: int,
    ) -> list[SuggestedAction]:
        return []


def test_a_stage_with_the_right_signature_satisfies_the_protocol() -> None:
    assert isinstance(StubActionSuggester(), ActionSuggester)


def test_something_without_suggest_does_not_satisfy_the_protocol() -> None:
    class NotASuggester:
        model_id = "mock"

    assert not isinstance(NotASuggester(), ActionSuggester)


def test_the_stage_is_never_handed_the_owner_description() -> None:
    """ADR-18 §5: the actions call sees the extraction, the category and the
    passages — never the owner's text, de-identified or not (ADR-10).

    `EntityExtractor.extract` takes a `text` argument; this stage must not, and
    the Protocol is where that is settled rather than left to each caller.
    """
    parameters = set(inspect.signature(ActionSuggester.suggest).parameters)

    assert parameters == {"self", "extraction", "category", "passages", "max_items"}


def test_passage_rank_is_what_an_action_cites() -> None:
    """`cited_ranks` are Passage.rank values, as in DraftRecommendation."""
    passage = Passage(
        rank=1,
        chunk_id=uuid.uuid4(),
        entry_id=uuid.uuid4(),
        entry_title="Fixture entry",
        source_title="Fixture source",
        source_url=None,
        text="Fixture passage.",
        score=0.5,
    )
    action = SuggestedAction(
        text="Recheck breathing effort every few minutes.",
        cited_ranks=[passage.rank],
        source=ActionSource.AI,
    )

    assert action.cited_ranks == [1]
