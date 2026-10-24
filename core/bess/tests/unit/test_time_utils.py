"""Tests for time_utils."""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest

from core.bess.time_utils import (
    TIMEZONE,
    get_current_period_index,
    get_period_count,
    period_index_to_timestamp,
    timestamp_to_period_index,
)


def test_normal_day_has_96_periods():
    """Normal day should have 96 quarterly periods."""
    normal_day = date(2025, 11, 15)  # Not a DST transition
    assert get_period_count(normal_day) == 96


@patch("core.bess.time_utils.datetime")
def test_timestamp_to_period_index_today(mock_datetime):
    """Should convert today's timestamp to period index."""
    # Mock "today" as 2025-11-15
    mock_now = datetime(2025, 11, 15, 12, 0, tzinfo=TIMEZONE)
    mock_datetime.now.return_value = mock_now
    mock_datetime.combine = datetime.combine

    # Test various times today
    dt_morning = datetime(2025, 11, 15, 0, 0, tzinfo=TIMEZONE)
    assert timestamp_to_period_index(dt_morning) == 0  # Midnight

    dt_afternoon = datetime(2025, 11, 15, 14, 30, tzinfo=TIMEZONE)
    assert timestamp_to_period_index(dt_afternoon) == 58  # 14 * 4 + 2

    dt_evening = datetime(2025, 11, 15, 23, 45, tzinfo=TIMEZONE)
    assert timestamp_to_period_index(dt_evening) == 95  # Last period


@patch("core.bess.time_utils.datetime")
def test_timestamp_to_period_index_tomorrow(mock_datetime):
    """Should convert tomorrow's timestamp to period index."""
    # Mock "today" as 2025-11-15
    mock_now = datetime(2025, 11, 15, 12, 0, tzinfo=TIMEZONE)
    mock_datetime.now.return_value = mock_now
    mock_datetime.combine = datetime.combine

    # Test tomorrow
    dt_tomorrow_midnight = datetime(2025, 11, 16, 0, 0, tzinfo=TIMEZONE)
    assert timestamp_to_period_index(dt_tomorrow_midnight) == 96  # Tomorrow 00:00

    dt_tomorrow_afternoon = datetime(2025, 11, 16, 14, 0, tzinfo=TIMEZONE)
    assert timestamp_to_period_index(dt_tomorrow_afternoon) == 152  # 96 + 56


@patch("core.bess.time_utils.datetime")
def test_period_index_to_timestamp(mock_datetime):
    """Should convert period index to timestamp."""
    # Mock "today" as 2025-11-15
    mock_now = datetime(2025, 11, 15, 12, 0, tzinfo=TIMEZONE)
    mock_datetime.now.return_value = mock_now
    mock_datetime.combine = datetime.combine

    # Today
    dt = period_index_to_timestamp(0)
    assert dt.date() == date(2025, 11, 15)
    assert dt.hour == 0
    assert dt.minute == 0

    dt = period_index_to_timestamp(58)
    assert dt.date() == date(2025, 11, 15)
    assert dt.hour == 14
    assert dt.minute == 30

    # Tomorrow
    dt = period_index_to_timestamp(96)
    assert dt.date() == date(2025, 11, 16)
    assert dt.hour == 0
    assert dt.minute == 0


@patch("core.bess.time_utils.datetime")
def test_roundtrip_conversion(mock_datetime):
    """period_index → timestamp → period_index should roundtrip."""
    # Mock "today" as 2025-11-15
    mock_now = datetime(2025, 11, 15, 12, 0, tzinfo=TIMEZONE)
    mock_datetime.now.return_value = mock_now
    mock_datetime.combine = datetime.combine

    for period_idx in [0, 56, 95, 96, 152]:
        timestamp = period_index_to_timestamp(period_idx)
        recovered_idx = timestamp_to_period_index(timestamp)
        assert recovered_idx == period_idx, f"Roundtrip failed for period {period_idx}"


@patch("core.bess.time_utils.datetime")
def test_get_current_period_index(mock_datetime):
    """Should return current period index."""
    # Mock current time as 2025-11-15 14:30
    now_time = datetime(2025, 11, 15, 14, 30, tzinfo=TIMEZONE)
    mock_datetime.now.return_value = now_time
    mock_datetime.combine = datetime.combine

    assert get_current_period_index() == 58  # 14 * 4 + 2


def test_timestamp_must_be_timezone_aware():
    """Should raise error for naive timestamps."""
    naive_dt = datetime(2025, 11, 15, 14, 30)  # No timezone
    with pytest.raises(ValueError, match="timezone-aware"):
        timestamp_to_period_index(naive_dt)


def test_negative_period_index_raises_error():
    """Should raise error for negative period indices."""
    with pytest.raises(ValueError, match="non-negative"):
        period_index_to_timestamp(-1)


@patch("core.bess.time_utils.datetime")
def test_past_timestamp_raises_error(mock_datetime):
    """Should raise error for past timestamps (before today)."""
    # Mock "today" as 2025-11-15
    mock_now = datetime(2025, 11, 15, 12, 0, tzinfo=TIMEZONE)
    mock_datetime.now.return_value = mock_now
    mock_datetime.combine = datetime.combine

    # Try to convert yesterday
    yesterday = datetime(2025, 11, 14, 12, 0, tzinfo=TIMEZONE)
    with pytest.raises(ValueError, match="Only today and tomorrow supported"):
        timestamp_to_period_index(yesterday)


