"""Background job for cleaning up expired sessions."""

import logging

from app.database import async_session_maker
from app.services.session import get_session_service

logger = logging.getLogger(__name__)


async def cleanup_expired_sessions() -> None:
    """Delete all expired sessions from the database.

    This job runs periodically to clean up sessions that have expired.
    It helps keep the sessions table from growing indefinitely.
    """
    session_service = get_session_service()

    async with async_session_maker() as db:
        try:
            deleted_count = await session_service.cleanup_expired_sessions(db)
            await db.commit()
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} expired sessions")
        except Exception as e:
            logger.exception(f"Session cleanup failed: {e}")
            await db.rollback()
