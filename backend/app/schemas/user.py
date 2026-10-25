"""Request and response bodies for `/users` (P09 §9.1, FR-60, FR-63, BR-04).

`UserAdminOut` is the administrator's view of an account. It never carries
`password_hash`. The temporary password has a response type of its own,
`UserWithTemporaryPassword`, used by exactly two endpoints (create and reset),
so "the password appears only once" can be checked by looking at one class.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import UserRole

SEARCH_MAX_LENGTH = 100

# A deliberately loose shape check: one `@`, no spaces, a dot in the domain. The
# address is only ever a sign-in name, and the project does not add the
# `email-validator` dependency for it.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=320, pattern=EMAIL_PATTERN)
    role: UserRole
    can_approve_kb: bool = False

    _stripped = field_validator("full_name", "email", mode="before")(_strip)


class UserUpdate(BaseModel):
    """Only the fields FR-60 lets an administrator edit; the e-mail is fixed."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: UserRole | None = None
    can_approve_kb: bool | None = None
    is_active: bool | None = None

    _stripped = field_validator("full_name", mode="before")(_strip)


class UserFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, max_length=SEARCH_MAX_LENGTH)

    @field_validator("q", mode="before")
    @classmethod
    def _blank_search_is_absent(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class UserAdminOut(BaseModel):
    """Everything the W-09 table shows. No credential material of any kind."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str
    role: UserRole
    can_approve_kb: bool
    is_active: bool
    must_change_password: bool
    locked_until: datetime | None
    last_login_at: datetime | None


class UserListOut(BaseModel):
    items: list[UserAdminOut]
    total: int


class UserWithTemporaryPassword(BaseModel):
    """The only response that carries a password, shown once (FR-60, SR-03)."""

    user: UserAdminOut
    temporary_password: str
