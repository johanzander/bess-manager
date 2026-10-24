"""Compose Octoplus free-import windows onto a day's price entries.

Octopus does not change the published Agile rate for a Power Up session or a
Weekend Happy Hour, so without this overlay BESS optimizes and accounts for a
free hour at full price. The overlay is applied when cached prices are read,
never when they are cached, so raw rates stay intact and a booking made
mid-day reaches the next optimization without invalidating the cache.
"""

import logging
from datetime import UTC, date, datetime, time, timedelta

from . import time_utils
from .calendar_windows import CalendarWindow

logger = logging.getLogger(__name__)

PERIOD_DURATION = timedelta(minutes=time_utils.INTERVAL_MINUTES)


def _day_start_utc(day: date) -> datetime:
    """The instant ``day`` starts in local time, as an aware UTC datetime."""
    return datetime.combine(day, time(0, 0), tzinfo=time_utils.TIMEZONE).astimezone(UTC)


def free_import_by_period_start(entries: list[dict], day: date) -> dict[datetime, bool]:
    """Map each period's start instant (UTC) to its ``isFreeImport`` flag.

    Entry ``i`` is the ``i``-th quarter-hour of elapsed time after local
    midnight, so on a DST day the repeated (or skipped) hour is addressed by
    instant. The entries' own ``timestamp`` strings are wall-clock labels and
    cannot tell the two 02:00 hours of a fall-back day apart.

    Args:
        entries: One day's price entries as returned by the price manager,
            each carrying ``isFreeImport``.
        day: The calendar day ``entries`` belong to.

    Returns:
        ``{period start (UTC): isFreeImport}``, one key per entry.
    """
    day_start = _day_start_utc(day)
    return {
        day_start + index * PERIOD_DURATION: entry["isFreeImport"]
        for index, entry in enumerate(entries)
    }


def apply_free_import_windows(
    entries: list[dict],
    day: date,
    windows: list[CalendarWindow],
    free_price: float,
) -> list[dict]:
    """Return ``entries`` with the buy price of fully covered periods set free.

    Args:
        entries: One day's price entries (``timestamp``/``price``/``buyPrice``/
            ``sellPrice``), period ``i`` starting ``i`` quarter-hours after
            local midnight.
        day: The calendar day ``entries`` belong to.
        windows: Free-import windows; any that miss ``day`` are ignored.
        free_price: Buy price for a period that lies fully inside a window.

    Returns:
        New entries, each carrying ``isFreeImport``. ``price`` and
        ``sellPrice`` are never changed, and ``entries`` is not mutated.

    """
    # Period i is i quarter-hours of *elapsed* time after local midnight --
    # the price sources index a 92/100-period DST day that way -- so period
    # instants are counted in UTC, not by wall clock.
    day_start = _day_start_utc(day)

    result = []
    partially_covering: set[CalendarWindow] = set()
    for index, entry in enumerate(entries):
        period_start = day_start + index * PERIOD_DURATION
        period_end = period_start + PERIOD_DURATION
        is_free = False
        for window in windows:
            if window.start <= period_start and period_end <= window.end:
                is_free = True
            elif window.start < period_end and period_start < window.end:
                partially_covering.add(window)

        composed = {**entry, "isFreeImport": is_free}
        if is_free:
            composed["buyPrice"] = free_price
        result.append(composed)

    for window in partially_covering:
        logger.warning(
            "Free import window %s - %s does not align with %d-minute price "
            "periods; partly covered periods keep their normal import price",
            window.start.astimezone(time_utils.TIMEZONE).strftime("%Y-%m-%d %H:%M"),
            window.end.astimezone(time_utils.TIMEZONE).strftime("%Y-%m-%d %H:%M"),
            time_utils.INTERVAL_MINUTES,
        )
    return result
