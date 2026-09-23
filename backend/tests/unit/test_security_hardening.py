"""Security hardening: owner lock, registration race, hashed session IDs,
debug-only API docs, SQL echo and security headers.

- ``OWNER_SPOTIFY_ID`` refuses every other Spotify account at the callback,
  including the first sign-in on an empty database.
- Two first sign-ins arriving together must not both register: the lookup,
  count and insert run under ``_registration_lock``.
- Sessions store the SHA-256 of the ID; the cookie value is hashed for every
  lookup, and the stored value is useless as a cookie.
- ``/api/docs``, ``/api/redoc`` and ``/api/openapi.json`` exist only with DEBUG.
- Every response carries nosniff / frame / referrer headers and a CSP.
"""

import asyncio
import hashlib
import itertools
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import engine as app_engine
from app.main import SecurityHeadersMiddleware, app, docs_urls
from app.models import Base, Session, User
from app.routers import auth as auth_module
from app.routers.auth import callback
from app.services.session import SessionService, hash_session_id


def _patch_spotify(monkeypatch, spotify_ids):
    """Stub SpotifyService; each profile fetch returns the next ID in turn."""
    ids = itertools.cycle(spotify_ids)
    token_data = {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
    }

    async def get_current_user():
        spotify_id = next(ids)
        # Yield so concurrent callbacks interleave the way real requests do.
        await asyncio.sleep(0)
        return {"id": spotify_id, "display_name": spotify_id, "email": f"{spotify_id}@example.com"}

    instance = MagicMock()
    instance.exchange_code_for_tokens = AsyncMock(return_value=token_data)
    instance.get_current_user = get_current_user
    monkeypatch.setattr(auth_module, "SpotifyService", MagicMock(return_value=instance))


async def _callback(db):
    return await callback(
        code="authcode",
        state="the-state",
        error=None,
        oauth_state="the-state",
        oauth_verifier="verifier",
        mobile_redirect_scheme=None,
        db=db,
        session_service=SessionService(),
    )


