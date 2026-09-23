"""Tests for the single meaning of ``is_enabled`` (issue #239).

The flag used to mean something different in each layer: the manual-run
endpoint ignored it, the web UI offered Run regardless, iOS greyed Run out,
and the cleanup job skipped disabled playlists. The rule is now defined once,
in the backend: **a disabled playlist is never written to on Spotify** — not
by the daily rebuild, not by cleanup, and not by a manual run either. Its
Spotify playlist keeps whatever it last had until it is re-enabled.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.routers import playlists as playlists_module
from app.database import Base
from app.jobs import locks, scheduler
from app.models import Playlist, User
from app.models.playlist import ALL_EPISODES, Arrangement, DateDirection
from app.rate_limit import limiter
from app.routers.playlists import run_playlist_update
from app.services.playlist_builder import PlaylistBuilder, PlaylistUpdateResult

SESSION = SimpleNamespace(user_id=1)


@pytest.fixture(autouse=True)
def _fresh_lock():
    """Fresh write lock per test — asyncio primitives bind to the running loop."""
    original = locks.playlist_write_lock
    locks.playlist_write_lock = asyncio.Lock()
    try:
        yield
    finally:
        locks.playlist_write_lock = original


@pytest.fixture(autouse=True)
def _limiter_disabled():
    """Direct route calls still pass through the slowapi wrapper; disable it
    so a MagicMock request doesn't have to satisfy the limiter."""
    limiter.enabled = False
    yield
    limiter.enabled = True


async def _make_db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    return engine, maker


def _user():
    return User(
        spotify_id="spotify-user",
        access_token="encrypted",
        refresh_token="encrypted",
        token_expires_at=datetime.now(UTC),
    )


def _make_playlist(*, is_enabled=True):
    playlist = MagicMock(spec=Playlist)
    playlist.id = 1
    playlist.name = "Test Playlist"
    playlist.is_enabled = is_enabled
    playlist.default_episode_limit = ALL_EPISODES
    playlist.default_pick_from = "newest"
    playlist.arrangement = Arrangement.BY_POSITION.value
    playlist.date_direction = DateDirection.OLDEST_FIRST.value
    playlist.spotify_playlist_id = "spotify123"
    playlist.last_updated_at = None
    return playlist


def _builder_with_spotify():
    """Builder with the Spotify write path mocked out."""
    builder = PlaylistBuilder(AsyncMock(), MagicMock())
    spotify = AsyncMock()
    builder._ensure_spotify_playlist = AsyncMock(return_value="spotify123")
    builder._get_spotify_client = AsyncMock(return_value=spotify)
    builder._build_playlist_content = AsyncMock(return_value=(["spotify:episode:1"], []))
    return builder, spotify


def _patch_cleanup_boundaries(monkeypatch, *, still_enabled: set[int]):
    """Wire the cleanup job's boundaries to fakes, as tests/integration does.

    The job is given one user with one enabled playlist by its phase-1 read;
    ``still_enabled`` is what the re-read under the write lock finds. Returns
    a callable for the number of Spotify clients constructed, and the client
    itself.
    """
    playlist = SimpleNamespace(id=1, name="Playlist", spotify_playlist_id="sp1", user_id=1)

    class _FakeResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

        def scalars(self):
            rows = MagicMock()
            rows.all.return_value = self._value if isinstance(self._value, list) else []
            return rows

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def execute(self, stmt):
            # Collapse whitespace first: SQLAlchemy renders "...\nFROM users",
            # so matching on " from <table>" needs the newline normalised.
            sql = " ".join(str(stmt).lower().split())
            if " from playlists" in sql:
                return _FakeResult([playlist])
            if " from users" in sql:
                return _FakeResult([SimpleNamespace(id=1)])
            # sync_logs recency gate and the app_settings cursor: nothing stored.
            return _FakeResult(None)

        async def commit(self):
            return None

        async def rollback(self):
            return None

        def add(self, _obj):
            return None

    monkeypatch.setattr(scheduler, "async_session_maker", lambda: _FakeSession())
    monkeypatch.setattr(scheduler, "_still_enabled_playlist_ids", AsyncMock(return_value=still_enabled))

    token_manager = MagicMock()
    token_manager.get_token = AsyncMock(return_value="token")
    token_manager.force_refresh = AsyncMock(return_value="token")
    monkeypatch.setattr(scheduler, "TokenManager", MagicMock(return_value=token_manager))

    client = MagicMock()
    client.api_calls_used = 0
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get_playlist_tracks = AsyncMock(return_value={"items": []})
    client.remove_tracks_from_playlist = AsyncMock()

    instances = 0

    def _ctor(*_args, **_kwargs):
        nonlocal instances
        instances += 1
        return client

    monkeypatch.setattr(scheduler, "SpotifyService", MagicMock(side_effect=_ctor))

    return (lambda: instances), client


