"""Bulk historical data fetcher from InfluxDB for ML training.

Queries multiple days of sensor data and returns a pandas DataFrame
with 15-minute aggregated readings for target and feature sensors.
Also fetches weather forecasts from Home Assistant and history context
from InfluxDB for prediction.
"""

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests

_LOGGER = logging.getLogger(__name__)

UTC = ZoneInfo("UTC")

QUARTER_HOUR_MINUTES = 15
PERIODS_PER_DAY = 96


def _get_local_tz(config: dict) -> ZoneInfo:
    """Extract the local timezone from config."""
    return ZoneInfo(config["location"]["timezone"])


def _build_sensor_filter(sensors: list[str]) -> str:
    """Build Flux sensor filter compatible with InfluxDB 1.x and 2.x."""
    conditions = []
    for sensor in sensors:
        conditions.append(
            f'(r["_measurement"] == "sensor.{sensor}" or r["entity_id"] == "{sensor}")'
        )
    return " or ".join(conditions)


def _query_influxdb(
    config: dict,
    flux_query: str,
    timeout: int = 60,
) -> str:
    """Execute a Flux query against InfluxDB and return raw CSV response.

    Raises:
        RuntimeError: If the query fails or returns no data.
    """
    influx_cfg = config["influxdb"]
    url = influx_cfg["url"]
    username = influx_cfg["username"]
    password = influx_cfg["password"]

    headers = {
        "Content-type": "application/vnd.flux",
        "Accept": "application/csv",
    }

    response = requests.post(
        url=url,
        auth=(username, password),
        headers=headers,
        data=flux_query,
        timeout=timeout,
    )

    if response.status_code == 204:
        raise RuntimeError("InfluxDB returned no data (HTTP 204)")

    if response.status_code != 200:
        raise RuntimeError(
            f"InfluxDB query failed with HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    return response.text


def _parse_csv_to_dataframe(csv_text: str, local_tz: ZoneInfo) -> pd.DataFrame:
    """Parse InfluxDB CSV response into a DataFrame with timestamp and sensor columns.

    Returns a DataFrame with columns: timestamp, sensor_name, value
    """
    rows: list[dict[str, object]] = []

    lines = csv_text.strip().split("\n")
    data_lines = [line for line in lines if not line.startswith("#")]

    # Find header row
    col_map: dict[str, int] | None = None
    for line in data_lines:
        parts = [p.strip() for p in line.split(",")]
        if "_value" in parts and "_time" in parts:
            col_map = {name: idx for idx, name in enumerate(parts)}
            break

    if col_map is None:
        _LOGGER.warning("No header row found in InfluxDB response")
        return pd.DataFrame(columns=["timestamp", "sensor", "value"])

    value_idx = col_map["_value"]
    time_idx = col_map["_time"]
    entity_id_idx = col_map.get("entity_id")
    measurement_idx = col_map.get("_measurement")

    for line in data_lines:
        parts = line.split(",")
        try:
            if len(parts) <= max(value_idx, time_idx):
                continue
            if parts[value_idx].strip() == "_value":
                continue

            # Extract sensor name (same logic as influxdb_helper)
            sensor_name = ""
            if entity_id_idx is not None and entity_id_idx < len(parts):
                entity_val = parts[entity_id_idx].strip()
                if entity_val and entity_val != "entity_id":
                    sensor_name = (
                        entity_val
                        if entity_val.startswith("sensor.")
                        else f"sensor.{entity_val}"
                    )

            if not sensor_name and measurement_idx is not None:
                measurement_val = parts[measurement_idx].strip()
                if measurement_val.startswith("sensor."):
                    sensor_name = measurement_val

            if not sensor_name:
                continue

            timestamp_str = parts[time_idx].strip()
            timestamp = datetime.fromisoformat(
                timestamp_str.replace("Z", "+00:00")
            ).astimezone(local_tz)
            value = float(parts[value_idx].strip())

            rows.append({"timestamp": timestamp, "sensor": sensor_name, "value": value})

        except (IndexError, ValueError):
            continue

    return pd.DataFrame(rows)


def _aggregate_to_quarters(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate raw sensor readings to 15-minute means.

    Takes a long-format DataFrame (timestamp, sensor, value) and returns
    a wide-format DataFrame indexed by quarter-hour timestamp with one
    column per sensor.
    """
    if df.empty:
        return pd.DataFrame()

    # Floor timestamps to 15-minute boundaries
    df = df.copy()
    df["quarter"] = df["timestamp"].dt.floor(f"{QUARTER_HOUR_MINUTES}min")

    # Pivot: each sensor becomes a column, aggregate by mean per quarter
    pivoted = df.pivot_table(
        index="quarter",
        columns="sensor",
        values="value",
        aggfunc="mean",
    )

    # Sort by time
    pivoted = pivoted.sort_index()

    return pivoted


def fetch_training_data(
    config: dict,
    target_date: date | None = None,
) -> pd.DataFrame:
    """Fetch historical sensor data for ML training.

    Queries InfluxDB for the configured number of days of history,
    aggregated to 15-minute intervals.

    Args:
        config: Resolved ML config dict.
        target_date: End date for the training window. Defaults to yesterday.

    Returns:
        Wide-format DataFrame indexed by quarter-hour timestamps,
        with columns for target sensor and each feature sensor.
        Values are raw sensor readings (W for power, °C for temp, etc.).

    Raises:
        RuntimeError: If InfluxDB query fails or returns no data.
    """
    local_tz = _get_local_tz(config)

    if target_date is None:
        target_date = (datetime.now(local_tz) - timedelta(days=1)).date()

    days_of_history = config["training"]["days_of_history"]
    start_date = target_date - timedelta(days=days_of_history)

    # Build list of all sensors to query
    target_sensor = config["target"]["sensor"]
    feature_sensors = list(config["feature_sensors"].values())
    all_sensors = [target_sensor, *feature_sensors]

    _LOGGER.info(
        "Fetching %d days of data (%s to %s) for %d sensors",
        days_of_history,
        start_date,
        target_date,
        len(all_sensors),
    )

    # Build time range
    start_dt = datetime.combine(start_date, datetime.min.time()).replace(
        tzinfo=local_tz
    )
    end_dt = datetime.combine(target_date, datetime.max.time()).replace(tzinfo=local_tz)

    start_str = start_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    sensor_filter = _build_sensor_filter(all_sensors)
    bucket = config["influxdb"]["bucket"]

    # Fetch raw data points; 15-minute aggregation done in Python via _aggregate_to_quarters
    # (InfluxDB 1.x compat mode does not support aggregateWindow)
    flux_query = f"""from(bucket: "{bucket}")
        |> range(start: {start_str}, stop: {end_str})
        |> filter(fn: (r) => {sensor_filter})
        |> filter(fn: (r) => r["_field"] == "value")
        |> sort(columns: ["_time"])
    """

    _LOGGER.info("Executing InfluxDB query for training data...")
    csv_text = _query_influxdb(config, flux_query, timeout=120)

    # Parse CSV to DataFrame
    raw_df = _parse_csv_to_dataframe(csv_text, local_tz)
    _LOGGER.info(
        "Parsed %d raw readings across %d sensors",
        len(raw_df),
        raw_df["sensor"].nunique() if not raw_df.empty else 0,
    )

    if raw_df.empty:
        raise RuntimeError(
            f"No data returned from InfluxDB for sensors {all_sensors} "
            f"between {start_date} and {target_date}"
        )

    # Aggregate to quarter-hourly wide format
    wide_df = _aggregate_to_quarters(raw_df)

    # Rename columns from sensor.xyz to friendly names
    column_renames = {f"sensor.{target_sensor}": "target"}
    for feature_name, sensor_id in config["feature_sensors"].items():
        column_renames[f"sensor.{sensor_id}"] = feature_name

    wide_df = wide_df.rename(columns=column_renames)

    # Forward-fill missing values (sensors may report at different rates)
    wide_df = wide_df.ffill()

    # Drop rows where target is still NaN (beginning of series before first reading)
    wide_df = wide_df.dropna(subset=["target"])

    _LOGGER.info(
        "Training data ready: %d rows, %d columns, date range %s to %s",
        len(wide_df),
        len(wide_df.columns),
        wide_df.index.min(),
        wide_df.index.max(),
    )

    return wide_df


def fetch_recent_data(
    config: dict,
    days: int = 2,
) -> pd.DataFrame:
    """Fetch recent sensor data for prediction context.

    Fetches recent observed data from InfluxDB. Used to compute
    history context features (yesterday's profile, weekly averages).

    Args:
        config: Resolved ML config dict.
        days: Number of days of recent data to fetch.

    Returns:
        Wide-format DataFrame with the same column structure as fetch_training_data.

    Raises:
        RuntimeError: If InfluxDB query fails or returns insufficient data.
    """
    local_tz = _get_local_tz(config)
    target_sensor = config["target"]["sensor"]
    feature_sensors = list(config["feature_sensors"].values())
    all_sensors = [target_sensor, *feature_sensors]

    end_dt = datetime.now(local_tz)
    start_dt = end_dt - timedelta(days=days)

    start_str = start_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    sensor_filter = _build_sensor_filter(all_sensors)
    bucket = config["influxdb"]["bucket"]

    flux_query = f"""from(bucket: "{bucket}")
        |> range(start: {start_str}, stop: {end_str})
        |> filter(fn: (r) => {sensor_filter})
        |> filter(fn: (r) => r["_field"] == "value")
        |> sort(columns: ["_time"])
    """

    _LOGGER.info("Fetching recent data for prediction (%d days)...", days)
    csv_text = _query_influxdb(config, flux_query, timeout=60)

    raw_df = _parse_csv_to_dataframe(csv_text, local_tz)
    if raw_df.empty:
        raise RuntimeError("No recent data returned from InfluxDB")

    wide_df = _aggregate_to_quarters(raw_df)

    # Rename columns
    column_renames = {f"sensor.{target_sensor}": "target"}
    for feature_name, sensor_id in config["feature_sensors"].items():
        column_renames[f"sensor.{sensor_id}"] = feature_name

    wide_df = wide_df.rename(columns=column_renames)
    wide_df = wide_df.ffill()
    wide_df = wide_df.dropna(subset=["target"])

    _LOGGER.info(
        "Recent data: %d rows, date range %s to %s",
        len(wide_df),
        wide_df.index.min(),
        wide_df.index.max(),
    )

    return wide_df


def fetch_weather_forecast(config: dict) -> pd.DataFrame:
    """Fetch hourly weather forecast from Home Assistant and interpolate to 15-min.

    Calls the HA REST API to get weather forecasts, then interpolates
    hourly values to 15-minute periods.

    Args:
        config: Resolved ML config dict with ha_api section.

    Returns:
        DataFrame indexed by 15-minute timestamps with columns:
        temperature, cloud_coverage, wind_speed, precipitation.

    Raises:
        RuntimeError: If the HA API call fails or returns unexpected data.
    """
    ha_cfg = config["ha_api"]
    base_url = ha_cfg["url"].rstrip("/")
    token = ha_cfg["token"]
    weather_entity = ha_cfg["weather_entity"]

    url = f"{base_url}/api/services/weather/get_forecasts?return_response"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "type": "hourly",
        "entity_id": weather_entity,
    }

    _LOGGER.info("Fetching weather forecast from HA (%s)...", weather_entity)
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

    local_tz = _get_local_tz(config)
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

    hourly_df = pd.DataFrame(rows).set_index("datetime").sort_index()

    _LOGGER.info(
        "Weather forecast: %d hourly entries from %s to %s",
        len(hourly_df),
        hourly_df.index.min(),
        hourly_df.index.max(),
    )

    # Interpolate to 15-minute periods
    # Create 15-min index spanning the forecast range
    freq_15min = pd.Timedelta(minutes=QUARTER_HOUR_MINUTES)
    new_index = pd.date_range(
        start=hourly_df.index.min(),
        end=hourly_df.index.max(),
        freq=freq_15min,
    )

    # Reindex and interpolate
    interpolated = hourly_df.reindex(hourly_df.index.union(new_index))

    # Linear interpolation for continuous values
    for col in ["temperature", "wind_speed", "precipitation"]:
        interpolated[col] = interpolated[col].interpolate(method="linear")

    # Forward-fill for cloud_coverage (categorical-like)
    interpolated["cloud_coverage"] = interpolated["cloud_coverage"].ffill()

    # Keep only the 15-min aligned timestamps
    interpolated = interpolated.reindex(new_index)
    interpolated = interpolated.ffill().bfill()

    _LOGGER.info(
        "Interpolated forecast: %d quarter-hourly entries",
        len(interpolated),
    )

    return interpolated


def fetch_history_context(
    config: dict,
    target_date: date | None = None,
) -> dict:
    """Fetch historical consumption context from InfluxDB.

    Queries yesterday's consumption pattern and weekly averages to provide
    context features for prediction. These are computed once and applied
    to all 96 prediction periods.

    Args:
        config: Resolved ML config dict.
        target_date: The date we're predicting for. Defaults to today.

    Returns:
        Dict with keys:
        - yesterday_profile: list of 96 floats (kWh per 15min for yesterday)
        - yesterday_total: float (total kWh yesterday)
        - week_avg_profile: list of 96 floats (average kWh per 15min over past 7 days)
        - recent_24h_mean: float (mean kWh per 15min over last 24h)

    Raises:
        RuntimeError: If InfluxDB query fails.
    """
    local_tz = _get_local_tz(config)

    if target_date is None:
        target_date = datetime.now(local_tz).date()

    target_sensor = config["target"]["sensor"]
    watts_to_kwh_15min = 1.0 / (4 * 1000)

    # Fetch 8 days of target sensor data (7 full days + buffer)
    start_date = target_date - timedelta(days=8)
    start_dt = datetime.combine(start_date, datetime.min.time()).replace(
        tzinfo=local_tz
    )
    end_dt = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=local_tz)

    start_str = start_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    sensor_filter = _build_sensor_filter([target_sensor])
    bucket = config["influxdb"]["bucket"]

    flux_query = f"""from(bucket: "{bucket}")
        |> range(start: {start_str}, stop: {end_str})
        |> filter(fn: (r) => {sensor_filter})
        |> filter(fn: (r) => r["_field"] == "value")
        |> sort(columns: ["_time"])
    """

    _LOGGER.info("Fetching history context (8 days ending %s)...", target_date)
    csv_text = _query_influxdb(config, flux_query, timeout=60)

    raw_df = _parse_csv_to_dataframe(csv_text, local_tz)
    if raw_df.empty:
        raise RuntimeError("No history context data returned from InfluxDB")

    wide_df = _aggregate_to_quarters(raw_df)

    # Get the target column (may be sensor.xyz format)
    target_col = f"sensor.{target_sensor}"
    if target_col not in wide_df.columns:
        raise RuntimeError(
            f"Target sensor column '{target_col}' not found in history data. "
            f"Available columns: {list(wide_df.columns)}"
        )

    consumption = wide_df[target_col].ffill()

    # Convert W to kWh/15min
    if config["target"].get("unit") == "W":
        consumption = consumption * watts_to_kwh_15min

    # Yesterday's profile (96 values)
    yesterday = target_date - timedelta(days=1)
    yesterday_mask = consumption.index.date == yesterday
    yesterday_data = consumption[yesterday_mask]

    yesterday_profile = [0.0] * PERIODS_PER_DAY
    yesterday_total = 0.0
    if not yesterday_data.empty:
        for i, val in enumerate(yesterday_data.values[:PERIODS_PER_DAY]):
            yesterday_profile[i] = float(val)
        yesterday_total = sum(yesterday_profile)

    _LOGGER.info(
        "Yesterday (%s): %d periods, total %.2f kWh",
        yesterday,
        sum(1 for v in yesterday_profile if v > 0),
        yesterday_total,
    )

    # Weekly average profile (96 values averaged across 7 days)
    week_start = target_date - timedelta(days=7)
    week_profiles: list[list[float]] = []

    for days_back in range(1, 8):
        day = target_date - timedelta(days=days_back)
        day_mask = consumption.index.date == day
        day_data = consumption[day_mask]
        if len(day_data) >= PERIODS_PER_DAY // 2:  # At least half a day
            profile = [0.0] * PERIODS_PER_DAY
            for i, val in enumerate(day_data.values[:PERIODS_PER_DAY]):
                profile[i] = float(val)
            week_profiles.append(profile)

    if week_profiles:
        week_avg_profile = [
            sum(p[i] for p in week_profiles) / len(week_profiles)
            for i in range(PERIODS_PER_DAY)
        ]
    else:
        week_avg_profile = yesterday_profile.copy()

    _LOGGER.info(
        "Weekly average: computed from %d days (%s to %s)",
        len(week_profiles),
        week_start,
        target_date - timedelta(days=1),
    )

    # Recent 24h mean
    recent_24h = consumption.tail(PERIODS_PER_DAY)
    recent_24h_mean = float(recent_24h.mean()) if not recent_24h.empty else 0.0

    _LOGGER.info("Recent 24h mean: %.4f kWh/15min", recent_24h_mean)

    return {
        "yesterday_profile": yesterday_profile,
        "yesterday_total": yesterday_total,
        "week_avg_profile": week_avg_profile,
        "recent_24h_mean": recent_24h_mean,
    }
