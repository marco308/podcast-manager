"""Tests for auth-router fixes.

- Issue #172: the OAuth callback must re-validate the ``mobile_redirect_scheme``
  cookie against ``ALLOWED_REDIRECT_SCHEMES``. Only ``/login`` validated it, so
  a cookie planted from a sibling subdomain (``COOKIE_DOMAIN=.example.com``)
  would exfiltrate the single-use exchange code to an arbitrary URL scheme.
- Issue #173: ``POST /api/auth/mobile-exchange`` is unauthenticated, so its
  rate limit must key on client IP — the default session-cookie key hands a
  fresh bucket to every forged cookie value.
- Issue #182: ``secrets.compare_digest`` raises TypeError on non-ASCII str
  input, turning garbage in the CSRF header or OAuth state param into a 500.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.routers.auth as auth_module
from app.database import Base
from app.models import User  # noqa: F401 — importing app.models registers every table on Base.metadata
from app.rate_limit import limiter
from app.routers.auth import callback, validate_csrf_token
from app.services.session import SessionService


class TestCsrfCompareDigest:
    """Issue #182 — non-ASCII CSRF header must be a 403 mismatch, not a 500."""

    def test_non_ascii_csrf_header_is_403(self):
        session = MagicMock(csrf_token="tok123")
        with pytest.raises(HTTPException) as exc_info:
            validate_csrf_token(x_csrf_token="café☃", session=session)
        assert exc_info.value.status_code == 403

    def test_matching_token_still_passes(self):
        session = MagicMock(csrf_token="tok123")
        assert validate_csrf_token(x_csrf_token="tok123", session=session) is session

    def test_wrong_ascii_token_is_403(self):
        session = MagicMock(csrf_token="tok123")
        with pytest.raises(HTTPException) as exc_info:
            validate_csrf_token(x_csrf_token="nope", session=session)
        assert exc_info.value.status_code == 403


class TestOAuthStateCompareDigest:
    """Issue #182 — non-ASCII state param must be a 400 mismatch, not a 500."""

    @pytest.mark.asyncio
    async def test_non_ascii_state_is_400(self):
        # The state check runs before any DB or Spotify access, so mocks
        # for those collaborators are never touched.
        with pytest.raises(HTTPException) as exc_info:
            await callback(
                code="authcode",
                state="café☃",
                error=None,
                oauth_state="ascii-state",
                oauth_verifier="verifier",
                mobile_redirect_scheme=None,
                db=MagicMock(),
                session_service=MagicMock(),
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "OAuth state mismatch"


def _patch_spotify(monkeypatch):
    """Stub the two SpotifyService instances the callback constructs."""
    token_data = {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
    }
    instance = MagicMock()
    instance.exchange_code_for_tokens = AsyncMock(return_value=token_data)
    instance.get_current_user = AsyncMock(
        return_value={"id": "spotify-user", "display_name": "User", "email": "user@example.com"}
    )
    monkeypatch.setattr(auth_module, "SpotifyService", MagicMock(return_value=instance))


async def _run_callback(monkeypatch, mobile_redirect_scheme):
    """Drive the callback against an in-memory DB with Spotify stubbed out."""
    _patch_spotify(monkeypatch)
    monkeypatch.setattr(auth_module, "issue_exchange_code", AsyncMock(return_value="exchange-code-123"))

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    try:
        async with maker() as db:
            return await callback(
                code="authcode",
                state="the-state",
                error=None,
                oauth_state="the-state",
                oauth_verifier="verifier",
                mobile_redirect_scheme=mobile_redirect_scheme,
                db=db,
                session_service=SessionService(),
            )
    finally:
        await engine.dispose()


class TestCallbackSchemeRevalidation:
    """Issue #172 — the callback must not trust the redirect-scheme cookie."""

    @pytest.mark.asyncio
    async def test_allowed_scheme_redirects_to_app(self, monkeypatch):
        response = await _run_callback(monkeypatch, "podcastmanager")
        assert response.headers["location"] == "podcastmanager://auth/callback?code=exchange-code-123"

    @pytest.mark.asyncio
    async def test_planted_scheme_falls_through_to_web_flow(self, monkeypatch):
        response = await _run_callback(monkeypatch, "evilscheme")
        location = response.headers["location"]
        assert "evilscheme" not in location
        assert "exchange-code-123" not in location
        assert location == auth_module.settings.FRONTEND_URL

    @pytest.mark.asyncio
    async def test_planted_scheme_cookie_is_deleted(self, monkeypatch):
        response = await _run_callback(monkeypatch, "evilscheme")
        set_cookies = [v.decode() for k, v in response.raw_headers if k == b"set-cookie"]
        deletions = [c for c in set_cookies if c.startswith("mobile_redirect_scheme=")]
        assert deletions, "expected the planted cookie to be cleared"
        assert all("Max-Age=0" in c for c in deletions)


class TestMobileExchangeRateLimitKey:
    """Issue #173 — rotating forged session cookies must not reset the bucket."""

    @pytest.fixture(autouse=True)
    def _reset_limiter(self):
        limiter.reset()
        yield
        limiter.reset()

    def test_rotating_session_cookies_share_one_ip_bucket(self):
        from app.main import app

        client = TestClient(app)
        body = {"code": "x" * 32}
        # 10/minute allowance — each request forges a different session_id,
        # which previously minted a fresh bucket per value.
        for i in range(10):
            response = client.post(
                "/api/auth/mobile-exchange",
                json=body,
                headers={"Cookie": f"session_id=forged-{i}"},
            )
            assert response.status_code == 401
        response = client.post(
            "/api/auth/mobile-exchange",
            json=body,
            headers={"Cookie": "session_id=forged-final"},
        )
        assert response.status_code == 429
