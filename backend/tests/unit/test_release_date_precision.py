"""Release dates must order correctly across Spotify's mixed precisions (issue #161).

Spotify's ``release_date`` string follows ``release_date_precision``: a
year-only episode is ``"2024"``, a month-only one ``"2024-03"``, a normal
one ``"2024-03-15"``. The builder used to sort on the raw string, so
``"2024"`` < ``"2024-03"`` < ``"2024-03-01"`` lexicographically — a
year-precision episode always sorted *before* everything else that year,
in both directions. Every sort now goes through ``Episode.release_date_key``.
"""

from datetime import date
from app.models.playlist import Arrangement, DateDirection, PickFrom
from app.services.assignment_rules import ResolvedRule
from app.services.playlist_builder import Episode, PlaylistBuilder, ShowContribution, parse_release_date


def _episode(name, release_date, show_id="show"):
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


def _contribution(show_id, episodes, pick=PickFrom.NEWEST):
    rule = ResolvedRule(episode_limit=0, pick_from=pick, episode_limit_source="playlist", pick_from_source="playlist")
    return ShowContribution(show_id=show_id, rule=rule, episodes=list(episodes))


def _names(episodes):
    return [e.name for e in episodes]


class TestParseReleaseDate:
    def test_day_precision(self):
        assert parse_release_date("2024-03-15") == date(2024, 3, 15)

    def test_month_precision_rounds_down_to_first_of_month(self):
        assert parse_release_date("2024-03") == date(2024, 3, 1)

    def test_year_precision_rounds_down_to_new_year(self):
        assert parse_release_date("2024") == date(2024, 1, 1)

    def test_empty_and_none_sort_earliest(self):
        assert parse_release_date("") == date.min
        assert parse_release_date(None) == date.min

    def test_garbage_sorts_earliest_rather_than_raising(self):
        assert parse_release_date("not-a-date") == date.min
        assert parse_release_date("2024-13") == date.min
        assert parse_release_date("2024-02-30") == date.min

    def test_too_many_components_is_unparseable_not_truncated(self):
        # Must not be read as 2024-03-15 by ignoring the tail.
        assert parse_release_date("2024-03-15-extra") == date.min
        assert parse_release_date("2024-03-15-") == date.min

    def test_zero_padded_and_unpadded_components_agree(self):
        assert parse_release_date("2024-03-05") == parse_release_date("2024-3-5") == date(2024, 3, 5)
        assert parse_release_date("2024-03") == parse_release_date("2024-3") == date(2024, 3, 1)

    def test_year_precision_ties_with_january_first(self):
        # A year-only value rounds down to Jan 1 and compares *equal* to an
        # explicit Jan 1 — sorted() is stable, so equal keys keep input order.
        assert parse_release_date("2024") == parse_release_date("2024-01-01")

    def test_the_lexicographic_bug_is_gone(self):
        # Raw strings: "2024" < "2024-03" < "2024-02-10" is *false* ("2024-03" > "2024-02-10"),
        # but "2024" < "2024-02-10" is true even though a year-only date is
        # not known to be earlier. The parsed keys are consistent instead.
        keys = [parse_release_date(v) for v in ("2024-06", "2024", "2024-02-10", "2023-12-31")]
        assert sorted(keys) == [date(2023, 12, 31), date(2024, 1, 1), date(2024, 2, 10), date(2024, 6, 1)]


# A mixed-precision fixture where the raw-string order and the real order differ.
#   raw string order:  "2024" < "2024-03" < "2024-03-15" < "2024-11-02"  (looks fine)
#   but a month-precision "2025-01" would sort *before* "2025-01-05" only by
#   luck, and "2025" sorts before "2024-11-02"? No: "2025" > "2024-11-02".
# The failure that actually bites is year/month values vs full dates in the
# same period, so pin those.
MIXED = [
    _episode("day_march", "2024-03-15"),
    _episode("year_only", "2024"),
    _episode("month_march", "2024-03"),
    _episode("day_feb", "2024-02-10"),
    _episode("day_prev_year", "2023-12-31"),
]
OLDEST_FIRST = ["day_prev_year", "year_only", "day_feb", "month_march", "day_march"]


class TestSortEpisodes:
    def test_equal_keys_keep_input_order(self):
        # Year-only and explicit Jan 1 tie; the sort must be stable so the
        # result is deterministic rather than depending on string luck.
        a = _episode("a", "2024-01-01")
        b = _episode("b", "2024")
        assert _names(PlaylistBuilder.sort_within_show([a, b], PickFrom.OLDEST)) == ["a", "b"]
        assert _names(PlaylistBuilder.sort_within_show([b, a], PickFrom.OLDEST)) == ["b", "a"]

    def test_sequential_is_oldest_first_across_precisions(self):
        result = PlaylistBuilder.sort_within_show(list(MIXED), PickFrom.OLDEST)
        assert _names(result) == OLDEST_FIRST

    def test_non_sequential_is_newest_first_across_precisions(self):
        result = PlaylistBuilder.sort_within_show(list(MIXED), PickFrom.NEWEST)
        assert _names(result) == list(reversed(OLDEST_FIRST))

    def test_raw_string_order_would_have_been_wrong(self):
        # Guard against a regression back to string keys: "2024-03" vs
        # "2024-02-10" is the case raw comparison gets right by accident,
        # while "2024" vs "2024-02-10" is only right because "2024" happens
        # to be a prefix. Use a pair where string and date order disagree.
        a = _episode("a", "2024-1")  # sloppy month, parses to 2024-01-01
        b = _episode("b", "2024-02-10")
        assert "2024-1" > "2024-02-10"  # string order says a is newer
        result = PlaylistBuilder.sort_within_show([a, b], PickFrom.OLDEST)
        assert _names(result) == ["a", "b"]  # date order says a is older


class TestAssembly:
    def test_by_date_asc_and_desc(self):
        groups = [_contribution("show", MIXED)]
        asc = PlaylistBuilder.assemble(groups, Arrangement.BY_DATE.value, DateDirection.OLDEST_FIRST.value)
        desc = PlaylistBuilder.assemble(groups, Arrangement.BY_DATE.value, DateDirection.NEWEST_FIRST.value)
        assert _names(asc) == OLDEST_FIRST
        assert _names(desc) == list(reversed(OLDEST_FIRST))

    def test_oldest_show_slots_in_newest_first_merge_use_parsed_dates(self):
        seq = [_episode("s_year", "2024", "seq"), _episode("s_day", "2024-03-15", "seq")]
        news = [_episode("n_day", "2024-02-01", "news")]
        result = PlaylistBuilder.assemble(
            [_contribution("seq", seq, PickFrom.OLDEST), _contribution("news", news)],
            Arrangement.BY_DATE.value,
            DateDirection.NEWEST_FIRST.value,
        )
        # Merge newest-first: s_day (Mar), n_day (Feb), s_year (Jan 1).
        # The serial holds slots 0 and 2, filled oldest-first.
        assert _names(result) == ["s_year", "n_day", "s_day"]

    def test_by_position_keeps_the_within_show_order_it_is_given(self):
        ordered = PlaylistBuilder.sort_within_show(list(MIXED), PickFrom.OLDEST)
        result = PlaylistBuilder.assemble(
            [_contribution("show", ordered, PickFrom.OLDEST)],
            Arrangement.BY_POSITION.value,
            DateDirection.NEWEST_FIRST.value,
        )
        assert _names(result) == OLDEST_FIRST
