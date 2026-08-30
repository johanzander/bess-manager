"""Reconstruct per-period sensor history from Home Assistant's recorder.

Drop-in replacement for the historical-read half of ``influxdb_helper``: same
return contract (``{"status", "data": {period: {sensor_key: value}}}``), same
15-minute period model, but sourced from HA's built-in recorder via
``GET /api/history/period`` instead of an external InfluxDB instance.

Every HA install has the recorder (default 10-day retention), so there is no
"configured?" gate — callers degrade on an empty/error result exactly as they
did on an InfluxDB miss.

Two entry points, mirroring ``influxdb_helper``:

* ``get_sensor_data_batch`` — the last value of each cumulative counter (kWh
  totals, SOC) at every 15-minute boundary of a day.
* ``get_power_sensor_data_batch`` — the mean of an instantaneous power (W)
  sensor within each 15-minute period, converted to kWh.

Not yet wired into any production path — see issue #722, PR 2.
"""

import logging
from datetime import date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from core.bess import time_utils

if TYPE_CHECKING:  # avoid a runtime import cycle once PR 2 wires this in
    from core.bess.ha_api_controller import HomeAssistantAPIController

_LOGGER = logging.getLogger(__name__)

_Series = dict[str, list[tuple[datetime, float]]]


# Instantaneous-power readings above this (W) are treated as sensor glitches
# and dropped — mirrors influxdb_helper's guard against the output_power
# 429496663.7 (uint overflow) spikes.
_MAX_PLAUSIBLE_WATTS = 100000

_PERIODS_PER_DAY = 96
_PERIOD_SECONDS = 900


def _day_bounds(target_date: date | datetime) -> tuple[datetime, datetime]:
    """Return (start, end) datetimes spanning target_date in the local tz."""
    local_tz = time_utils.TIMEZONE
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=local_tz)
    end = datetime.combine(target_date, datetime.max.time()).replace(tzinfo=local_tz)
    return start, end


def _parse_timestamp(entry: dict, local_tz: tzinfo) -> datetime | None:
    """Extract a timezone-aware local datetime from a history entry."""
    raw = entry.get("last_changed") or entry.get("last_updated")
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=ZoneInfo("UTC"))
    return ts.astimezone(local_tz)


def _fetch_series(
    controller: "HomeAssistantAPIController",
    entity_ids: list[str],
    start: datetime,
    end: datetime,
) -> _Series:
    """Fetch and normalise recorder history into per-entity (ts, value) series.

    Returns a dict keyed by full entity id (``sensor.x``). Each value is a
    time-sorted list of ``(local_datetime, float)`` samples. Non-numeric
    states (``unknown`` / ``unavailable``) are skipped. HA prepends the state
    as of ``start`` to every entity's list, so a sparse counter that has not
    changed today still yields one sample.
    """
    local_tz = time_utils.TIMEZONE
    start_iso = start.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

    raw = controller.get_history_period(entity_ids, start_iso, end_iso)

    series: dict[str, list[tuple[datetime, float]]] = {}
    for entity_history in raw or []:
        if not entity_history:
            continue
        # With minimal_response only the first entry carries entity_id.
        entity_id = entity_history[0].get("entity_id")
        if not entity_id:
            continue
        samples: list[tuple[datetime, float]] = []
        for entry in entity_history:
            state = str(entry.get("state", "")).strip()
            try:
                value = float(state)
            except ValueError:
                continue
            ts = _parse_timestamp(entry, local_tz)
            if ts is None:
                continue
            samples.append((ts, value))
        samples.sort(key=lambda s: s[0])
        series[entity_id] = samples
    return series


