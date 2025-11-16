"""Time utilities for quarterly period handling.

KEY PRINCIPLE: All arrays start at index 0 = today 00:00.
Period indices are continuous integers from today's 00:00.

This module provides conversion between timestamps and period indices,
handling DST transitions correctly.
"""

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Constants - NOT configurable
TIMEZONE = ZoneInfo("Europe/Stockholm")
INTERVAL_MINUTES = 15  # Quarterly resolution
PERIODS_PER_HOUR = 4
PERIODS_PER_DAY_NORMAL = 96


def get_period_count(target_date: date) -> int:
    """Get number of quarterly periods in a day.

    Handles DST transitions:
    - Normal day: 96 periods (24 hours * 4)
    - DST spring: 92 periods (23 hours * 4)
    - DST fall: 100 periods (25 hours * 4)

    Args:
        target_date: The calendar date

    Returns:
        Number of quarterly periods in this day
    """
    start = datetime.combine(target_date, time(0, 0), tzinfo=TIMEZONE)
    next_day = start + timedelta(days=1)

    # Calculate actual hours (DST-aware)
    elapsed_hours = (next_day - start).total_seconds() / 3600

    return int(elapsed_hours * PERIODS_PER_HOUR)


def timestamp_to_period_index(dt: datetime) -> int:
    """Convert timestamp to continuous period index from today's 00:00.

    Args:
        dt: Timestamp to convert (must be timezone-aware)

    Returns:
        Continuous index where:
        - Today 00:00 → 0
        - Today 14:00 → 56
        - Today 23:45 → 95
        - Tomorrow 00:00 → 96
        - Tomorrow 14:00 → 152

    Example:
        >>> dt = datetime(2025, 11, 15, 14, 30, tzinfo=TIMEZONE)
        >>> timestamp_to_period_index(dt)
        58  # (14 * 4) + 2 = 58

    Raises:
        ValueError: If dt is not timezone-aware
    """
    if dt.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware")

    today = datetime.now(tz=TIMEZONE).date()
    target_date = dt.date()

    # Calculate days from today
    days_from_today = (target_date - today).days

    # Get periods elapsed within the target day
    day_start = datetime.combine(target_date, time(0, 0), tzinfo=dt.tzinfo)
    elapsed_minutes = (dt - day_start).total_seconds() / 60
    period_within_day = int(elapsed_minutes / INTERVAL_MINUTES)

    if days_from_today == 0:
        # Today
        return period_within_day
    elif days_from_today == 1:
        # Tomorrow - offset by today's period count
        today_periods = get_period_count(today)
        return today_periods + period_within_day
    elif days_from_today > 1:
        # Future days (general case)
        total_periods = 0
        current_date = today
        while current_date < target_date:
            total_periods += get_period_count(current_date)
            current_date += timedelta(days=1)
        return total_periods + period_within_day
    else:
        # Past days (negative offset)
        raise ValueError(
            f"Cannot convert past timestamp {dt} to period index "
            f"(today is {today}). Only today and future dates supported."
        )


def period_index_to_timestamp(period_index: int) -> datetime:
    """Convert period index to timestamp for debugging/display.

    Args:
        period_index: Continuous index from today 00:00

    Returns:
        Timestamp for this period

    Example:
        >>> period_index_to_timestamp(0)
        datetime(2025, 11, 15, 0, 0, tzinfo=ZoneInfo('Europe/Stockholm'))
        >>> period_index_to_timestamp(56)
        datetime(2025, 11, 15, 14, 0, tzinfo=ZoneInfo('Europe/Stockholm'))
        >>> period_index_to_timestamp(96)
        datetime(2025, 11, 16, 0, 0, tzinfo=ZoneInfo('Europe/Stockholm'))

    Raises:
        ValueError: If period_index is negative
    """
    if period_index < 0:
        raise ValueError(f"Period index must be non-negative, got {period_index}")

    today = datetime.now(tz=TIMEZONE).date()
    today_periods = get_period_count(today)

    if period_index < today_periods:
        # Today
        day_start = datetime.combine(today, time(0, 0), tzinfo=TIMEZONE)
        delta = timedelta(minutes=period_index * INTERVAL_MINUTES)
        return day_start + delta
    else:
        # Tomorrow or later - walk through days
        current_date = today
        periods_to_skip = period_index

        while periods_to_skip >= get_period_count(current_date):
            periods_to_skip -= get_period_count(current_date)
            current_date += timedelta(days=1)

        day_start = datetime.combine(current_date, time(0, 0), tzinfo=TIMEZONE)
        delta = timedelta(minutes=periods_to_skip * INTERVAL_MINUTES)
        return day_start + delta


def get_current_period_index() -> int:
    """Get current period index.

    Returns:
        Current period as continuous index from today 00:00
        (typically 0-95 for current day)

    Example:
        At 14:30 → returns 58
    """
    now = datetime.now(tz=TIMEZONE)
    return timestamp_to_period_index(now)
