"""Knowledge-base management endpoints (FR-49..FR-56, NFR-08, BR-04, SR-05).

The router holds no business logic (CLAUDE.md §7): it declares who may call,
hands the request to `KBService`, and returns what comes back.

Roles follow the P08 §8.1 table, and the split is the point of the phase:

* **Authoring is the Administrator's.** Creating, editing, submitting and
  retiring entries is curation work.
* **Approval is the KB approver's.** `require_role(VETERINARY_REVIEWER,
  kb_approver=True)` is the BR-04 gate, and `can_approve_kb` can only be held by
  a Veterinary Reviewer (FR-58). An approver who lacks the permission gets 403.
* **Reading is both.** An administrator curates and an approver reviews, so both
  see the catalogue, the versions and the rules. Intake Staff see none of it.
* **Rules are retired by the approver, not the administrator.** Retiring a rule
  lowers the red-flag safety floor, and NFR-08 puts every change to the rules
  behind veterinary approval.

Answers: 409 when the entry or rule is not in a state that allows the action,
422 when a field is missing or out of bounds (naming the field), 404 for an
unknown id.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, KBIndexerDep, require_role
from app.models import User, UserRole
from app.schemas.kb import (
    ComplaintOption,
    KBEntryActionResult,
    KBEntryCreate,
    KBEntryDetail,
    KBEntryFilters,
    KBEntryListResponse,
    KBEntryUpdate,
    KBRejection,
    KBVersionDetail,
    KBVersionSummary,
    RedFlagRuleActionResult,
    RedFlagRuleCreate,
    RedFlagRuleOut,
    RedFlagRuleUpdate,
)
from app.services.kb_service import KBService

router = APIRouter(prefix="/kb", tags=["knowledge-base"])

# 202 Accepted, not 200: approving enqueues the `KB_INDEX` job and the entry is
# not active yet. The response promises the approval has been taken on, and the
# screen polls the entry for the indexing outcome (FR-53, ADR-08).
APPROVAL_ACCEPTED_STATUS = status.HTTP_202_ACCEPTED

CuratorUser = Annotated[User, Depends(require_role(UserRole.ADMINISTRATOR))]
KBReader = Annotated[
    User, Depends(require_role(UserRole.ADMINISTRATOR, UserRole.VETERINARY_REVIEWER))
]
ApproverUser = Annotated[
    User, Depends(require_role(UserRole.VETERINARY_REVIEWER, kb_approver=True))
]


# --- Entries --------------------------------------------------------------


@router.get("/entries")
def list_entries(
    filters: Annotated[KBEntryFilters, Query()], db: DbSession, user: KBReader
) -> KBEntryListResponse:
    """The W-08 catalogue: entries, the four tab counts, the published version."""
    return KBService(db).list_entries(filters)


@router.post("/entries", status_code=status.HTTP_201_CREATED)
def create_entry(payload: KBEntryCreate, db: DbSession, user: CuratorUser) -> KBEntryDetail:
    """Write a new draft entry (FR-49, FR-50).

    Answers 422 naming the field when the citation is incomplete or the content
    is outside the 50–1,500 word range.
    """
    return KBService(db).create_entry(payload, user)


@router.patch("/entries/{entry_id}")
def update_entry(
    entry_id: uuid.UUID, payload: KBEntryUpdate, db: DbSession, user: CuratorUser
) -> KBEntryDetail:
    """Edit a draft.

    Answers 409 for an entry that is awaiting review, active or retired: active
    content is never edited in place, it is superseded by a new draft (ADR-14).
    """
    return KBService(db).update_entry(entry_id, payload, user)


@router.post("/entries/{entry_id}/submit")
def submit_entry(entry_id: uuid.UUID, db: DbSession, user: CuratorUser) -> KBEntryActionResult:
    """`DRAFT` → `PENDING_REVIEW` (FR-51)."""
    return KBService(db).submit_entry(entry_id, user)


@router.post("/entries/{entry_id}/approve", status_code=APPROVAL_ACCEPTED_STATUS)
def approve_entry(entry_id: uuid.UUID, db: DbSession, user: ApproverUser) -> KBEntryActionResult:
    """Approve an entry; a `KB_INDEX` job then indexes and publishes it.

    The response carries the job id and the entry still in `PENDING_REVIEW`; the
    entry becomes `ACTIVE` and version N+1 appears when the job succeeds
    (FR-52, FR-53, FR-54).
    """
    return KBService(db).approve_entry(entry_id, user)


@router.post("/entries/{entry_id}/reject")
def reject_entry(
    entry_id: uuid.UUID, payload: KBRejection, db: DbSession, user: ApproverUser
) -> KBEntryActionResult:
    """Send an entry back to its author with comments, which are required."""
    return KBService(db).reject_entry(entry_id, payload, user)


@router.post("/entries/{entry_id}/retire")
def retire_entry(
    entry_id: uuid.UUID, db: DbSession, indexer: KBIndexerDep, user: CuratorUser
) -> KBEntryActionResult:
    """`ACTIVE` → `RETIRED`: remove its chunks and publish a version (FR-53, FR-54).

    Irreversible from the screen's point of view, so W-08 confirms first
    (IR-08). The entry itself is kept: a recommendation that cited it stays
    explainable.
    """
    return KBService(db, indexer=indexer).retire_entry(entry_id, user)


@router.get("/complaints")
def list_complaints(db: DbSession, user: KBReader) -> list[ComplaintOption]:
    """The fixed presenting-complaint list, for W-08's editor and entry list (FR-10).

    Read-only reference data, so both KB roles see it; Intake Staff, who see no
    part of the knowledge base, get 403.
    """
    return KBService(db).list_complaints()


@router.get("/entries/{entry_id}")
def read_entry(entry_id: uuid.UUID, db: DbSession, user: KBReader) -> KBEntryDetail:
    """One entry, with its citation, its rules and its indexing state.

    Declared after the `/entries/{entry_id}/<literal>` routes above, so none of
    them is swallowed by this one.
    """
    return KBService(db).get_entry(entry_id)


# --- Versions (FR-54, DR-05) ---------------------------------------------


@router.get("/versions")
def list_versions(db: DbSession, user: KBReader) -> list[KBVersionSummary]:
    """Every published version, newest first, for the W-08 history drawer."""
    return KBService(db).list_versions()


@router.get("/versions/{version_id}")
def read_version(version_id: uuid.UUID, db: DbSession, user: KBReader) -> KBVersionDetail:
    """One version and the entries it contains, including retired ones."""
    return KBService(db).get_version(version_id)


# --- Red-flag rules (FR-12, FR-23, NFR-08) -------------------------------


@router.get("/red-flag-rules")
def list_red_flag_rules(db: DbSession, user: KBReader) -> list[RedFlagRuleOut]:
    """The rules table, with each rule's approval and whether it is screening now."""
    return KBService(db).list_rules()


