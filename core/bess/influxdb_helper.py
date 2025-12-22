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

_LOGGER = logging.getLogger(__name__)


def get_influxdb_config():
    """Load InfluxDB config with environment variable precedence.

    Configuration priority (highest to lowest):
    1. Environment variables (HA_DB_URL, HA_DB_USER_NAME, HA_DB_PASSWORD)
    2. /data/options.json influxdb section

    This supports both environments:
    - Production: Reads from /data/options.json (configured via HA UI)
    - Development: Environment variables override (from .env, keeps secrets out of git)

    Returns:
        dict: Configuration with url, username, and password keys

    Raises:
        KeyError: If configuration is incomplete from all sources
        FileNotFoundError: If options.json doesn't exist and env vars not set
    """
    # Check environment variables first (highest priority - development override)
    url = os.getenv("HA_DB_URL")
    username = os.getenv("HA_DB_USER_NAME")
    password = os.getenv("HA_DB_PASSWORD")

    # If all environment variables are set, use them
    if url and username and password:
        _LOGGER.debug("Loaded InfluxDB config from environment variables")
        return {
            "url": url,
            "username": username,
            "password": password,
        }

    # Otherwise, read from options.json (production path)
    with open("/data/options.json") as f:
        options = json.load(f)

    influxdb = options["influxdb"]
    _LOGGER.debug("Loaded InfluxDB config from options.json")

    return {
        "url": influxdb["url"],
        "username": influxdb["username"],
        "password": influxdb["password"],
    }


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
    local_tz = ZoneInfo("Europe/Stockholm")

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

    url = influxdb_config.get("url", "")
    username = influxdb_config.get("username", "")
    password = influxdb_config.get("password", "")

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

    sensor_filter = " or ".join(
        [f'r["_measurement"] == "sensor.{sensor}"' for sensor in sensors_list]
    )

    # Time-bounded query (always uses range since we always have start_time)
    flux_query = f"""from(bucket: "home_assistant/autogen")
                    |> range(start: {start_str}, stop: {end_str})
                    |> filter(fn: (r) => {sensor_filter})
                    |> filter(fn: (r) => r["_field"] == "value")
                    |> filter(fn: (r) => r["domain"] == "sensor")
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
        return {"status": "success", "data": sensor_readings}

    except requests.RequestException as e:
        _LOGGER.error("Error connecting to InfluxDB: %s", str(e))
        return {"status": "error", "message": f"Connection error: {e!s}"}
    except Exception as e:
        _LOGGER.error("Unexpected error: %s", str(e))
        return {"status": "error", "message": f"Unexpected error: {e!s}"}


def parse_influxdb_response(response_text) -> dict:
    """Parse InfluxDB response to extract the latest measurement for each sensor."""
    readings = {}
    lines = response_text.strip().split("\n")

    # Skip metadata rows (lines starting with '#')
    data_lines = [line for line in lines if not line.startswith("#")]

    # Process each data line
    for line in data_lines:
        parts = line.split(",")
        try:
            # Ensure the line has enough parts and the value can be converted to float
            if len(parts) < 9 or parts[6] == "_value":
                continue

            # Extract sensor name (_measurement) and value (_value)
            sensor_name = parts[
                10
            ].strip()  # _measurement is the 11th column (index 10)
            value = float(parts[6].strip())  # _value is the 7th column (index 6)

            # Store the value in the readings dictionary with the sensor name
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
    local_tz = ZoneInfo("Europe/Stockholm")

    # Convert target_date to datetime if it's a date
    if isinstance(target_date, datetime):
        target_date = target_date.date()

    # Create start and end times for the full day
    start_datetime = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=local_tz)
    end_datetime = datetime.combine(target_date, datetime.max.time()).replace(tzinfo=local_tz)

    # Get configuration
    influxdb_config = get_influxdb_config()
    url = influxdb_config.get("url", "")
    username = influxdb_config.get("username", "")
    password = influxdb_config.get("password", "")

    if not url or not username or not password:
        _LOGGER.error("InfluxDB configuration is incomplete")
        return {"status": "error", "message": "Incomplete InfluxDB configuration"}

    headers = {
        "Content-type": "application/vnd.flux",
        "Accept": "application/csv",
    }

    # Format times for InfluxDB query (UTC)
    start_str = start_datetime.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end_datetime.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

    sensor_filter = " or ".join(
        [f'r["_measurement"] == "sensor.{sensor}"' for sensor in sensors_list]
    )

    # Batch query: Get ALL data points, then for each period we'll find the last value
    # BEFORE that period's end time (same logic as individual queries for sparse data)
    flux_query = f"""from(bucket: "home_assistant/autogen")
                    |> range(start: {start_str}, stop: {end_str})
                    |> filter(fn: (r) => {sensor_filter})
                    |> filter(fn: (r) => r["_field"] == "value")
                    |> filter(fn: (r) => r["domain"] == "sensor")
                    |> sort(columns: ["_time"])
                    """

    try:
        _LOGGER.info(
            "Batch fetching sensor data for %s (%d sensors, 96 periods)",
            target_date.strftime("%Y-%m-%d"),
            len(sensors_list)
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

        # Log unique measurements to see what sensors we got
        measurements = {}
        for line in data_lines:
            parts = line.split(",")
            if len(parts) > 10 and parts[10] != "entity_id" and parts[6] != "_value":
                sensor = parts[10].strip()
                measurements[sensor] = measurements.get(sensor, 0) + 1
        _LOGGER.info("Sensor counts in response: %s", measurements)

        # Parse the batch response
        period_data = _parse_batch_response(response.text, target_date, local_tz, sensors_list)

        _LOGGER.info(
            "Batch fetch complete: got data for %d periods",
            len(period_data)
        )

        # Debug: log which periods we got
        if period_data:
            periods = sorted(period_data.keys())
            _LOGGER.info(
                "Periods found in batch: %s...%s (total: %d)",
                periods[:5] if len(periods) > 5 else periods,
                periods[-5:] if len(periods) > 5 else [],
                len(periods)
            )
            # Log sensor counts for first few periods
            for p in periods[:3]:
                sensors = list(period_data[p].keys())
                _LOGGER.info(
                    "Period %d has %d sensors: %s",
                    p,
                    len(sensors),
                    sensors[:5] if len(sensors) > 5 else sensors
                )

        return {"status": "success", "data": period_data}

    except requests.RequestException as e:
        _LOGGER.error("Error connecting to InfluxDB: %s", str(e))
        return {"status": "error", "message": f"Connection error: {e!s}"}
    except Exception as e:
        _LOGGER.error("Unexpected error in batch fetch: %s", str(e))
        return {"status": "error", "message": f"Unexpected error: {e!s}"}


def _parse_batch_response(response_text, target_date, local_tz, sensors_list) -> dict[int, dict[str, float]]:
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

    # Step 1: Parse all data points grouped by sensor
    sensor_data = {}  # {sensor_name: [(timestamp, value), ...]}

    for line in data_lines:
        parts = line.split(",")
        try:
            if len(parts) < 11 or parts[6] == "_value":
                continue

            timestamp_str = parts[5].strip()
            sensor_name = parts[10].strip()
            value = float(parts[6].strip())

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
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=local_tz)

    # Collect all sensors that need initial values first (batch them)
    sensors_needing_initial_values = []

    for sensor_name in sensors_list:
        # Check if sensor needs initial value from previous day
        needs_initial_value = False

        if sensor_name not in sensor_data or not sensor_data[sensor_name]:
            # Sensor has no data at all for this day
            needs_initial_value = True
            _LOGGER.debug("Sensor %s has no data for %s, will fetch initial value", sensor_name, target_date)
        else:
            # Sensor has data, but check if first data point is after day start
            first_timestamp = sensor_data[sensor_name][0][0]
            if first_timestamp > day_start:
                needs_initial_value = True
                _LOGGER.debug("Sensor %s first data at %s (after day start), will fetch initial value", sensor_name, first_timestamp)

        if needs_initial_value:
            sensors_needing_initial_values.append(sensor_name)

    # Batch fetch all initial values in a single query
    if sensors_needing_initial_values:
        _LOGGER.info("Batch fetching initial values for %d sensors", len(sensors_needing_initial_values))
        result = get_sensor_data(sensors_needing_initial_values, stop_time=day_start - timedelta(seconds=1))

        if result.get("status") == "success" and result.get("data"):
            for sensor_name in sensors_needing_initial_values:
                sensor_value = result["data"].get(f"sensor.{sensor_name}") or result["data"].get(sensor_name)
                if sensor_value is not None:
                    _LOGGER.debug("Found initial value for %s: %.2f (from before %s)", sensor_name, sensor_value, target_date)
                    # Add this as a data point just before the day started
                    initial_datapoint = (day_start - timedelta(seconds=1), sensor_value)
                    if sensor_name in sensor_data:
                        # Prepend to existing data
                        sensor_data[sensor_name].insert(0, initial_datapoint)
                    else:
                        # Create new list with just this initial value
                        sensor_data[sensor_name] = [initial_datapoint]

    # Step 3: For each period, find last value BEFORE period end time
    period_data = {}
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=local_tz)

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

    _LOGGER.debug("Parsed %d sensors with data for %d periods", len(sensor_data), len(period_data))

    return period_data
