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
from sqlalchemy.exc import SQLAlchemyError

from app.database import async_session_maker
from app.models.user import User
from app.services.encryption import get_encryption_service
from app.services.spotify import SpotifyService

logger = logging.getLogger(__name__)

# Saving a rotated refresh token is retried this many times in total, with a
# linearly growing pause, before the failure is logged as unrecoverable.
TOKEN_COMMIT_ATTEMPTS = 3
TOKEN_COMMIT_RETRY_DELAY_SECONDS = 0.5


class TokenManager:
    """Manages a single user's Spotify access token with just-in-time refresh.

    The manager is scoped to a ``user_id`` and opens its own short-lived DB
    session per call. A refresh keeps that session open across the Spotify
    ``POST /api/token`` call (it reads the refresh token, calls Spotify, then
    writes the rotated tokens back on the same session), so at most one such
    session per user is open at a time — the per-user ``asyncio.Lock`` that
    makes concurrent ``get_token`` / ``force_refresh`` calls share a single
    refresh also serialises the sessions.
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
        """Compute seconds until token expiry.

        ``User.token_expires_at`` is a :class:`UTCDateTime`, so it always
        reads back timezone-aware and needs no naive fix-up (issue #156).
        """
        return (token_expires_at - datetime.now(UTC)).total_seconds()

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

    async def force_refresh(self, rejected_token: str | None = None) -> str:
        """Refresh after a 401 and return the new bearer token.

        Intended as the ``on_unauthorized`` callback for
        :func:`SpotifyService._request_with_retry`, which passes the token
        Spotify just rejected. When Spotify returns 401 we want a refresh even
        if the cached expiry says we should still be valid (clock skew,
        revoked token, etc.) — unless another caller already refreshed while
        this one was waiting: if the stored token is no longer the rejected
        one, it is returned as-is. Every needless refresh rotates the refresh
        token, so a burst of concurrent 401s must share one refresh.

        Args:
            rejected_token: The bearer token that got the 401. ``None``
                refreshes unconditionally.
        """
        lock = self._lock_for(self._user_id)
        async with lock, async_session_maker() as db:
            result = await db.execute(select(User).where(User.id == self._user_id))
            user = result.scalar_one_or_none()
            if user is None:
                raise RuntimeError(f"User {self._user_id} not found")

            if rejected_token is not None:
                current = self._encryption.decrypt(user.access_token)
                if current != rejected_token and self._seconds_remaining(user.token_expires_at) > 0:
                    logger.info("Token for user %s was already refreshed; skipping refresh", self._user_id)
                    return current

            return await self._refresh_locked(db, user)

    async def _refresh_locked(self, db, user: User) -> str:
        """Perform the actual refresh + persist. Must be called with lock held.

        The DB session ``db`` is short-lived (created by the caller); we
        commit it before returning so the new token is durable even if the
        caller crashes immediately after.

        Once Spotify has answered, the old refresh token is already dead —
        Spotify rotates it on every refresh — so failing to store the new one
        loses the user's credentials for good. The commit is therefore retried
        a few times (a busy SQLite is the likely cause), and a final failure
        is logged at CRITICAL before it propagates.
        """
        refresh_token = self._encryption.decrypt(user.refresh_token)
        spotify = SpotifyService()
        token_data = await spotify.refresh_access_token(refresh_token)

        encrypted_access = self._encryption.encrypt(token_data["access_token"])
        encrypted_refresh = self._encryption.encrypt(token_data["refresh_token"])
        for attempt in range(1, TOKEN_COMMIT_ATTEMPTS + 1):
            try:
                user.access_token = encrypted_access
                user.refresh_token = encrypted_refresh
                user.token_expires_at = token_data["expires_at"]
                await db.commit()
                break
            except SQLAlchemyError as e:
                await db.rollback()
                if attempt == TOKEN_COMMIT_ATTEMPTS:
                    logger.critical(
                        "Spotify rotated the refresh token for user %s but saving it failed %d times (%s). "
                        "The stored refresh token is now invalid; the user must sign in again.",
                        self._user_id,
                        attempt,
                        e,
                    )
                    raise
                logger.warning(
                    "Saving refreshed Spotify token for user %s failed (attempt %d/%d): %s — retrying",
                    self._user_id,
                    attempt,
                    TOKEN_COMMIT_ATTEMPTS,
                    e,
                )
                await asyncio.sleep(TOKEN_COMMIT_RETRY_DELAY_SECONDS * attempt)

        logger.info("Refreshed Spotify token for user %s", self._user_id)
        return token_data["access_token"]
