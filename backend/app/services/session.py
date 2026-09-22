"""Session management service for database-backed sessions."""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session


class SessionService:
    """Service for managing database-backed sessions."""

    SESSION_EXPIRY_HOURS = 24

    @staticmethod
    def generate_session_id() -> str:
        """Generate a cryptographically secure session ID."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def generate_csrf_token() -> str:
        """Generate a cryptographically secure CSRF token."""
        return secrets.token_urlsafe(32)

    async def create_session(self, db: AsyncSession, user_id: int) -> Session:
        """Create a new session for a user.

        Args:
            db: Database session.
            user_id: The user ID to create a session for.

        Returns:
            The created Session object.
        """
        now = datetime.now(UTC)
        session = Session(
            session_id=self.generate_session_id(),
            user_id=user_id,
            csrf_token=self.generate_csrf_token(),
            expires_at=now + timedelta(hours=self.SESSION_EXPIRY_HOURS),
            last_accessed_at=now,
        )
        db.add(session)
        await db.flush()
        return session

    async def get_session(self, db: AsyncSession, session_id: str) -> Session | None:
        """Get a valid (non-expired) session by ID.

        Args:
            db: Database session.
            session_id: The session ID to look up.

        Returns:
            The Session object if found and not expired, None otherwise.
        """
        now = datetime.now(UTC)
        result = await db.execute(
            select(Session).where(
                Session.session_id == session_id,
                Session.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    async def update_last_accessed(self, db: AsyncSession, session: Session) -> None:
        """Update session's last accessed timestamp.

        Args:
            db: Database session.
            session: The session to update.
        """
        session.last_accessed_at = datetime.now(UTC)
        await db.flush()

    async def delete_session(self, db: AsyncSession, session_id: str) -> None:
        """Delete a session by ID.

        Args:
            db: Database session.
            session_id: The session ID to delete.
        """
        await db.execute(delete(Session).where(Session.session_id == session_id))
        await db.flush()

    async def delete_user_sessions(self, db: AsyncSession, user_id: int) -> None:
        """Delete all sessions for a user.

        Args:
            db: Database session.
            user_id: The user ID whose sessions to delete.
        """
        await db.execute(delete(Session).where(Session.user_id == user_id))
        await db.flush()

    async def cleanup_expired_sessions(self, db: AsyncSession) -> int:
        """Delete all expired sessions.

        Args:
            db: Database session.

        Returns:
            Count of deleted sessions.
        """
        now = datetime.now(UTC)
        result = await db.execute(delete(Session).where(Session.expires_at < now))
        await db.flush()
        return result.rowcount or 0


# Singleton instance
_session_service: SessionService | None = None


def get_session_service() -> SessionService:
    """Get the session service singleton."""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service
