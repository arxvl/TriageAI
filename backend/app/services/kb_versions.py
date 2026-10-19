"""Publishing one immutable knowledge-base version (FR-54, DR-05, ADR-14).

Every approval and every retirement — of an entry *or* of a red-flag rule —
ends here, which is why it is one function rather than a method on the service
that happens to need it first.

Two properties it has to hold.

**A version lists every ACTIVE entry, not the one that changed.** A version is a
snapshot of the knowledge the system would retrieve at that moment, so a
recommendation pinned to it can be explained in full later. Listing only the
changed entry would make the snapshot useless.

**A published version is never modified.** `kb_version_entries` rejects UPDATE at
the database level (migration 0002), and nothing here updates a `kb_versions`
row after inserting it. A correction is a new version with a higher number.

The version number is `max + 1` against a unique column, so two publications
racing for the same number produce an integrity error. That becomes a 409 the
caller can retry rather than a renumbered version nobody expected.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import VersionPublishConflict
from app.models import UserRole
from app.repositories.kb_repository import KBRepository
from app.services.audit_service import KB_VERSION_ENTITY, AuditAction, AuditService

__all__ = ["PublishedVersion", "publish_version"]


@dataclass(frozen=True)
class PublishedVersion:
    """The version that was just published, for the response and the audit."""

    id: uuid.UUID
    version_no: int
    entry_count: int


def publish_version(
    session: Session,
    *,
    published_by: uuid.UUID | None,
    role: UserRole | None,
    at: datetime,
    note: str,
    reason: dict[str, object] | None = None,
) -> PublishedVersion:
    """Insert a version listing every ACTIVE entry. Flushes; never commits.

    The caller owns the transaction, so the version and the status change that
    caused it are committed together or not at all: there can be no version
    published for an approval that was rolled back, and no active entry that no
    version contains.

    `note` is the one piece of prose stored, and it says what the version was
    published *for* — "Approved entry urinary-straining-cat". It names
    identifiers, never content (CLAUDE.md §9).
    """
    repository = KBRepository(session)
    entry_ids = repository.active_entry_ids()
    version_no = repository.next_version_no()

    try:
        version = repository.insert_version(
            version_no=version_no, published_by=published_by, at=at, note=note
        )
        repository.link_version_entries(version.id, entry_ids)
    except IntegrityError as error:
        # The unique index on `version_no` fired. Roll back so the caller's
        # session is usable for the error response, and say what happened.
        session.rollback()
        raise VersionPublishConflict() from error

    AuditService(session).record(
        action=AuditAction.KB_VERSION_PUBLISHED,
        entity_type=KB_VERSION_ENTITY,
        entity_id=str(version.id),
        user_id=published_by,
        role=role,
        after={
            "version_no": version_no,
            "entry_count": len(entry_ids),
            **(reason or {}),
        },
    )
    return PublishedVersion(id=version.id, version_no=version_no, entry_count=len(entry_ids))
