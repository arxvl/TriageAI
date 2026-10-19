"""Which knowledge-base status allows which action, as one explicit table.

The lifecycle is FR-51 and ADR-14: Draft → Pending Review → Active → Retired,
with rejection sending an entry back to Draft. Two moves must not be possible,
and they are the reason this table exists rather than a chain of `if`s inside
the service:

* **An ACTIVE entry is never edited.** Retrieval cites entries by id, and a
  recommendation made last week must still mean what it said. A change to
  active content is a new draft revision, never an edit (ADR-14, DR-05).
* **Nothing reaches ACTIVE without an approval.** `APPROVE` is allowed from
  `PENDING_REVIEW` alone, and the only code that writes `ACTIVE` is the
  `KB_INDEX` job the approval enqueues (FR-52, BR-04).

Red-flag rules have no status column — they are unapproved, approved, or retired
— so their two guards are functions here rather than a table.

Nothing in this module touches a session, a request or FastAPI: it answers
questions about enum values and two timestamps (CLAUDE.md §7).
"""

from enum import StrEnum

from app.core.errors import InvalidKBTransition
from app.models import KBEntryStatus, RedFlagRule

__all__ = [
    "ENTRY_ACTION_FROM",
    "ENTRY_ACTION_TO",
    "KBEntryAction",
    "require_entry_action_allowed",
    "require_rule_editable",
    "require_rule_not_approved",
    "require_rule_retirable",
]


class KBEntryAction(StrEnum):
    """What someone is asking to do to an entry.

    Not a database enum: these are the five endpoints under
    `/kb/entries/{id}`, not a stored value.
    """

    EDIT = "EDIT"
    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RETIRE = "RETIRE"


# Where each action may be asked for.
#
# EDIT and SUBMIT are the author's and belong to DRAFT only. APPROVE and REJECT
# are the approver's answer to a submission, so both require PENDING_REVIEW —
# including REJECT, because sending back a draft that was never submitted would
# record a review that nobody asked for. RETIRE applies to live content alone:
# a draft that should not exist is left as a draft, not retired, so RETIRED keeps
# meaning "this was active once".
ENTRY_ACTION_FROM: dict[KBEntryAction, frozenset[KBEntryStatus]] = {
    KBEntryAction.EDIT: frozenset({KBEntryStatus.DRAFT}),
    KBEntryAction.SUBMIT: frozenset({KBEntryStatus.DRAFT}),
    KBEntryAction.APPROVE: frozenset({KBEntryStatus.PENDING_REVIEW}),
    KBEntryAction.REJECT: frozenset({KBEntryStatus.PENDING_REVIEW}),
    KBEntryAction.RETIRE: frozenset({KBEntryStatus.ACTIVE}),
}

# Where the entry lands. `EDIT` and `APPROVE` are absent on purpose: an edit
# leaves the status where it was, and an approval moves the entry only once the
# `KB_INDEX` job has indexed it (FR-53), so the request itself changes nothing.
ENTRY_ACTION_TO: dict[KBEntryAction, KBEntryStatus] = {
    KBEntryAction.SUBMIT: KBEntryStatus.PENDING_REVIEW,
    KBEntryAction.REJECT: KBEntryStatus.DRAFT,
    KBEntryAction.RETIRE: KBEntryStatus.RETIRED,
}


def require_entry_action_allowed(
    status: KBEntryStatus, action: KBEntryAction
) -> KBEntryStatus | None:
    """The status this action moves the entry to, or raise 409.

    Returns `None` for an action that leaves the status alone — an edit, and an
    approval, which only enqueues the indexing job.
    """
    if status not in ENTRY_ACTION_FROM[action]:
        raise InvalidKBTransition(_not_allowed_message(status, action))
    return ENTRY_ACTION_TO.get(action)


def require_rule_not_approved(rule: RedFlagRule) -> None:
    """Raise 409 unless the rule is still unapproved (NFR-08).

    An approved rule is part of the safety floor, and the floor is versioned:
    editing one in place would change what a stored recommendation's floor
    meant. Retiring it and approving a replacement is the supported path.
    """
    if rule.retired_at is not None:
        raise InvalidKBTransition("This rule has been retired. Create a replacement instead.")
    if rule.approved_at is not None:
        raise InvalidKBTransition(
            "This rule has already been approved. Retire it and approve a replacement "
            "instead of changing it."
        )


def require_rule_editable(rule: RedFlagRule) -> None:
    """Raise 409 unless the rule may still be edited (P08 §8.1 task 4)."""
    require_rule_not_approved(rule)


def require_rule_retirable(rule: RedFlagRule) -> None:
    """Raise 409 unless the rule can be retired."""
    if rule.retired_at is not None:
        raise InvalidKBTransition("This rule has already been retired.")


def _not_allowed_message(status: KBEntryStatus, action: KBEntryAction) -> str:
    """Why this action cannot be taken now, in a sentence an author can act on."""
    if action in (KBEntryAction.EDIT, KBEntryAction.SUBMIT):
        if status is KBEntryStatus.PENDING_REVIEW:
            return "This entry is waiting for review. Ask the approver to send it back first."
        if status is KBEntryStatus.ACTIVE:
            return (
                "An active entry cannot be changed. Create a new draft revision of it "
                "instead, and submit that for approval."
            )
        return "This entry has been retired. Create a new draft instead."
    if action in (KBEntryAction.APPROVE, KBEntryAction.REJECT):
        if status is KBEntryStatus.DRAFT:
            return "This entry has not been submitted for review yet."
        return "This entry is no longer waiting for review."
    if status is KBEntryStatus.RETIRED:
        return "This entry has already been retired."
    return "Only an active entry can be retired."