@patch("core.bess.time_utils.datetime")
def test_future_beyond_tomorrow_raises_error(mock_datetime):
    """Should raise error for timestamps beyond tomorrow."""
    # Mock "today" as 2025-11-15
    mock_now = datetime(2025, 11, 15, 12, 0, tzinfo=TIMEZONE)
    mock_datetime.now.return_value = mock_now
    mock_datetime.combine = datetime.combine

    # Try to convert day after tomorrow
    day_after_tomorrow = datetime(2025, 11, 17, 12, 0, tzinfo=TIMEZONE)
    with pytest.raises(ValueError, match="Only today and tomorrow supported"):
        timestamp_to_period_index(day_after_tomorrow)


def test_period_index_beyond_tomorrow_raises_error():
    """Should raise error for period indices beyond tomorrow."""
    with pytest.raises(ValueError, match="beyond tomorrow"):
        period_index_to_timestamp(200)  # Way beyond tomorrow


@patch("core.bess.time_utils.datetime")
def test_midnight_is_period_zero(mock_datetime):
    """Midnight should be period 0."""
    mock_now = datetime(2025, 11, 15, 12, 0, tzinfo=TIMEZONE)
    mock_datetime.now.return_value = mock_now
    mock_datetime.combine = datetime.combine

    dt = datetime(2025, 11, 15, 0, 0, tzinfo=TIMEZONE)
    assert timestamp_to_period_index(dt) == 0


@patch("core.bess.time_utils.datetime")
def test_end_of_day_is_period_95(mock_datetime):
    """23:45 should be period 95."""
    mock_now = datetime(2025, 11, 15, 12, 0, tzinfo=TIMEZONE)
    mock_datetime.now.return_value = mock_now
    mock_datetime.combine = datetime.combine

    dt = datetime(2025, 11, 15, 23, 45, tzinfo=TIMEZONE)
    assert timestamp_to_period_index(dt) == 95


# TODO: Add DST tests when we know specific DST dates for 2025
# These would test days with 92 periods (spring) and 100 periods (fall)


# --- DST days (issue #830): period indices follow real elapsed time -----------
# Fall-back 2026-10-25 is 100 periods: 02:00-03:00 happens twice (+02:00, +01:00).


def _utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _mock_today(mock_datetime: MagicMock, y: int, m: int, d: int) -> None:
    mock_datetime.now.return_value = datetime(y, m, d, 12, 0, tzinfo=TIMEZONE)
    mock_datetime.combine = datetime.combine


@patch("core.bess.time_utils.datetime")
@pytest.mark.parametrize(
    "instant,expected",
    [
        (_utc(2026, 10, 24, 22, 0), 0),  # 00:00 +02:00
        (_utc(2026, 10, 25, 0, 0), 8),  # 02:00 +02:00 (first)
        (_utc(2026, 10, 25, 1, 0), 12),  # 02:00 +01:00 (repeated)
        (_utc(2026, 10, 25, 2, 0), 16),  # 03:00 +01:00
        (_utc(2026, 10, 25, 22, 45), 99),  # 23:45 +01:00, last period
    ],
)
def test_fall_back_day_index_follows_elapsed_time(
    mock_datetime: MagicMock, instant: datetime, expected: int
) -> None:
    _mock_today(mock_datetime, 2026, 10, 25)
    assert timestamp_to_period_index(instant.astimezone(TIMEZONE)) == expected


@patch("core.bess.time_utils.datetime")
def test_fall_back_day_index_to_timestamp_is_unique_and_stays_on_the_day(
    mock_datetime: MagicMock,
) -> None:
    _mock_today(mock_datetime, 2026, 10, 25)
    stamps = [period_index_to_timestamp(i) for i in range(100)]

    assert len({s.astimezone(UTC) for s in stamps}) == 100
    assert {s.date() for s in stamps} == {date(2026, 10, 25)}
    offset = stamps[12].utcoffset()
    assert offset is not None and offset.total_seconds() == 3600  # repeated hour, CET
    assert stamps[12].hour == 2 and stamps[8].hour == 2
    assert stamps[99].hour == 23 and stamps[99].minute == 45
    assert all(timestamp_to_period_index(s) == i for i, s in enumerate(stamps))


@patch("core.bess.time_utils.datetime")
def test_fall_back_day_as_tomorrow_roundtrips(mock_datetime: MagicMock) -> None:
    _mock_today(mock_datetime, 2026, 10, 24)
    for i in range(96, 196):
        stamp = period_index_to_timestamp(i)
        assert stamp.date() == date(2026, 10, 25)
        assert timestamp_to_period_index(stamp) == i
    with pytest.raises(ValueError):
        period_index_to_timestamp(196)


@patch("core.bess.time_utils.datetime")
def test_spring_forward_day_roundtrips(mock_datetime: MagicMock) -> None:
    _mock_today(mock_datetime, 2026, 3, 29)
    stamps = [period_index_to_timestamp(i) for i in range(92)]

    assert len({s.astimezone(UTC) for s in stamps}) == 92
    assert {s.date() for s in stamps} == {date(2026, 3, 29)}
    assert all(timestamp_to_period_index(s) == i for i, s in enumerate(stamps))
