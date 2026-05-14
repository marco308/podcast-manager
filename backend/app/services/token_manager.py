"""Per-user Spotify token manager with just-in-time refresh.

Issue #89: long-running playlist build jobs would decrypt a single bearer
token up front, then 20+ minutes later try to write playlists with a token
Spotify had already expired. The fix is to refresh the token immediately
before each playlist write (and on a 401 retry), with a per-user
``asyncio.Lock`` so concurrent callers share a single refresh — Spotify
rotates the refresh token on every refresh, and two concurrent refresh
calls can invalidate each other.

Usage::

    tm = TokenManager(user_id=user.id)
    token = await tm.get_token(min_remaining_seconds=300)
    # ... pass token + tm.force_refresh as on_unauthorized callback ...
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import async_session_maker
from app.models.user import User
from app.services.encryption import get_encryption_service
from app.services.spotify import SpotifyService

logger = logging.getLogger(__name__)


class TokenManager:
    """Manages a single user's Spotify access token with just-in-time refresh.

    The manager is scoped to a ``user_id`` and uses short-lived DB sessions —
    it does NOT hold a session across the Spotify ``POST /api/token`` call.
    Concurrent ``get_token`` calls for the same user share a single refresh
    via a class-level per-user ``asyncio.Lock``.
    """

    # Class-level so two TokenManager instances for the same user serialize
    # their refreshes. Lives for the process lifetime — acceptable for a
    # single-process app server (this is what the rest of the codebase
    # assumes too).
    _user_locks: dict[int, asyncio.Lock] = {}

    def __init__(self, user_id: int) -> None:
        """Initialize the token manager.

        Args:
            user_id: The user whose token to manage.
        """
        self._user_id = user_id
        self._encryption = get_encryption_service()

    @classmethod
    def _lock_for(cls, user_id: int) -> asyncio.Lock:
        """Get (or lazily create) the per-user refresh lock."""
        lock = cls._user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            cls._user_locks[user_id] = lock
        return lock

    @staticmethod
    def _seconds_remaining(token_expires_at: datetime) -> float:
        """Compute seconds until token expiry, tolerating naive datetimes."""
        exp = token_expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        return exp.timestamp() - datetime.now(UTC).timestamp()

    async def get_token(self, *, min_remaining_seconds: int = 300) -> str:
        """Return a valid bearer token, refreshing if it expires soon.

        Args:
            min_remaining_seconds: refresh if the access token has less than
                this many seconds of life left. Defaults to 300 (5 minutes),
                which comfortably covers Spotify's per-request latency plus
                a small safety margin.

        Returns:
            A decrypted, currently-valid Spotify access token.

        Raises:
            RuntimeError: if the user no longer exists.
            TokenDecryptionError: if the stored token can't be decrypted.
        """
        # Fast path: read current token state without acquiring the lock.
        async with async_session_maker() as db:
            result = await db.execute(select(User).where(User.id == self._user_id))
            user = result.scalar_one_or_none()
            if user is None:
                raise RuntimeError(f"User {self._user_id} not found")

            if self._seconds_remaining(user.token_expires_at) > min_remaining_seconds:
                return self._encryption.decrypt(user.access_token)

        # Slow path: refresh under the per-user lock. Re-check after acquiring
        # in case another caller already refreshed while we were waiting.
        lock = self._lock_for(self._user_id)
        async with lock, async_session_maker() as db:
            result = await db.execute(select(User).where(User.id == self._user_id))
            user = result.scalar_one_or_none()
            if user is None:
                raise RuntimeError(f"User {self._user_id} not found")

            if self._seconds_remaining(user.token_expires_at) > min_remaining_seconds:
                # Someone else refreshed while we waited for the lock.
                return self._encryption.decrypt(user.access_token)

            return await self._refresh_locked(db, user)

    async def force_refresh(self) -> str:
        """Refresh unconditionally and return the new bearer token.

        Intended as the ``on_unauthorized`` callback for
        :func:`SpotifyService._request_with_retry` — when Spotify returns 401
        we want a refresh even if the cached expiry says we should still be
        valid (clock skew, revoked token, etc.).
        """
        lock = self._lock_for(self._user_id)
        async with lock, async_session_maker() as db:
            result = await db.execute(select(User).where(User.id == self._user_id))
            user = result.scalar_one_or_none()
            if user is None:
                raise RuntimeError(f"User {self._user_id} not found")
            return await self._refresh_locked(db, user)

    async def _refresh_locked(self, db, user: User) -> str:
        """Perform the actual refresh + persist. Must be called with lock held.

        The DB session ``db`` is short-lived (created by the caller); we
        commit it before returning so the new token is durable even if the
        caller crashes immediately after.
        """
        refresh_token = self._encryption.decrypt(user.refresh_token)
        spotify = SpotifyService()
        token_data = await spotify.refresh_access_token(refresh_token)

        user.access_token = self._encryption.encrypt(token_data["access_token"])
        user.refresh_token = self._encryption.encrypt(token_data["refresh_token"])
        user.token_expires_at = token_data["expires_at"]
        await db.commit()

        logger.info("Refreshed Spotify token for user %s", self._user_id)
        return token_data["access_token"]
