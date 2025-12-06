"""UK holiday and weekend detection utilities."""

from datetime import date

import holidays


def is_weekend_or_holiday(check_date: date | None = None) -> bool:
    """Check if the given date is a weekend or UK public holiday.

    Args:
        check_date: The date to check. Defaults to today.

    Returns:
        True if the date is Friday, Saturday, Sunday, or a UK public holiday.
    """
    if check_date is None:
        check_date = date.today()

    # Check if Friday (4), Saturday (5), or Sunday (6)
    if check_date.weekday() >= 4:
        return True

    # Check UK public holidays
    uk_holidays = holidays.UK(years=check_date.year)
    return check_date in uk_holidays


def get_uk_holidays(year: int) -> list[tuple[date, str]]:
    """Get all UK public holidays for a given year.

    Args:
        year: The year to get holidays for.

    Returns:
        List of (date, holiday_name) tuples.
    """
    uk_holidays = holidays.UK(years=year)
    return sorted([(d, name) for d, name in uk_holidays.items()])
