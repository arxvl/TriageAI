"""Database access for `users`. No business rules live here (CLAUDE.md §7)."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import User, UserRole


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_email(self, email: str) -> User | None:
        """Look up an account by e-mail, ignoring case and surrounding spaces.

        Staff type their address on a shared workstation; `Intake@Clinic.local`
        is the same account as `intake@clinic.local`.
        """
        normalised = email.strip().lower()
        statement = select(User).where(func.lower(User.email) == normalised)
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self._session.get(User, user_id)

    def list_users(self, search: str | None = None) -> list[User]:
        """Every account, optionally narrowed by name or e-mail, ordered by name."""
        statement = select(User)
        if search:
            pattern = f"%{_escape_like(search)}%"
            statement = statement.where(
                or_(
                    User.full_name.ilike(pattern, escape="\\"),
                    User.email.ilike(pattern, escape="\\"),
                )
            )
        statement = statement.order_by(func.lower(User.full_name), User.id)
        return list(self._session.execute(statement).scalars())

    def add(self, user: User) -> User:
        """Flushes; never commits."""
        self._session.add(user)
        self._session.flush()
        return user

    def count_active_administrators(self) -> int:
        statement = select(func.count()).where(
            User.role == UserRole.ADMINISTRATOR, User.is_active.is_(True)
        )
        return int(self._session.execute(statement).scalar_one())


def _escape_like(value: str) -> str:
    """Make `%` and `_` literal, so searching for "j_cruz" finds that address only."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