def _load_series(
    controller: "HomeAssistantAPIController",
    names: list[str],
    target_date: date | datetime,
) -> tuple[_Series, datetime] | dict:
    """Shared preamble for both batch entry points.

    Returns ``(series, day_start)`` on success, or a ready-to-return
    ``{"status": "error", "message": ...}`` dict for an empty sensor list, a
    fetch exception, or a window with no recorder data.
    """
    if not names:
        return {"status": "error", "message": "No sensors configured"}

    start, end = _day_bounds(target_date)
    entity_ids = [f"sensor.{name}" for name in names]

    try:
        series = _fetch_series(controller, entity_ids, start, end)
    except Exception as e:  # mirror influxdb_helper's catch-all
        _LOGGER.error("Recorder history fetch failed: %s", e)
        return {"status": "error", "message": f"Recorder history error: {e!s}"}

    if not any(series.values()):
        return {
            "status": "error",
            "message": f"No recorder history for {start.date().isoformat()}",
        }

    return series, start


def get_sensor_data_batch(
    controller: "HomeAssistantAPIController",
    sensors_list: list[str],
    target_date: date | datetime,
) -> dict:
    """Last value of each cumulative sensor at all 96 period boundaries.

    Args:
        controller: an HomeAssistantAPIController exposing ``get_history_period``.
        sensors_list: entity IDs without the ``sensor.`` prefix.
        target_date: date (or datetime) to fetch.

    Returns:
        ``{"status": "success", "data": {period_int: {"sensor.x": float}}}`` or
        ``{"status": "error", "message": str}``. Periods with no data are
        omitted.
    """
    loaded = _load_series(controller, sensors_list, target_date)
    if isinstance(loaded, dict):
        return loaded
    series, start = loaded

    period_data: dict[int, dict[str, float]] = {}
    for period in range(_PERIODS_PER_DAY):
        period_end = start + timedelta(seconds=(period + 1) * _PERIOD_SECONDS - 1)
        bucket: dict[str, float] = {}
        for entity_id, samples in series.items():
            last_value = None
            for ts, value in samples:
                if ts <= period_end:
                    last_value = value
                else:
                    break
            if last_value is not None:
                bucket[entity_id] = last_value
        if bucket:
            period_data[period] = bucket

    _LOGGER.info(
        "Recorder batch: %d/%d periods populated for %s (%d sensors)",
        len(period_data),
        _PERIODS_PER_DAY,
        start.date().isoformat(),
        len(sensors_list),
    )
    return {"status": "success", "data": period_data}


def get_power_sensor_data_batch(
    controller: "HomeAssistantAPIController",
    power_sensors: list[str],
    target_date: date | datetime,
) -> dict:
    """Mean power (W) per 15-minute period, converted to energy (kWh).

    ``kWh = mean_watts * (15 / 60) / 1000`` per period. Readings whose
    magnitude exceeds ``_MAX_PLAUSIBLE_WATTS`` are dropped as glitches.

    Args / Returns: as ``get_sensor_data_batch``.
    """
    loaded = _load_series(controller, power_sensors, target_date)
    if isinstance(loaded, dict):
        return loaded
    series, start = loaded

    # {entity_id: {period: [watt readings]}}
    readings: dict[str, dict[int, list[float]]] = {}
    for entity_id, samples in series.items():
        for ts, value in samples:
            if abs(value) > _MAX_PLAUSIBLE_WATTS:
                continue
            offset = (ts - start).total_seconds()
            if offset < 0 or offset >= _PERIODS_PER_DAY * _PERIOD_SECONDS:
                continue
            period = int(offset // _PERIOD_SECONDS)
            readings.setdefault(entity_id, {}).setdefault(period, []).append(value)

    period_data: dict[int, dict[str, float]] = {}
    for entity_id, periods in readings.items():
        for period, values in periods.items():
            mean_watts = sum(values) / len(values)
            period_data.setdefault(period, {})[entity_id] = mean_watts * 0.25 / 1000.0

    _LOGGER.info(
        "Recorder power batch: %d periods for %s (%d sensors)",
        len(period_data),
        start.date().isoformat(),
        len(power_sensors),
    )
    return {"status": "success", "data": period_data}
