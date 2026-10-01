"""Database access for `users`. No business rules live here (CLAUDE.md §7)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User


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
