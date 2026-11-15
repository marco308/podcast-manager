"""Shared router helpers for talking to Spotify as the signed-in user.

Every route that calls Spotify gets its client from :func:`spotify_client`,
so they all share the same token handling: a token fresh from
:class:`TokenManager` (refreshed just in time, under the per-user lock), the
manager itself for 401 recovery (``on_unauthorized=token_manager.force_refresh``),
and one answer when the stored credentials can't be read, whether that shows up
on the first token read or inside a 401 retry.
"""

import logging

from fastapi import HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import Response
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.routers.auth import clear_session_cookies
from app.services.encryption import TokenDecryptionError
from app.services.spotify import REQUEST_MAX_RETRY_AFTER_SECONDS, SpotifyService
from app.services.token_manager import TokenManager

logger = logging.getLogger(__name__)

REAUTH_DETAIL = "Stored credentials could not be read. Please sign in again."


class ReauthRequired(HTTPException):
    """A 401 that also signs the client out.

    Raised once the user's sessions are gone; :func:`reauth_required_handler`
    clears the session and CSRF cookies on the way out.
    """

    def __init__(self, detail: str = REAUTH_DETAIL) -> None:
        super().__init__(status_code=401, detail=detail)


async def reauth_required_handler(request: Request, exc: ReauthRequired) -> Response:
    """Render :class:`ReauthRequired` as a plain 401 that clears the cookies."""
    response = await http_exception_handler(request, exc)
    clear_session_cookies(response)
    return response


async def sign_out_for_reauth(db: AsyncSession, user_id: int) -> ReauthRequired:
    """Delete every session of a user whose stored credentials are unreadable.

    If the stored Spotify tokens can't be decrypted (key rotation,
    corruption), the only way forward is a fresh Spotify login. A 401 alone
    isn't enough: the session would stay valid, so the web client's redirect
    to ``/login`` would see ``/auth/status`` report "authenticated" and bounce
    straight back. So the user's sessions are deleted — every one of them,
    since none can reach Spotify any more — and the caller raises the
    returned :class:`ReauthRequired`, whose handler clears the cookies,
    leaving the client on a working login page.
    """
    logger.warning(f"Stored credentials for user {user_id} could not be decrypted; signing out to force reauth")
    # Drop anything the request had pending; it is failing anyway.
    await db.rollback()
    await db.execute(delete(Session).where(Session.user_id == user_id))
    await db.commit()
    return ReauthRequired()


class RequestTokenManager:
    """A :class:`TokenManager` for request paths: unreadable credentials sign out.

    Either token can turn out unreadable: the access token on the first
    ``get_token``, or only the refresh token, which is first decrypted when a
    refresh runs — just in time, or inside a 401 retry through
    ``force_refresh`` (issue #308). Both end in :func:`sign_out_for_reauth`.
    """

    def __init__(self, db: AsyncSession, user_id: int) -> None:
        self._db = db
        self._user_id = user_id
        self._manager = TokenManager(user_id)

    async def get_token(self, *, min_remaining_seconds: int = 300) -> str:
        try:
            return await self._manager.get_token(min_remaining_seconds=min_remaining_seconds)
        except TokenDecryptionError:
            raise await sign_out_for_reauth(self._db, self._user_id) from None

    async def force_refresh(self, rejected_token: str | None = None) -> str:
        try:
            return await self._manager.force_refresh(rejected_token)
        except TokenDecryptionError:
            raise await sign_out_for_reauth(self._db, self._user_id) from None


async def spotify_client(db: AsyncSession, user_id: int) -> tuple[SpotifyService, RequestTokenManager]:
    """A Spotify client with a fresh token, plus the manager for 401 recovery.

    Pass ``on_unauthorized=token_manager.force_refresh`` to every call. A
    route that catches broad exceptions around those calls must let
    :class:`ReauthRequired` through.

    The client gives up on a 429 sooner than a job's would
    (``REQUEST_MAX_RETRY_AFTER_SECONDS``): the request is holding a
    connection, and often a lock, while it sleeps.

    Raises:
        ReauthRequired: the stored credentials could not be decrypted.
    """
    token_manager = RequestTokenManager(db, user_id)
    token = await token_manager.get_token()
    return SpotifyService(access_token=token, max_retry_after=REQUEST_MAX_RETRY_AFTER_SECONDS), token_manager
