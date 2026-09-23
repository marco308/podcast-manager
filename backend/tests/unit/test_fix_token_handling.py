"""Spotify token handling: 401 recovery, refresh dedupe and re-auth.

- After a 401, ``SpotifyService`` used the refreshed token for the one retry
  only; later calls on the same instance (every later batch of a >100-URI
  ``replace_playlist_items``) sent the stale token, 401'd and refreshed again.
- ``TokenManager.force_refresh`` refreshed even when a concurrent caller had
  just done so. Spotify rotates the refresh token on every refresh, so each
  needless one is a chance to lose it. It now takes the rejected token and
  skips the refresh when the stored token has already moved on.
- Saving the rotated refresh token is retried: once Spotify has answered, the
  old one is dead, and a failed commit loses the credentials for good.
- ``POST /podcasts/sync`` and ``DELETE /podcasts/{id}`` used the raw stored
  access token with no refresh and no 401 recovery, and turned Spotify errors
  into bare 500s.
- Unreadable stored credentials returned 401 but left the session valid, so
  the web client's redirect to /login bounced straight back to /. The session
  is now deleted and the cookies cleared.
- The token refresh job's first run was one interval after startup.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.jobs import scheduler
from app.models import Podcast, User
from app.models.session import Session
from app.rate_limit import limiter
from app.routers import _deps
from app.routers._deps import ReauthRequired, reauth_required_handler, spotify_client
from app.routers.podcasts import sync_podcasts, unfollow_podcast
from app.services import token_manager as token_manager_module
from app.services.encryption import TokenDecryptionError
from app.services.spotify import SpotifyService
from app.services.token_manager import TokenManager

# --- SpotifyService keeps the refreshed token --------------------------------


@pytest.mark.asyncio
async def test_refreshed_token_is_used_by_every_later_batch():
    """One 401 in a 250-URI replace means one refresh, not one per batch."""
    seen: list[tuple[str, str]] = []

    async def _handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        seen.append((request.method, auth))
        if auth == "Bearer stale":
            return httpx.Response(401, json={"error": {"status": 401}})
        return httpx.Response(201, json={"snapshot_id": "s"})

    callback = AsyncMock(return_value="fresh")
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        service = SpotifyService(access_token="stale", client=client)
        uris = [f"spotify:episode:{i}" for i in range(250)]
        await service.replace_playlist_items("p1", uris, on_unauthorized=callback)

    callback.assert_awaited_once_with("stale")
    assert seen == [
        ("PUT", "Bearer stale"),
        ("PUT", "Bearer fresh"),
        ("POST", "Bearer fresh"),
        ("POST", "Bearer fresh"),
    ]
    assert service._access_token == "fresh"


# --- TokenManager.force_refresh dedupe and commit retry ----------------------


def _user_row(*, access="cached-access", expires_in=3600):
    user = MagicMock()
    user.id = 1
    user.access_token = f"enc:{access}"
    user.refresh_token = "enc:cached-refresh"
    user.token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    return user


def _encryption():
    enc = MagicMock()
    enc.decrypt.side_effect = lambda c: c.removeprefix("enc:")
    enc.encrypt.side_effect = lambda p: f"enc:{p}"
    return enc


class _FakeDb:
    """Session stand-in: returns one user row; ``commit`` fails ``failures`` times."""

    def __init__(self, user, failures=0):
        self._user = user
        self.failures = failures
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def execute(self, _stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._user
        return result

    async def commit(self):
        self.commits += 1
        if self.commits <= self.failures:
            raise OperationalError("UPDATE users", {}, Exception("database is locked"))

    async def rollback(self):
        self.rollbacks += 1


def _rotation(access="rotated-access"):
    return {
        "access_token": access,
        "refresh_token": "rotated-refresh",
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
    }


@pytest.fixture(autouse=True)
def _clear_locks():
    TokenManager._user_locks.clear()
    yield
    TokenManager._user_locks.clear()


def _patched(user, refresh, db=None):
    db = db or _FakeDb(user)
    return (
        patch.object(token_manager_module, "async_session_maker", lambda: db),
        patch.object(token_manager_module, "get_encryption_service", return_value=_encryption()),
        patch.object(token_manager_module.SpotifyService, "refresh_access_token", refresh),
        patch.object(token_manager_module, "TOKEN_COMMIT_RETRY_DELAY_SECONDS", 0),
    )


@pytest.mark.asyncio
async def test_force_refresh_skips_when_token_already_rotated():
    """The rejected token is no longer stored: someone refreshed; reuse theirs."""
    user = _user_row(access="newer-access")
    refresh = AsyncMock(return_value=_rotation())
    p1, p2, p3, p4 = _patched(user, refresh)
    with p1, p2, p3, p4:
        token = await TokenManager(1).force_refresh("stale-access")

    assert token == "newer-access"
    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_force_refresh_refreshes_when_rejected_token_is_the_stored_one():
    user = _user_row(access="cached-access")
    refresh = AsyncMock(return_value=_rotation())
    p1, p2, p3, p4 = _patched(user, refresh)
    with p1, p2, p3, p4:
        token = await TokenManager(1).force_refresh("cached-access")

    assert token == "rotated-access"
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_force_refresh_refreshes_when_stored_token_has_expired():
    """A different stored token that has itself expired is no use; refresh."""
    user = _user_row(access="other-access", expires_in=-10)
    refresh = AsyncMock(return_value=_rotation())
    p1, p2, p3, p4 = _patched(user, refresh)
    with p1, p2, p3, p4:
        token = await TokenManager(1).force_refresh("stale-access")

    assert token == "rotated-access"
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_401s_share_one_refresh():
    """Two requests rejected with the same token: one refresh, both get it."""
    user = _user_row(access="cached-access")
    refresh = AsyncMock(return_value=_rotation())
    p1, p2, p3, p4 = _patched(user, refresh)
    with p1, p2, p3, p4:
        tokens = await asyncio.gather(
            TokenManager(1).force_refresh("cached-access"),
            TokenManager(1).force_refresh("cached-access"),
        )

    assert tokens == ["rotated-access", "rotated-access"]
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_rotated_token_commit_is_retried():
    user = _user_row()
    db = _FakeDb(user, failures=1)
    refresh = AsyncMock(return_value=_rotation())
    p1, p2, p3, p4 = _patched(user, refresh, db)
    with p1, p2, p3, p4:
        token = await TokenManager(1).force_refresh()

    assert token == "rotated-access"
    assert db.commits == 2
    assert db.rollbacks == 1
    assert user.refresh_token == "enc:rotated-refresh"
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_rotated_token_commit_failure_is_logged_loudly(caplog):
    user = _user_row()
    db = _FakeDb(user, failures=token_manager_module.TOKEN_COMMIT_ATTEMPTS)
    refresh = AsyncMock(return_value=_rotation())
    p1, p2, p3, p4 = _patched(user, refresh, db)
    with p1, p2, p3, p4, caplog.at_level(logging.CRITICAL), pytest.raises(OperationalError):
        await TokenManager(1).force_refresh()

    assert db.commits == token_manager_module.TOKEN_COMMIT_ATTEMPTS
    assert any(r.levelno == logging.CRITICAL and "sign in again" in r.message for r in caplog.records)
    # Spotify is asked once — retrying the refresh itself would use a dead token.
    refresh.assert_awaited_once()


# --- Podcast routes go through TokenManager ----------------------------------


@pytest.fixture(autouse=True)
def _limiter_disabled():
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    await engine.dispose()


async def _seed(maker, *extra):
    async with maker() as db:
        db.add(
            User(
                spotify_id="me",
                access_token="x",
                refresh_token="x",
                token_expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        db.add_all(extra)
        await db.commit()


def _wire_spotify(monkeypatch, handler):
    """Route the helper's SpotifyService through ``handler``; token 'old' -> 'new'."""
    token_manager = MagicMock()
    token_manager.get_token = AsyncMock(return_value="old")
    token_manager.force_refresh = AsyncMock(return_value="new")
    monkeypatch.setattr(_deps, "TokenManager", MagicMock(return_value=token_manager))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        _deps,
        "SpotifyService",
        lambda access_token: SpotifyService(access_token=access_token, client=client),
    )
    return token_manager


