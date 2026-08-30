"""Managed loads — exclude a declared load from the consumption forecast baseline.

Issue #706. The `ha_statistics` strategy learns "normal" load from history,
which bakes in any managed load (typically EV charging) that happened during
the training window: an EV session that occurred yesterday reads as part of
today's expected pattern. Managed loads is the exclusion mechanism — the
user names the load's own cumulative/lifetime energy sensor, its energy is
subtracted from the historical data before the baseline is computed, and the
learned "normal" becomes the residual (house load with managed loads
excluded). The user then re-declares any expected managed-load energy via
Planned Consumption Changes (`consumption_overlay`), which composes on top
of this residual baseline exactly as it does today.

Scoped to `ha_statistics` only: `load_power_7d_avg` averages instantaneous
power samples, a different data source/shape than HA Recorder's cumulative
`change` values, and needs its own subtraction mechanism.
"""

from .exceptions import ManagedLoadsError

# HA Recorder statistics entries are {"start": <epoch-ms int, or ISO string>,
# "change": <float>}. Same query (same statistic_id set, start_time, end_time,
# period="hour") returns identical "start" values across calls, so matching
# by the raw "start" value -- whatever type it is -- is exact; no parsing
# needed.
StatEntry = dict


def subtract_managed_loads(
    base_stats: list[StatEntry],
    managed_stats: list[list[StatEntry]],
) -> tuple[list[StatEntry], int]:
    """Subtract each managed load's per-hour energy from the base sensor's.

    Args:
        base_stats: The `lifetime_load_consumption` sensor's raw
            {"start", "change"} entries for the training window.
        managed_stats: One raw entry list per managed-load sensor, fetched
            over the identical window (same statistic query parameters as
            ``base_stats``, so "start" values line up exactly).

    Returns:
        (adjusted_stats, clamped_hours) -- adjusted_stats has the same
        "start" values as base_stats, with "change" reduced by the sum of
        matching managed-load hours. A managed load can only ever reduce
        recorded load, never invert it, so any hour where the subtraction
        would go negative is floored at 0.0 and counted in clamped_hours --
        this means the managed load's own historical draw exceeded the total
        load sensor's for that hour, which points at a sensor/entity
        mismatch worth surfacing, not silently absorbing.

    Raises:
        ManagedLoadsError: A managed-load entry is missing "start" or
            "change" -- never skipped, since silently dropping an hour would
            silently understate the subtraction for that hour.
    """
    managed_by_start: dict[object, float] = {}
    for stats in managed_stats:
        for entry in stats:
            if "start" not in entry or "change" not in entry:
                raise ManagedLoadsError(
                    f"managed-load statistics entry is missing 'start' or "
                    f"'change': {entry!r}"
                )
            change = entry["change"]
            if change is None:
                continue
            start = entry["start"]
            managed_by_start[start] = managed_by_start.get(start, 0.0) + float(change)

    adjusted: list[StatEntry] = []
    clamped_hours = 0
    for entry in base_stats:
        change = entry.get("change")
        if change is None:
            adjusted.append(entry)
            continue
        managed = managed_by_start.get(entry.get("start"), 0.0)
        residual = float(change) - managed
        if residual < 0:
            residual = 0.0
            clamped_hours += 1
        adjusted.append({**entry, "change": residual})

    return adjusted, clamped_hours
