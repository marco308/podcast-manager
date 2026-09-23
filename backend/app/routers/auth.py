"""Authentication router for Spotify OAuth2 flow with secure cookie-based sessions."""

import asyncio
import base64
import hashlib
import logging
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.jobs import locks
from app.models.session import Session
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.user import UserResponse
from app.services.account import AccountDeletionResult, delete_account
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
OAUTH_VERIFIER_COOKIE_NAME = "oauth_verifier"
COOKIE_MAX_AGE = 24 * 60 * 60  # 24 hours in seconds
OAUTH_STATE_MAX_AGE = 600  # 10 minutes for OAuth flow

# How long account deletion waits for a running sync or rebuild to finish
# before giving up with a 409.
ACCOUNT_DELETE_LOCK_WAIT_SECONDS = 10


def _pkce_pair() -> tuple[str, str]:
    """Return a (code_verifier, code_challenge) pair for PKCE (RFC 7636).

    Verifier is 64 bytes of URL-safe entropy. Challenge is
    BASE64URL(SHA256(verifier)) with '=' padding stripped, per the spec.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def get_cookie_settings() -> dict:
    """Get cookie configuration based on environment."""
    cookie_settings = {
        "httponly": True,
        "secure": True,  # Always True since we use HTTPS
        "samesite": "lax",  # "lax" allows OAuth redirects
        "max_age": COOKIE_MAX_AGE,
        "path": "/",
    }
    # Add domain for cross-subdomain cookies (e.g., ".example.com")
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

    # Compare as bytes — compare_digest raises TypeError on non-ASCII str
    # input, which would turn a garbage header into a 500 (issue #182).
    if not secrets.compare_digest(x_csrf_token.encode(), session.csrf_token.encode()):
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
    code_verifier, code_challenge = _pkce_pair()
    auth_url = settings.spotify_auth_url(state, code_challenge)
    logger.info("Redirecting to Spotify auth URL with state + PKCE challenge")
    response = RedirectResponse(url=auth_url)
    # Store state + verifier in httpOnly cookies for validation in the callback
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
    response.set_cookie(key=OAUTH_VERIFIER_COOKIE_NAME, value=code_verifier, **state_cookie_settings)

    # Store mobile redirect scheme if provided (for iOS/Android OAuth flow)
    if redirect_scheme:
        response.set_cookie(key=MOBILE_REDIRECT_COOKIE, value=redirect_scheme, **state_cookie_settings)

    return response


@router.get("/callback")
async def callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    oauth_state: str | None = Cookie(None, alias=OAUTH_STATE_COOKIE_NAME),
    oauth_verifier: str | None = Cookie(None, alias=OAUTH_VERIFIER_COOKIE_NAME),
    mobile_redirect_scheme: str | None = Cookie(None, alias=MOBILE_REDIRECT_COOKIE),
    db: AsyncSession = Depends(get_db),
    session_service: SessionService = Depends(get_session_service),
) -> RedirectResponse:
    """Handle Spotify OAuth callback.

    Exchanges the authorization code for tokens, creates/updates user,
    creates a database session, sets cookies, then redirects to frontend.
    """
    # `error` is attacker-controlled (anyone can hit this URL); strip line
    # breaks so it can't forge extra log lines.
    if error:
        error = error.replace("\r", " ").replace("\n", " ")
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

    # Compare as bytes — compare_digest raises TypeError on non-ASCII str
    # input, which would turn an attacker-supplied state into a 500 (issue #182).
    if not secrets.compare_digest(state.encode(), oauth_state.encode()):
        logger.error("OAuth state mismatch - possible CSRF attack")
        raise HTTPException(status_code=400, detail="OAuth state mismatch")

    # PKCE: the matching verifier was stashed in an httpOnly cookie at /login.
    # If it's missing the flow was likely forged or the cookie was cleared
    # mid-flow — either way, don't attempt the exchange.
    if not oauth_verifier:
        logger.error("Missing PKCE verifier cookie on callback")
        raise HTTPException(status_code=400, detail="Missing PKCE verifier")

    # Re-validate the mobile redirect scheme against the allowlist. /login
    # validates it on the way in, but the cookie itself is attacker-writable
    # when COOKIE_DOMAIN spans subdomains — a planted value would exfiltrate
    # the single-use exchange code to an arbitrary URL scheme (issue #172).
    # Ignore it and fall through to the web flow; the cookie is deleted below.
    if mobile_redirect_scheme is not None and mobile_redirect_scheme not in ALLOWED_REDIRECT_SCHEMES:
        logger.warning(f"Ignoring disallowed mobile redirect scheme cookie: {mobile_redirect_scheme!r}")
        mobile_redirect_scheme = None

    encryption = get_encryption_service()

    try:
        # Exchange code for tokens (with PKCE verifier)
        spotify = SpotifyService()
        token_data = await spotify.exchange_code_for_tokens(code, code_verifier=oauth_verifier)
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
            response.delete_cookie(key=OAUTH_VERIFIER_COOKIE_NAME, **delete_kwargs)
            response.delete_cookie(key=MOBILE_REDIRECT_COOKIE, **delete_kwargs)
            logger.info("Redirecting to mobile app with exchange code")
            return response

        # Web flow: redirect to frontend with cookies. FRONTEND_URL is
        # normalised (trailing slash stripped) by Settings itself.
        response = RedirectResponse(url=settings.FRONTEND_URL, status_code=302)
        set_session_cookies(response, session)
        response.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, **delete_kwargs)
        response.delete_cookie(key=OAUTH_VERIFIER_COOKIE_NAME, **delete_kwargs)
        # Also clears any disallowed scheme cookie ignored above (issue #172).
        response.delete_cookie(key=MOBILE_REDIRECT_COOKIE, **delete_kwargs)

        logger.info("Redirecting to frontend with session cookie")
        return response

    except HTTPException:
        # Deliberate rejections (e.g. the single-user registration gate above)
        # carry their own status and message — don't flatten them into a
        # generic "Authentication failed" (issue #152).
        raise
    except Exception as e:
        logger.exception(f"OAuth callback failed: {str(e)}")
        raise HTTPException(status_code=400, detail="Authentication failed") from None


class MobileExchangeRequest(BaseModel):
    code: str = Field(min_length=16, max_length=128)


class MobileExchangeResponse(BaseModel):
    session_id: str
    csrf_token: str


# Key on client IP, not the default session-cookie key: this endpoint is
# unauthenticated, so an attacker could rotate forged session_id cookies to
# get a fresh bucket per request — bypassing the limit and growing slowapi's
# in-memory store without bound (issue #173).
@router.post("/mobile-exchange", response_model=MobileExchangeResponse)
@limiter.limit("10/minute", key_func=get_remote_address)
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


@router.delete("/me")
async def delete_me(
    response: Response,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete the signed-in user's account and data (issue #266).

    First closes ``account_write_gate`` and lets in-flight API writes drain,
    so none can insert a row for the user after it's gone. Then waits for any
    library sync or playlist write job, for the same reason. The gate comes
    first: a manual run holds the gate while it waits for the playlist lock,
    so taking the job locks first could leave both sides waiting. Spotify
    playlists are left in place; see ``services/account.py``.
    """
    busy = HTTPException(
        status_code=409,
        detail="A sync or playlist update is running. Try again in a minute.",
    )
    try:
        async with locks.account_write_gate.exclusive(ACCOUNT_DELETE_LOCK_WAIT_SECONDS):
            result = await _delete_holding_job_locks(db, session.user_id, busy)
    except TimeoutError:
        raise busy from None

    logger.info(
        f"Deleted account {session.user_id}: {result.playlists} playlists, "
        f"{result.podcasts} podcasts, {result.sessions} sessions"
    )
    clear_session_cookies(response)
    return {"message": "Your account and data have been deleted"}


async def _delete_holding_job_locks(db: AsyncSession, user_id: int, busy: HTTPException) -> AccountDeletionResult:
    acquired: list[asyncio.Lock] = []
    try:
        for lock in (locks.library_sync_lock, locks.playlist_write_lock):
            try:
                await asyncio.wait_for(lock.acquire(), timeout=ACCOUNT_DELETE_LOCK_WAIT_SECONDS)
            except TimeoutError:
                raise busy from None
            acquired.append(lock)

        result = await delete_account(db, user_id)
        await db.commit()
        return result
    finally:
        for lock in reversed(acquired):
            lock.release()


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
