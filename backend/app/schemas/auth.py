"""Request and response bodies for `/auth` (IR-05).

`email` is a plain string rather than a validated address: a malformed address
must come back as the same generic 401 as a wrong password, not a 422 that
reveals the field was even looked at. The password policy is checked in the
service so the response carries the policy wording.
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import UserRole


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class UserOut(BaseModel):
    """The account fields the SPA needs. Never includes `password_hash`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str
    role: UserRole
    can_approve_kb: bool
    must_change_password: bool


class UserEnvelope(BaseModel):
    """`{"user": {...}}` — the shape of the login, me, and change-password bodies."""

    user: UserOut
