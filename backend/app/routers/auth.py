"""Authentication router for Spotify OAuth2 flow."""

from datetime import datetime

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

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Simple in-memory session store (for demo purposes)
# In production, use Redis or database-backed sessions
_sessions: dict[str, int] = {}


def get_current_user_id(session_id: str | None = Query(None, alias="session")) -> int:
    """Get current user ID from session."""
    if not session_id or session_id not in _sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _sessions[session_id]


@router.get("/login")
async def login() -> RedirectResponse:
    """Redirect to Spotify authorization page."""
    settings = get_settings()
    return RedirectResponse(url=settings.spotify_auth_url)


@router.get("/callback")
async def callback(
    code: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle Spotify OAuth callback.

    Exchanges the authorization code for tokens, creates/updates user,
    and redirects to frontend with session.
    """
    settings = get_settings()
    encryption = get_encryption_service()

    try:
        # Exchange code for tokens
        spotify = SpotifyService()
        token_data = await spotify.exchange_code_for_tokens(code)

        # Get user profile
        spotify_with_token = SpotifyService(access_token=token_data["access_token"])
        profile = await spotify_with_token.get_current_user()

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

        await db.flush()

        # Create session
        import secrets

        session_id = secrets.token_urlsafe(32)
        _sessions[session_id] = user.id

        # Redirect to frontend with session
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}?session={session_id}"
        )

    except Exception as e:
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
