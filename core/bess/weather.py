"""Shared weather forecast utilities for BESS.

Fetches hourly weather forecasts from Home Assistant and provides
temperature data for optimization and ML modules.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

QUARTER_HOUR_MINUTES = 15
PERIODS_PER_DAY = 96


def fetch_hourly_weather_forecast(
    ha_url: str,
    ha_token: str,
    weather_entity: str,
    timezone: str,
) -> list[dict]:
    """Fetch hourly weather forecast entries from Home Assistant.

    Calls the HA weather/get_forecasts service and returns parsed hourly entries.

    Args:
        ha_url: Home Assistant base URL (e.g. "http://homeassistant.local:8123").
        ha_token: Long-lived access token for HA API.
        weather_entity: HA weather entity ID (e.g. "weather.forecast_home").
        timezone: IANA timezone string (e.g. "Europe/Stockholm").

    Returns:
        List of dicts with keys: datetime, temperature, cloud_coverage,
        wind_speed, precipitation. Sorted by datetime ascending.

    Raises:
        RuntimeError: If the HA API call fails or returns unexpected data.
    """
    base_url = ha_url.rstrip("/")
    local_tz = ZoneInfo(timezone)

    url = f"{base_url}/api/services/weather/get_forecasts?return_response"
    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "type": "hourly",
        "entity_id": weather_entity,
    }

    logger.info("Fetching weather forecast from HA (%s)...", weather_entity)
    response = requests.post(url, headers=headers, json=payload, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(
            f"HA weather forecast API failed with HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    data = response.json()

    # Response structure: {"service_response": {"weather.entity": {"forecast": [...]}}}
    service_response = data.get("service_response", data)
    entity_data = service_response.get(weather_entity)
    if entity_data is None:
        raise RuntimeError(
            f"No forecast data for entity '{weather_entity}' in HA response. "
            f"Available keys: {list(service_response.keys())}"
        )

    forecasts = entity_data["forecast"]
    if not forecasts:
        raise RuntimeError("HA returned empty forecast list")

    rows: list[dict] = []
    for entry in forecasts:
        dt_str = entry["datetime"]
        dt = datetime.fromisoformat(dt_str).astimezone(local_tz)
        rows.append(
            {
                "datetime": dt,
                "temperature": float(entry["temperature"]),
                "cloud_coverage": float(entry.get("cloud_coverage", 0)),
                "wind_speed": float(entry.get("wind_speed", 0)),
                "precipitation": float(entry.get("precipitation", 0)),
            }
        )

    rows.sort(key=lambda r: r["datetime"])

    logger.info(
        "Weather forecast: %d hourly entries from %s to %s",
        len(rows),
        rows[0]["datetime"],
        rows[-1]["datetime"],
    )

    return rows


def fetch_temperature_forecast(
    ha_url: str,
    ha_token: str,
    weather_entity: str,
    timezone: str,
    num_periods: int = PERIODS_PER_DAY,
) -> list[float]:
    """Fetch temperature forecast interpolated to quarter-hourly periods.

    Fetches the hourly weather forecast and linearly interpolates temperature
    values to the requested number of 15-minute periods.

    Args:
        ha_url: Home Assistant base URL.
        ha_token: Long-lived access token for HA API.
        weather_entity: HA weather entity ID.
        timezone: IANA timezone string.
        num_periods: Number of 15-minute periods to return (default 96 = 24h).

    Returns:
        List of temperature values in Celsius, one per 15-minute period.

    Raises:
        RuntimeError: If the HA API call fails or returns unexpected data.
    """
    hourly_entries = fetch_hourly_weather_forecast(
        ha_url, ha_token, weather_entity, timezone
    )

    # Extract hourly temperatures
    hourly_temps = [entry["temperature"] for entry in hourly_entries]

    if len(hourly_temps) < 2:
        # Not enough data to interpolate; repeat single value
        return [hourly_temps[0]] * num_periods

    # Linearly interpolate hourly to quarter-hourly (4 periods per hour)
    interpolated: list[float] = []
    for i in range(len(hourly_temps) - 1):
        t_start = hourly_temps[i]
        t_end = hourly_temps[i + 1]
        for q in range(4):
            fraction = q / 4.0
            interpolated.append(t_start + fraction * (t_end - t_start))

    # Add the last hour's value for the final 4 periods
    interpolated.extend([hourly_temps[-1]] * 4)

    # Trim or pad to exactly num_periods
    if len(interpolated) >= num_periods:
        return interpolated[:num_periods]

    # Pad with last value if forecast is shorter than requested
    last_temp = interpolated[-1] if interpolated else 10.0
    interpolated.extend([last_temp] * (num_periods - len(interpolated)))
    return interpolated
