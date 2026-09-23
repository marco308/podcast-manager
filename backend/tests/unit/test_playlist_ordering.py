"""Tests for playlist assembly (issue #249; the sequential contract from #146).

``assemble`` takes per-show contributions, each with its resolved rule.
``by_position`` keeps assignment order; ``by_date`` merges by release date
and then refills the slots of any ``oldest`` show oldest-first, so a serial is
never played out of order. That refill is done by explicit slot lookup: after
a date merge a show's episodes are rarely adjacent, which is what silently
broke ``itertools.groupby`` before. ``shuffle`` interleaves shows at random
but never reorders episodes within a show.
"""

import random

from app.models.playlist import Arrangement, DateDirection, PickFrom
from app.services.assignment_rules import ResolvedRule
from app.services.playlist_builder import Episode, PlaylistBuilder, ShowContribution

BY_POSITION = Arrangement.BY_POSITION.value
BY_DATE = Arrangement.BY_DATE.value
SHUFFLE = Arrangement.SHUFFLE.value
NEWEST_FIRST = DateDirection.NEWEST_FIRST.value
OLDEST_FIRST = DateDirection.OLDEST_FIRST.value


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


def _rule(pick):
    return ResolvedRule(episode_limit=0, pick_from=pick, episode_limit_source="playlist", pick_from_source="playlist")


def _contribution(show_id, episodes, pick=PickFrom.NEWEST):
    return ShowContribution(show_id=show_id, rule=_rule(pick), episodes=list(episodes))


def _names(episodes):
    return [e.name for e in episodes]


STORY = [
    _episode("story1", "seq", "2026-01-01"),
    _episode("story2", "seq", "2026-01-03"),
    _episode("story3", "seq", "2026-01-05"),
]
NEWS = [
    _episode("chat1", "news", "2026-01-02"),
    _episode("chat2", "news", "2026-01-04"),
]


class TestByPosition:
    def test_groups_are_concatenated_in_the_order_given(self):
        result = PlaylistBuilder.assemble(
            [_contribution("news", reversed(NEWS)), _contribution("seq", STORY, PickFrom.OLDEST)],
            BY_POSITION,
            OLDEST_FIRST,
        )
        assert _names(result) == ["chat2", "chat1", "story1", "story2", "story3"]

    def test_date_direction_is_ignored(self):
        groups = [_contribution("news", NEWS), _contribution("seq", STORY)]
        assert PlaylistBuilder.assemble(groups, BY_POSITION, NEWEST_FIRST) == PlaylistBuilder.assemble(
            groups, BY_POSITION, OLDEST_FIRST
        )


class TestByDateNewestFirst:
    def test_oldest_show_keeps_its_slots_but_plays_oldest_first(self):
        result = PlaylistBuilder.assemble(
            [_contribution("seq", STORY, PickFrom.OLDEST), _contribution("news", NEWS)],
            BY_DATE,
            NEWEST_FIRST,
        )
        # Merge is newest-first: story3, chat2, story2, chat1, story1.
        # The serial holds slots 0, 2, 4 and fills them oldest-first.
        assert _names(result) == ["story1", "chat2", "story2", "chat1", "story3"]

    def test_interleaving_is_preserved(self):
        result = PlaylistBuilder.assemble(
            [_contribution("seq", STORY, PickFrom.OLDEST), _contribution("news", NEWS)],
            BY_DATE,
            NEWEST_FIRST,
        )
        assert [e.show_id for e in result] == ["seq", "news", "seq", "news", "seq"]

    def test_newest_shows_follow_the_playlist_direction(self):
        result = PlaylistBuilder.assemble(
            [_contribution("seq", STORY), _contribution("news", NEWS)],
            BY_DATE,
            NEWEST_FIRST,
        )
        assert _names(result) == ["story3", "chat2", "story2", "chat1", "story1"]

    def test_single_episode_oldest_show_needs_no_refill(self):
        result = PlaylistBuilder.assemble(
            [_contribution("seq", STORY[:1], PickFrom.OLDEST), _contribution("news", NEWS)],
            BY_DATE,
            NEWEST_FIRST,
        )
        assert _names(result) == ["chat2", "chat1", "story1"]


class TestByDateOldestFirst:
    def test_plain_ascending_merge(self):
        result = PlaylistBuilder.assemble(
            [_contribution("seq", STORY, PickFrom.OLDEST), _contribution("news", NEWS)],
            BY_DATE,
            OLDEST_FIRST,
        )
        assert _names(result) == ["story1", "chat1", "story2", "chat2", "story3"]

    def test_newest_preference_does_not_reverse_a_show(self):
        """``newest`` is a preference the playlist direction may override."""
        result = PlaylistBuilder.assemble(
            [_contribution("seq", STORY), _contribution("news", NEWS)],
            BY_DATE,
            OLDEST_FIRST,
        )
        assert _names(result) == ["story1", "chat1", "story2", "chat2", "story3"]


class TestShuffle:
    GROUPS = [
        _contribution("seq", STORY, PickFrom.OLDEST),
        _contribution("news", list(reversed(NEWS))),
        _contribution("solo", [_episode("solo1", "solo", "2026-01-06")]),
    ]

    def _shuffled(self, seed):
        return PlaylistBuilder.assemble(self.GROUPS, SHUFFLE, NEWEST_FIRST, rng=random.Random(seed))

    def test_every_show_keeps_its_own_order(self):
        for seed in range(200):
            result = self._shuffled(seed)
            assert sorted(_names(result)) == sorted(_names(e for g in self.GROUPS for e in g.episodes))
            for group in self.GROUPS:
                assert [e for e in result if e.show_id == group.show_id] == group.episodes

    def test_shows_are_interleaved_not_just_reordered_as_blocks(self):
        # Across many draws, some result must split a show's episodes apart
        # with another show's episode in between.
        def interleaved(result):
            shows = [e.show_id for e in result]
            runs = [s for i, s in enumerate(shows) if i == 0 or shows[i - 1] != s]
            return len(runs) > len(set(shows))

        assert any(interleaved(self._shuffled(seed)) for seed in range(50))

    def test_order_varies_between_draws(self):
        assert len({tuple(_names(self._shuffled(seed))) for seed in range(50)}) > 1

    def test_date_direction_is_ignored(self):
        a = PlaylistBuilder.assemble(self.GROUPS, SHUFFLE, NEWEST_FIRST, rng=random.Random(7))
        b = PlaylistBuilder.assemble(self.GROUPS, SHUFFLE, OLDEST_FIRST, rng=random.Random(7))
        assert a == b


class TestSortWithinShow:
    def test_newest_and_oldest(self):
        assert _names(PlaylistBuilder.sort_within_show(STORY, PickFrom.NEWEST)) == ["story3", "story2", "story1"]
        assert _names(PlaylistBuilder.sort_within_show(list(reversed(STORY)), PickFrom.OLDEST)) == [
            "story1",
            "story2",
            "story3",
        ]


class TestNoEpisodes:
    def test_empty_input_is_safe_in_every_mode(self):
        for arrangement in (BY_POSITION, BY_DATE, SHUFFLE):
            for direction in (NEWEST_FIRST, OLDEST_FIRST):
                assert PlaylistBuilder.assemble([], arrangement, direction) == []
                assert (
                    PlaylistBuilder.assemble([_contribution("seq", [], PickFrom.OLDEST)], arrangement, direction) == []
                )
