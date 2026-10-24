"""Which case statuses allow which decision, as one explicit table (FR-32..FR-38).

Until now every status write in the application was an unchecked assignment:
`PipelineRepository.set_status` takes whatever it is handed. That was fine while
only the pipeline wrote statuses, because the orchestrator drives them in a fixed
order. P06 opens status changes to people, and two of them must not be possible:

* confirming a case that nobody has produced a recommendation for, and
* replacing a decision a reviewer has already recorded (FR-48, NFR-11).

So the allowed moves live here, as data, next to the one function that checks
them. A table can be read and tested exhaustively; a chain of `if` statements
spread over a service cannot, and this is the guarantee the clinical record rests
on (BR-01, ADR-12).

Nothing here touches a session, a request or FastAPI: it answers questions about
two enum values (CLAUDE.md §7).
"""

from app.core.errors import AmendmentRequired, InvalidCaseTransition
from app.core.vtl import more_urgent
from app.models import CaseStatus, DecisionDirection, DecisionType, VTLCategory

# The statuses a case reaches by a human decision. A case here has a
# `StaffDecision` behind its category, which is what `CaseStatus` alone cannot
# say and what IR-04 turns into the "requires staff confirmation" chip.
DECIDED_STATUSES: frozenset[CaseStatus] = frozenset(
    {CaseStatus.CONFIRMED, CaseStatus.ADJUSTED, CaseStatus.MANUALLY_TRIAGED}
)

# The statuses in which suggested actions cannot be regenerated (P07 §7.2b): no
# category has been settled on yet (still being processed, or waiting for manual
# triage), or the case has left the working list.
ACTIONS_REGENERATION_BLOCKED_STATUSES: frozenset[CaseStatus] = frozenset(
    {
        CaseStatus.SUBMITTED,
        CaseStatus.PROCESSING,
        CaseStatus.MANUAL_TRIAGE_REQUIRED,
        CaseStatus.CLOSED,
    }
)

# Where a first decision of each type may be made from.
#
# CONFIRM and ADJUST both speak about a recommendation — one accepts it, the
# other departs from it — so both require `AWAITING_REVIEW`, the one status that
# means "a recommendation exists and no human has decided yet".
#
# MANUAL is deliberately wider. It is the answer when the AI failed
# (`MANUAL_TRIAGE_REQUIRED`), and also when a reviewer looks at a perfectly good
# recommendation and judges that the case is not one the system should be
# triaging at all — FR-34 and ADR-15 §4 both require it to be available at any
# time, not only after a failure.
DECISION_FROM: dict[DecisionType, frozenset[CaseStatus]] = {
    DecisionType.CONFIRM: frozenset({CaseStatus.AWAITING_REVIEW}),
    DecisionType.ADJUST: frozenset({CaseStatus.AWAITING_REVIEW}),
    DecisionType.MANUAL: frozenset({CaseStatus.AWAITING_REVIEW, CaseStatus.MANUAL_TRIAGE_REQUIRED}),
}

# Where the case lands. One status per decision type, so the status and the
# stored decision can never disagree about what happened.
DECISION_TO: dict[DecisionType, CaseStatus] = {
    DecisionType.CONFIRM: CaseStatus.CONFIRMED,
    DecisionType.ADJUST: CaseStatus.ADJUSTED,
    DecisionType.MANUAL: CaseStatus.MANUALLY_TRIAGED,
}


def require_decision_allowed(
    status: CaseStatus, decision_type: DecisionType, *, is_amendment: bool
) -> CaseStatus:
    """The status this decision moves the case to, or raise 409.

    An amendment is the only way to decide a case twice (FR-48). It is allowed
    from any decided status and from no other: amending a case that has not been
    decided would reference a decision that does not exist, and a second plain
    decision on a decided case answers `AMENDMENT_REQUIRED` so the client knows
    the correction is available rather than that the case is unusable.

    A closed case is immovable. Closing is the clinic saying the patient has been
    seen; reopening it is not a P06 feature and must not happen by accident.
    """
    if status is CaseStatus.CLOSED:
        raise InvalidCaseTransition("This case is closed. Closed cases cannot be decided again.")

    if is_amendment:
        if status not in DECIDED_STATUSES:
            raise InvalidCaseTransition(
                "This case has no decision yet, so there is nothing to amend."
            )
        return DECISION_TO[decision_type]

    if status in DECIDED_STATUSES:
        raise AmendmentRequired()

    if status not in DECISION_FROM[decision_type]:
        raise InvalidCaseTransition(_not_allowed_message(status, decision_type))

    return DECISION_TO[decision_type]


def require_closable(status: CaseStatus) -> None:
    """Raise 409 unless the case may be closed (FR-38).

    Closing removes a case from the active queue, so it is allowed only after a
    reviewer has settled the category. Closing an undecided case would drop a
    patient off the working list with no recorded urgency, which is the one
    outcome the queue exists to prevent.
    """
    if status is CaseStatus.CLOSED:
        raise InvalidCaseTransition("This case is already closed.")
    if status not in DECIDED_STATUSES:
        raise InvalidCaseTransition("Record a decision on this case before closing it.")


def direction(recommended: VTLCategory | None, final: VTLCategory) -> DecisionDirection:
    """Which way the reviewer moved the category, for the disagreement analysis.

    `NONE` when there was no recommendation to move away from — a manually
    triaged case after an AI failure has a category but no AI category, and
    counting that as agreement would overstate how often the model was right
    (FR-42, FR-46).
    """
    if recommended is None:
        return DecisionDirection.NONE
    if recommended is final:
        return DecisionDirection.SAME
    return DecisionDirection.UP if more_urgent(final, recommended) else DecisionDirection.DOWN


def _not_allowed_message(status: CaseStatus, decision_type: DecisionType) -> str:
    """Why this decision cannot be made now, in a sentence a reviewer can act on."""
    if decision_type is DecisionType.MANUAL:
        return "This case cannot be triaged manually while it is still being processed."
    if status is CaseStatus.MANUAL_TRIAGE_REQUIRED:
        return "There is no AI recommendation for this case. Use manual triage to set the category."
    return "This case is still being processed. Wait for the recommendation, then decide."
