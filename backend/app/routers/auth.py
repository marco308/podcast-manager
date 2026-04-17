"""Authentication router for Spotify OAuth2 flow with secure cookie-based sessions."""

import logging
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.session import Session
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.user import UserResponse
from app.services.encryption import get_encryption_service
from app.services.mobile_auth import issue_exchange_code, redeem_exchange_code
from app.services.session import SessionService, get_session_service
from app.services.spotify import SpotifyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

settings = get_settings()

# Cookie configuration
COOKIE_NAME = "session_id"
CSRF_COOKIE_NAME = "csrf_token"
OAUTH_STATE_COOKIE_NAME = "oauth_state"
COOKIE_MAX_AGE = 24 * 60 * 60  # 24 hours in seconds
OAUTH_STATE_MAX_AGE = 600  # 10 minutes for OAuth flow


def get_cookie_settings() -> dict:
    """Get cookie configuration based on environment."""
    cookie_settings = {
        "httponly": True,
        "secure": True,  # Always True since we use HTTPS
        "samesite": "lax",  # "lax" allows OAuth redirects
        "max_age": COOKIE_MAX_AGE,
        "path": "/",
    }
    # Add domain for cross-subdomain cookies (e.g., ".marcuslab.uk")
    if settings.COOKIE_DOMAIN:
        cookie_settings["domain"] = settings.COOKIE_DOMAIN
    return cookie_settings


def set_session_cookies(response: Response, session: Session) -> None:
    """Set session and CSRF cookies on the response."""
    cookie_settings = get_cookie_settings()

    # Session cookie (HTTP-only)
    response.set_cookie(key=COOKIE_NAME, value=session.session_id, **cookie_settings)

    # CSRF cookie (NOT HTTP-only so JavaScript can read it)
    csrf_settings = {**cookie_settings, "httponly": False}
    response.set_cookie(key=CSRF_COOKIE_NAME, value=session.csrf_token, **csrf_settings)


def clear_session_cookies(response: Response) -> None:
    """Clear session cookies from the response."""
    delete_kwargs: dict = {"path": "/"}
    if settings.COOKIE_DOMAIN:
        delete_kwargs["domain"] = settings.COOKIE_DOMAIN
    response.delete_cookie(key=COOKIE_NAME, **delete_kwargs)
    response.delete_cookie(key=CSRF_COOKIE_NAME, **delete_kwargs)


