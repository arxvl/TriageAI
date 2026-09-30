from argon2 import PasswordHasher

_password_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _password_hasher.hash(plain)
