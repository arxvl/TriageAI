"""The Veterinary Triage List constants (CLAUDE.md §6).

Three layers need these numbers — the queue query orders by the rank, the case
service derives the overdue flag from the target, and P05's safety validator
compares urgency — so they live in one module rather than being restated.

`QUEUE_RANK` is the part worth reading twice. FR-29 does not sort by urgency
alone: a case with no category yet (still processing, or handed to manual triage)
sits directly *below* RED and above ORANGE, because an unclassified case might be
the most urgent one in the room. That is why the rank is its own table instead of
an index into `URGENCY_ORDER`.
"""

from app.models.enums import VTLCategory

# Target waiting time in minutes, per CLAUDE.md §6.
TARGET_MINUTES: dict[VTLCategory, int] = {
    VTLCategory.RED: 0,
    VTLCategory.ORANGE: 15,
    VTLCategory.YELLOW: 60,
    VTLCategory.GREEN: 120,
    VTLCategory.BLUE: 240,
}

# Most urgent first. Used to compare two categories (P05 FR-23 safety floor).
URGENCY_ORDER: tuple[VTLCategory, ...] = (
    VTLCategory.RED,
    VTLCategory.ORANGE,
    VTLCategory.YELLOW,
    VTLCategory.GREEN,
    VTLCategory.BLUE,
)

# The Triage Queue ordering (FR-29). `None` is a real key, not a fallback.
QUEUE_RANK: dict[VTLCategory | None, int] = {
    VTLCategory.RED: 0,
    None: 1,
    VTLCategory.ORANGE: 2,
    VTLCategory.YELLOW: 3,
    VTLCategory.GREEN: 4,
    VTLCategory.BLUE: 5,
}

# Used when a category somehow falls outside the table above, so a row is never
# dropped from the queue by an ordering expression.
UNRANKED = max(QUEUE_RANK.values()) + 1


def target_minutes(category: VTLCategory | None) -> int | None:
    """The target waiting time, or None for a case with no category yet."""
    if category is None:
        return None
    return TARGET_MINUTES[category]


def is_overdue(category: VTLCategory | None, waiting_minutes: int) -> bool:
    """True when the wait has passed the category's target (FR-30).

    A case with no category has no target, so it is never overdue — the queue
    marks it for manual triage instead.

    RED's target is 0, so a RED case is overdue one minute after arrival. That
    follows FR-30 as written; how loudly the queue says so is a presentation
    choice for the screen, not a rule for this module.
    """
    target = target_minutes(category)
    if target is None:
        return False
    return waiting_minutes > target


def more_urgent(left: VTLCategory, right: VTLCategory) -> bool:
    """True when `left` is more urgent than `right`."""
    return URGENCY_ORDER.index(left) < URGENCY_ORDER.index(right)
