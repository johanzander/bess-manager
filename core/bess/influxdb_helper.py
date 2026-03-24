"""Provides helper functions to interact with InfluxDB for fetching sensor data.

The module includes functionality to parse responses, handle timezones, and process sensor readings.
This module is designed to run within either the Pyscript environment or a standard Python environment.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from core.bess import time_utils

_LOGGER = logging.getLogger(__name__)


def get_influxdb_config():
    """Load InfluxDB config with environment variable precedence.

    Configuration priority (highest to lowest):
    1. Environment variables (HA_DB_URL, HA_DB_BUCKET, HA_DB_USER_NAME, HA_DB_PASSWORD)
    2. /data/options.json influxdb section

    This supports both environments:
    - Production: Reads from /data/options.json (configured via HA UI)
    - Development: Environment variables override (from .env, keeps secrets out of git)

    Returns:
        dict: Configuration with url, bucket, username, and password keys

    Raises:
        KeyError: If configuration is incomplete from all sources
        FileNotFoundError: If options.json doesn't exist and env vars not set
    """
    # Check environment variables first (highest priority - development override)
    url = os.getenv("HA_DB_URL")
    bucket = os.getenv("HA_DB_BUCKET")
    username = os.getenv("HA_DB_USER_NAME")
    password = os.getenv("HA_DB_PASSWORD")

    # If all environment variables are set, use them
    if url and username and password and bucket:
        _LOGGER.debug("Loaded InfluxDB config from environment variables")
        return {
            "url": url,
            "username": username,
            "password": password,
            "bucket": bucket,
        }

    # Otherwise, read from options.json (production path)
    with open("/data/options.json") as f:
        options = json.load(f)

    influxdb = options["influxdb"]
    _LOGGER.debug("Loaded InfluxDB config from options.json")

    return {
        "url": influxdb.get("url", ""),
        "username": influxdb.get("username", ""),
        "password": influxdb.get("password", ""),
        "bucket": influxdb.get("bucket", ""),
    }


def test_influxdb_connection() -> dict:
    """Test InfluxDB connectivity and bucket configuration.

    Fetches a single row from the bucket without filtering by sensor name,
    so the result is independent of which sensors are configured.

    Returns:
        dict: {"status": "ok" | "misconfigured" | "error", "message": str}
    """
    config = get_influxdb_config()
    url = config["url"]
    bucket = config["bucket"]
    username = config["username"]
    password = config["password"]

    if not url or not username or not password or not bucket:
        return {"status": "error", "message": "Incomplete InfluxDB configuration"}

    flux_query = f"""from(bucket: "{bucket}")
  |> range(start: -24h)
  |> limit(n: 1)
