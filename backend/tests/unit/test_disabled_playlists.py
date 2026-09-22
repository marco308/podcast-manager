"""Tests for the single meaning of ``is_enabled`` (issue #239).

The flag used to mean something different in each layer: the manual-run
endpoint ignored it, the web UI offered Run regardless, iOS greyed Run out,
and the cleanup job skipped disabled playlists. The rule is now defined once,
in the backend: **a disabled playlist is never written to on Spotify** — not
by the daily rebuild, not by cleanup, and not by a manual run either. Its
Spotify playlist keeps whatever it last had until it is re-enabled.
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.routers.playlists as playlists_module
from app.database import Base
from app.jobs import locks
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


def _make_playlist(*, is_enabled=True, is_weekend_only=False):
    playlist = MagicMock(spec=Playlist)
    playlist.id = 1
    playlist.name = "Test Playlist"
    playlist.is_enabled = is_enabled
    playlist.is_weekend_only = is_weekend_only
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


class TestUpdatePlaylistDisabledGate:
    """The gate sits in ``update_playlist``, so no caller can slip past it."""

    @pytest.mark.asyncio
    async def test_disabled_playlist_is_skipped_before_any_spotify_call(self):
        builder, spotify = _builder_with_spotify()

        with patch("app.services.playlist_builder.is_weekend_or_holiday", return_value=True):
            result = await builder.update_playlist(_make_playlist(is_enabled=False))

        # The critical assertion: nothing is written, so the previous
        # contents survive untouched — and the playlist isn't even created
        # on Spotify if it doesn't exist yet.
        spotify.replace_playlist_items.assert_not_awaited()
        builder._build_playlist_content.assert_not_awaited()
        builder._ensure_spotify_playlist.assert_not_awaited()
        builder._get_spotify_client.assert_not_awaited()

        assert result.skipped is True
        assert result.skip_reason == "disabled"
        assert result.success is True, "a skip is not a failure"
        assert result.episode_count == 0

    @pytest.mark.asyncio
    async def test_disabled_wins_over_the_weekend_gate(self):
        """A disabled weekend-only playlist is skipped as *disabled*, on any day."""
        builder, spotify = _builder_with_spotify()

        with patch("app.services.playlist_builder.is_weekend_or_holiday", return_value=True):
            result = await builder.update_playlist(_make_playlist(is_enabled=False, is_weekend_only=True))

        spotify.replace_playlist_items.assert_not_awaited()
        assert result.skip_reason == "disabled"

    @pytest.mark.asyncio
    async def test_weekend_skip_keeps_its_own_reason(self):
        builder, _spotify = _builder_with_spotify()

        with patch("app.services.playlist_builder.is_weekend_or_holiday", return_value=False):
            result = await builder.update_playlist(_make_playlist(is_weekend_only=True))

        assert result.skipped is True
        assert result.skip_reason == "weekend_only"

    @pytest.mark.asyncio
    async def test_enabled_playlist_still_runs(self):
        builder, spotify = _builder_with_spotify()

        with patch("app.services.playlist_builder.is_weekend_or_holiday", return_value=False):
            result = await builder.update_playlist(_make_playlist())

        spotify.replace_playlist_items.assert_awaited_once()
        assert result.skipped is False
        assert result.skip_reason is None


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