class TestUpdatePlaylistDisabledGate:
    """The gate sits in ``update_playlist``, so no caller can slip past it."""

    @pytest.mark.asyncio
    async def test_disabled_playlist_is_skipped_before_any_spotify_call(self):
        builder, spotify = _builder_with_spotify()

        result = await builder.update_playlist(_make_playlist(is_enabled=False))

        # The critical assertion: nothing is written, so the previous
        # contents survive untouched — and the playlist isn't even created
        # on Spotify if it doesn't exist yet.
        spotify.replace_playlist_items.assert_not_awaited()
        builder._build_playlist_content.assert_not_awaited()
        builder._ensure_spotify_playlist.assert_not_awaited()
        builder._get_spotify_client.assert_not_awaited()

        assert result.skipped is True
        assert result.success is True, "a skip is not a failure"
        assert result.episode_count == 0

    @pytest.mark.asyncio
    async def test_enabled_playlist_still_runs(self):
        builder, spotify = _builder_with_spotify()

        result = await builder.update_playlist(_make_playlist())

        spotify.replace_playlist_items.assert_awaited_once()
        assert result.skipped is False


class TestUpdateAllPlaylists:
    @pytest.mark.asyncio
    async def test_disabled_playlists_are_not_even_selected(self):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                user = _user()
                db.add(user)
                db.add(Playlist(user_id=1, name="On", is_enabled=True))
                db.add(Playlist(user_id=1, name="Off", is_enabled=False))
                await db.commit()

                builder = PlaylistBuilder(db, user, token_manager=MagicMock())
                builder.update_playlist = AsyncMock(
                    side_effect=lambda p: PlaylistUpdateResult(
                        playlist_id=p.id, playlist_name=p.name, success=True, episode_count=0
                    )
                )

                results = await builder.update_all_playlists()

                assert [r.playlist_name for r in results] == ["On"]
        finally:
            await engine.dispose()


class TestManualRunRefusesDisabled:
    @pytest.mark.asyncio
    async def test_disabled_playlist_run_is_refused_with_409(self, monkeypatch):
        engine, maker = await _make_db()
        builder_factory = MagicMock()
        monkeypatch.setattr(playlists_module, "PlaylistBuilder", builder_factory)
        monkeypatch.setattr(playlists_module, "TokenManager", MagicMock())
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="Off", is_enabled=False, spotify_playlist_id="sp1"))
                await db.commit()

                with pytest.raises(HTTPException) as exc_info:
                    await run_playlist_update(request=MagicMock(), playlist_id=1, session=SESSION, db=db)

                assert exc_info.value.status_code == 409
                assert "disabled" in exc_info.value.detail.lower()
                # Refused before any work: no builder, so no Spotify write and
                # no contention on the shared write lock.
                builder_factory.assert_not_called()
                assert not locks.playlist_write_lock.locked()
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_enabled_playlist_still_runs(self, monkeypatch):
        engine, maker = await _make_db()
        builder = MagicMock()
        builder.update_playlist = AsyncMock(
            return_value=PlaylistUpdateResult(playlist_id=1, playlist_name="On", success=True, episode_count=3)
        )
        monkeypatch.setattr(playlists_module, "PlaylistBuilder", MagicMock(return_value=builder))
        monkeypatch.setattr(playlists_module, "TokenManager", MagicMock())
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="On", is_enabled=True, spotify_playlist_id="sp1"))
                await db.commit()

                response = await run_playlist_update(request=MagicMock(), playlist_id=1, session=SESSION, db=db)

                assert response["episode_count"] == 3
                builder.update_playlist.assert_awaited_once()
        finally:
            await engine.dispose()


