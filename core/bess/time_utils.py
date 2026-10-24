"""Time utilities for quarterly period handling.

KEY PRINCIPLE: All arrays start at index 0 = today 00:00.
Period indices are continuous integers from today's 00:00.

This module provides conversion between timestamps and period indices,
handling DST transitions correctly.
"""

import logging
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def set_timezone(tz_name: str) -> None:
    """Set the global timezone from HA config. Must be called before scheduling."""
    global TIMEZONE
    TIMEZONE = ZoneInfo(tz_name)


# Timezone — overridden at startup by set_timezone() from HA config
TIMEZONE = ZoneInfo("Europe/Stockholm")
INTERVAL_MINUTES = 15  # Quarterly resolution
PERIODS_PER_HOUR = 4
PERIODS_PER_DAY_NORMAL = 96


def now() -> datetime:
    """Current datetime in the user's configured timezone."""
    return datetime.now(tz=TIMEZONE)


def today() -> date:
    """Today's date in the user's configured timezone."""
    return now().date()


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
    next_midnight = datetime.combine(
        target_date + timedelta(days=1), time(0, 0), tzinfo=TIMEZONE
    )

    # Use epoch timestamps for correct DST-aware elapsed time.
    # Direct datetime subtraction with ZoneInfo gives wall-clock difference
    # (always 24h), not actual elapsed time.
    elapsed_hours = (next_midnight.timestamp() - start.timestamp()) / 3600

    return int(elapsed_hours * PERIODS_PER_HOUR)


def _local_midnight_utc(target_date: date) -> datetime:
    """The instant the given local calendar day starts, as an aware UTC datetime."""
    return datetime.combine(target_date, time(0, 0), tzinfo=TIMEZONE).astimezone(UTC)


def _period_start(target_date: date, period_within_day: int) -> datetime:
    """Start of a period, counted in real elapsed time from the day's midnight.

    Adding a timedelta to a ZoneInfo datetime is wall-clock arithmetic, so on a
    DST day it would skip (or repeat) the transition hour; elapsed time does not.
    """
    start = _local_midnight_utc(target_date)
    elapsed = timedelta(minutes=period_within_day * INTERVAL_MINUTES)
    return (start + elapsed).astimezone(TIMEZONE)


def timestamp_to_period_index(dt: datetime) -> int:
    """Convert timestamp to continuous period index from today's 00:00.

    Only supports today and tomorrow.

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
        ValueError: If dt is not timezone-aware, or not today/tomorrow
    """
    if dt.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware")

    today = datetime.now(tz=TIMEZONE).date()
    dt = dt.astimezone(TIMEZONE)
    target_date = dt.date()
    days_from_today = (target_date - today).days

    # Validate: only today and tomorrow supported
    if days_from_today < 0:
        raise ValueError(
            f"Only today and tomorrow supported, got {target_date} (today is {today})"
        )
    if days_from_today > 1:
        raise ValueError(
            f"Only today and tomorrow supported, got {target_date} (today is {today})"
        )

    # Elapsed real time since the day's local midnight. Subtracting two datetimes
    # that share a ZoneInfo is wall-clock arithmetic, which loses (or invents) the
    # DST hour, so both sides go through UTC.
    elapsed_minutes = (
        dt.astimezone(UTC) - _local_midnight_utc(target_date)
    ).total_seconds() / 60
    period_within_day = int(elapsed_minutes / INTERVAL_MINUTES)

    if days_from_today == 0:
        # Today
        return period_within_day
    else:
        # Tomorrow (days_from_today == 1)
        today_periods = get_period_count(today)
        return today_periods + period_within_day


def period_index_to_timestamp(period_index: int) -> datetime:
    """Convert period index to timestamp for debugging/display.

    Only supports today and tomorrow (0-191).

    Args:
        period_index: Continuous index from today 00:00 (0-191)

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
        ValueError: If period_index is negative or > 191 (beyond tomorrow)
    """
    if period_index < 0:
        raise ValueError(f"Period index must be non-negative, got {period_index}")

    today = datetime.now(tz=TIMEZONE).date()
    today_periods = get_period_count(today)

    if period_index < today_periods:
        # Today (0-95 normally)
        return _period_start(today, period_index)
    else:
        # Tomorrow
        tomorrow = today + timedelta(days=1)
        tomorrow_periods = get_period_count(tomorrow)
        max_period = today_periods + tomorrow_periods - 1

        if period_index > max_period:
            raise ValueError(
                f"Period index {period_index} beyond tomorrow "
                f"(max: {max_period} = today {today_periods} + tomorrow {tomorrow_periods})"
            )

        period_within_tomorrow = period_index - today_periods
        return _period_start(tomorrow, period_within_tomorrow)


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


def format_period(period_index: int) -> str:
    """Format period index as HH:MM time string for logging.

    Args:
        period_index: Period index (0-95 for today, 96-191 for tomorrow)

    Returns:
        Formatted time string like "14:30" or "00:00"

    Example:
        >>> format_period(0)
        "00:00"
        >>> format_period(58)
        "14:30"
        >>> format_period(95)
        "23:45"
    """
    try:
        timestamp = period_index_to_timestamp(period_index)
        return timestamp.strftime("%H:%M")
    except ValueError:
        # Fallback for invalid period indices
        return f"period_{period_index}"