@pytest_asyncio.fixture
async def maker(tmp_path):
    """A file-backed database, so concurrent callbacks get separate
    connections like real requests do."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    await engine.dispose()


@pytest.fixture(autouse=True)
def fresh_registration_lock(monkeypatch):
    """asyncio.Lock binds to the first loop that contends for it; each test
    runs on its own loop."""
    monkeypatch.setattr(auth_module, "_registration_lock", asyncio.Lock())


async def _user_ids(maker) -> list[str]:
    async with maker() as db:
        return list((await db.execute(select(User.spotify_id))).scalars().all())


class TestOwnerSpotifyId:
    @pytest.mark.asyncio
    async def test_non_owner_first_sign_in_is_refused(self, maker, monkeypatch):
        monkeypatch.setattr(auth_module.settings, "OWNER_SPOTIFY_ID", "owner")
        _patch_spotify(monkeypatch, ["intruder"])

        async with maker() as db:
            with pytest.raises(HTTPException) as exc_info:
                await _callback(db)

        assert exc_info.value.status_code == 403
        assert "single-user" in exc_info.value.detail
        assert await _user_ids(maker) == []

    @pytest.mark.asyncio
    async def test_owner_signs_in(self, maker, monkeypatch):
        monkeypatch.setattr(auth_module.settings, "OWNER_SPOTIFY_ID", "owner")
        _patch_spotify(monkeypatch, ["owner"])

        async with maker() as db:
            response = await _callback(db)

        assert response.status_code == 302
        assert await _user_ids(maker) == ["owner"]

    @pytest.mark.asyncio
    async def test_unset_keeps_first_sign_in_wins(self, maker, monkeypatch):
        monkeypatch.setattr(auth_module.settings, "OWNER_SPOTIFY_ID", "")
        _patch_spotify(monkeypatch, ["first", "second"])

        async with maker() as db:
            await _callback(db)
        async with maker() as db:
            with pytest.raises(HTTPException) as exc_info:
                await _callback(db)

        assert exc_info.value.status_code == 403
        assert await _user_ids(maker) == ["first"]


class TestConcurrentRegistration:
    @pytest.mark.asyncio
    async def test_two_first_sign_ins_register_one_user(self, maker, monkeypatch):
        _patch_spotify(monkeypatch, ["alice", "mallory"])

        async def attempt():
            async with maker() as db:
                return await _callback(db)

        results = await asyncio.gather(attempt(), attempt(), return_exceptions=True)

        refused = [r for r in results if isinstance(r, HTTPException)]
        assert len(refused) == 1 and refused[0].status_code == 403, results
        assert len(await _user_ids(maker)) == 1

    @pytest.mark.asyncio
    async def test_same_account_signing_in_twice_at_once_is_fine(self, maker, monkeypatch):
        _patch_spotify(monkeypatch, ["alice"])

        async def attempt():
            async with maker() as db:
                return await _callback(db)

        results = await asyncio.gather(attempt(), attempt(), return_exceptions=True)

        assert all(r.status_code == 302 for r in results), results
        assert await _user_ids(maker) == ["alice"]


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with maker() as session:
        user = User(
            spotify_id="me",
            access_token="enc-access",
            refresh_token="enc-refresh",
            token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(user)
        await session.flush()
        yield session, user
    await engine.dispose()


class TestHashedSessionIds:
    @pytest.mark.asyncio
    async def test_only_the_hash_is_stored(self, db):
        db, user = db
        session, session_id = await SessionService().create_session(db, user.id)

        stored = (await db.execute(select(Session.session_id_hash))).scalar_one()
        assert stored == hashlib.sha256(session_id.encode()).hexdigest()
        assert stored != session_id
        assert session.session_id_hash == stored

    @pytest.mark.asyncio
    async def test_lookup_by_cookie_value(self, db):
        db, user = db
        service = SessionService()
        session, session_id = await service.create_session(db, user.id)

        assert await service.get_session(db, session_id) is session

    @pytest.mark.asyncio
    async def test_stored_hash_is_not_a_valid_cookie(self, db):
        db, user = db
        service = SessionService()
        session, _ = await service.create_session(db, user.id)

        assert await service.get_session(db, session.session_id_hash) is None

    @pytest.mark.asyncio
    async def test_delete_session(self, db):
        db, user = db
        service = SessionService()
        session, session_id = await service.create_session(db, user.id)
        other, other_id = await service.create_session(db, user.id)

        await service.delete_session(db, session)

        assert await service.get_session(db, session_id) is None
        assert await service.get_session(db, other_id) is other

    @pytest.mark.asyncio
    async def test_callback_cookie_resolves_to_the_session(self, maker, monkeypatch):
        _patch_spotify(monkeypatch, ["alice"])
        async with maker() as db:
            response = await _callback(db)

        set_cookies = [v.decode() for k, v in response.raw_headers if k == b"set-cookie"]
        cookie = next(c for c in set_cookies if c.startswith("session_id="))
        session_id = cookie.split(";", 1)[0].split("=", 1)[1]

        async with maker() as db:
            session = await SessionService().get_session(db, session_id)
            count = (await db.execute(select(func.count()).select_from(Session))).scalar_one()
        assert session is not None
        assert session.session_id_hash == hash_session_id(session_id)
        assert count == 1


class TestApiDocsDebugOnly:
    @pytest.mark.parametrize("path", ["/api/docs", "/api/redoc", "/api/openapi.json"])
    def test_docs_are_not_served_without_debug(self, path):
        assert TestClient(app).get(path).status_code == 404

    def test_debug_serves_them(self):
        assert docs_urls(True) == {
            "docs_url": "/api/docs",
            "redoc_url": "/api/redoc",
            "openapi_url": "/api/openapi.json",
        }
        assert set(docs_urls(False).values()) == {None}


class TestSecurityHeaders:
    def _assert_headers(self, response, csp=True):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        if csp:
            assert response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
        else:
            assert "content-security-policy" not in response.headers

    def test_on_api_responses(self):
        self._assert_headers(TestClient(app).get("/api/health"))

    def test_on_errors(self):
        client = TestClient(app)
        self._assert_headers(client.get("/api/nope"))
        self._assert_headers(client.get("/api/auth/me"))  # 401

    def test_on_cors_preflight(self):
        response = TestClient(app).options(
            "/api/health",
            headers={"Origin": auth_module.settings.FRONTEND_URL, "Access-Control-Request-Method": "GET"},
        )
        assert response.status_code == 200
        self._assert_headers(response)

    def test_debug_docs_get_no_csp(self):
        """Swagger UI loads from a CDN; a default-src 'none' CSP would blank it."""
        debug_app = FastAPI(**docs_urls(True))
        debug_app.add_middleware(SecurityHeadersMiddleware)
        client = TestClient(debug_app)

        docs = client.get("/api/docs")
        assert docs.status_code == 200
        self._assert_headers(docs, csp=False)
        self._assert_headers(client.get("/api/openapi.json"))

    def test_endpoint_header_is_not_overridden(self):
        custom = FastAPI()
        custom.add_middleware(SecurityHeadersMiddleware)

        @custom.get("/framed")
        def framed():
            return JSONResponse({}, headers={"X-Frame-Options": "SAMEORIGIN"})

        response = TestClient(custom).get("/framed")
        assert response.headers.get_list("x-frame-options") == ["SAMEORIGIN"]


class TestSqlEcho:
    def test_parameters_are_hidden_and_echo_is_off_by_default(self):
        assert app_engine.sync_engine.hide_parameters is True
        assert app_engine.echo is False