"""
    headers = {"Content-type": "application/vnd.flux", "Accept": "application/csv"}

    try:
        response = requests.post(
            url=url,
            auth=(username, password),
            headers=headers,
            data=flux_query,
            timeout=10,
        )

        if response.status_code != 200:
            return {
                "status": "error",
                "message": f"InfluxDB returned HTTP {response.status_code}",
            }

        has_valid_csv = "_value" in response.text and "_time" in response.text
        if has_valid_csv:
            return {"status": "ok", "message": "InfluxDB connection successful"}

        return {
            "status": "misconfigured",
            "message": (
                f"InfluxDB responded (HTTP 200) but returned no valid data. "
                f"Current bucket: '{bucket}'. "
                f"For InfluxDB 1.x, the bucket must be set to '<database>/autogen' "
                f"(e.g. 'homeassistant/autogen'). "
                f"Also verify the username has read access to the database."
            ),
        }

    except requests.RequestException as e:
        return {"status": "error", "message": f"Connection error: {e!s}"}


def get_sensor_data(sensors_list, start_time=None, stop_time=None) -> dict:
    """Get sensor data with configurable time range.

    Args:
        sensors_list: List of sensor names to query
        start_time: Start time for the query (defaults to 24h before stop_time)
        stop_time: End time for the query (defaults to now)

    Returns:
        dict: Query results with status and data
    """
    # Set up timezone
    local_tz = time_utils.TIMEZONE

    # Determine stop time
    if stop_time is None:
        stop_time = datetime.now(local_tz)
    elif stop_time.tzinfo is None:
        stop_time = stop_time.replace(tzinfo=local_tz)

    # Determine start time - default to 24h before stop time
    if start_time is None:
        start_time = stop_time - timedelta(hours=24)
        _LOGGER.debug("Using default 24-hour window")
    elif start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=local_tz)

    # Get configuration
    influxdb_config = get_influxdb_config()
    url = influxdb_config["url"]
    bucket = influxdb_config["bucket"]
    username = influxdb_config["username"]
    password = influxdb_config["password"]

    # Validate required configuration
    if not url or not username or not password:
        _LOGGER.error(
            "InfluxDB configuration is incomplete. URL: %s, Username: %s",
            url,
            username,
        )
        return {"status": "error", "message": "Incomplete InfluxDB configuration"}

    headers = {
        "Content-type": "application/vnd.flux",
        "Accept": "application/csv",
    }

    # Format times for InfluxDB query
    start_str = start_time.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = stop_time.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build sensor filter compatible with both InfluxDB 1.x and 2.x:
    # - InfluxDB 2.x: _measurement contains the full entity_id (e.g. "sensor.xyz_...")
    # - InfluxDB 1.x: _measurement contains the unit (e.g. "%", "W"),
    #   entity_id tag stores the short name without domain prefix (e.g. "xyz_...")
    sensor_conditions = []
    for sensor in sensors_list:
        sensor_conditions.append(
            f'r["_measurement"] == "sensor.{sensor}" or r["entity_id"] == "{sensor}"'
        )
    sensor_filter = " or ".join(f"({c})" for c in sensor_conditions)

    # Time-bounded query (always uses range since we always have start_time)
    flux_query = f"""from(bucket: "{bucket}")
                    |> range(start: {start_str}, stop: {end_str})
                    |> filter(fn: (r) => {sensor_filter})
                    |> filter(fn: (r) => r["_field"] == "value")
                    |> last()
                    """

    try:
        # Use the environment-aware executor to make the request
        response = requests.post(
            url=url,
            auth=(username, password),
            headers=headers,
            data=flux_query,
            timeout=10,
        )

        if response.status_code == 204:
            _LOGGER.warning("No data found for the requested sensors")
            return {"status": "error", "message": "No data found"}

        if response.status_code != 200:
            _LOGGER.error("Error from InfluxDB: %s", response.status_code)
            return {
                "status": "error",
                "message": f"InfluxDB error: {response.status_code}",
            }

        sensor_readings = parse_influxdb_response(response.text)
        has_valid_csv = "_value" in response.text and "_time" in response.text
        return {
            "status": "success",
            "data": sensor_readings,
            "has_valid_csv": has_valid_csv,
        }

    except requests.RequestException as e:
        _LOGGER.error("Error connecting to InfluxDB: %s", str(e))
        return {"status": "error", "message": f"Connection error: {e!s}"}
    except Exception as e:
        _LOGGER.error("Unexpected error: %s", str(e))
        return {"status": "error", "message": f"Unexpected error: {e!s}"}


def _build_column_index(data_lines: list[str]) -> dict[str, int] | None:
    """Find the header row in CSV data lines and return a column name-to-index map.

    The header row is the first non-empty line that contains known InfluxDB column
    names like '_value' and '_time'. Returns None if no header row is found.
    """
    for line in data_lines:
        parts = [p.strip() for p in line.split(",")]
        if "_value" in parts and "_time" in parts:
            return {name: idx for idx, name in enumerate(parts)}
    return None


def _extract_sensor_name(parts: list[str], col_map: dict[str, int]) -> str:
    """Extract the sensor entity_id from a CSV row, supporting both InfluxDB versions.

    InfluxDB 2.x stores the full entity_id (e.g. "sensor.xyz_...") in _measurement.
    InfluxDB 1.x stores the short name without domain prefix (e.g. "xyz_...") in the
    entity_id tag column, with the domain ("sensor") in a separate domain tag.

    Returns a normalized name always prefixed with "sensor." so downstream consumers
    (e.g. _normalize_sensor_readings) can consistently strip the prefix.
    """
    entity_id_idx = col_map.get("entity_id")
    measurement_idx = col_map.get("_measurement")

    # Prefer entity_id tag if present and non-empty
    if entity_id_idx is not None and entity_id_idx < len(parts):
        entity_val = parts[entity_id_idx].strip()
        if entity_val:
            # InfluxDB 2.x: already has "sensor." prefix
            if entity_val.startswith("sensor."):
                return entity_val
            # InfluxDB 1.x: short name without prefix — normalize it
            if entity_val and entity_val != "entity_id":
                return f"sensor.{entity_val}"

    # Fall back to _measurement (InfluxDB 2.x stores entity_id here)
    if measurement_idx is not None and measurement_idx < len(parts):
        measurement_val = parts[measurement_idx].strip()
        if measurement_val.startswith("sensor."):
            return measurement_val

    return ""


def parse_influxdb_response(response_text) -> dict:
    """Parse InfluxDB response to extract the latest measurement for each sensor.

    Uses header-aware column detection to support both InfluxDB 1.x and 2.x,
    where columns may appear at different positions depending on the tag set.
    """
    readings = {}
    lines = response_text.strip().split("\n")

    # Skip metadata rows (lines starting with '#')
    data_lines = [line for line in lines if not line.startswith("#")]

    col_map = _build_column_index(data_lines)
    if col_map is None:
        _LOGGER.warning("No header row found in InfluxDB response")
        return readings

    value_idx = col_map["_value"]

    # Process each data line (skip the header row itself)
    for line in data_lines:
        parts = line.split(",")
        try:
            # Skip header row and short lines
            if len(parts) <= value_idx or parts[value_idx].strip() == "_value":
                continue

            sensor_name = _extract_sensor_name(parts, col_map)
            if not sensor_name:
                continue

            value = float(parts[value_idx].strip())
            readings[sensor_name] = value
        except (IndexError, ValueError) as e:
            _LOGGER.error("Failed to parse line: %s, error: %s", line, e)
            continue

    _LOGGER.debug("Parsed response: %s", readings)
    return readings


def get_sensor_data_batch(sensors_list, target_date) -> dict:
    """Fetch all 96 periods of sensor data for a given date in a single query.

    This is dramatically faster than making 96+ individual queries.

    Args:
        sensors_list: List of sensor names to query
        target_date: Date to fetch data for (datetime.date or datetime)

    Returns:
        dict: {
            "status": "success" or "error",
            "message": error message if status is "error",
            "data": {
                0: {sensor1: value, sensor2: value, ...},  # Period 0 (00:00-00:14)
                1: {...},  # Period 1 (00:15-00:29)
                ...
                95: {...}  # Period 95 (23:45-23:59)
            }
        }
    """
    local_tz = time_utils.TIMEZONE

    # Convert target_date to datetime if it's a date
    if isinstance(target_date, datetime):
        target_date = target_date.date()

    # Create start and end times for the full day
    start_datetime = datetime.combine(target_date, datetime.min.time()).replace(
        tzinfo=local_tz
    )
    end_datetime = datetime.combine(target_date, datetime.max.time()).replace(
        tzinfo=local_tz
    )

    # Get configuration
    influxdb_config = get_influxdb_config()
    url = influxdb_config["url"]
    bucket = influxdb_config["bucket"]
    username = influxdb_config["username"]
    password = influxdb_config["password"]

    if not url or not username or not password or not bucket:
        _LOGGER.error("InfluxDB configuration is incomplete")
        return {"status": "error", "message": "Incomplete InfluxDB configuration"}

    headers = {
        "Content-type": "application/vnd.flux",
        "Accept": "application/csv",
    }

    # Format times for InfluxDB query (UTC)
    start_str = start_datetime.astimezone(ZoneInfo("UTC")).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    end_str = end_datetime.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build sensor filter compatible with both InfluxDB 1.x and 2.x:
    # - InfluxDB 2.x: _measurement contains the full entity_id (e.g. "sensor.xyz_...")
    # - InfluxDB 1.x: _measurement contains the unit (e.g. "%", "W"),
    #   entity_id tag stores the short name without domain prefix (e.g. "xyz_...")
    sensor_conditions = []
    for sensor in sensors_list:
        sensor_conditions.append(
            f'r["_measurement"] == "sensor.{sensor}" or r["entity_id"] == "{sensor}"'
        )
    sensor_filter = " or ".join(f"({c})" for c in sensor_conditions)

    # Batch query: Get ALL data points, then for each period we'll find the last value
    # BEFORE that period's end time (same logic as individual queries for sparse data).
    flux_query = f"""from(bucket: "{bucket}")
                    |> range(start: {start_str}, stop: {end_str})
                    |> filter(fn: (r) => {sensor_filter})
                    |> filter(fn: (r) => r["_field"] == "value")
                    |> sort(columns: ["_time"])
                    """

    try:
        _LOGGER.info(
            "Batch fetching sensor data for %s (%d sensors, 96 periods)",
            target_date.strftime("%Y-%m-%d"),
            len(sensors_list),
        )
        _LOGGER.info("Querying sensors: %s", sensors_list)

        response = requests.post(
            url=url,
            auth=(username, password),
            headers=headers,
            data=flux_query,
            timeout=30,  # Increased timeout for larger query
        )

        if response.status_code == 204:
            _LOGGER.warning("No data found for date %s", target_date)
            return {"status": "error", "message": "No data found"}

        if response.status_code != 200:
            _LOGGER.error("Error from InfluxDB: %s", response.status_code)
            return {
                "status": "error",
                "message": f"InfluxDB error: {response.status_code}",
            }

        # Log first few lines of response for debugging
        response_lines = response.text.strip().split("\n")
        _LOGGER.info("InfluxDB returned %d lines total", len(response_lines))
        data_lines = [line for line in response_lines if not line.startswith("#")]
        _LOGGER.info("InfluxDB returned %d data lines (non-header)", len(data_lines))

        # Log unique sensors found using header-aware column detection
        col_map = _build_column_index(data_lines)
        measurements = {}
        if col_map is not None:
            value_idx = col_map["_value"]
            for line in data_lines:
                parts = line.split(",")
                if len(parts) <= value_idx or parts[value_idx].strip() == "_value":
                    continue
                sensor = _extract_sensor_name(parts, col_map)
                if sensor:
                    measurements[sensor] = measurements.get(sensor, 0) + 1
        _LOGGER.info("Sensor counts in response: %s", measurements)
        if not measurements and data_lines:
            _LOGGER.warning(
                "Zero sensors found. First 3 data lines: %s", data_lines[:3]
            )

        # Parse the batch response
        period_data = _parse_batch_response(
            response.text, target_date, local_tz, sensors_list
        )

        _LOGGER.info("Batch fetch complete: got data for %d periods", len(period_data))

        # Debug: log which periods we got
        if period_data:
            periods = sorted(period_data.keys())
            _LOGGER.info(
                "Periods found in batch: %s...%s (total: %d)",
                periods[:5] if len(periods) > 5 else periods,
                periods[-5:] if len(periods) > 5 else [],
                len(periods),
            )
            # Log sensor counts for first few periods
            for p in periods[:3]:
                sensors = list(period_data[p].keys())
                _LOGGER.info(
                    "Period %d has %d sensors: %s",
                    p,
                    len(sensors),
                    sensors[:5] if len(sensors) > 5 else sensors,
                )

        return {"status": "success", "data": period_data}

    except requests.RequestException as e:
        _LOGGER.error("Error connecting to InfluxDB: %s", str(e))
        return {"status": "error", "message": f"Connection error: {e!s}"}
    except Exception as e:
        _LOGGER.error("Unexpected error in batch fetch: %s", str(e))
        return {"status": "error", "message": f"Unexpected error: {e!s}"}


def _parse_batch_response(
    response_text, target_date, local_tz, sensors_list
) -> dict[int, dict[str, float]]:
    """Parse batch InfluxDB response and group by period number.

    For sparse data (like SOC sensor), this finds the last value BEFORE each period boundary,
    mimicking how individual queries work with last().

    Args:
        response_text: CSV response from InfluxDB
        target_date: The date being queried
        local_tz: Local timezone for period calculation
        sensors_list: List of sensor names being queried

    Returns:
        dict: {period_num: {sensor_name: value, ...}, ...}
    """
    lines = response_text.strip().split("\n")
    data_lines = [line for line in lines if not line.startswith("#")]

    col_map = _build_column_index(data_lines)
    if col_map is None:
        _LOGGER.warning("No header row found in batch InfluxDB response")
        return {}

    value_idx = col_map["_value"]
    time_idx = col_map["_time"]

    # Step 1: Parse all data points grouped by sensor
    sensor_data = {}  # {sensor_name: [(timestamp, value), ...]}

    for line in data_lines:
        parts = line.split(",")
        try:
            if (
                len(parts) <= max(value_idx, time_idx)
                or parts[value_idx].strip() == "_value"
            ):
                continue

            timestamp_str = parts[time_idx].strip()
            sensor_name = _extract_sensor_name(parts, col_map)
            if not sensor_name:
                continue
            value = float(parts[value_idx].strip())

            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            timestamp_local = timestamp.astimezone(local_tz)

            if sensor_name not in sensor_data:
                sensor_data[sensor_name] = []
            sensor_data[sensor_name].append((timestamp_local, value))

        except (IndexError, ValueError, TypeError):
            continue

    # Step 2: Sort data points by timestamp for each sensor
    for sensor in sensor_data:
        sensor_data[sensor].sort(key=lambda x: x[0])

    # Step 2.5: For sensors with sparse data, fetch the last known value from before the day started
    # This mimics the behavior of individual queries with last() which look at ALL historical data
    day_start = datetime.combine(target_date, datetime.min.time()).replace(
        tzinfo=local_tz
    )

    # Collect all sensors that need initial values first (batch them)
    sensors_needing_initial_values = []

    for sensor_name in sensors_list:
        # Check if sensor needs initial value from previous day
        # sensor_data keys are prefixed with "sensor." (from _extract_sensor_name),
        # but sensors_list contains entity IDs without prefix
        prefixed_name = f"sensor.{sensor_name}"
        needs_initial_value = False

        if prefixed_name not in sensor_data or not sensor_data[prefixed_name]:
            # Sensor has no data at all for this day
            needs_initial_value = True
            _LOGGER.debug(
                "Sensor %s has no data for %s, will fetch initial value",
                sensor_name,
                target_date,
            )
        else:
            # Sensor has data, but check if first data point is after day start
            first_timestamp = sensor_data[prefixed_name][0][0]
            if first_timestamp > day_start:
                needs_initial_value = True
                _LOGGER.debug(
                    "Sensor %s first data at %s (after day start), will fetch initial value",
                    sensor_name,
                    first_timestamp,
                )

        if needs_initial_value:
            sensors_needing_initial_values.append(sensor_name)

    # Batch fetch all initial values in a single query
    if sensors_needing_initial_values:
        _LOGGER.info(
            "Batch fetching initial values for %d sensors",
            len(sensors_needing_initial_values),
        )
        result = get_sensor_data(
            sensors_needing_initial_values, stop_time=day_start - timedelta(seconds=1)
        )

        if result.get("status") == "success" and result.get("data"):
            for sensor_name in sensors_needing_initial_values:
                sensor_value = result["data"].get(f"sensor.{sensor_name}") or result[
                    "data"
                ].get(sensor_name)
                if sensor_value is not None:
                    _LOGGER.debug(
                        "Found initial value for %s: %.2f (from before %s)",
                        sensor_name,
                        sensor_value,
                        target_date,
                    )
                    # Add this as a data point just before the day started
                    # Use prefixed name to match sensor_data keys from _extract_sensor_name
                    prefixed_name = f"sensor.{sensor_name}"
                    initial_datapoint = (day_start - timedelta(seconds=1), sensor_value)
                    if prefixed_name in sensor_data:
                        # Prepend to existing data
                        sensor_data[prefixed_name].insert(0, initial_datapoint)
                    else:
                        # Create new list with just this initial value
                        sensor_data[prefixed_name] = [initial_datapoint]

    # Step 3: For each period, find last value BEFORE period end time
    period_data = {}
    day_start = datetime.combine(target_date, datetime.min.time()).replace(
        tzinfo=local_tz
    )

    for period in range(96):
        # Calculate period end time (e.g., period 0 ends at 00:14:59)
        period_end = day_start + timedelta(minutes=(period + 1) * 15 - 1, seconds=59)

        period_data[period] = {}

        for sensor_name, data_points in sensor_data.items():
            # Find last data point with timestamp <= period_end
            last_value = None
            for timestamp, value in data_points:
                if timestamp <= period_end:
                    last_value = value
                else:
                    break  # Data is sorted, no need to continue

            if last_value is not None:
                period_data[period][sensor_name] = last_value

    # Remove empty periods
    period_data = {p: data for p, data in period_data.items() if data}

    _LOGGER.debug(
        "Parsed %d sensors with data for %d periods", len(sensor_data), len(period_data)
    )

    return period_data


def get_power_sensor_data_batch(power_sensors: list[str], target_date) -> dict:
    """Fetch average power (W) per period and convert to energy (kWh).

    Power sensors report instantaneous wattage every ~5 minutes. By averaging
    all readings within each 15-minute period and converting W -> kWh, we get
    much higher resolution than cumulative energy sensors (which only increment
    in 0.1 kWh steps).

    Args:
        power_sensors: List of power sensor entity IDs (without 'sensor.' prefix)
        target_date: Date to fetch data for (datetime.date or datetime)

    Returns:
        dict: {
            "status": "success" or "error",
            "message": error message if status is "error",
            "data": {
                0: {sensor1: avg_kwh, sensor2: avg_kwh, ...},
                ...
                95: {...}
            }
        }
    """
    local_tz = time_utils.TIMEZONE

    if isinstance(target_date, datetime):
        target_date = target_date.date()

    start_datetime = datetime.combine(target_date, datetime.min.time()).replace(
        tzinfo=local_tz
    )
    end_datetime = datetime.combine(target_date, datetime.max.time()).replace(
        tzinfo=local_tz
    )

    influxdb_config = get_influxdb_config()
    url = influxdb_config["url"]
    bucket = influxdb_config["bucket"]
    username = influxdb_config["username"]
    password = influxdb_config["password"]

    if not url or not username or not password or not bucket:
        _LOGGER.error("InfluxDB configuration is incomplete")
        return {"status": "error", "message": "Incomplete InfluxDB configuration"}

    headers = {
        "Content-type": "application/vnd.flux",
        "Accept": "application/csv",
    }

    start_str = start_datetime.astimezone(ZoneInfo("UTC")).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    end_str = end_datetime.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build sensor filter for power sensors (W measurement)
    sensor_conditions = []
    for sensor in power_sensors:
        sensor_conditions.append(
            f'r["_measurement"] == "sensor.{sensor}" or r["entity_id"] == "{sensor}"'
        )
    sensor_filter = " or ".join(f"({c})" for c in sensor_conditions)

    flux_query = f"""from(bucket: "{bucket}")
                    |> range(start: {start_str}, stop: {end_str})
                    |> filter(fn: (r) => {sensor_filter})
                    |> filter(fn: (r) => r["_field"] == "value")
                    |> sort(columns: ["_time"])
                    """

    try:
        _LOGGER.info(
            "Batch fetching power sensor data for %s (%d sensors)",
            target_date.strftime("%Y-%m-%d"),
            len(power_sensors),
        )

        response = requests.post(
            url=url,
            auth=(username, password),
            headers=headers,
            data=flux_query,
            timeout=30,
        )

        if response.status_code == 204:
            _LOGGER.warning("No power sensor data found for date %s", target_date)
            return {"status": "error", "message": "No data found"}

        if response.status_code != 200:
            _LOGGER.error("Error from InfluxDB: %s", response.status_code)
            return {
                "status": "error",
                "message": f"InfluxDB error: {response.status_code}",
            }

        period_data = _parse_power_batch_response(response.text, target_date, local_tz)

        _LOGGER.info(
            "Power sensor batch complete: got data for %d periods", len(period_data)
        )

        return {"status": "success", "data": period_data}

    except requests.RequestException as e:
        _LOGGER.error("Error connecting to InfluxDB for power sensors: %s", str(e))
        return {"status": "error", "message": f"Connection error: {e!s}"}
    except Exception as e:
        _LOGGER.error("Unexpected error in power sensor batch fetch: %s", str(e))
        return {"status": "error", "message": f"Unexpected error: {e!s}"}


def _parse_power_batch_response(
    response_text: str, target_date, local_tz
) -> dict[int, dict[str, float]]:
    """Parse power sensor response: compute mean W per period, convert to kWh.

    For each 15-minute period, averages all power readings within that period
    and converts: kWh = mean_watts * (15/60) / 1000

    Args:
        response_text: CSV response from InfluxDB
        target_date: The date being queried
        local_tz: Local timezone

    Returns:
        dict: {period_num: {"sensor.entity_id": kwh_value, ...}, ...}
    """
    lines = response_text.strip().split("\n")
    data_lines = [line for line in lines if not line.startswith("#")]

    col_map = _build_column_index(data_lines)
    if col_map is None:
        _LOGGER.warning("No header row found in power sensor batch response")
        return {}

    value_idx = col_map["_value"]
    time_idx = col_map["_time"]

    day_start = datetime.combine(target_date, datetime.min.time()).replace(
        tzinfo=local_tz
    )

    # Collect readings per sensor per period: {sensor: {period: [values]}}
    sensor_period_readings: dict[str, dict[int, list[float]]] = {}

    for line in data_lines:
        parts = line.split(",")
        try:
            if (
                len(parts) <= max(value_idx, time_idx)
                or parts[value_idx].strip() == "_value"
            ):
                continue

            timestamp_str = parts[time_idx].strip()
            sensor_name = _extract_sensor_name(parts, col_map)
            if not sensor_name:
                continue
            value = float(parts[value_idx].strip())

            # Skip clearly bogus values (e.g. the output_power 429496663.7 overflow)
            if abs(value) > 100000:
                continue

            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            timestamp_local = timestamp.astimezone(local_tz)

            # Calculate which period this reading belongs to
            seconds_since_start = (timestamp_local - day_start).total_seconds()
            if seconds_since_start < 0 or seconds_since_start >= 86400:
                continue
            period = int(seconds_since_start // 900)  # 900 seconds = 15 minutes

            if sensor_name not in sensor_period_readings:
                sensor_period_readings[sensor_name] = {}
            if period not in sensor_period_readings[sensor_name]:
                sensor_period_readings[sensor_name][period] = []
            sensor_period_readings[sensor_name][period].append(value)

        except (IndexError, ValueError, TypeError):
            continue

    # Convert mean W to kWh per period (15 min = 0.25 hours)
    period_data: dict[int, dict[str, float]] = {}
    for sensor_name, periods in sensor_period_readings.items():
        for period, values in periods.items():
            mean_watts = sum(values) / len(values)
            kwh = mean_watts * 0.25 / 1000.0  # W * hours / 1000 = kWh

            if period not in period_data:
                period_data[period] = {}
            period_data[period][sensor_name] = kwh

    _LOGGER.debug(
        "Parsed power data: %d sensors across %d periods",
        len(sensor_period_readings),
        len(period_data),
    )

    return period_data