def _expired_old_token(ok_response):
    async def _handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") == "Bearer old":
            return httpx.Response(401, json={"error": {"status": 401}})
        return ok_response(request)

    return _handler


SESSION = SimpleNamespace(user_id=1)


@pytest.mark.asyncio
async def test_sync_recovers_from_401(maker, monkeypatch):
    await _seed(maker)
    tm = _wire_spotify(
        monkeypatch,
        _expired_old_token(
            lambda _r: httpx.Response(
                200,
                json={
                    "items": [{"show": {"id": "s1", "name": "Show", "images": [], "publisher": "p"}}],
                    "total": 1,
                },
            )
        ),
    )

    async with maker() as db:
        result = await sync_podcasts(request=MagicMock(), session=SESSION, db=db)

    assert result["new"] == 1
    tm.force_refresh.assert_awaited_once_with("old")


@pytest.mark.asyncio
async def test_sync_spotify_failure_is_502(maker, monkeypatch):
    await _seed(maker)
    _wire_spotify(monkeypatch, lambda _r: httpx.Response(503))

    async with maker() as db:
        with pytest.raises(HTTPException) as exc_info:
            await sync_podcasts(request=MagicMock(), session=SESSION, db=db)

    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_unfollow_recovers_from_401(maker, monkeypatch):
    await _seed(maker, Podcast(spotify_id="s1", name="Show"))
    tm = _wire_spotify(monkeypatch, _expired_old_token(lambda _r: httpx.Response(200)))

    async with maker() as db:
        await unfollow_podcast(podcast_id="1", session=SESSION, db=db)
        remaining = (await db.execute(select(Podcast))).scalars().all()

    assert remaining == []
    tm.force_refresh.assert_awaited_once_with("old")


