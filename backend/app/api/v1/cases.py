"""Case intake and Triage Queue endpoints (FR-01..FR-07, FR-29, FR-39, SR-05).

The router holds no business logic (CLAUDE.md §7): it declares who may call,
hands the request to `CaseService`, and returns what comes back.

Roles follow the P04 prompt. Intake Staff and Veterinary Reviewers create cases
and poll them; an Administrator may read the queue — they run the clinic's
accounts and reports — but may not enter a case, because that is clinical data
entry (BR-02, BR-05).

No response model carries an owner name or contact number, so nothing here has
to remember to strip them (FR-07, DR-04).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, require_role
from app.models import User, UserRole
from app.schemas.case import (
    CaseCreate,
    CaseCreated,
    CaseDetail,
    CaseListResponse,
    CaseQueueFilters,
    CaseStatusOut,
)
from app.schemas.review import (
    AuditTimeline,
    CaseClosed,
    DecisionCreate,
    DecisionOut,
    NoteCreate,
    NoteOut,
    RetryAccepted,
)
from app.services.case_service import CaseService
from app.services.review_service import ReviewService

router = APIRouter(prefix="/cases", tags=["cases"])

# 202 Accepted, not 201 Created: submitting a case enqueues the triage pipeline
# and the recommendation does not exist yet, so the response promises that the
# work has been taken on rather than that it is finished (FR-06, ADR-08). The
# client polls `GET /cases/{id}/status` for the rest (IR-22).
CASE_CREATED_STATUS = status.HTTP_202_ACCEPTED

IntakeUser = Annotated[
    User, Depends(require_role(UserRole.INTAKE_STAFF, UserRole.VETERINARY_REVIEWER))
]
QueueReader = Annotated[
    User,
    Depends(
        require_role(UserRole.INTAKE_STAFF, UserRole.VETERINARY_REVIEWER, UserRole.ADMINISTRATOR)
    ),
]
# Confirm, adjust, manual triage, notes and close are the Veterinary Reviewer's
# alone — not the administrator's, who runs the clinic's accounts and reports but
# makes no clinical judgement (FR-35, BR-02, SR-05).
ReviewerUser = Annotated[User, Depends(require_role(UserRole.VETERINARY_REVIEWER))]


@router.post("", status_code=CASE_CREATED_STATUS)
def create_case(payload: CaseCreate, db: DbSession, user: IntakeUser) -> CaseCreated:
    """Record a new case, start its triage, and return its number (FR-01, FR-06).

    Answers 202: the case and its `PIPELINE_RUN` job are committed together and a
    worker picks the job up within about half a second (ADR-08). The returned
    status is `SUBMITTED`; the client polls `/cases/{id}/status` from there.

    An out-of-scope species answers 422 `SPECIES_OUT_OF_SCOPE` and enqueues
    nothing (FR-02); a field that fails validation answers 422 `VALIDATION_ERROR`
    naming the field (FR-04).
    """
    return CaseService(db).create_case(payload, user)


@router.get("")
def list_cases(
    filters: Annotated[CaseQueueFilters, Query()],
    db: DbSession,
    user: QueueReader,
) -> CaseListResponse:
    """The Triage Queue: open cases in urgency order, with the W-02 counters.

    Ordering is FR-29 and the counters always describe the whole open queue, so
    filtering the rows does not move the numbers.
    """
    return CaseService(db).list_queue(filters)


@router.get("/{case_id}/status")
def read_case_status(case_id: uuid.UUID, db: DbSession, user: IntakeUser) -> CaseStatusOut:
    """What a case looks like now, polled while it is being processed (IR-22).

    Carries `actions_status` as well, because the suggested actions arrive after
    the category and the screen polls for both (FR-77, ADR-18 §3).
    """
    return CaseService(db).get_status(case_id)


@router.post("/{case_id}/decision")
def record_decision(
    case_id: uuid.UUID, payload: DecisionCreate, db: DbSession, user: ReviewerUser
) -> DecisionOut:
    """Confirm, adjust, or manually triage a case (FR-32, FR-33, FR-34, FR-35).

    This is the endpoint that makes a category final. Nothing else in the system
    writes one, which is the Human-in-the-Loop guarantee (BR-01, NFR-07).

    Answers 409 when the case is not in a state that allows the decision — it
    has already been decided, or is still being processed — and 422 when the
    decision's fields do not agree with each other, such as an adjustment with
    no reason code (BR-03). A case that has already been decided is changed only
    by sending `amends_id`; the original is never edited (FR-48).
    """
    return ReviewService(db).record_decision(case_id, payload, user)


@router.post("/{case_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_pipeline(case_id: uuid.UUID, db: DbSession, user: ReviewerUser) -> RetryAccepted:
    """Run the AI pipeline again for a case it gave up on (UC-08, NFR-09, W-06).

    Answers 202: a new `PIPELINE_RUN` job is queued and the case returns to
    `SUBMITTED`; the client polls `GET /cases/{id}/status` for the outcome.
    Answers 409 unless the case is in `MANUAL_TRIAGE_REQUIRED` with no decision,
    which also means a second press of the button while the first retry is
    running is refused rather than queued twice.
    """
    return CaseService(db).retry_pipeline(case_id, user)


@router.post("/{case_id}/notes")
def add_note(case_id: uuid.UUID, payload: NoteCreate, db: DbSession, user: ReviewerUser) -> NoteOut:
    """Attach a clinical note to a case (FR-37).

    The note appears on the case's audit timeline (FR-45).
    """
    return ReviewService(db).add_note(case_id, payload, user)


@router.post("/{case_id}/close")
def close_case(case_id: uuid.UUID, db: DbSession, user: ReviewerUser) -> CaseClosed:
    """Close a case, removing it from the active queue (FR-38).

    Answers 409 before a decision has been recorded: a case must not leave the
    working list without an urgency category behind it.
    """
    return ReviewService(db).close_case(case_id, user)


@router.get("/{case_id}/audit")
def read_case_audit(case_id: uuid.UUID, db: DbSession, user: QueueReader) -> AuditTimeline:
    """The chronological record of one case, with its timing intervals (FR-45, FR-46).

    Readable by all three roles: the audit trail is what makes the system
    accountable, and an administrator reporting on it is one of the reasons it
    exists (FR-41, ADR-12).
    """
    return ReviewService(db).get_timeline(case_id)


@router.get("/{case_id}")
def read_case(case_id: uuid.UUID, db: DbSession, user: QueueReader) -> CaseDetail:
    """One case, everything the Case Review screen shows (FR-31, W-04).

    Declared after the `/{case_id}/<literal>` routes above, so none of them is
    swallowed by this one.

    All three roles may read a case — a reviewer decides on it, intake staff
    follow one they entered, an administrator reports on it. What differs is the
    content: unfinalized AI-suggested actions are returned to Veterinary
    Reviewers only, and reading the case **as a reviewer** acknowledges its
    red-flag alerts. The service enforces both rather than the router
    (FR-12, FR-79).
    """
    return CaseService(db).get_detail(case_id, user)
