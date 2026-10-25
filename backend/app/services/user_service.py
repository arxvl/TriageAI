"""Account administration for the Administrator (P09 §9.1, FR-60, FR-63, SR-03, BR-04).

The service owns the rules a request must not be able to skip: the knowledge-base
approval permission belongs to a Veterinary Reviewer only, and the system never
loses its last active administrator. It raises `AppError` subclasses and knows
nothing about HTTP (CLAUDE.md §7).

A temporary password exists in memory for the length of one call. Only its
Argon2id hash is stored, and it is never logged or audited.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import (
    EmailAlreadyInUse,
    InvalidUserUpdate,
    LastAdministrator,
    UserNotFound,
)
from app.core.security import generate_temporary_password, hash_password
from app.models import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.user import (
    UserAdminOut,
    UserCreate,
    UserFilters,
    UserListOut,
    UserUpdate,
    UserWithTemporaryPassword,
)
from app.services.audit_service import USER_ENTITY, AuditAction, AuditService

Clock = Callable[[], datetime]

KB_APPROVAL_MESSAGE = "Knowledge base approval can be granted only to a Veterinary Reviewer."


def _utc_now() -> datetime:
    return datetime.now(UTC)


class UserService:
    def __init__(self, session: Session, *, now: Clock | None = None) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._audit = AuditService(session)
        self._now = now or _utc_now

    def list_users(self, filters: UserFilters) -> UserListOut:
        users = self._users.list_users(filters.q)
        return UserListOut(
            items=[UserAdminOut.model_validate(user) for user in users], total=len(users)
        )

    def create_user(self, payload: UserCreate, actor: User) -> UserWithTemporaryPassword:
        """Create an account with a random temporary password, returned once (FR-60)."""
        email = payload.email.strip().lower()
        if self._users.get_by_email(email) is not None:
            raise EmailAlreadyInUse()
        self._require_approval_allowed(payload.role, payload.can_approve_kb)

        temporary_password = generate_temporary_password()
        user = self._users.add(
            User(
                full_name=payload.full_name,
                email=email,
                role=payload.role,
                can_approve_kb=payload.can_approve_kb,
                is_active=True,
                must_change_password=True,
                password_hash=hash_password(temporary_password),
            )
        )
        self._record(
            AuditAction.USER_CREATED,
            user,
            actor,
            after={
                "role": user.role.value,
                "can_approve_kb": user.can_approve_kb,
                "is_active": user.is_active,
            },
        )
        self._session.commit()
        return UserWithTemporaryPassword(
            user=UserAdminOut.model_validate(user), temporary_password=temporary_password
        )

    def update_user(self, user_id: uuid.UUID, payload: UserUpdate, actor: User) -> UserAdminOut:
        user = self._require_user(user_id)
        # None is how a client says "leave it", and no account field is nullable.
        changes = {
            field: value
            for field, value in payload.model_dump(exclude_unset=True).items()
            if value is not None
        }

        new_role = changes.get("role", user.role)
        new_approval = changes.get("can_approve_kb", user.can_approve_kb)
        self._require_approval_allowed(new_role, new_approval)

        loses_administrator = user.role is UserRole.ADMINISTRATOR and user.is_active
        loses_administrator = loses_administrator and (
            new_role is not UserRole.ADMINISTRATOR or changes.get("is_active", True) is False
        )
        if loses_administrator and self._users.count_active_administrators() <= 1:
            raise LastAdministrator()

        before: dict[str, object] = {}
        after: dict[str, object] = {}
        for field, value in changes.items():
            current = getattr(user, field)
            if current == value:
                continue
            # The name is not audited: only role and the two flags are (SR-12).
            if field != "full_name":
                before[field] = getattr(current, "value", current)
                after[field] = getattr(value, "value", value)
            setattr(user, field, value)
        self._session.flush()

        self._record(
            AuditAction.USER_UPDATED,
            user,
            actor,
            before=before,
            after={**after, "fields": sorted(changes)},
        )
        self._session.commit()
        return UserAdminOut.model_validate(user)

    def unlock_user(self, user_id: uuid.UUID, actor: User) -> UserAdminOut:
        """Clear the failed-login counter and the lock (FR-63, SR-03)."""
        user = self._require_user(user_id)
        user.failed_login_count = 0
        user.locked_until = None
        self._session.flush()
        self._record(AuditAction.USER_UNLOCKED, user, actor)
        self._session.commit()
        return UserAdminOut.model_validate(user)

    def reset_password(self, user_id: uuid.UUID, actor: User) -> UserWithTemporaryPassword:
        """Issue a new temporary password, returned once (FR-60).

        The account is also unlocked: the person is being let back in, and a lock
        left over from earlier failures would defeat that.
        """
        user = self._require_user(user_id)
        temporary_password = generate_temporary_password()
        user.password_hash = hash_password(temporary_password)
        user.must_change_password = True
        user.failed_login_count = 0
        user.locked_until = None
        self._session.flush()
        self._record(AuditAction.USER_PASSWORD_RESET, user, actor)
        self._session.commit()
        return UserWithTemporaryPassword(
            user=UserAdminOut.model_validate(user), temporary_password=temporary_password
        )

    # --- helpers ---------------------------------------------------------

    def _require_user(self, user_id: uuid.UUID) -> User:
        user = self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFound()
        return user

    @staticmethod
    def _require_approval_allowed(role: UserRole, can_approve_kb: bool) -> None:
        if can_approve_kb and role is not UserRole.VETERINARY_REVIEWER:
            raise InvalidUserUpdate(KB_APPROVAL_MESSAGE, field="can_approve_kb")

    def _record(
        self,
        action: AuditAction,
        target: User,
        actor: User,
        *,
        before: dict | None = None,
        after: dict | None = None,
    ) -> None:
        self._audit.record(
            action=action,
            entity_type=USER_ENTITY,
            entity_id=str(target.id),
            user_id=actor.id,
            role=actor.role,
            before=before,
            after=after,
        )
