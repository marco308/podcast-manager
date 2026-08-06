"""UK holiday and weekend detection utilities."""

from datetime import date
from functools import lru_cache

import holidays


@lru_cache(maxsize=8)
def _uk_holidays(year: int) -> holidays.HolidayBase:
    """Return (and cache) the UK holiday set for a year.

    Building the set is not free and this is consulted once per weekend-only
    playlist per job run, so cache it. Keyed on year; a handful of entries
    covers any realistic run.
    """
    return holidays.UK(years=year)


def is_weekend_or_holiday(check_date: date | None = None) -> bool:
    """Check if the given date is a weekend or UK public holiday.

    Args:
        check_date: The date to check. Defaults to today (system local time,
            matching the timezone APScheduler fires the daily job in).

    Returns:
        True if the date is Friday, Saturday, Sunday, or a UK public holiday.
    """
    if check_date is None:
        check_date = date.today()

    # Check if Friday (4), Saturday (5), or Sunday (6)
    if check_date.weekday() >= 4:
        return True

    return check_date in _uk_holidays(check_date.year)


def get_uk_holidays(year: int) -> list[tuple[date, str]]:
    """Get all UK public holidays for a given year.

    Args:
        year: The year to get holidays for.

    Returns:
        List of (date, holiday_name) tuples.
    """
    return sorted(_uk_holidays(year).items())
