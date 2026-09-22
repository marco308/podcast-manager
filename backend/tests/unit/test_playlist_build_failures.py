"""Regression tests for issue #145 — a failed fetch must not clear a playlist.

``replace_playlist_items`` is a full replace, so writing an empty URI list
empties the playlist on Spotify. Before this fix, ``_get_unplayed_episodes``
swallowed every exception and returned ``[]``, which meant a transient Spotify
outage produced an empty build, wiped the playlist, and reported success.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from types import SimpleNamespace

from app.models.playlist import ALL_EPISODES, Arrangement, DateDirection, Playlist
from app.services.playlist_builder import (
    AssignmentEntry,
    EpisodeFetchError,
    PlaylistBuilder,
    PlaylistBuildError,
)


def _make_playlist(default_episode_limit=ALL_EPISODES):
    playlist = MagicMock(spec=Playlist)
    playlist.id = 1
    playlist.name = "Test Playlist"
    playlist.is_weekend_only = False
    playlist.is_enabled = True
    playlist.default_episode_limit = default_episode_limit
    playlist.default_pick_from = "newest"
    playlist.arrangement = Arrangement.BY_POSITION.value
    playlist.date_direction = DateDirection.OLDEST_FIRST.value
    playlist.spotify_playlist_id = "spotify123"
    playlist.last_updated_at = None
    return playlist


def _make_podcast(name, spotify_id, is_sequential=False):
    podcast = MagicMock()
    podcast.name = name
    podcast.spotify_id = spotify_id
    podcast.is_sequential = is_sequential
    return podcast


def _assignment(position):
    return SimpleNamespace(position=position, episode_limit=None, pick_from=None)


def _builder_with_podcasts(*podcasts):
    builder = PlaylistBuilder(AsyncMock(), MagicMock())
    builder._get_playlist_podcasts = AsyncMock(
        return_value=[AssignmentEntry(podcast=p, assignment=_assignment(i)) for i, p in enumerate(podcasts)]
    )
    return builder


def _episode(uri, release_date="2026-01-01", show_id="show1"):
    episode = MagicMock()
    episode.uri = uri
    episode.release_date = release_date
    episode.release_date_key = date.fromisoformat(release_date)
    episode.show_id = show_id
    return episode


class TestBuildRefusesEmptyWrite:
    """A build where every podcast failed must raise, not return []."""

    @pytest.mark.asyncio
    async def test_all_podcasts_failing_raises_rather_than_returning_empty(self):
        builder = _builder_with_podcasts(
            _make_podcast("Alpha", "show1"),
            _make_podcast("Beta", "show2"),
        )
        builder._fetch_unplayed = AsyncMock(side_effect=EpisodeFetchError("boom"))

        with pytest.raises(PlaylistBuildError):
            await builder.build_playlist(_make_playlist())

    @pytest.mark.asyncio
    async def test_update_playlist_does_not_write_when_all_fetches_fail(self):
        """The critical assertion: no Spotify write happens at all."""
        builder = _builder_with_podcasts(_make_podcast("Alpha", "show1"))
        builder._fetch_unplayed = AsyncMock(side_effect=EpisodeFetchError("boom"))

        spotify = AsyncMock()
        builder._ensure_spotify_playlist = AsyncMock(return_value="spotify123")
        builder._get_spotify_client = AsyncMock(return_value=spotify)

        result = await builder.update_playlist(_make_playlist())

        spotify.replace_playlist_items.assert_not_awaited()
        assert result.success is False
        assert result.episode_count == 0

    @pytest.mark.asyncio
    async def test_empty_playlist_with_no_podcasts_still_writes_empty(self):
        """A playlist with nothing assigned legitimately builds to []."""
        builder = _builder_with_podcasts()

        assert await builder.build_playlist(_make_playlist()) == []


class TestPartialFailures:
    """Some podcasts failing still writes, but is reported as a failure."""

    @pytest.mark.asyncio
    async def test_partial_failure_writes_surviving_episodes(self):
        builder = _builder_with_podcasts(
            _make_podcast("Alpha", "show1"),
            _make_podcast("Beta", "show2"),
        )

        async def fetch(podcast, *, need, from_oldest):
            if podcast.name == "Beta":
                raise EpisodeFetchError("boom")
            return [_episode("spotify:episode:a1")]

        builder._fetch_unplayed = AsyncMock(side_effect=fetch)

        spotify = AsyncMock()
        builder._ensure_spotify_playlist = AsyncMock(return_value="spotify123")
        builder._get_spotify_client = AsyncMock(return_value=spotify)

        result = await builder.update_playlist(_make_playlist())

        spotify.replace_playlist_items.assert_awaited_once()
        written_uris = spotify.replace_playlist_items.await_args.args[1]
        assert written_uris == ["spotify:episode:a1"]

        # Written, but not advertised as a clean rebuild.
        assert result.success is False
        assert result.error is not None
        assert "Beta" in result.error
        assert result.episode_count == 1

    @pytest.mark.asyncio
    async def test_clean_build_reports_success(self):
        builder = _builder_with_podcasts(_make_podcast("Alpha", "show1"))
        builder._fetch_unplayed = AsyncMock(return_value=[_episode("spotify:episode:a1")])

        spotify = AsyncMock()
        builder._ensure_spotify_playlist = AsyncMock(return_value="spotify123")
        builder._get_spotify_client = AsyncMock(return_value=spotify)

        result = await builder.update_playlist(_make_playlist())

        spotify.replace_playlist_items.assert_awaited_once()
        assert result.success is True
        assert result.error is None
        assert result.episode_count == 1


def _page(items, *, total, more):
    return {"items": items, "total": total, "next": "next-url" if more else None}


class TestUnplayedCountSideEffect:
    """unplayed_episodes is an exact by-product of a *complete* walk (issue #155).

    sync_podcasts used to extrapolate it from the newest 50 episodes and store
    the guess as fact. A limited rule reads a slice and must not overwrite it.
    """

    @pytest.mark.asyncio
    async def test_exact_count_is_recorded_after_a_full_walk(self):
        podcast = _make_podcast("Alpha", "show1")
        podcast.unplayed_episodes = 999
        builder = _builder_with_podcasts(podcast)

        spotify = AsyncMock()
        # 3 episodes, one already played -> 2 unplayed.
        spotify.get_show_episodes = AsyncMock(
            return_value=_page(
                [
                    {"id": "a", "uri": "spotify:episode:a", "release_date": "2026-01-01"},
                    {"id": "b", "uri": "spotify:episode:b", "release_date": "2026-01-02"},
                    {
                        "id": "c",
                        "uri": "spotify:episode:c",
                        "release_date": "2026-01-03",
                        "resume_point": {"fully_played": True},
                    },
                ],
                total=3,
                more=False,
            )
        )
        builder._get_spotify_client = AsyncMock(return_value=spotify)

        result = await builder._fetch_unplayed(podcast, need=None, from_oldest=False)

        assert len(result) == 2
        assert podcast.unplayed_episodes == 2

    @pytest.mark.asyncio
    async def test_count_is_left_alone_when_a_limited_walk_stopped_early(self):
        """A short walk can't see the whole catalogue, so don't claim a total."""
        podcast = _make_podcast("Alpha", "show1")
        podcast.unplayed_episodes = 999
        builder = _builder_with_podcasts(podcast)

        spotify = AsyncMock()
        spotify.get_show_episodes = AsyncMock(
            return_value=_page(
                [{"id": str(i), "uri": f"spotify:episode:{i}", "release_date": "2026-01-01"} for i in range(50)],
                total=200,
                more=True,
            )
        )
        builder._get_spotify_client = AsyncMock(return_value=spotify)

        await builder._fetch_unplayed(podcast, need=1, from_oldest=False)

        assert podcast.unplayed_episodes == 999, "a truncated fetch must not overwrite the count"
        spotify.get_show_episodes.assert_awaited_once()
