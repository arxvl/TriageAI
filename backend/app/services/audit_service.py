"""The one write path into the append-only audit log (FR-43, SR-12, ADR-12).

Services never insert `AuditEntry` rows themselves; they call `record`. The log
cannot be updated or deleted by the application database role, so a wrong value
written here is permanent — pass identifiers and small structured payloads, and
never owner descriptions, owner references, prompts or model output
(CLAUDE.md §9).

Later phases add their own actions to `AuditAction`.
"""

import uuid
from enum import StrEnum

from sqlalchemy.orm import Session

from app.models import AuditEntry, UserRole

# The entity every security event is about.
USER_ENTITY = "user"

# The entity every case event is about.
CASE_ENTITY = "case"

# Used when a login is attempted for an address that has no account, so the
# failure is still auditable (SR-12).
UNKNOWN_ENTITY_ID = "unknown"


class AuditAction(StrEnum):
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILURE = "LOGIN_FAILURE"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    LOGOUT = "LOGOUT"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"  # noqa: S105 - an audit action name
    CASE_CREATED = "CASE_CREATED"
    # The triage pipeline (P05 §5.4). Written with no user_id: the pipeline is not
    # a person, and the decision a person makes about its output is audited
    # separately in P06.
    PIPELINE_STARTED = "PIPELINE_STARTED"
    RED_FLAG_ALERT = "RED_FLAG_ALERT"
    RECOMMENDATION_CREATED = "RECOMMENDATION_CREATED"
    PIPELINE_FAILED = "PIPELINE_FAILED"


class AuditService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        action: AuditAction | str,
        entity_type: str,
        entity_id: str,
        user_id: uuid.UUID | None = None,
        role: UserRole | None = None,
        before: dict | None = None,
        after: dict | None = None,
    ) -> AuditEntry:
        """Append one entry. Flushes; the caller owns the transaction."""
        entry = AuditEntry(
            action=str(action),
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            role=role,
            before=before,
            after=after,
        )
        self._session.add(entry)
        self._session.flush()
        return entry