class TestManualRunRechecksUnderTheLock:
    """The first check runs before the wait for ``playlist_write_lock``.

    ``PATCH /playlists/{id}`` doesn't take that lock, so a playlist disabled
    while a manual run queued behind the daily rebuild would otherwise be
    written anyway.
    """

    @pytest.mark.asyncio
    async def test_disabled_while_waiting_for_the_lock_is_refused(self, monkeypatch):
        engine, maker = await _make_db()
        builder_factory = MagicMock()
        monkeypatch.setattr(playlists_module, "PlaylistBuilder", builder_factory)
        monkeypatch.setattr(playlists_module, "TokenManager", MagicMock())

        @asynccontextmanager
        async def _lock_that_disables_the_playlist():
            # Stand in for the wait: someone flips the flag, in their own
            # session, while this request is queued.
            async with maker() as other:
                playlist = (await other.execute(select(Playlist))).scalar_one()
                playlist.is_enabled = False
                await other.commit()
            yield

        monkeypatch.setattr(playlists_module, "_playlist_write_lock", _lock_that_disables_the_playlist)

        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="On", is_enabled=True, spotify_playlist_id="sp1"))
                await db.commit()

                with pytest.raises(HTTPException) as exc_info:
                    await run_playlist_update(request=MagicMock(), playlist_id=1, session=SESSION, db=db)

                assert exc_info.value.status_code == 409
                assert "disabled" in exc_info.value.detail.lower()
                builder_factory.assert_not_called()
        finally:
            await engine.dispose()


class TestCleanupRechecksUnderTheLock:
    """Cleanup reads its playlists before it takes the lock, so it re-reads."""

    @pytest.mark.asyncio
    async def test_helper_returns_only_enabled_ids(self, monkeypatch):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="On", is_enabled=True))
                db.add(Playlist(user_id=1, name="Off", is_enabled=False))
                await db.commit()

            monkeypatch.setattr(scheduler, "async_session_maker", maker)
            assert await scheduler._still_enabled_playlist_ids() == {1}
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_failed_reread_falls_back_to_the_earlier_read(self, monkeypatch):
        """A DB hiccup must not silently skip every playlist."""

        def _boom():
            raise RuntimeError("db gone")

        monkeypatch.setattr(scheduler, "async_session_maker", _boom)
        assert await scheduler._still_enabled_playlist_ids() is None

    @pytest.mark.asyncio
    async def test_playlist_disabled_before_the_lock_is_not_cleaned(self, monkeypatch):
        spotify_instances, client = _patch_cleanup_boundaries(monkeypatch, still_enabled=set())

        await scheduler.remove_played_episodes_from_playlists()

        assert spotify_instances() == 0, "a disabled playlist must not even open a Spotify client"
        client.get_playlist_tracks.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_still_enabled_playlist_is_cleaned(self, monkeypatch):
        """Control: the same wiring cleans a playlist that is still enabled."""
        spotify_instances, client = _patch_cleanup_boundaries(monkeypatch, still_enabled={1})

        await scheduler.remove_played_episodes_from_playlists()

        assert spotify_instances() == 1
        client.get_playlist_tracks.assert_awaited()
