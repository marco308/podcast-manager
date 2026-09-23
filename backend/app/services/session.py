"""Session management service for database-backed sessions."""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session

logger = logging.getLogger(__name__)


def hash_session_id(session_id: str) -> str:
    """Return the stored form of a session ID: its SHA-256, hex-encoded.

    The ID is 32 random bytes, so a plain unsalted hash is enough — there is
    nothing to guess — and it keeps the lookup a single indexed equality.
    """
    return hashlib.sha256(session_id.encode()).hexdigest()


class SessionService:
    """Service for managing database-backed sessions."""

    SESSION_EXPIRY_HOURS = 24

    # How stale ``last_accessed_at`` may get before a request rewrites it.
    # Nothing reads the column at finer resolution, and every rewrite is a
    # SQLite write.
    LAST_ACCESSED_RESOLUTION = timedelta(minutes=5)

    @staticmethod
    def generate_session_id() -> str:
        """Generate a cryptographically secure session ID."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def generate_csrf_token() -> str:
        """Generate a cryptographically secure CSRF token."""
        return secrets.token_urlsafe(32)

    async def create_session(self, db: AsyncSession, user_id: int) -> tuple[Session, str]:
        """Create a new session for a user.

        Args:
            db: Database session.
            user_id: The user ID to create a session for.

        Returns:
            The created Session object and the plaintext session ID. Only its
            hash is stored, so this is the one chance to hand it to the client.
        """
        now = datetime.now(UTC)
        session_id = self.generate_session_id()
        session = Session(
            session_id_hash=hash_session_id(session_id),
            user_id=user_id,
            csrf_token=self.generate_csrf_token(),
            expires_at=now + timedelta(hours=self.SESSION_EXPIRY_HOURS),
            last_accessed_at=now,
        )
        db.add(session)
        await db.flush()
        return session, session_id

    async def get_session(self, db: AsyncSession, session_id: str) -> Session | None:
        """Get a valid (non-expired) session by ID.

        Args:
            db: Database session.
            session_id: The plaintext session ID from the client.

        Returns:
            The Session object if found and not expired, None otherwise.
        """
        now = datetime.now(UTC)
        result = await db.execute(
            select(Session).where(
                Session.session_id_hash == hash_session_id(session_id),
                Session.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    async def update_last_accessed(self, db: AsyncSession, session: Session) -> None:
        """Update session's last accessed timestamp, committing straight away.

        This runs in ``get_current_session``, i.e. at the start of every
        authenticated request, on the request's own DB session. It used to
        ``flush()``, which opens SQLite's single write transaction and keeps
        it open until the handler commits — minutes, for a manual run or a
        library sync that spends its time on Spotify calls. Every other
        writer (including ``TokenManager`` saving a rotated refresh token)
        then waited out the busy timeout and failed with "database is
        locked". So the write is throttled to once per
        ``LAST_ACCESSED_RESOLUTION`` and committed immediately; it is
        best-effort, and a failure never fails the request.

        Args:
            db: Database session.
            session: The session to update.
        """
        now = datetime.now(UTC)
        last = session.last_accessed_at
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            if now - last < self.LAST_ACCESSED_RESOLUTION:
                return
        session.last_accessed_at = now
        try:
            await db.commit()
        except Exception as e:
            logger.warning(f"Could not record session last-accessed time: {e}")
            await db.rollback()
            # The rollback expired the row; reload it so callers can keep
            # reading it (csrf_token, user_id) without a lazy load.
            await db.refresh(session)

    async def delete_session(self, db: AsyncSession, session: Session) -> None:
        """Delete a session.

        Takes the row rather than an ID: a loaded session only knows its hash.

        Args:
            db: Database session.
            session: The session to delete.
        """
        await db.execute(delete(Session).where(Session.id == session.id))
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
