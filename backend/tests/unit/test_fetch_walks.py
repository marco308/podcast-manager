"""Tests for the rule-proportional episode fetch (issue #249).

Spotify pages ``/shows/{id}/episodes`` newest-first for most shows. A
``newest`` rule walks from the head and stops once it has enough unplayed
episodes; an ``oldest`` rule (a serial's "next unfinished") reads ``total``
from the first page and walks backwards from the tail, so it never has to
read a 300-episode back-catalogue to find episode 4. A show listed
oldest-first swaps the two ends.
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.playlist import PickFrom
from app.services.playlist_builder import EpisodeFetchError, PlaylistBuilder, listed_oldest_first


def _ep(i, *, played=False):
    """Episode ``e{i}``, the i-th newest: one day older for each step of ``i``."""
    release_date = (date(2030, 1, 1) - timedelta(days=i)).isoformat()
    ep = {"id": f"e{i}", "uri": f"spotify:episode:e{i}", "release_date": release_date}
    if played:
        ep["resume_point"] = {"fully_played": True}
    return ep


class FakeSpotify:
    """A catalogue of ``total`` episodes, served by offset.

    Listed newest first (``e0`` at offset 0) unless ``oldest_first``, which
    lists the same episodes the other way round, as Spotify does for some
    serials: ``e{total-1}`` at offset 0.
    """

    def __init__(self, total, played=(), oldest_first=False):
        self.total = total
        self.played = set(played)
        self.oldest_first = oldest_first
        self.calls = []

    def _at(self, offset):
        return self.total - 1 - offset if self.oldest_first else offset

    async def get_show_episodes(self, show_id, limit=50, offset=0):
        self.calls.append((limit, offset))
        indices = [self._at(j) for j in range(offset, min(offset + limit, self.total))]
        items = [_ep(i, played=i in self.played) for i in indices]
        has_more = offset + limit < self.total
        return {"items": items, "total": self.total, "next": "next-url" if has_more else None}


class OverstatedSpotify(FakeSpotify):
    """Reports ``total`` episodes but only returns the first ``returnable``.

    What Spotify does when ``total`` counts episodes that are not available in
    the user's market: offsets past the real end come back empty.
    """

    def __init__(self, total, returnable, played=()):
        super().__init__(total, played)
        self.returnable = returnable

    async def get_show_episodes(self, show_id, limit=50, offset=0):
        self.calls.append((limit, offset))
        end = min(offset + limit, self.returnable)
        items = [_ep(i, played=i in self.played) for i in range(offset, end)]
        return {"items": items, "total": self.total, "next": "next-url" if end < self.returnable else None}


def _builder(spotify):
    builder = PlaylistBuilder(AsyncMock(), MagicMock())
    builder._get_spotify_client = AsyncMock(return_value=spotify)
    return builder


def _podcast():
    podcast = MagicMock()
    podcast.spotify_id = "show"
    podcast.name = "Show"
    podcast.unplayed_episodes = 999
    podcast.unplayed_counted_at = None
    return podcast


class TestWalkFromHead:
    @pytest.mark.asyncio
    async def test_latest_one_stops_after_the_first_page(self):
        spotify = FakeSpotify(total=300)
        result = await _builder(spotify)._fetch_unplayed(_podcast(), need=1, from_oldest=False)
        assert len(result) == 50  # the caller trims; the walk only bounds the read
        assert spotify.calls == [(50, 0)]

    @pytest.mark.asyncio
    async def test_keeps_paging_until_enough_unplayed_are_seen(self):
        # Newest 60 are played; need 1 unplayed -> must reach the second page.
        spotify = FakeSpotify(total=300, played=range(60))
        result = await _builder(spotify)._fetch_unplayed(_podcast(), need=1, from_oldest=False)
        assert [e.id for e in result][:1] == ["e60"]
        assert spotify.calls == [(50, 0), (50, 50)]

    @pytest.mark.asyncio
    async def test_unlimited_reads_everything_and_records_the_count(self):
        podcast = _podcast()
        spotify = FakeSpotify(total=120, played={3, 4})
        result = await _builder(spotify)._fetch_unplayed(podcast, need=None, from_oldest=False)
        assert len(result) == 118
        assert podcast.unplayed_episodes == 118
        assert podcast.unplayed_counted_at is not None  # issue #241
        assert spotify.calls == [(50, 0), (50, 50), (50, 100)]

    @pytest.mark.asyncio
    async def test_unlimited_is_capped_and_does_not_record_a_count(self):
        podcast = _podcast()
        spotify = FakeSpotify(total=2000)
        result = await _builder(spotify)._fetch_unplayed(podcast, need=None, from_oldest=False)
        assert len(result) == 500
        assert podcast.unplayed_episodes == 999
        assert podcast.unplayed_counted_at is None


class TestWalkFromTail:
    @pytest.mark.asyncio
    async def test_next_unfinished_reads_only_the_first_and_last_pages(self):
        # 300 episodes, the oldest 3 (indices 297..299) already played.
        spotify = FakeSpotify(total=300, played={297, 298, 299})
        result = await _builder(spotify)._fetch_unplayed(_podcast(), need=1, from_oldest=True)
        ids = [e.id for e in result]
        # Newest-first order is preserved; the oldest unplayed is last.
        assert ids[-1] == "e296"
        assert "e299" not in ids
        assert spotify.calls == [(50, 0), (50, 250)]

    @pytest.mark.asyncio
    async def test_walks_further_back_when_the_tail_page_is_all_played(self):
        # Oldest 55 played -> the last page is useless, read one more.
        spotify = FakeSpotify(total=300, played=range(245, 300))
        result = await _builder(spotify)._fetch_unplayed(_podcast(), need=1, from_oldest=True)
        assert [e.id for e in result][-1] == "e244"
        assert spotify.calls == [(50, 0), (50, 250), (50, 200)]

    @pytest.mark.asyncio
    async def test_short_catalogue_is_a_single_page_and_complete(self):
        podcast = _podcast()
        spotify = FakeSpotify(total=20, played={19})
        result = await _builder(spotify)._fetch_unplayed(podcast, need=1, from_oldest=True)
        assert len(result) == 19
        assert podcast.unplayed_episodes == 19
        assert spotify.calls == [(50, 0)]

    @pytest.mark.asyncio
    async def test_head_and_tail_meeting_counts_as_complete(self):
        podcast = _podcast()
        spotify = FakeSpotify(total=80, played=range(50, 80))  # everything in the tail is played
        result = await _builder(spotify)._fetch_unplayed(podcast, need=1, from_oldest=True)
        assert len(result) == 50
        assert podcast.unplayed_episodes == 50
        assert spotify.calls == [(50, 0), (30, 50)]

    @pytest.mark.asyncio
    async def test_partial_tail_walk_does_not_record_a_count(self):
        podcast = _podcast()
        spotify = FakeSpotify(total=300)
        await _builder(spotify)._fetch_unplayed(podcast, need=1, from_oldest=True)
        assert podcast.unplayed_episodes == 999
        assert podcast.unplayed_counted_at is None

    @pytest.mark.asyncio
    async def test_cap_applies_to_the_tail_and_excludes_the_head_when_incomplete(self):
        """A max-sized oldest rule on a 600-episode show must return the 500
        oldest, not 450 oldest plus the 50 newest (the unread middle is older
        than every head episode)."""
        spotify = FakeSpotify(total=600)
        result = await _builder(spotify)._fetch_unplayed(_podcast(), need=500, from_oldest=True)
        ids = [e.id for e in result]
        assert len(ids) == 500
        assert ids[0] == "e100" and ids[-1] == "e599"
        assert not any(e.id in {f"e{i}" for i in range(50)} for e in result)

    @pytest.mark.asyncio
    async def test_incomplete_walk_with_a_played_tail_does_not_fall_back_to_the_head(self):
        """If the capped tail is all played, the honest answer is 'nothing
        within budget', not the newest episode from the head page."""
        spotify = FakeSpotify(total=600, played=range(100, 600))
        result = await _builder(spotify)._fetch_unplayed(_podcast(), need=1, from_oldest=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_episode_seen_in_both_reads_is_not_duplicated(self):
        spotify = FakeSpotify(total=60)
        # Simulate a release between the two reads: the tail page overlaps the head.
        real = spotify.get_show_episodes

        async def shifted(show_id, limit=50, offset=0):
            if offset:
                offset -= 1
            return await real(show_id, limit=limit, offset=offset)

        spotify.get_show_episodes = shifted
        result = await _builder(spotify)._fetch_unplayed(_podcast(), need=1, from_oldest=True)
        ids = [e.id for e in result]
        assert len(ids) == len(set(ids))


class TestTailWalkWithAnOverstatedTotal:
    """An empty tail page used to drop the head too, so the show silently
    contributed nothing and was not reported as a failure."""

    @pytest.mark.asyncio
    async def test_empty_tail_page_falls_back_to_reading_from_the_head(self):
        podcast = _podcast()
        spotify = OverstatedSpotify(total=300, returnable=240, played={239})
        result = await _builder(spotify)._fetch_unplayed(podcast, need=1, from_oldest=True)
        ids = [e.id for e in result]
        # The real oldest unplayed episode is found, not nothing.
        assert ids[-1] == "e238"
        assert len(ids) == 239
        # First page, the empty tail page, then a forward walk to the real end.
        assert spotify.calls[:2] == [(50, 0), (50, 250)]
        assert spotify.calls[2:] == [(50, offset) for offset in range(0, 250, 50)]
        # The forward walk saw the whole (returnable) catalogue.
        assert podcast.unplayed_episodes == 239

    @pytest.mark.asyncio
    async def test_nothing_returned_on_the_fallback_is_a_fetch_failure(self):
        spotify = OverstatedSpotify(total=300, returnable=240)
        real = spotify.get_show_episodes

        async def first_page_only(show_id, limit=50, offset=0):
            if spotify.calls:
                spotify.calls.append((limit, offset))
                return {"items": [], "total": 300, "next": None}
            return await real(show_id, limit=limit, offset=offset)

        spotify.get_show_episodes = first_page_only
        with pytest.raises(EpisodeFetchError):
            await _builder(spotify)._fetch_unplayed(_podcast(), need=1, from_oldest=True)


class TestOldestFirstListing:
    """Some shows (serials, typically) are listed oldest-first. The walk must
    read from the end that holds what the rule wants, and hand back
    newest-first like any other show."""

    @pytest.mark.asyncio
    async def test_next_unfinished_reads_only_the_first_page(self):
        spotify = FakeSpotify(total=300, played={299, 298, 297}, oldest_first=True)
        result = await _builder(spotify)._fetch_unplayed(_podcast(), need=1, from_oldest=True)
        ids = [e.id for e in result]
        assert ids[-1] == "e296"
        assert ids == sorted(ids, key=lambda i: int(i[1:]))  # newest-first
        assert spotify.calls == [(50, 0)]

    @pytest.mark.asyncio
    async def test_latest_reads_from_the_tail(self):
        spotify = FakeSpotify(total=300, played={0}, oldest_first=True)
        result = await _builder(spotify)._fetch_unplayed(_podcast(), need=1, from_oldest=False)
        assert [e.id for e in result][0] == "e1"
        assert spotify.calls == [(50, 0), (50, 250)]

    @pytest.mark.asyncio
    async def test_unlimited_returns_the_same_episodes_either_way(self):
        newest = await _builder(FakeSpotify(total=80))._fetch_unplayed(_podcast(), need=None, from_oldest=True)
        oldest = await _builder(FakeSpotify(total=80, oldest_first=True))._fetch_unplayed(
            _podcast(), need=None, from_oldest=True
        )
        assert [e.id for e in oldest] == [e.id for e in newest]


class ListingSpotify:
    """Serves a fixed listing, in the order given."""

    def __init__(self, items):
        self.items = items

    async def get_show_episodes(self, show_id, limit=50, offset=0):
        page = self.items[offset : offset + limit]
        more = offset + limit < len(self.items)
        return {"items": page, "total": len(self.items), "next": "next-url" if more else None}


class TestSameDaySerialListedOldestFirst:
    """Bear Hunt released Ep 1 and Ep 2 on one day and is listed oldest-first.
    Reading that listing as newest-first put Ep 2 ahead of Ep 1, and a limit
    of two then picked the trailer and Ep 2, skipping Ep 1."""

    LISTING = [
        {"id": "trailer", "release_date": "2026-09-02"},
        {"id": "ep1", "release_date": "2026-09-09"},
        {"id": "ep2", "release_date": "2026-09-09"},
        {"id": "ep3", "release_date": "2026-09-16"},
    ]

    @pytest.mark.parametrize("listing", [LISTING, LISTING[::-1]], ids=["oldest-first", "newest-first"])
    @pytest.mark.asyncio
    async def test_parts_play_in_order(self, listing):
        builder = _builder(ListingSpotify(listing))
        episodes = await builder._fetch_unplayed(_podcast(), need=2, from_oldest=True)
        oldest = PlaylistBuilder.sort_within_show(episodes, PickFrom.OLDEST)
        assert [e.id for e in oldest] == ["trailer", "ep1", "ep2", "ep3"]
        assert [e.id for e in PlaylistBuilder.sort_within_show(episodes, PickFrom.NEWEST)] == [
            "ep3",
            "ep2",
            "ep1",
            "trailer",
        ]


class TestListedOldestFirst:
    def test_compares_the_first_and_last_dates(self):
        assert listed_oldest_first([_ep(2), _ep(1), _ep(0)])
        assert not listed_oldest_first([_ep(0), _ep(1), _ep(2)])

    def test_no_two_distinct_dates_reads_as_newest_first(self):
        assert not listed_oldest_first([])
        assert not listed_oldest_first([_ep(0)])
        same_day = {"release_date": "2026-09-09"}
        assert not listed_oldest_first([same_day, dict(same_day)])

    def test_undated_episodes_are_skipped(self):
        undated = {"release_date": ""}
        assert not listed_oldest_first([undated, _ep(0), _ep(1)])
        assert listed_oldest_first([_ep(1), _ep(0), undated, None])
