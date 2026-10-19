"""Which red-flag rules are screening cases right now (P08 §8.1 task 4, NFR-08).

The red-flag safety floor cannot be switched off, so the only control over it is
*which rules it knows about*. That is this function, and it is read fresh on
every case: a rule approved while the worker is running must take effect on the
next case, and a retired one must stop firing immediately (FR-12, FR-23).

Three rules decide membership:

* **Retired rules never fire.** They are kept so a recommendation whose floor
  cited one stays explainable (ADR-14), and that is all.
* **Approved rules always fire.** Approval by an account holding
  `can_approve_kb` is what NFR-08 and BR-04 require before a rule may change
  triage.
* **Placeholder rules fire in development only.** The eight rules
  `scripts/seed.py` writes are drawn from the published triage list but have not
  been through the approval workflow. Excluding them outside development is what
  stops unapproved content from influencing a real clinic; including them in
  development is what lets the keyword screener (M1) and the walkthrough work
  before the team has approved anything.

`KeywordRedFlagScreener` already depends on exactly this contract: a rule this
function omits "never fires", because the screener looks each matched code up in
the list and skips what is not there.
"""

import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppEnv
from app.models import RedFlagRule

logger = logging.getLogger(__name__)

__all__ = ["active_rules_provider", "get_active_rules", "is_active_rule"]


def get_active_rules(session: Session, app_env: AppEnv) -> list[RedFlagRule]:
    """The rules the safety floor and the keyword screener may use.

    Ordered by code, so a log line or a test comparing two reads of the same
    table sees them in the same order.
    """
    statement = (
        select(RedFlagRule).where(RedFlagRule.retired_at.is_(None)).order_by(RedFlagRule.code)
    )
    if app_env is AppEnv.DEV:
        statement = statement.where(
            RedFlagRule.approved_at.is_not(None) | RedFlagRule.is_placeholder.is_(True)
        )
    else:
        statement = statement.where(RedFlagRule.approved_at.is_not(None))
    return list(session.scalars(statement))


def is_active_rule(rule: RedFlagRule, app_env: AppEnv) -> bool:
    """The same answer for one rule already in hand, for the W-08 rules table.

    Kept beside `get_active_rules` rather than re-derived in a schema, so the
    table cannot claim a rule is screening cases when the query would exclude it.
    """
    if rule.retired_at is not None:
        return False
    if rule.approved_at is not None:
        return True
    return app_env is AppEnv.DEV and rule.is_placeholder


def active_rules_provider(
    session_factory: sessionmaker, app_env: AppEnv
) -> Callable[[], list[RedFlagRule]]:
    """The `rules_provider` the registry injects into the screening stages.

    A fresh session per call, not a cached list: see the module docstring. The
    callable takes no arguments because `PipelineDeps.rules_provider` is what
    every stage is handed (CLAUDE.md §8.3).
    """

    def provider() -> list[RedFlagRule]:
        with session_factory() as session:
            return get_active_rules(session, app_env)

    return provider
