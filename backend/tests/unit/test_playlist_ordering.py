"""Tests for playlist ordering, especially the is_sequential contract (issue #146).

The chronological modes previously grouped with ``itertools.groupby`` over a
globally date-sorted list. ``groupby`` only groups *consecutive* runs, so a
show's episodes were almost never grouped together and ``is_sequential`` was
silently ignored. These tests pin the intended behaviour: a sequential show
keeps its slots in the global ordering but fills them oldest-first.
"""

from unittest.mock import MagicMock

from app.models.playlist import PlaylistOrderingMode
from app.services.playlist_builder import Episode, PlaylistBuilder, PodcastWithPosition

ASC = PlaylistOrderingMode.CHRONOLOGICAL_ASC.value
DESC = PlaylistOrderingMode.CHRONOLOGICAL_DESC.value
BY_PODCAST = PlaylistOrderingMode.PODCAST_ORDER.value


def _episode(name, show_id, release_date):
    return Episode(
        id=name,
        uri=f"spotify:episode:{name}",
        name=name,
        release_date=release_date,
        duration_ms=0,
        fully_played=False,
        show_id=show_id,
        show_name=show_id,
    )


def _entry(spotify_id, *, is_sequential=False, position=None):
    podcast = MagicMock()
    podcast.spotify_id = spotify_id
    podcast.is_sequential = is_sequential
    podcast.name = spotify_id
    return PodcastWithPosition(podcast=podcast, position=position)


def _names(episodes):
    return [e.name for e in episodes]


def _builder():
    return PlaylistBuilder(MagicMock(), MagicMock())


# A deliberately interleaved fixture: the two shows alternate by release date,
# so groupby-based grouping collapses to size-1 groups.
INTERLEAVED = [
    _episode("story1", "seq", "2026-01-01"),
    _episode("chat1", "news", "2026-01-02"),
    _episode("story2", "seq", "2026-01-03"),
    _episode("chat2", "news", "2026-01-04"),
    _episode("story3", "seq", "2026-01-05"),
]


class TestChronologicalDescending:
    """Newest-first globally, but a sequential show plays oldest-first."""

    def test_sequential_show_plays_oldest_first_within_its_slots(self):
        result = _builder()._apply_ordering(
            list(INTERLEAVED),
            DESC,
            [_entry("seq", is_sequential=True), _entry("news")],
        )

        # Global order is newest-first: story3, chat2, story2, chat1, story1.
        # The sequential show holds slots 0, 2, 4 — filled oldest-first.
        assert _names(result) == ["story1", "chat2", "story2", "chat1", "story3"]

    def test_non_sequential_shows_are_untouched(self):
        result = _builder()._apply_ordering(
            list(INTERLEAVED),
            DESC,
            [_entry("seq"), _entry("news")],
        )

        assert _names(result) == ["story3", "chat2", "story2", "chat1", "story1"]

    def test_interleaving_is_preserved(self):
        """A sequential show must not be collapsed into a contiguous block."""
        result = _builder()._apply_ordering(
            list(INTERLEAVED),
            DESC,
            [_entry("seq", is_sequential=True), _entry("news")],
        )

        assert [e.show_id for e in result] == ["seq", "news", "seq", "news", "seq"]


class TestChronologicalAscending:
    """Ascending order already satisfies the sequential contract."""

    def test_sequential_show_is_oldest_first(self):
        result = _builder()._apply_ordering(
            list(INTERLEAVED),
            ASC,
            [_entry("seq", is_sequential=True), _entry("news")],
        )

        assert _names(result) == ["story1", "chat1", "story2", "chat2", "story3"]

    def test_matches_plain_sort_when_nothing_is_sequential(self):
        result = _builder()._apply_ordering(list(INTERLEAVED), ASC, [_entry("seq"), _entry("news")])

        assert _names(result) == ["story1", "chat1", "story2", "chat2", "story3"]


class TestPodcastOrder:
    """Position drives show order; is_sequential drives order within a show."""

    def test_shows_follow_position_and_sequential_shows_are_oldest_first(self):
        result = _builder()._apply_ordering(
            list(INTERLEAVED),
            BY_PODCAST,
            [
                _entry("news", position=1),
                _entry("seq", is_sequential=True, position=2),
            ],
        )

        # news first (position 1), newest-first within it; then seq, oldest-first.
        assert _names(result) == ["chat2", "chat1", "story1", "story2", "story3"]

    def test_unpositioned_shows_sort_last(self):
        result = _builder()._apply_ordering(
            list(INTERLEAVED),
            BY_PODCAST,
            [_entry("news"), _entry("seq", position=1)],
        )

        assert [e.show_id for e in result] == ["seq", "seq", "seq", "news", "news"]


class TestDefaultMode:
    def test_default_returns_input_untouched(self):
        result = _builder()._apply_ordering(list(INTERLEAVED), "default", [_entry("seq", is_sequential=True)])

        assert _names(result) == _names(INTERLEAVED)


class TestNoEpisodes:
    def test_empty_input_is_safe_in_every_mode(self):
        builder = _builder()
        entries = [_entry("seq", is_sequential=True, position=1)]

        for mode in (ASC, DESC, BY_PODCAST, "default"):
            assert builder._apply_ordering([], mode, entries) == []
