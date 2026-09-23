"""Shared router helpers for talking to Spotify as the signed-in user.

Every route that calls Spotify gets its client from :func:`spotify_client`,
so they all share the same token handling: a token fresh from
:class:`TokenManager` (refreshed just in time, under the per-user lock), the
manager itself for 401 recovery (``on_unauthorized=token_manager.force_refresh``),
and one answer when the stored credentials can't be read.
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
from app.services.spotify import SpotifyService
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


async def spotify_client(db: AsyncSession, user_id: int) -> tuple[SpotifyService, TokenManager]:
    """A Spotify client with a fresh token, plus the manager for 401 recovery.

    If the stored credentials can't be decrypted (key rotation, corruption),
    the only way forward is a fresh Spotify login. A 401 alone isn't enough:
    the session would stay valid, so the web client's redirect to ``/login``
    would see ``/auth/status`` report "authenticated" and bounce straight back.
    So the user's sessions are deleted first — every one of them, since none
    can reach Spotify any more — and :class:`ReauthRequired` clears the
    cookies, leaving the client on a working login page.

    Raises:
        ReauthRequired: the stored credentials could not be decrypted.
    """
    token_manager = TokenManager(user_id)
    try:
        token = await token_manager.get_token()
    except TokenDecryptionError:
        logger.warning(f"Access token for user {user_id} could not be decrypted; signing out to force reauth")
        # Drop anything the request had pending; it is failing anyway.
        await db.rollback()
        await db.execute(delete(Session).where(Session.user_id == user_id))
        await db.commit()
        raise ReauthRequired() from None
    return SpotifyService(access_token=token), token_manager
