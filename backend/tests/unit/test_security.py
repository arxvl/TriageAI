"""Password hashing, the password policy, and session tokens (SR-02, SR-04)."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.errors import WeakPassword
from app.core.security import (
    JWT_ALGORITHM,
    MIN_PASSWORD_LENGTH,
    InvalidSessionToken,
    create_session_token,
    decode_session_token,
    hash_password,
    validate_password_policy,
    verify_password,
)
from app.models import UserRole

GOOD_PASSWORD = "Sampaguita2026"


# --- Hashing --------------------------------------------------------------


def test_hash_is_not_the_plain_password() -> None:
    password_hash = hash_password(GOOD_PASSWORD)

    assert GOOD_PASSWORD not in password_hash
    assert password_hash.startswith("$argon2id$")


def test_verify_accepts_the_right_password_and_rejects_others() -> None:
    password_hash = hash_password(GOOD_PASSWORD)

    assert verify_password(GOOD_PASSWORD, password_hash) is True
    assert verify_password("Sampaguita2027", password_hash) is False
    assert verify_password("", password_hash) is False


def test_the_same_password_hashes_differently_each_time() -> None:
    """Argon2 salts every hash, so two accounts never share a digest."""
    assert hash_password(GOOD_PASSWORD) != hash_password(GOOD_PASSWORD)


def test_verify_rejects_an_unparseable_stored_hash() -> None:
    """A damaged row must fail the login, not raise and become a 500."""
    assert verify_password(GOOD_PASSWORD, "not-a-real-hash") is False


# --- Password policy (SR-02) ---------------------------------------------


@pytest.mark.parametrize(
    "password",
    [
        "Short1",  # under 12 characters
        "Sampaguita1"[:11],  # one character under the limit
        "OnlyLettersHere",  # no digit
        "1234567890123",  # no letter
        "",
    ],
)
def test_policy_rejects_weak_passwords(password: str) -> None:
    with pytest.raises(WeakPassword):
        validate_password_policy(password)


@pytest.mark.parametrize("password", [GOOD_PASSWORD, "a1" * 6, "Tarsier-2026-Clinic"])
def test_policy_accepts_compliant_passwords(password: str) -> None:
    assert len(password) >= MIN_PASSWORD_LENGTH
    validate_password_policy(password)  # does not raise


def test_policy_message_tells_the_user_how_to_fix_it() -> None:
    """IR-05: the error states the requirement, not a code."""
    with pytest.raises(WeakPassword) as raised:
        validate_password_policy("short")

    assert "12 characters" in raised.value.message


# --- Session tokens (SR-04) ----------------------------------------------


def test_token_round_trip_carries_the_session_claims() -> None:
    user_id = uuid.uuid4()

    claims = decode_session_token(create_session_token(user_id, UserRole.VETERINARY_REVIEWER))

    assert claims["sub"] == str(user_id)
    assert claims["role"] == UserRole.VETERINARY_REVIEWER.value
    assert claims["jti"]
    assert claims["exp"] - claims["iat"] == get_settings().session_idle_minutes * 60


def test_each_token_has_its_own_jti() -> None:
    user_id = uuid.uuid4()

    first = decode_session_token(create_session_token(user_id, UserRole.INTAKE_STAFF))
    second = decode_session_token(create_session_token(user_id, UserRole.INTAKE_STAFF))

    assert first["jti"] != second["jti"]


def test_a_token_older_than_the_idle_timeout_is_expired() -> None:
    idle_minutes = get_settings().session_idle_minutes
    issued_at = datetime.now(UTC) - timedelta(minutes=idle_minutes + 1)

    token = create_session_token(uuid.uuid4(), UserRole.INTAKE_STAFF, issued_at=issued_at)

    with pytest.raises(InvalidSessionToken):
        decode_session_token(token)


def test_a_token_just_inside_the_idle_timeout_is_still_valid() -> None:
    idle_minutes = get_settings().session_idle_minutes
    issued_at = datetime.now(UTC) - timedelta(minutes=idle_minutes - 1)

    token = create_session_token(uuid.uuid4(), UserRole.INTAKE_STAFF, issued_at=issued_at)

    assert decode_session_token(token)["sub"]


def test_a_token_signed_with_another_key_is_rejected() -> None:
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": UserRole.ADMINISTRATOR.value,
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(minutes=30)).timestamp()),
            "jti": uuid.uuid4().hex,
        },
        "not-the-server-key",
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(InvalidSessionToken):
        decode_session_token(forged)


def test_a_tampered_token_is_rejected() -> None:
    token = create_session_token(uuid.uuid4(), UserRole.INTAKE_STAFF)
    header, payload, signature = token.split(".")

    with pytest.raises(InvalidSessionToken):
        decode_session_token(f"{header}.{payload}x.{signature}")


def test_a_token_missing_a_required_claim_is_rejected() -> None:
    """A token without `jti` or `role` is not one this application issued."""
    settings = get_settings()
    incomplete = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": int((datetime.now(UTC)).timestamp()) + 600},
        settings.secret_key,
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(InvalidSessionToken):
        decode_session_token(incomplete)
