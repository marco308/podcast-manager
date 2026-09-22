"""Tests for the per-assignment rule resolver (issue #249).

Precedence: assignment override, then the podcast's ``is_sequential`` hint
(direction only), then the playlist default. ``None`` on the assignment means
inherit, so a refined row keeps its value when the playlist default changes.
"""

from types import SimpleNamespace

from app.models.playlist import ALL_EPISODES, PickFrom
from app.services.assignment_rules import resolve_rule


def _playlist(limit=ALL_EPISODES, pick="newest"):
    return SimpleNamespace(default_episode_limit=limit, default_pick_from=pick)


def _podcast(sequential=False):
    return SimpleNamespace(is_sequential=sequential)


def _assignment(limit=None, pick=None):
    return SimpleNamespace(episode_limit=limit, pick_from=pick)


class TestEpisodeLimit:
    def test_inherits_playlist_default(self):
        rule = resolve_rule(_playlist(limit=1), _podcast(), _assignment())
        assert rule.episode_limit == 1
        assert rule.episode_limit_source == "playlist"

    def test_override_wins(self):
        rule = resolve_rule(_playlist(limit=1), _podcast(), _assignment(limit=3))
        assert rule.episode_limit == 3
        assert rule.episode_limit_source == "override"

    def test_zero_override_means_all_even_when_playlist_is_limited(self):
        # 0 is a real value ("all"), distinct from None ("inherit").
        rule = resolve_rule(_playlist(limit=1), _podcast(), _assignment(limit=ALL_EPISODES))
        assert rule.episode_limit == ALL_EPISODES
        assert rule.unlimited
        assert rule.episode_limit_source == "override"


class TestPickFrom:
    def test_inherits_playlist_default(self):
        rule = resolve_rule(_playlist(pick="newest"), _podcast(), _assignment())
        assert rule.pick_from == PickFrom.NEWEST
        assert rule.pick_from_source == "playlist"

    def test_sequential_hint_beats_playlist_default(self):
        rule = resolve_rule(_playlist(pick="newest"), _podcast(sequential=True), _assignment())
        assert rule.pick_from == PickFrom.OLDEST
        assert rule.pick_from_source == "sequential"

    def test_override_beats_sequential_hint(self):
        rule = resolve_rule(_playlist(pick="newest"), _podcast(sequential=True), _assignment(pick="newest"))
        assert rule.pick_from == PickFrom.NEWEST
        assert rule.pick_from_source == "override"

    def test_no_assignment_previews_a_fresh_row(self):
        rule = resolve_rule(_playlist(limit=1, pick="newest"), _podcast(sequential=True), None)
        assert (rule.episode_limit, rule.pick_from) == (1, PickFrom.OLDEST)


class TestMorningPlaylist:
    """The motivating case: daily news (latest) plus one story (next unfinished)."""

    def test_news_and_story_resolve_differently_under_the_same_defaults(self):
        morning = _playlist(limit=1, pick="newest")
        news = resolve_rule(morning, _podcast(), _assignment())
        story = resolve_rule(morning, _podcast(sequential=True), _assignment())

        assert (news.episode_limit, news.pick_from) == (1, PickFrom.NEWEST)
        assert (story.episode_limit, story.pick_from) == (1, PickFrom.OLDEST)
