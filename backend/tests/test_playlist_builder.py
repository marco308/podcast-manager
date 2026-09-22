"""Tests for PlaylistBuilder weekend-only logic (issue #150).

History matters here. The original implementation gated ``build_playlist``,
so on a weekday a weekend-only playlist built an *empty* list — and since
``replace_playlist_items`` is a full replace, that **blanked** the playlist on
Spotify. Commit 525f76b fixed the symptom by removing the gate entirely,
which left the setting doing nothing at all while the UI still advertised it.

The gate now lives in ``update_playlist`` and skips the whole update, so the
playlist is left exactly as it was. These tests pin both halves: building is
day-agnostic, and updating is the thing that's gated.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.playlist import ALL_EPISODES, Arrangement, DateDirection, Playlist
from app.services.playlist_builder import PlaylistBuilder


def _make_playlist(*, is_weekend_only=False):
    """Create a mock Playlist object."""
    playlist = MagicMock(spec=Playlist)
    playlist.id = 1
    playlist.name = "Test Playlist"
    playlist.is_weekend_only = is_weekend_only
    playlist.is_enabled = True
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


class TestBuildPlaylistIsDayAgnostic:
    """build_playlist never applies the weekend gate — update_playlist does."""

    @pytest.mark.asyncio
    async def test_build_playlist_does_not_short_circuit_on_a_weekday(self):
        builder = PlaylistBuilder(AsyncMock(), MagicMock())
        builder._get_playlist_podcasts = AsyncMock(return_value=[])
        playlist = _make_playlist(is_weekend_only=True)

        with patch("app.services.playlist_builder.is_weekend_or_holiday", return_value=False):
            result = await builder.build_playlist(playlist)

        # Empty because no podcasts are assigned, NOT because of the day.
        assert result == []
        builder._get_playlist_podcasts.assert_called_once_with(playlist.id)


class TestUpdatePlaylistWeekendGate:
    """The gate skips the update outright rather than writing an empty list."""

    @pytest.mark.asyncio
    async def test_weekend_only_playlist_is_skipped_on_a_weekday(self):
        builder, spotify = _builder_with_spotify()

        with patch("app.services.playlist_builder.is_weekend_or_holiday", return_value=False):
            result = await builder.update_playlist(_make_playlist(is_weekend_only=True))

        # The critical assertion: nothing is written, so the previous
        # contents survive untouched.
        spotify.replace_playlist_items.assert_not_awaited()
        builder._build_playlist_content.assert_not_awaited()
        assert result.skipped is True
        assert result.success is True, "a skip is not a failure"
        assert result.episode_count == 0

    @pytest.mark.asyncio
    async def test_weekend_only_playlist_updates_on_a_weekend(self):
        builder, spotify = _builder_with_spotify()

        with patch("app.services.playlist_builder.is_weekend_or_holiday", return_value=True):
            result = await builder.update_playlist(_make_playlist(is_weekend_only=True))

        spotify.replace_playlist_items.assert_awaited_once()
        assert result.skipped is False
        assert result.success is True
        assert result.episode_count == 1

    @pytest.mark.asyncio
    async def test_normal_playlist_updates_on_a_weekday(self):
        builder, spotify = _builder_with_spotify()

        with patch("app.services.playlist_builder.is_weekend_or_holiday", return_value=False):
            result = await builder.update_playlist(_make_playlist(is_weekend_only=False))

        spotify.replace_playlist_items.assert_awaited_once()
        assert result.skipped is False
        assert result.success is True

    @pytest.mark.asyncio
    async def test_skip_happens_before_any_spotify_call(self):
        """Not even playlist creation should fire on a skipped day."""
        builder, _spotify = _builder_with_spotify()

        with patch("app.services.playlist_builder.is_weekend_or_holiday", return_value=False):
            await builder.update_playlist(_make_playlist(is_weekend_only=True))

        builder._ensure_spotify_playlist.assert_not_awaited()
        builder._get_spotify_client.assert_not_awaited()
