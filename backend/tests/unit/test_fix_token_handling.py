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
  is now deleted and the cookies cleared — also when only the refresh token
  is unreadable and the failure surfaces inside a 401 retry (issue #308).
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
from app.jobs import locks, playlist_update, scheduler, sync_log
from app.models import Podcast, User
from app.models.session import Session
from app.rate_limit import limiter
from app.routers import _deps
from app.routers._deps import ReauthRequired, reauth_required_handler, spotify_client
from app.routers.podcasts import sync_podcasts, unfollow_podcast
from app.services import token_manager as token_manager_module
from app.services.encryption import TokenDecryptionError
from app.services.session import hash_session_id
from app.services.spotify import SpotifyService
from app.services.token_manager import TokenManager
from tests.job_patches import JOB_MODULES_WITH_SESSIONS

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
        lambda access_token, **kwargs: SpotifyService(access_token=access_token, client=client, **kwargs),
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


@pytest.mark.asyncio
async def test_daily_library_sync_recovers_from_401(maker, monkeypatch):
    """The daily job's sync gets the same 401 recovery as the manual one."""
    await _seed(maker)
    token_manager = MagicMock()
    token_manager.get_token = AsyncMock(return_value="old")
    token_manager.force_refresh = AsyncMock(return_value="new")
    handler = _expired_old_token(
        lambda _r: httpx.Response(
            200,
            json={"items": [{"show": {"id": "s1", "name": "Show", "images": [], "publisher": "p"}}], "total": 1},
        )
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    for module in JOB_MODULES_WITH_SESSIONS:
        monkeypatch.setattr(f"{module}.async_session_maker", maker)
    monkeypatch.setattr(playlist_update, "TokenManager", MagicMock(return_value=token_manager))
    monkeypatch.setattr(
        playlist_update,
        "SpotifyService",
        lambda access_token, **kwargs: SpotifyService(access_token=access_token, client=client, **kwargs),
    )

    await scheduler.sync_all_libraries()

    token_manager.force_refresh.assert_awaited_once_with("old")
    async with maker() as db:
        assert [p.spotify_id for p in (await db.execute(select(Podcast))).scalars()] == ["s1"]


# --- Unreadable credentials sign the user out --------------------------------


@pytest.mark.asyncio
async def test_decrypt_failure_deletes_sessions_and_requires_reauth(maker, monkeypatch):
    now = datetime.now(UTC)
    await _seed(
        maker,
        Session(session_id_hash=hash_session_id("web"), user_id=1, csrf_token="c", expires_at=now + timedelta(days=1)),
        Session(session_id_hash=hash_session_id("ios"), user_id=1, csrf_token="c", expires_at=now + timedelta(days=1)),
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


def _two_sessions():
    now = datetime.now(UTC)
    return (
        Session(session_id_hash=hash_session_id("web"), user_id=1, csrf_token="c", expires_at=now + timedelta(days=1)),
        Session(session_id_hash=hash_session_id("ios"), user_id=1, csrf_token="c", expires_at=now + timedelta(days=1)),
    )


async def _sessions_left(maker):
    async with maker() as db:
        return (await db.execute(select(Session))).scalars().all()


@pytest.mark.asyncio
async def test_unreadable_refresh_token_is_not_sent_to_spotify(caplog):
    """Issue #308: the refresh token fails to decrypt inside force_refresh."""
    user = _user_row()
    refresh = AsyncMock(return_value=_rotation())
    p1, p2, p3, p4 = _patched(user, refresh)
    encryption = _encryption()

    def _decrypt(ciphertext):
        if ciphertext == user.refresh_token:
            raise TokenDecryptionError("bad refresh token")
        return ciphertext.removeprefix("enc:")

    encryption.decrypt.side_effect = _decrypt
    with (
        p1,
        patch.object(token_manager_module, "get_encryption_service", return_value=encryption),
        p3,
        p4,
        caplog.at_level(logging.ERROR),
        pytest.raises(TokenDecryptionError),
    ):
        await TokenManager(1).force_refresh("cached-access")

    refresh.assert_not_awaited()
    assert any("refresh token" in r.message and "sign in again" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_unreadable_refresh_token_during_401_retry_signs_out(maker, monkeypatch):
    """The access token decrypts, Spotify 401s it, and the refresh token doesn't (#308)."""
    await _seed(maker, *_two_sessions())
    tm = _wire_spotify(monkeypatch, _expired_old_token(lambda _r: httpx.Response(200, json={"items": [], "total": 0})))
    tm.force_refresh.side_effect = TokenDecryptionError("bad refresh token")

    async with maker() as db:
        with pytest.raises(ReauthRequired) as exc_info:
            await sync_podcasts(request=MagicMock(), session=SESSION, db=db)

    assert exc_info.value.status_code == 401
    assert await _sessions_left(maker) == []
    # The sync lock was released on the way out.
    assert not locks.library_sync_lock.locked()


@pytest.mark.asyncio
async def test_rename_with_unreadable_refresh_token_signs_out_rather_than_502(maker, monkeypatch):
    """The rename's broad ``except`` must not turn the sign-out into a 502."""
    from app.models import Playlist
    from app.routers.playlists import update_playlist
    from app.schemas.playlist import PlaylistUpdate

    await _seed(maker, *_two_sessions(), Playlist(user_id=1, name="Old", spotify_playlist_id="sp1"))
    tm = _wire_spotify(monkeypatch, _expired_old_token(lambda _r: httpx.Response(200)))
    tm.force_refresh.side_effect = TokenDecryptionError("bad refresh token")

    async with maker() as db:
        with pytest.raises(ReauthRequired):
            await update_playlist(1, PlaylistUpdate(name="New"), session=SESSION, db=db)

    assert await _sessions_left(maker) == []
    async with maker() as db:
        assert (await db.execute(select(Playlist.name))).scalar_one() == "Old"


@pytest.mark.asyncio
async def test_manual_run_with_unreadable_credentials_signs_out(maker, monkeypatch):
    """A run's builder reports the failure as a result; the route signs out."""
    from app.models import Playlist
    from app.routers import playlists as playlists_module
    from app.services.playlist_builder import EpisodeFetchError, PlaylistUpdateResult

    await _seed(maker, *_two_sessions(), Playlist(user_id=1, name="P", spotify_playlist_id="sp1"))
    monkeypatch.setattr(locks, "playlist_write_lock", asyncio.Lock())
    try:
        raise EpisodeFetchError("Show: wrapped") from TokenDecryptionError("bad refresh token")
    except EpisodeFetchError as e:
        failure = e
    builder = MagicMock()
    builder.update_playlist = AsyncMock(
        return_value=PlaylistUpdateResult(
            playlist_id=1, playlist_name="P", success=False, episode_count=0, error=str(failure), exception=failure
        )
    )
    monkeypatch.setattr(playlists_module, "PlaylistBuilder", MagicMock(return_value=builder))

    async with maker() as db:
        with pytest.raises(ReauthRequired):
            await playlists_module.run_playlist_update(request=MagicMock(), playlist_id=1, session=SESSION, db=db)

    assert await _sessions_left(maker) == []


def test_jobs_classify_unreadable_credentials_apart_from_spotify_errors():
    """A credentials failure outranks the Spotify errors around it (#308)."""
    request = httpx.Request("GET", "https://api.spotify.com/v1/x")
    rate_limited = httpx.HTTPStatusError("429", request=request, response=httpx.Response(429, request=request))
    try:
        raise RuntimeError("wrapped") from TokenDecryptionError("bad refresh token")
    except RuntimeError as e:
        wrapped = e

    assert (
        sync_log.classify_failure(
            playlists_attempted=2,
            playlists_failed=2,
            error_messages=["a", "b"],
            exceptions=[rate_limited, wrapped],
        )
        == sync_log.CREDENTIALS_UNREADABLE_FAILURE_CODE
    )
    assert (
        sync_log.classify_failure(
            playlists_attempted=1, playlists_failed=1, error_messages=["a"], exceptions=[rate_limited]
        )
        == "rate_limit"
    )


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
        patch.object(scheduler, "load_update_times", AsyncMock(return_value=[(3, 0)])),
        patch("app.jobs.schedule.scheduler", fake_scheduler),
    ):
        await scheduler.init_scheduler()

    jobs = {c.kwargs["id"]: c.kwargs for c in fake_scheduler.add_job.call_args_list}
    next_run = jobs["token_refresh"]["next_run_time"]
    assert before <= next_run <= datetime.now(UTC)
