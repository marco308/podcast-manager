"""Issue #307: the mobile exchange code is bound to the app that started the login.

The app sends ``code_challenge = BASE64URL(SHA256(code_verifier))`` to
``/api/auth/login``; the exchange code issued at the callback is then only
redeemable with that verifier. Builds that send no challenge keep working.
"""

import base64
import hashlib
import secrets
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.rate_limit import limiter
from app.routers import auth as auth_module
from app.routers.auth import MOBILE_CHALLENGE_COOKIE, callback, login
from app.services import mobile_auth
from app.services.mobile_auth import issue_exchange_code, redeem_exchange_code


def _pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@pytest.fixture(autouse=True)
def _clean_state():
    mobile_auth._pending.clear()
    limiter.reset()
    yield
    mobile_auth._pending.clear()
    limiter.reset()


class TestRedeem:
    @pytest.mark.asyncio
    async def test_matching_verifier_redeems(self):
        verifier, challenge = _pair()
        code = await issue_exchange_code("sid", "csrf", code_challenge=challenge)
        pending = await redeem_exchange_code(code, verifier)
        assert pending is not None
        assert pending.session_id == "sid"

    @pytest.mark.asyncio
    async def test_missing_verifier_is_refused(self):
        _, challenge = _pair()
        code = await issue_exchange_code("sid", "csrf", code_challenge=challenge)
        assert await redeem_exchange_code(code) is None

    @pytest.mark.asyncio
    async def test_wrong_verifier_is_refused_and_burns_the_code(self):
        verifier, challenge = _pair()
        other, _ = _pair()
        code = await issue_exchange_code("sid", "csrf", code_challenge=challenge)
        assert await redeem_exchange_code(code, other) is None
        # Single-use: the right verifier can't rescue a code already spent.
        assert await redeem_exchange_code(code, verifier) is None

    @pytest.mark.asyncio
    async def test_non_ascii_verifier_is_refused_not_an_error(self):
        _, challenge = _pair()
        code = await issue_exchange_code("sid", "csrf", code_challenge=challenge)
        assert await redeem_exchange_code(code, "é" * 43) is None

    @pytest.mark.asyncio
    async def test_code_without_challenge_still_redeems_for_old_builds(self):
        code = await issue_exchange_code("sid", "csrf")
        assert await redeem_exchange_code(code) is not None

    @pytest.mark.asyncio
    async def test_unneeded_verifier_is_ignored(self):
        verifier, _ = _pair()
        code = await issue_exchange_code("sid", "csrf")
        assert await redeem_exchange_code(code, verifier) is not None


class TestLogin:
    @pytest.mark.asyncio
    async def test_challenge_is_stored_in_a_cookie(self):
        _, challenge = _pair()
        response = await login(redirect_scheme="podcastmanager", code_challenge=challenge)
        cookies = response.headers.getlist("set-cookie")
        stored = [c for c in cookies if c.startswith(f"{MOBILE_CHALLENGE_COOKIE}=")]
        assert len(stored) == 1
        assert challenge in stored[0]
        assert "HttpOnly" in stored[0]
        # The app's challenge must not replace the backend's own Spotify PKCE.
        assert challenge not in response.headers["location"]

    @pytest.mark.asyncio
    async def test_no_challenge_sets_no_cookie(self):
        response = await login(redirect_scheme="podcastmanager", code_challenge=None)
        cookies = response.headers.getlist("set-cookie")
        assert not [c for c in cookies if c.startswith(f"{MOBILE_CHALLENGE_COOKIE}=")]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", ["short", "a" * 44, "!" * 43, "a" * 42 + "="])
    async def test_malformed_challenge_is_400(self, bad):
        with pytest.raises(HTTPException) as exc:
            await login(redirect_scheme="podcastmanager", code_challenge=bad)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_challenge_without_redirect_scheme_is_400(self):
        _, challenge = _pair()
        with pytest.raises(HTTPException) as exc:
            await login(redirect_scheme=None, code_challenge=challenge)
        assert exc.value.status_code == 400


class TestCallback:
    @pytest.mark.asyncio
    async def test_malformed_challenge_cookie_fails_the_login(self):
        """A planted cookie must not downgrade the login to an unbound code."""
        with pytest.raises(HTTPException) as exc:
            await callback(
                code="authcode",
                state="the-state",
                error=None,
                oauth_state="the-state",
                oauth_verifier="verifier",
                mobile_redirect_scheme="podcastmanager",
                mobile_code_challenge="not-a-challenge",
                db=AsyncMock(),
                session_service=AsyncMock(),
            )
        assert exc.value.status_code == 400


class TestEndpoint:
    def _client(self) -> TestClient:
        from app.main import app

        return TestClient(app)

    @pytest.mark.asyncio
    async def test_verifier_round_trip(self):
        verifier, challenge = _pair()
        code = await issue_exchange_code("sid", "csrf", code_challenge=challenge)
        response = self._client().post("/api/auth/mobile-exchange", json={"code": code, "code_verifier": verifier})
        assert response.status_code == 200
        assert response.json() == {"session_id": "sid", "csrf_token": "csrf"}

    @pytest.mark.asyncio
    async def test_bound_code_without_verifier_is_401(self):
        _, challenge = _pair()
        code = await issue_exchange_code("sid", "csrf", code_challenge=challenge)
        response = self._client().post("/api/auth/mobile-exchange", json={"code": code})
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_old_build_without_verifier_still_works(self):
        code = await issue_exchange_code("sid", "csrf")
        response = self._client().post("/api/auth/mobile-exchange", json={"code": code})
        assert response.status_code == 200


class TestCallbackWiring:
    @pytest.mark.asyncio
    async def test_challenge_cookie_reaches_the_exchange_code(self, monkeypatch):
        from tests.unit.test_fix_api_auth import _run_callback

        _, challenge = _pair()
        response = await _run_callback(monkeypatch, "podcastmanager", challenge)
        assert auth_module.issue_exchange_code.await_args.kwargs["code_challenge"] == challenge
        deletions = [c for c in response.headers.getlist("set-cookie") if c.startswith(f"{MOBILE_CHALLENGE_COOKIE}=")]
        assert len(deletions) == 1

    @pytest.mark.asyncio
    async def test_no_cookie_issues_an_unbound_code(self, monkeypatch):
        from tests.unit.test_fix_api_auth import _run_callback

        await _run_callback(monkeypatch, "podcastmanager")
        assert auth_module.issue_exchange_code.await_args.kwargs["code_challenge"] is None
