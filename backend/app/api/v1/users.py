"""Account administration endpoints (FR-60, FR-63, SR-03, SR-05, BR-04).

Every route is for the Administrator and nobody else. The router holds no
business logic (CLAUDE.md §7): it declares who may call and hands the request to
`UserService`. The temporary password appears in the create and reset-password
responses and nowhere else.

Answers: 404 for an unknown id, 409 for a duplicate e-mail or when the change
would remove the last active administrator, 422 naming the field otherwise.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, require_role
from app.models import User, UserRole
from app.schemas.user import (
    UserAdminOut,
    UserCreate,
    UserFilters,
    UserListOut,
    UserUpdate,
    UserWithTemporaryPassword,
)
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])

AdminUser = Annotated[User, Depends(require_role(UserRole.ADMINISTRATOR))]


@router.get("")
def list_users(
    filters: Annotated[UserFilters, Query()], db: DbSession, admin: AdminUser
) -> UserListOut:
    """The W-09 table, optionally narrowed by name or e-mail."""
    return UserService(db).list_users(filters)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: DbSession, admin: AdminUser) -> UserWithTemporaryPassword:
    """Create an account. The temporary password is in this response only."""
    return UserService(db).create_user(payload, admin)


@router.patch("/{user_id}")
def update_user(
    user_id: uuid.UUID, payload: UserUpdate, db: DbSession, admin: AdminUser
) -> UserAdminOut:
    return UserService(db).update_user(user_id, payload, admin)


@router.post("/{user_id}/unlock")
def unlock_user(user_id: uuid.UUID, db: DbSession, admin: AdminUser) -> UserAdminOut:
    return UserService(db).unlock_user(user_id, admin)


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: uuid.UUID, db: DbSession, admin: AdminUser
) -> UserWithTemporaryPassword:
    """Issue a new temporary password. It is in this response only."""
    return UserService(db).reset_password(user_id, admin)