async def get_current_session(
    session_id: str | None = Cookie(None, alias=COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
    session_service: SessionService = Depends(get_session_service),
) -> Session:
    """Get current session from cookie and validate it."""
    if not session_id:
        logger.warning("No session cookie provided")
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = await session_service.get_session(db, session_id)

    if not session:
        logger.warning(f"Session not found or expired: {session_id[:8]}...")
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    # Update last accessed timestamp
    await session_service.update_last_accessed(db, session)

    return session


async def get_current_user_id(
    session: Session = Depends(get_current_session),
) -> int:
    """Get current user ID from session."""
    return session.user_id


def validate_csrf_token(
    x_csrf_token: str | None = Header(None, alias="X-CSRF-Token"),
    session: Session = Depends(get_current_session),
) -> Session:
    """Validate CSRF token for state-changing operations.

    Use this dependency on POST, PUT, PATCH, DELETE endpoints.
    """
    if not x_csrf_token:
        raise HTTPException(status_code=403, detail="CSRF token missing")

    if not secrets.compare_digest(x_csrf_token, session.csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token invalid")

    return session


MOBILE_REDIRECT_COOKIE = "mobile_redirect_scheme"

# Allowed custom URL schemes for mobile OAuth redirects.
# Only schemes listed here can be used as redirect targets after OAuth callback.
ALLOWED_REDIRECT_SCHEMES: set[str] = {"podcastmanager"}


@router.get("/login")
async def login(redirect_scheme: str | None = Query(None)) -> RedirectResponse:
    """Redirect to Spotify authorization page with CSRF state parameter.

    Args:
        redirect_scheme: Optional custom URL scheme for mobile apps (e.g. "podcastmanager").
            When provided, the OAuth callback will redirect to
            ``{redirect_scheme}://auth/callback?session_id=...&csrf_token=...``
            instead of the frontend URL.
            Must be one of the allowed schemes.
    """
    # Validate redirect_scheme against allowlist to prevent credential leakage
    if redirect_scheme is not None and redirect_scheme not in ALLOWED_REDIRECT_SCHEMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid redirect_scheme. Allowed schemes: {', '.join(sorted(ALLOWED_REDIRECT_SCHEMES))}",
        )

    state = secrets.token_urlsafe(32)
    auth_url = settings.spotify_auth_url(state)
    logger.info("Redirecting to Spotify auth URL with state parameter")
    response = RedirectResponse(url=auth_url)
    # Store state in a secure cookie for validation in the callback
    state_cookie_settings = {
        "httponly": True,
        "secure": True,
        "samesite": "lax",
        "max_age": OAUTH_STATE_MAX_AGE,
        "path": "/",
    }
    if settings.COOKIE_DOMAIN:
        state_cookie_settings["domain"] = settings.COOKIE_DOMAIN
    response.set_cookie(key=OAUTH_STATE_COOKIE_NAME, value=state, **state_cookie_settings)

    # Store mobile redirect scheme if provided (for iOS/Android OAuth flow)
    if redirect_scheme:
        response.set_cookie(
            key=MOBILE_REDIRECT_COOKIE, value=redirect_scheme, **state_cookie_settings
        )

    return response


@router.get("/callback")
async def callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    oauth_state: str | None = Cookie(None, alias=OAUTH_STATE_COOKIE_NAME),
    mobile_redirect_scheme: str | None = Cookie(None, alias=MOBILE_REDIRECT_COOKIE),
    db: AsyncSession = Depends(get_db),
    session_service: SessionService = Depends(get_session_service),
) -> RedirectResponse:
    """Handle Spotify OAuth callback.

    Exchanges the authorization code for tokens, creates/updates user,
    creates a database session, sets cookies, then redirects to frontend.
    """
    logger.info(f"Callback received: code={'present' if code else 'missing'}, error={error}")

    if error:
        logger.error(f"OAuth error: {error}")
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")

    if not code:
        logger.error("No authorization code provided")
        raise HTTPException(status_code=400, detail="No authorization code provided")

    # Validate OAuth state parameter to prevent CSRF attacks
    if not state or not oauth_state:
        logger.error("Missing OAuth state parameter or state cookie")
        raise HTTPException(status_code=400, detail="Missing OAuth state parameter")

    if not secrets.compare_digest(state, oauth_state):
        logger.error("OAuth state mismatch - possible CSRF attack")
        raise HTTPException(status_code=400, detail="OAuth state mismatch")

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
        result = await db.execute(select(User).where(User.spotify_id == profile["id"]))
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
            user.updated_at = datetime.now(UTC)
            logger.info(f"Updated existing user: {user.id}")
        else:
            # Block new registrations if a user already exists (single-user app)
            existing_user_count = await db.execute(select(func.count()).select_from(User))
            if existing_user_count.scalar() > 0:
                logger.warning(f"Rejected sign-up attempt from Spotify ID: {profile['id']}")
                raise HTTPException(
                    status_code=403,
                    detail="Registration is closed. This is a single-user application.",
                )

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

        # Rotate sessions on login: invalidate any prior sessions for this user so a
        # compromised session cannot survive re-authentication. This also doubles as
        # "sign out everywhere" for the user when they re-complete OAuth.
        await session_service.delete_user_sessions(db, user.id)

        # Create database-backed session
        session = await session_service.create_session(db, user.id)
        await db.commit()
        logger.info(f"Created session for user {user.id}")

        # Clear OAuth cookies
        delete_kwargs: dict = {"path": "/"}
        if settings.COOKIE_DOMAIN:
            delete_kwargs["domain"] = settings.COOKIE_DOMAIN

        # Mobile flow: never ship the session_id/csrf_token through the URL.
        # Instead mint a single-use 2-minute exchange code; the app redeems it
        # at POST /api/auth/mobile-exchange to get the real credentials in a
        # JSON response body. Mitigates URL-scheme hijacking and log exposure.
        if mobile_redirect_scheme:
            exchange_code = await issue_exchange_code(
                session_id=session.session_id,
                csrf_token=session.csrf_token,
            )
            redirect_url = f"{mobile_redirect_scheme}://auth/callback?code={exchange_code}"
            response = RedirectResponse(url=redirect_url, status_code=302)
            response.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, **delete_kwargs)
            response.delete_cookie(key=MOBILE_REDIRECT_COOKIE, **delete_kwargs)
            logger.info("Redirecting to mobile app with exchange code")
            return response

        # Web flow: redirect to frontend with cookies
        frontend_base = settings.FRONTEND_URL.rstrip("/")
        response = RedirectResponse(url=frontend_base, status_code=302)
        set_session_cookies(response, session)
        response.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, **delete_kwargs)

        logger.info("Redirecting to frontend with session cookie")
        return response

    except Exception as e:
        logger.exception(f"OAuth callback failed: {str(e)}")
        raise HTTPException(status_code=400, detail="Authentication failed") from None


class MobileExchangeRequest(BaseModel):
    code: str = Field(min_length=16, max_length=128)


class MobileExchangeResponse(BaseModel):
    session_id: str
    csrf_token: str


@router.post("/mobile-exchange", response_model=MobileExchangeResponse)
@limiter.limit("10/minute")
async def mobile_exchange(
    request: Request,
    body: MobileExchangeRequest,
) -> MobileExchangeResponse:
    """Trade a single-use mobile exchange code for session credentials.

    The mobile OAuth callback returns `podcastmanager://auth/callback?code=…`.
    The app POSTs that `code` here; we pop it out of the pending-exchange
    map and return the real `session_id` and `csrf_token` in the JSON
    response body. Credentials never appear in any URL.

    Rate-limited because the code is 32 bytes of entropy — brute force is
    effectively impossible — but 10/min keeps a leaked-log scenario from
    being weaponised.
    """
    pending = await redeem_exchange_code(body.code)
    if pending is None:
        logger.warning("Mobile exchange attempted with invalid or expired code")
        raise HTTPException(status_code=401, detail="Invalid or expired exchange code")
    return MobileExchangeResponse(
        session_id=pending.session_id,
        csrf_token=pending.csrf_token,
    )


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


@router.get("/csrf-token")
async def get_csrf_token(
    session: Session = Depends(get_current_session),
) -> dict[str, str]:
    """Get CSRF token for the current session.

    The frontend can call this to get the CSRF token if the cookie
    isn't accessible (fallback endpoint).
    """
    return {"csrf_token": session.csrf_token}


@router.post("/logout")
async def logout(
    response: Response,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
    session_service: SessionService = Depends(get_session_service),
) -> dict[str, str]:
    """Clear session and log out."""
    await session_service.delete_session(db, session.session_id)
    await db.commit()
    clear_session_cookies(response)
    return {"message": "Logged out successfully"}


@router.get("/status")
async def auth_status(
    session_id: str | None = Cookie(None, alias=COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
    session_service: SessionService = Depends(get_session_service),
) -> dict[str, bool]:
    """Check if user is authenticated."""
    if not session_id:
        return {"authenticated": False}

    session = await session_service.get_session(db, session_id)
    return {"authenticated": session is not None}