@pytest.mark.asyncio
async def test_unfollow_spotify_failure_is_502_and_keeps_podcast(maker, monkeypatch):
    await _seed(maker, Podcast(spotify_id="s1", name="Show"))
    _wire_spotify(monkeypatch, lambda _r: httpx.Response(500))

    async with maker() as db:
        with pytest.raises(HTTPException) as exc_info:
            await unfollow_podcast(podcast_id="1", session=SESSION, db=db)
        await db.rollback()
        remaining = (await db.execute(select(Podcast))).scalars().all()

    assert exc_info.value.status_code == 502
    assert len(remaining) == 1


# --- Unreadable credentials sign the user out --------------------------------


@pytest.mark.asyncio
async def test_decrypt_failure_deletes_sessions_and_requires_reauth(maker, monkeypatch):
    now = datetime.now(UTC)
    await _seed(
        maker,
        Session(session_id="web", user_id=1, csrf_token="c", expires_at=now + timedelta(days=1)),
        Session(session_id="ios", user_id=1, csrf_token="c", expires_at=now + timedelta(days=1)),
    )
    token_manager = MagicMock()
    token_manager.get_token = AsyncMock(side_effect=TokenDecryptionError("bad key"))
    monkeypatch.setattr(_deps, "TokenManager", MagicMock(return_value=token_manager))

    async with maker() as db:
        with pytest.raises(ReauthRequired) as exc_info:
            await spotify_client(db, 1)

    assert exc_info.value.status_code == 401
    async with maker() as db:
        assert (await db.execute(select(Session))).scalars().all() == []


@pytest.mark.asyncio
async def test_reauth_response_clears_session_cookies():
    response = await reauth_required_handler(MagicMock(), ReauthRequired())

    assert response.status_code == 401
    cookies = response.headers.getlist("set-cookie")
    assert any(c.startswith("session_id=") and "Max-Age=0" in c for c in cookies)
    assert any(c.startswith("csrf_token=") and "Max-Age=0" in c for c in cookies)


def test_reauth_handler_is_registered():
    from app.main import app

    assert app.exception_handlers[ReauthRequired] is reauth_required_handler


# --- Token refresh job runs at startup ----------------------------------------


@pytest.mark.asyncio
async def test_token_refresh_job_first_runs_at_startup():
    fake_scheduler = MagicMock()
    fake_scheduler.running = False
    before = datetime.now(UTC)

    with (
        patch.object(scheduler, "fail_orphaned_sync_logs", AsyncMock(return_value=0)),
        patch.object(scheduler, "_load_update_times", AsyncMock(return_value=[(3, 0)])),
        patch.object(scheduler, "scheduler", fake_scheduler),
    ):
        await scheduler.init_scheduler()

    jobs = {c.kwargs["id"]: c.kwargs for c in fake_scheduler.add_job.call_args_list}
    next_run = jobs["token_refresh"]["next_run_time"]
    assert before <= next_run <= datetime.now(UTC)
