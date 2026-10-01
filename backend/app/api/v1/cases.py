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
    CaseListResponse,
    CaseQueueFilters,
    CaseStatusOut,
)
from app.services.case_service import CaseService

router = APIRouter(prefix="/cases", tags=["cases"])

# 201 while a case is simply recorded. P05 starts the triage pipeline on
# submission, at which point this becomes 202 Accepted (FR-06) — this constant is
# the one line that changes.
CASE_CREATED_STATUS = status.HTTP_201_CREATED

IntakeUser = Annotated[
    User, Depends(require_role(UserRole.INTAKE_STAFF, UserRole.VETERINARY_REVIEWER))
]
QueueReader = Annotated[
    User,
    Depends(
        require_role(UserRole.INTAKE_STAFF, UserRole.VETERINARY_REVIEWER, UserRole.ADMINISTRATOR)
    ),
]


@router.post("", status_code=CASE_CREATED_STATUS)
def create_case(payload: CaseCreate, db: DbSession, user: IntakeUser) -> CaseCreated:
    """Record a new case and return its number (FR-01, FR-03).

    An out-of-scope species answers 422 `SPECIES_OUT_OF_SCOPE` (FR-02); a field
    that fails validation answers 422 `VALIDATION_ERROR` naming the field (FR-04).
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
    """What a case looks like now, polled while it is being processed (IR-22)."""
    return CaseService(db).get_status(case_id)
