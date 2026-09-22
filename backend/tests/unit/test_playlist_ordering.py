"""Tests for playlist assembly (issue #249; the sequential contract from #146).

``assemble`` takes per-show contributions, each with its resolved rule.
``by_position`` keeps assignment order; ``by_date`` merges by release date
and then refills the slots of any ``oldest`` show oldest-first, so a serial is
never played out of order. That refill is done by explicit slot lookup: after
a date merge a show's episodes are rarely adjacent, which is what silently
broke ``itertools.groupby`` before.
"""

from app.models.playlist import Arrangement, DateDirection, PickFrom
from app.services.assignment_rules import ResolvedRule
from app.services.playlist_builder import Episode, PlaylistBuilder, ShowContribution

BY_POSITION = Arrangement.BY_POSITION.value
BY_DATE = Arrangement.BY_DATE.value
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
        for arrangement in (BY_POSITION, BY_DATE):
            for direction in (NEWEST_FIRST, OLDEST_FIRST):
                assert PlaylistBuilder.assemble([], arrangement, direction) == []
                assert (
                    PlaylistBuilder.assemble([_contribution("seq", [], PickFrom.OLDEST)], arrangement, direction) == []
                )
