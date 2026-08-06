"""Tests for weekend/UK-holiday detection (issue #150).

This module drives whether a weekend-only playlist is updated at all, so the
Friday boundary and the holiday lookup are worth pinning explicitly.
"""

from datetime import date

from app.utils.holidays import get_uk_holidays, is_weekend_or_holiday


class TestWeekendDetection:
    # 2026-08-03 is a Monday, so this week runs Mon-Sun predictably.
    def test_monday_to_thursday_are_not_weekend(self):
        for day in range(3, 7):  # Mon 3rd .. Thu 6th
            assert is_weekend_or_holiday(date(2026, 8, day)) is False, f"2026-08-{day:02d} should be a weekday"

    def test_friday_counts_as_weekend(self):
        """Friday is deliberately included — see the docstring in holidays.py."""
        assert is_weekend_or_holiday(date(2026, 8, 7)) is True

    def test_saturday_and_sunday_count_as_weekend(self):
        assert is_weekend_or_holiday(date(2026, 8, 8)) is True
        assert is_weekend_or_holiday(date(2026, 8, 9)) is True


class TestHolidayDetection:
    def test_christmas_day_on_a_weekday_counts(self):
        # 2026-12-25 is a Friday, so use a year where Christmas is midweek:
        # 2024-12-25 was a Wednesday.
        christmas = date(2024, 12, 25)
        assert christmas.weekday() < 4, "fixture assumes a midweek Christmas"
        assert is_weekend_or_holiday(christmas) is True

    def test_new_years_day_on_a_weekday_counts(self):
        # 2025-01-01 was a Wednesday.
        nye = date(2025, 1, 1)
        assert nye.weekday() < 4, "fixture assumes a midweek New Year's Day"
        assert is_weekend_or_holiday(nye) is True

    def test_ordinary_midweek_day_does_not_count(self):
        assert is_weekend_or_holiday(date(2026, 3, 4)) is False


class TestHolidayListing:
    def test_returns_sorted_date_name_pairs(self):
        result = get_uk_holidays(2026)

        assert result, "expected at least one UK holiday"
        assert result == sorted(result), "results should be date-ordered"
        first_date, first_name = result[0]
        assert isinstance(first_date, date)
        assert isinstance(first_name, str)

    def test_caching_returns_consistent_results(self):
        """The lru_cache must not hand back a mutated set."""
        assert get_uk_holidays(2026) == get_uk_holidays(2026)
