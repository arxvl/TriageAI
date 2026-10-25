"""The W-07 filter model (FR-44): defaults, paging arithmetic, and validation."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.models import VTLCategory
from app.schemas.case import HISTORY_DEFAULT_LIMIT, CaseHistoryFilters, CaseScope


def test_defaults_are_the_first_page_of_twenty_five() -> None:
    filters = CaseHistoryFilters()

    assert (filters.page, filters.limit) == (1, HISTORY_DEFAULT_LIMIT) == (1, 25)
    assert filters.offset == 0
    assert filters.disagreement is False


@pytest.mark.parametrize(("page", "limit", "offset"), [(1, 25, 0), (2, 25, 25), (4, 10, 30)])
def test_the_offset_follows_the_page(page: int, limit: int, offset: int) -> None:
    assert CaseHistoryFilters(page=page, limit=limit).offset == offset


@pytest.mark.parametrize("params", [{"page": 0}, {"limit": 0}, {"limit": 501}])
def test_paging_is_bounded(params: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        CaseHistoryFilters(**params)


def test_an_unknown_parameter_is_refused() -> None:
    with pytest.raises(ValidationError):
        CaseHistoryFilters.model_validate({"q": "Max"})


def test_blank_text_means_not_given() -> None:
    filters = CaseHistoryFilters(case_no="   ", complaint_code="")

    assert filters.case_no is None
    assert filters.complaint_code is None


def test_text_is_trimmed() -> None:
    assert CaseHistoryFilters(case_no=" C-0137 ").case_no == "C-0137"


def test_an_end_date_before_the_start_date_is_refused() -> None:
    with pytest.raises(ValidationError) as caught:
        CaseHistoryFilters(date_from=date(2026, 10, 12), date_to=date(2026, 10, 11))

    assert caught.value.errors()[0]["loc"] == ("date_to",)


def test_a_single_day_range_is_allowed() -> None:
    filters = CaseHistoryFilters(date_from=date(2026, 10, 11), date_to=date(2026, 10, 11))

    assert filters.date_from == filters.date_to


def test_categories_are_the_five_vtl_values() -> None:
    assert CaseHistoryFilters(ai_category="RED").ai_category is VTLCategory.RED
    with pytest.raises(ValidationError):
        CaseHistoryFilters(final_category="MANUAL")


def test_the_scopes_are_queue_and_history() -> None:
    assert {scope.value for scope in CaseScope} == {"queue", "history"}
