"""Password hashing, session tokens, and the password policy (SR-02, SR-04).

Argon2id is the hashing algorithm (ADR-11); do not substitute another without
updating SRS §SR-02 and re-hashing on next login. The session token is an HS256
JWT carried only in an HttpOnly cookie — see `app/api/cookies.py`.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

from app.core.config import get_settings
from app.core.errors import WeakPassword
from app.models.enums import UserRole

_password_hasher = PasswordHasher()

JWT_ALGORITHM = "HS256"

# SR-03: five consecutive failures lock the account for fifteen minutes. These
# are requirement values, not deployment knobs, so they live here.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# SR-02: at least twelve characters, with at least one letter and one digit.
MIN_PASSWORD_LENGTH = 12
PASSWORD_POLICY_MESSAGE = (
    "Use at least 12 characters, including at least one letter and one number."  # noqa: S105
)

_HAS_LETTER = re.compile(r"[A-Za-z]")
_HAS_DIGIT = re.compile(r"\d")


class InvalidSessionToken(Exception):
    """The session cookie is missing a valid, unexpired token."""


def hash_password(plain: str) -> str:
    return _password_hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    """True when `plain` matches `password_hash`.

    Returns False rather than raising for every rejection, including a stored
    hash that argon2 cannot parse, so a damaged row cannot turn a failed login
    into a 500. `InvalidHashError` is a `ValueError`, not an `Argon2Error`, so it
    has to be named separately.
    """
    try:
        return _password_hasher.verify(password_hash, plain)
    except (Argon2Error, InvalidHashError):
        return False


def validate_password_policy(password: str) -> None:
    """Raise `WeakPassword` unless `password` satisfies SR-02."""
    if (
        len(password) < MIN_PASSWORD_LENGTH
        or _HAS_LETTER.search(password) is None
        or _HAS_DIGIT.search(password) is None
    ):
        raise WeakPassword(PASSWORD_POLICY_MESSAGE)


def create_session_token(
    user_id: uuid.UUID,
    role: UserRole,
    *,
    issued_at: datetime | None = None,
) -> str:
    """Sign a session token for `user_id`.

    `exp` is `issued_at + SESSION_IDLE_MINUTES`; the cookie is re-issued on
    every authenticated request, which is what makes the timeout an idle one
    (SR-04). `issued_at` is injectable so a test can mint an already-expired
    token without touching the clock.
    """
    settings = get_settings()
    now = issued_at or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.session_idle_minutes)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_session_token(token: str) -> dict:
    """Verify and decode a session token, or raise `InvalidSessionToken`."""
    try:
        return jwt.decode(
            token,
            get_settings().secret_key,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "role", "iat", "exp", "jti"]},
        )
    except jwt.PyJWTError as error:
        raise InvalidSessionToken(str(error)) from error
