"""Tests for PlaylistBuilder weekend-only logic."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.playlist import Playlist, PlaylistOrderingMode
from app.services.playlist_builder import PlaylistBuilder, PlaylistUpdateResult


def _make_playlist(*, is_weekend_only=False, episode_mode="all_unplayed"):
    """Create a mock Playlist object."""
    playlist = MagicMock(spec=Playlist)
    playlist.id = 1
    playlist.name = "Test Playlist"
    playlist.is_weekend_only = is_weekend_only
    playlist.is_enabled = True
    playlist.episode_mode = episode_mode
    playlist.ordering_mode = PlaylistOrderingMode.DEFAULT
    playlist.spotify_playlist_id = "spotify123"
    playlist.last_updated_at = None
    return playlist


class TestBuildPlaylistWeekendOnly:
    """Tests that weekend-only playlists still return episodes on weekdays."""

    @pytest.mark.asyncio
    @patch("app.services.playlist_builder.is_weekend_or_holiday", return_value=False)
    async def test_build_playlist_returns_episodes_on_weekday(self, mock_weekend):
        """Weekend-only playlist should still return unplayed episodes on weekdays."""
        db = AsyncMock()
        user = MagicMock()
        builder = PlaylistBuilder(db, user)

        # Mock internal methods
        builder._get_playlist_podcasts = AsyncMock(return_value=[])
        playlist = _make_playlist(is_weekend_only=True)

        result = await builder.build_playlist(playlist)

        # Should return empty list because no podcasts assigned, NOT because of weekend check
        assert result == []
        # Crucially, _get_playlist_podcasts should have been called (no early return)
        builder._get_playlist_podcasts.assert_called_once_with(playlist.id)

    @pytest.mark.asyncio
    @patch("app.services.playlist_builder.is_weekend_or_holiday", return_value=True)
    async def test_build_playlist_returns_episodes_on_weekend(self, mock_weekend):
        """Weekend-only playlist returns episodes on weekends (baseline)."""
        db = AsyncMock()
        user = MagicMock()
        builder = PlaylistBuilder(db, user)

        builder._get_playlist_podcasts = AsyncMock(return_value=[])
        playlist = _make_playlist(is_weekend_only=True)

        result = await builder.build_playlist(playlist)

        assert result == []
        builder._get_playlist_podcasts.assert_called_once_with(playlist.id)


class TestUpdatePlaylistWeekendOnly:
    """Tests that update_playlist skips Spotify update on weekdays for weekend-only playlists."""

    @pytest.mark.asyncio
    @patch("app.services.playlist_builder.is_weekend_or_holiday", return_value=False)
    async def test_update_skipped_on_weekday_for_weekend_only(self, mock_weekend):
        """Weekend-only playlist should skip update on weekdays to preserve content."""
        db = AsyncMock()
        user = MagicMock()
        builder = PlaylistBuilder(db, user)

        builder._ensure_spotify_playlist = AsyncMock()
        builder.build_playlist = AsyncMock()

        playlist = _make_playlist(is_weekend_only=True)

        result = await builder.update_playlist(playlist)

        assert result.success is True
        assert result.episode_count == -1
        # Should NOT have called build_playlist or _ensure_spotify_playlist
        builder._ensure_spotify_playlist.assert_not_called()
        builder.build_playlist.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.playlist_builder.is_weekend_or_holiday", return_value=True)
    async def test_update_runs_on_weekend_for_weekend_only(self, mock_weekend):
        """Weekend-only playlist should update normally on weekends."""
        db = AsyncMock()
        user = MagicMock()
        builder = PlaylistBuilder(db, user)

        builder._ensure_spotify_playlist = AsyncMock(return_value="spotify123")
        builder.build_playlist = AsyncMock(return_value=["spotify:episode:1"])
        builder._get_spotify_client = AsyncMock()
        mock_spotify = AsyncMock()
        builder._get_spotify_client.return_value = mock_spotify

        playlist = _make_playlist(is_weekend_only=True)

        result = await builder.update_playlist(playlist)

        assert result.success is True
        assert result.episode_count == 1
        builder.build_playlist.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.playlist_builder.is_weekend_or_holiday", return_value=False)
    async def test_update_runs_on_weekday_for_normal_playlist(self, mock_weekend):
        """Non-weekend-only playlist should update normally on weekdays."""
        db = AsyncMock()
        user = MagicMock()
        builder = PlaylistBuilder(db, user)

        builder._ensure_spotify_playlist = AsyncMock(return_value="spotify123")
        builder.build_playlist = AsyncMock(return_value=["spotify:episode:1", "spotify:episode:2"])
        builder._get_spotify_client = AsyncMock()
        mock_spotify = AsyncMock()
        builder._get_spotify_client.return_value = mock_spotify

        playlist = _make_playlist(is_weekend_only=False)

        result = await builder.update_playlist(playlist)

        assert result.success is True
        assert result.episode_count == 2
        builder.build_playlist.assert_called_once()