@router.post("/red-flag-rules", status_code=status.HTTP_201_CREATED)
def create_red_flag_rule(
    payload: RedFlagRuleCreate, db: DbSession, user: CuratorUser
) -> RedFlagRuleOut:
    """Create a rule. It is unapproved, so it changes no triage yet (NFR-08)."""
    return KBService(db).create_rule(payload, user)


@router.patch("/red-flag-rules/{rule_id}")
def update_red_flag_rule(
    rule_id: uuid.UUID, payload: RedFlagRuleUpdate, db: DbSession, user: CuratorUser
) -> RedFlagRuleOut:
    """Edit a rule that has not been approved. Answers 409 once it has."""
    return KBService(db).update_rule(rule_id, payload, user)


@router.post("/red-flag-rules/{rule_id}/approve")
def approve_red_flag_rule(
    rule_id: uuid.UUID, db: DbSession, user: ApproverUser
) -> RedFlagRuleActionResult:
    """Approve a rule and publish a version, so the floor is versioned too."""
    return KBService(db).approve_rule(rule_id, user)


@router.post("/red-flag-rules/{rule_id}/retire")
def retire_red_flag_rule(
    rule_id: uuid.UUID, db: DbSession, user: ApproverUser
) -> RedFlagRuleActionResult:
    """Retire a rule and publish a version. It stops firing immediately."""
    return KBService(db).retire_rule(rule_id, user)
