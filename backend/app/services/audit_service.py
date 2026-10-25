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

# The three entities the knowledge-base workflow acts on (P08 §8.1). Separate
# types rather than one "kb", so the W-08 history of an entry is not mixed with
# the rule changes and the published versions.
KB_ENTRY_ENTITY = "kb_entry"
RED_FLAG_RULE_ENTITY = "red_flag_rule"
KB_VERSION_ENTITY = "kb_version"

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
    # A reviewer re-queued a case the pipeline gave up on (P07 §7.1 task 3). Unlike
    # the pipeline's own entries this one has a person: the user and role are set.
    # The payload is the previous reason code and the new status — nothing else.
    PIPELINE_RETRY = "PIPELINE_RETRY"
    # A reviewer corrected the extracted information and asked for a new
    # recommendation (P07 §7.2, FR-27). The payload lists the *names* of the
    # changed fields and never their values: they are clinical free text and the
    # log cannot be corrected (FR-43).
    EXTRACTION_CORRECTED = "EXTRACTION_CORRECTED"
    # The pipeline's own entries for a regeneration. The previous recommendation
    # version is kept; these say a later one was written, or why it was not.
    RECOMMENDATION_REGENERATED = "RECOMMENDATION_REGENERATED"
    REGENERATE_FAILED = "REGENERATE_FAILED"
    # The suggested-actions job (P05b §5b.3, ADR-18 §3). Counts and reason codes
    # only: action text is untrusted model output and the log cannot be
    # corrected (SR-17, FR-43).
    ACTIONS_SUGGESTED = "ACTIONS_SUGGESTED"
    ACTIONS_FAILED = "ACTIONS_FAILED"
    # A reviewer asked for new suggested actions for the category they settled on
    # (P07 §7.2b, FR-78). The category and the set number, nothing else.
    ACTIONS_REGENERATION_REQUESTED = "ACTIONS_REGENERATION_REQUESTED"
    # The human-in-the-loop decision (P06 §6.1). `DECISION_RECORDED` carries the
    # before and after **category and status only** — never the reviewer's
    # reason text, which is clinical free text and lives on the decision row
    # where it can be read beside the case (FR-42, ADR-12).
    DECISION_RECORDED = "DECISION_RECORDED"
    # Counts per status, never an action's text (SR-17).
    ACTIONS_FINALIZED = "ACTIONS_FINALIZED"
    # The note itself is not audited, only that one was added: a note is
    # clinical content and the log cannot be corrected (FR-43).
    NOTE_ADDED = "NOTE_ADDED"
    CASE_CLOSED = "CASE_CLOSED"
    # The knowledge-base workflow (P08 §8.1, FR-51, FR-52, FR-54, NFR-08,
    # BR-04). Payloads carry ids, slugs, codes, statuses, version numbers and
    # chunk counts — never an entry's content and never a rejection's comments,
    # which are curated clinical text that the log cannot correct (FR-43).
    #
    # Approval is two entries, not one. `KB_ENTRY_APPROVED` records the person
    # and the moment they approved; `KB_ENTRY_ACTIVATED` records that indexing
    # then succeeded and the entry went live. Keeping them apart is what makes a
    # failed indexing visible as an approval that did not take effect (FR-53).
    KB_ENTRY_CREATED = "KB_ENTRY_CREATED"
    KB_ENTRY_UPDATED = "KB_ENTRY_UPDATED"
    KB_ENTRY_SUBMITTED = "KB_ENTRY_SUBMITTED"
    KB_ENTRY_APPROVED = "KB_ENTRY_APPROVED"
    KB_ENTRY_ACTIVATED = "KB_ENTRY_ACTIVATED"
    KB_ENTRY_REJECTED = "KB_ENTRY_REJECTED"
    KB_ENTRY_RETIRED = "KB_ENTRY_RETIRED"
    KB_INDEX_FAILED = "KB_INDEX_FAILED"
    KB_VERSION_PUBLISHED = "KB_VERSION_PUBLISHED"
    RED_FLAG_RULE_CREATED = "RED_FLAG_RULE_CREATED"
    RED_FLAG_RULE_UPDATED = "RED_FLAG_RULE_UPDATED"
    RED_FLAG_RULE_APPROVED = "RED_FLAG_RULE_APPROVED"
    RED_FLAG_RULE_RETIRED = "RED_FLAG_RULE_RETIRED"
    # Account administration (P09 §9.1, FR-60, FR-63, SR-03). The actor is the
    # administrator and the entity is the account that changed. Payloads hold
    # the role, the approval flag and the active flag — never a password, a
    # hash, or a temporary password, which the log could not take back.
    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"
    USER_UNLOCKED = "USER_UNLOCKED"
    USER_PASSWORD_RESET = "USER_PASSWORD_RESET"  # noqa: S105 - an audit action name


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
