"""Authentication router for Spotify OAuth2 flow."""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserResponse
from app.services.encryption import get_encryption_service
from app.services.spotify import SpotifyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# In-memory session store with expiration
# Maps session_id -> (user_id, created_at)
_sessions: dict[str, tuple[int, datetime]] = {}


def get_current_user_id(session_id: str | None = Query(None, alias="session")) -> int:
    """Get current user ID from session."""
    if not session_id or session_id not in _sessions:
        logger.warning(f"Session not found: {session_id}, available: {list(_sessions.keys())}")
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_id, created_at = _sessions[session_id]
    
    # Check if session expired (24 hours)
    if datetime.utcnow() - created_at > timedelta(hours=24):
        del _sessions[session_id]
        logger.info(f"Session expired: {session_id}")
        raise HTTPException(status_code=401, detail="Session expired")
    
    return user_id


@router.get("/login")
async def login() -> RedirectResponse:
    """Redirect to Spotify authorization page."""
    settings = get_settings()
    auth_url = settings.spotify_auth_url
    logger.info(f"Redirecting to Spotify auth URL: {auth_url}")
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle Spotify OAuth callback.

    Exchanges the authorization code for tokens, creates/updates user,
    then redirects to the frontend with the session ID in the query string.
    """
    logger.info(f"Callback received: code={code}, state={state}, error={error}")
    
    if error:
        logger.error(f"OAuth error: {error}")
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    
    if not code:
        logger.error("No authorization code provided")
        raise HTTPException(status_code=400, detail="No authorization code provided")
    
    settings = get_settings()
    encryption = get_encryption_service()

    try:
        # Exchange code for tokens
        spotify = SpotifyService()
        token_data = await spotify.exchange_code_for_tokens(code)
        logger.info("Successfully exchanged code for tokens")

        # Get user profile
        spotify_with_token = SpotifyService(access_token=token_data["access_token"])
        profile = await spotify_with_token.get_current_user()
        logger.info(f"Got Spotify profile: {profile.get('id')}")

        # Check if user exists
        result = await db.execute(
            select(User).where(User.spotify_id == profile["id"])
        )
        user = result.scalar_one_or_none()

        # Encrypt tokens
        encrypted_access = encryption.encrypt(token_data["access_token"])
        encrypted_refresh = encryption.encrypt(token_data["refresh_token"])

        if user:
            # Update existing user
            user.display_name = profile.get("display_name")
            user.email = profile.get("email")
            user.access_token = encrypted_access
            user.refresh_token = encrypted_refresh
            user.token_expires_at = token_data["expires_at"]
            user.updated_at = datetime.utcnow()
            logger.info(f"Updated existing user: {user.id}")
        else:
            # Create new user
            user = User(
                spotify_id=profile["id"],
                display_name=profile.get("display_name"),
                email=profile.get("email"),
                access_token=encrypted_access,
                refresh_token=encrypted_refresh,
                token_expires_at=token_data["expires_at"],
            )
            db.add(user)
            logger.info(f"Created new user for Spotify ID: {profile['id']}")

        await db.flush()
        await db.commit()
        logger.info(f"Committed user to database: {user.id}")

        # Create session AFTER user is committed
        import secrets

        session_id = secrets.token_urlsafe(32)
        _sessions[session_id] = (user.id, datetime.utcnow())
        logger.info(f"Created session {session_id} for user {user.id}")

        # Redirect the browser back to the frontend with the session ID
        frontend_base = settings.FRONTEND_URL.rstrip("/")
        redirect_url = f"{frontend_base}/?session={session_id}"
        logger.info(f"Redirecting to frontend with session: {redirect_url}")
        return RedirectResponse(url=redirect_url)

    except Exception as e:
        logger.exception(f"OAuth callback failed: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Authentication failed: {str(e)}")


@router.get("/me", response_model=UserResponse)
async def get_me(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get current authenticated user."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


@router.post("/logout")
async def logout(
    session_id: str = Query(..., alias="session"),
) -> dict[str, str]:
    """Clear session and log out."""
    if session_id in _sessions:
        del _sessions[session_id]
    return {"message": "Logged out successfully"}


@router.get("/status")
async def auth_status(
    session_id: str | None = Query(None, alias="session"),
) -> dict[str, bool]:
    """Check if user is authenticated."""
    is_authenticated = session_id is not None and session_id in _sessions
    return {"authenticated": is_authenticated}
