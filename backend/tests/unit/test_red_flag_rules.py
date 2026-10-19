"""Which rules the safety floor may use, per environment (P08 §8.1, NFR-08).

The red-flag floor cannot be switched off, so this query is the only control
over it. Two things have to hold at once:

* outside development, a rule nobody has approved never screens a case (BR-04);
* in development, the seeded placeholders do, or the keyword screener (M1) and
  the walkthrough would have nothing to match against.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppEnv
from app.models import Species, UserRole, VTLCategory
from app.services.red_flag_rules import (
    active_rules_provider,
    get_active_rules,
    is_active_rule,
)
from tests.conftest import make_red_flag_rule, make_user

ENVIRONMENTS = [AppEnv.DEV, AppEnv.TEST, AppEnv.PROD]


def _approver(session: Session):
    return make_user(session, role=UserRole.VETERINARY_REVIEWER, can_approve_kb=True)


def codes(session: Session, app_env: AppEnv) -> list[str]:
    return [rule.code for rule in get_active_rules(session, app_env)]


@pytest.mark.parametrize("app_env", ENVIRONMENTS)
def test_an_approved_rule_is_active_everywhere(db_session: Session, app_env: AppEnv) -> None:
    make_red_flag_rule(db_session, code="FIXTURE_APPROVED_RULE", approved_by=_approver(db_session))

    assert "FIXTURE_APPROVED_RULE" in codes(db_session, app_env)


def test_a_placeholder_is_active_in_development_only(db_session: Session) -> None:
    """The seeded eight are drawn from a published source but unapproved."""
    make_red_flag_rule(db_session, code="FIXTURE_PLACEHOLDER_RULE", is_placeholder=True)

    assert "FIXTURE_PLACEHOLDER_RULE" in codes(db_session, AppEnv.DEV)
    assert "FIXTURE_PLACEHOLDER_RULE" not in codes(db_session, AppEnv.PROD)
    assert "FIXTURE_PLACEHOLDER_RULE" not in codes(db_session, AppEnv.TEST)


def test_an_unapproved_rule_that_is_not_a_placeholder_is_active_nowhere(
    db_session: Session,
) -> None:
    """A rule typed into W-08 screens nothing until it has been approved."""
    make_red_flag_rule(db_session, code="FIXTURE_NEW_RULE", is_placeholder=False)

    for app_env in ENVIRONMENTS:
        assert "FIXTURE_NEW_RULE" not in codes(db_session, app_env)


@pytest.mark.parametrize("app_env", ENVIRONMENTS)
def test_a_retired_rule_is_active_nowhere(db_session: Session, app_env: AppEnv) -> None:
    """Retired rules are kept so an old recommendation stays explainable."""
    make_red_flag_rule(
        db_session,
        code="FIXTURE_RETIRED_RULE",
        approved_by=_approver(db_session),
        retired_at=datetime.now(UTC),
    )

    assert "FIXTURE_RETIRED_RULE" not in codes(db_session, app_env)


def test_a_retired_placeholder_is_not_resurrected_by_development(db_session: Session) -> None:
    make_red_flag_rule(
        db_session,
        code="FIXTURE_RETIRED_PLACEHOLDER",
        is_placeholder=True,
        retired_at=datetime.now(UTC),
    )

    assert "FIXTURE_RETIRED_PLACEHOLDER" not in codes(db_session, AppEnv.DEV)


def test_rules_come_back_ordered_by_code(db_session: Session) -> None:
    approver = _approver(db_session)
    for code in ("FIXTURE_ZZZ", "FIXTURE_AAA", "FIXTURE_MMM"):
        make_red_flag_rule(db_session, code=code, approved_by=approver)

    active = [code for code in codes(db_session, AppEnv.PROD) if code.startswith("FIXTURE_")]

    assert active == sorted(active)


def test_min_category_and_species_survive_the_read(db_session: Session) -> None:
    """The screener reads both off the rule, so they have to come back typed."""
    make_red_flag_rule(
        db_session,
        code="FIXTURE_CAT_ONLY",
        min_category=VTLCategory.ORANGE,
        species=(Species.CAT,),
        approved_by=_approver(db_session),
    )

    rule = next(
        rule
        for rule in get_active_rules(db_session, AppEnv.PROD)
        if rule.code == "FIXTURE_CAT_ONLY"
    )

    assert rule.min_category is VTLCategory.ORANGE
    assert rule.species == [Species.CAT]


# --- `is_active_rule`, the same answer for the W-08 table ----------------


def test_is_active_rule_agrees_with_the_query(db_session: Session) -> None:
    """The rules table must not claim a rule is screening when it is not."""
    approver = _approver(db_session)
    approved = make_red_flag_rule(db_session, code="FIXTURE_AGREE_1", approved_by=approver)
    placeholder = make_red_flag_rule(db_session, code="FIXTURE_AGREE_2", is_placeholder=True)
    retired = make_red_flag_rule(
        db_session, code="FIXTURE_AGREE_3", approved_by=approver, retired_at=datetime.now(UTC)
    )

    for app_env in ENVIRONMENTS:
        active = set(codes(db_session, app_env))
        for rule in (approved, placeholder, retired):
            assert is_active_rule(rule, app_env) is (rule.code in active), (rule.code, app_env)


# --- The provider the registry injects (FR-12, FR-23) --------------------


def test_the_provider_reads_the_table_on_every_call(
    db_session: Session, app_session_factory: sessionmaker
) -> None:
    """A rule approved while the worker runs must fire on the next case."""
    provider = active_rules_provider(app_session_factory, AppEnv.PROD)
    before = {rule.code for rule in provider()}

    make_red_flag_rule(db_session, code="FIXTURE_LATE_RULE", approved_by=_approver(db_session))
    db_session.commit()

    after = {rule.code for rule in provider()}

    assert "FIXTURE_LATE_RULE" not in before
    assert "FIXTURE_LATE_RULE" in after
