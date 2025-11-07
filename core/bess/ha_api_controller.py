"""Home Assistant REST API Controller.

This controller provides the same interface as HomeAssistantController
but uses the REST API instead of direct pyscript access.
"""

import logging
import time
from typing import ClassVar

import requests

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


def run_request(http_method, *args, **kwargs):
    """Log the request and response for debugging purposes."""
    try:
        # Log the request details
        logger.debug("HTTP Method: %s", http_method.__name__.upper())
        logger.debug("Request Args: %s", args)
        logger.debug("Request Kwargs: %s", kwargs)

        # Make the HTTP request
        response = http_method(*args, **kwargs)

        # Log the response details
        logger.debug("Response Status Code: %s", response.status_code)
        logger.debug("Response Headers: %s", response.headers)
        logger.debug("Response Content: %s", response.text)

        return response
    except Exception as e:
        logger.error("Error during HTTP request: %s", str(e))
        raise


class HomeAssistantAPIController:
    """A class for interacting with Inverter controls via Home Assistant REST API."""

    def _get_sensor_display_name(self, sensor_key: str) -> str:
        """Get display name for a sensor key from METHOD_SENSOR_MAP."""
        for method_info in self.METHOD_SENSOR_MAP.values():
            if method_info["sensor_key"] == sensor_key:
                name = method_info["name"]
                return str(name) if name else f"sensor '{sensor_key}'"
        return f"sensor '{sensor_key}'"

    def _get_entity_for_service(self, sensor_key: str) -> str:
        """Get entity ID for service calls with proper error handling."""
        try:
            entity_id, _ = self._resolve_entity_id(sensor_key)
            return entity_id
        except ValueError as e:
            description = self._get_sensor_display_name(sensor_key)
            raise ValueError(f"No entity ID configured for {description}") from e

    def _get_sensor_key(self, method_name: str) -> str | None:
        """Get the sensor key for a method - compatibility method for existing code."""
        return self.get_method_sensor_key(method_name)

    @classmethod
    def get_method_info(cls, method_name: str) -> dict[str, object] | None:
        """Get method information including sensor key and display name."""
        return cls.METHOD_SENSOR_MAP.get(method_name)

    @classmethod
    def get_method_name(cls, method_name: str) -> str | None:
        """Get the display name for a method."""
        method_info = cls.METHOD_SENSOR_MAP.get(method_name)
        if method_info:
            name = method_info["name"]
            return str(name) if name else None
        return None

    @classmethod
    def get_method_sensor_key(cls, method_name: str) -> str | None:
        """Get the sensor key for a method."""
        method_info = cls.METHOD_SENSOR_MAP.get(method_name)
        if method_info:
            sensor_key = method_info["sensor_key"]
            return str(sensor_key) if sensor_key else None
        return None

    def __init__(self, ha_url: str, token: str, sensor_config: dict | None = None):
        """Initialize the Controller with Home Assistant API access.

        Args:
            ha_url: Base URL of Home Assistant (default: "http://supervisor/core")
            token: Long-lived access token for Home Assistant
            sensor_config: Sensor configuration mapping from options.json

        """
        self.base_url = ha_url
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.max_attempts = 4
        self.retry_delay = 4  # seconds
        self.test_mode = False

        # Use provided sensor configuration
        self.sensors = sensor_config or {}

        logger.info(
            f"Initialized HomeAssistantAPIController with {len(self.sensors)} sensor mappings"
        )

    # Class-level sensor mapping - immutable mapping
    METHOD_SENSOR_MAP: ClassVar[dict[str, dict[str, object]]] = {
        # Battery control methods
        "get_battery_soc": {
            "sensor_key": "battery_soc",
            "name": "Battery State of Charge",
            "unit": "%",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_charging_power_rate": {
            "sensor_key": "battery_charging_power_rate",
            "name": "Battery Charging Power Rate",
            "unit": "%",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_discharging_power_rate": {
            "sensor_key": "battery_discharging_power_rate",
            "name": "Battery Discharging Power Rate",
            "unit": "%",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_charge_stop_soc": {
            "sensor_key": "battery_charge_stop_soc",
            "name": "Battery Charge Stop SOC",
            "unit": "%",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_discharge_stop_soc": {
            "sensor_key": "battery_discharge_stop_soc",
            "name": "Battery Discharge Stop SOC",
            "unit": "%",
            "precision": 1,
            "conversion_threshold": None,
        },
        "grid_charge_enabled": {
            "sensor_key": "grid_charge",
            "name": "Grid Charge Enabled",
            "unit": "bool",
            "precision": 1,
            "conversion_threshold": None,
        },
        # Power monitoring methods
        "get_pv_power": {
            "sensor_key": "pv_power",
            "name": "Solar Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_import_power": {
            "sensor_key": "import_power",
            "name": "Grid Import Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_export_power": {
            "sensor_key": "export_power",
            "name": "Grid Export Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_local_load_power": {
            "sensor_key": "local_load_power",
            "name": "Home Load Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_output_power": {
            "sensor_key": "output_power",
            "name": "Output Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_self_power": {
            "sensor_key": "self_power",
            "name": "Self Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_system_power": {
            "sensor_key": "system_power",
            "name": "System Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_battery_charge_power": {
            "sensor_key": "battery_charge_power",
            "name": "Battery Charging Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_battery_discharge_power": {
            "sensor_key": "battery_discharge_power",
            "name": "Battery Discharging Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_net_battery_power": {
            "sensor_key": "net_battery_power",
            "name": "Net Battery Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_net_grid_power": {
            "sensor_key": "net_grid_power",
            "name": "Net Grid Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_l1_current": {
            "sensor_key": "current_l1",
            "name": "Current L1",
            "unit": "A",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_l2_current": {
            "sensor_key": "current_l2",
            "name": "Current L2",
            "unit": "A",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_l3_current": {
            "sensor_key": "current_l3",
            "name": "Current L3",
            "unit": "A",
            "precision": 1,
            "conversion_threshold": None,
        },
        # Energy totals
        # Price sensors
        "get_nordpool_prices_today": {
            "sensor_key": "nordpool_kwh_today",
            "name": "Nord Pool Prices Today",
            "unit": "list",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_nordpool_prices_tomorrow": {
            "sensor_key": "nordpool_kwh_tomorrow",
            "name": "Nord Pool Prices Tomorrow",
            "unit": "list",
            "precision": 1,
            "conversion_threshold": None,
        },
        # Home consumption forecast
        "get_estimated_consumption": {
            "sensor_key": "48h_avg_grid_import",
            "name": "Average Hourly Power Consumption",
            "unit": "W",
            "precision": 1,
            "conversion_threshold": 1000,
        },
        # Solar forecast
        "get_solar_forecast": {
            "sensor_key": "solar_forecast_today",
            "name": "Solar Forecast",
            "unit": "list",
            "precision": 1,
            "conversion_threshold": None,
        },
        # Lifetime and meter sensors (added for abstraction)
        "get_battery_charged_lifetime": {
            "sensor_key": "lifetime_battery_charged",
            "name": "Lifetime Total Battery Charged",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_battery_discharged_lifetime": {
            "sensor_key": "lifetime_battery_discharged",
            "name": "Lifetime Total Battery Discharged",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_solar_production_lifetime": {
            "sensor_key": "lifetime_solar_energy",
            "name": "Lifetime Total Solar Energy",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_grid_import_lifetime": {
            "sensor_key": "lifetime_import_from_grid",
            "name": "Lifetime Import from Grid",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_grid_export_lifetime": {
            "sensor_key": "lifetime_export_to_grid",
            "name": "Lifetime Total Export to Grid",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_load_consumption_lifetime": {
            "sensor_key": "lifetime_load_consumption",
            "name": "Lifetime Total Load Consumption",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_system_production_lifetime": {
            "sensor_key": "lifetime_system_production",
            "name": "Lifetime System Production",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_self_consumption_lifetime": {
            "sensor_key": "lifetime_self_consumption",
            "name": "Lifetime Self Consumption",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_ev_energy_meter": {
            "sensor_key": "ev_energy_meter",
            "name": "EV Energy Meter",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
    }

    def resolve_sensor_for_influxdb(self, sensor_key: str) -> str | None:
        """Resolve sensor key to entity ID formatted for InfluxDB (without 'sensor.' prefix).

        Args:
            sensor_key: The sensor key from config

        Returns:
            Entity ID without 'sensor.' prefix, or None if not configured

        Raises:
            TypeError: If sensor_key is not a string
        """
        if not isinstance(sensor_key, str):
            raise TypeError(f"sensor_key must be a string, got {type(sensor_key)}")

        try:
            entity_id, _ = self._resolve_entity_id(sensor_key)
            return entity_id[7:] if entity_id.startswith("sensor.") else entity_id
        except ValueError:
            return None

    def _resolve_entity_id(self, sensor_key: str) -> tuple[str, str]:
        """Unified entity ID resolution with consistent logic.

        Args:
            sensor_key: The sensor key to resolve

        Returns:
            tuple: (entity_id, resolution_method)

        Raises:
            ValueError: If sensor_key not found
        """
        # First check our sensor configuration
        if sensor_key in self.sensors:
            entity_id = self.sensors[sensor_key]
            return entity_id, "configured"

        # Require explicit configuration for all operations
        # This ensures proper sensor mapping and prevents silent failures
        raise ValueError(f"No entity ID configured for sensor '{sensor_key}'")

    def get_method_sensor_info(self, method_name: str) -> dict:
        """Get sensor configuration info for a controller method."""
        method_info = self.METHOD_SENSOR_MAP.get(method_name)
        if not method_info:
            return {
                "method_name": method_name,
                "name": method_name,
                "sensor_key": None,
                "entity_id": None,
                "status": "unknown_method",
                "error": f"Method '{method_name}' not found in sensor mapping",
            }

        sensor_key = str(method_info["sensor_key"])
        try:
            entity_id, resolution_method = self._resolve_entity_id(sensor_key)
        except ValueError as e:
            return {
                "method_name": method_name,
                "name": method_info["name"],
                "sensor_key": sensor_key,
                "entity_id": "Not configured",
                "status": "not_configured",
                "error": str(e),
                "current_value": None,
            }

        result = {
            "method_name": method_name,
            "name": method_info["name"],
            "sensor_key": sensor_key,
            "entity_id": entity_id,
            "status": "unknown",
            "error": None,
            "current_value": None,
            "resolution_method": resolution_method,
        }

        try:
            response = self._api_request("get", f"/api/states/{entity_id}")
            if not response:
                result.update(
                    {
                        "status": "entity_missing",
                        "error": f"Entity '{entity_id}' does not exist in Home Assistant",
                    }
                )
            elif response.get("state") in ["unavailable", "unknown"]:
                result.update(
                    {
                        "status": "entity_unavailable",
                        "error": f"Entity '{entity_id}' state is '{response.get('state')}'",
                    }
                )
            else:
                result.update({"status": "ok", "current_value": response.get("state")})
        except Exception as e:
            result.update(
                {
                    "status": "error",
                    "error": f"Failed to check entity '{entity_id}': {e!s}",
                }
            )
        return result

    def validate_methods_sensors(self, method_list: list) -> list:
        """Validate sensors for multiple methods at once."""
        return [self.get_method_sensor_info(method) for method in method_list]

    def _api_request(self, method, path, **kwargs):
        """Make an API request to Home Assistant with retry logic.

        Args:
            method: HTTP method ('get', 'post', etc.)
            path: API path (without base URL)
            **kwargs: Additional arguments for requests

        Returns:
            Response data from API

        Raises:
            requests.RequestException: If all retries fail

        """
        # List of operations that modify state (write operations)
        write_operations = [
            ("post", "/api/services/growatt_server/update_tlx_inverter_time_segment"),
            ("post", "/api/services/switch/turn_on"),
            ("post", "/api/services/switch/turn_off"),
            ("post", "/api/services/number/set_value"),
        ]

        # Check if this is a write operation and we're in test mode
        is_write_operation = (method.lower(), path) in write_operations

        # Test mode only blocks write operations, never read operations
        if self.test_mode and is_write_operation:
            logger.info(
                "[TEST MODE] Would call %s %s with args: %s",
                method.upper(),
                path,
                kwargs.get("json", {}),
            )
            return None

        url = f"{self.base_url}{path}"
        logger.debug("Making API request to %s %s", method.upper(), url)
        for attempt in range(self.max_attempts):
            try:
                http_method = getattr(requests, method.lower())

                # Use the environment-aware request function
                response = run_request(
                    http_method, url=url, headers=self.headers, timeout=30, **kwargs
                )

                # Raise an exception if the response status is an error
                response.raise_for_status()

                # Only try to parse JSON if there's content
                if (
                    response.content
                    and response.headers.get("content-type") == "application/json"
                ):
                    return response.json()
                return None

            except requests.RequestException as e:
                # Don't retry on 404 (sensor not found) - fail fast for missing sensors
                if (
                    hasattr(e, "response")
                    and e.response is not None
                    and e.response.status_code == 404
                ):
                    logger.error(
                        "API request to %s failed: Sensor not found (404). This indicates a missing or misconfigured sensor.",
                        url,
                    )
                    raise  # Fail immediately on 404

                if attempt < self.max_attempts - 1:  # Not the last attempt
                    logger.warning(
                        "API request to %s failed on attempt %d/%d: %s. Retrying in %d seconds...",
                        url,
                        attempt + 1,
                        self.max_attempts,
                        str(e),
                        self.retry_delay,
                    )
                    time.sleep(self.retry_delay)
                else:  # Last attempt failed
                    logger.error(
                        "API request to %s failed on final attempt %d/%d: %s",
                        path,
                        attempt + 1,
                        self.max_attempts,
                        str(e),
                    )
                    raise  # Re-raise the last exception

    def _service_call_with_retry(self, service_domain, service_name, **kwargs):
        """Call Home Assistant service with retry logic.

        Args:
            service_domain: Service domain (e.g., 'switch', 'number')
            service_name: Service name (e.g., 'turn_on', 'set_value')
            **kwargs: Service parameters

        Returns:
            Response from service call or None

        """
        # List of read-only operations that are safe to execute in test mode
        # In test mode, we block ALL operations EXCEPT these safe reads
        safe_read_operations = [
            ("growatt_server", "read_time_segments"),
            ("nordpool", "get_prices_for_date"),
        ]

        is_safe_read = (service_domain, service_name) in safe_read_operations

        # Test mode blocks ALL operations except safe reads (deny by default)
        if self.test_mode and not is_safe_read:
            logger.info(
                "[TEST MODE] Would call service %s.%s with args: %s",
                service_domain,
                service_name,
                kwargs,
            )
            return None

        # Prepare API call parameters
        path = f"/api/services/{service_domain}/{service_name}"
        json_data = kwargs.copy()

        # Add return_response query parameter for read operations
        query_params = {}
        if json_data.pop("return_response", is_safe_read):
            query_params["return_response"] = "true"

        # Remove 'blocking' from payload
        json_data.pop("blocking", True)

        # Modify URL to include query parameters if needed
        if query_params:
            import urllib.parse

            path += "?" + urllib.parse.urlencode(query_params)

        # Make API call
        return self._api_request("post", path, json=json_data)

    def _get_sensor_value(self, sensor_name):
        """Get value from any sensor by name using unified entity resolution."""
        try:
            entity_id, resolution_method = self._resolve_entity_id(sensor_name)
            logger.debug(
                f"Resolving sensor '{sensor_name}' to entity '{entity_id}' (method: {resolution_method})"
            )

            # Make API call to get state
            response = self._api_request("get", f"/api/states/{entity_id}")

            if response and "state" in response:
                return float(response["state"])
            else:
                logger.warning(
                    "Sensor %s (entity_id: %s) returned invalid response or no state",
                    sensor_name,
                    entity_id,
                )
                return 0.0

        except (ValueError, TypeError):
            logger.warning("Could not get value for %s", sensor_name)
            return 0.0
        except requests.RequestException as e:
            logger.error("Error fetching sensor %s: %s", sensor_name, str(e))
            return 0.0

    def get_estimated_consumption(self):
        """Get estimated hourly consumption for 24 hours."""
        avg_consumption = self._get_sensor_value("48h_avg_grid_import") / 1000
        return [avg_consumption] * 24

    def get_battery_soc(self):
        """Get the battery state of charge (SOC)."""
        return self._get_sensor_value("battery_soc")

    def get_charge_stop_soc(self):
        """Get the charge stop state of charge (SOC)."""
        return self._get_sensor_value("battery_charge_stop_soc")

    def set_charge_stop_soc(self, charge_stop_soc):
        """Set the charge stop state of charge (SOC)."""
        entity_id = self._get_entity_for_service("battery_charge_stop_soc")
        self._service_call_with_retry(
            "number",
            "set_value",
            entity_id=entity_id,
            value=charge_stop_soc,
        )

    def get_discharge_stop_soc(self):
        """Get the discharge stop state of charge (SOC)."""
        return self._get_sensor_value("battery_discharge_stop_soc")

    def set_discharge_stop_soc(self, discharge_stop_soc):
        """Set the discharge stop state of charge (SOC)."""
        entity_id = self._get_entity_for_service("battery_discharge_stop_soc")
        self._service_call_with_retry(
            "number",
            "set_value",
            entity_id=entity_id,
            value=discharge_stop_soc,
        )

    def get_charging_power_rate(self):
        """Get the charging power rate."""
        return self._get_sensor_value("battery_charging_power_rate")

    def set_charging_power_rate(self, rate):
        """Set the charging power rate."""
        entity_id = self._get_entity_for_service("battery_charging_power_rate")
        self._service_call_with_retry(
            "number",
            "set_value",
            entity_id=entity_id,
            value=rate,
        )

    def get_discharging_power_rate(self):
        """Get the discharging power rate."""
        return self._get_sensor_value("battery_discharging_power_rate")

    def set_discharging_power_rate(self, rate):
        """Set the discharging power rate."""
        entity_id = self._get_entity_for_service("battery_discharging_power_rate")
        self._service_call_with_retry(
            "number",
            "set_value",
            entity_id=entity_id,
            value=rate,
        )

    def get_battery_charge_power(self):
        """Get current battery charging power in watts."""
        return self._get_sensor_value("battery_charge_power")

    def get_battery_discharge_power(self):
        """Get current battery discharging power in watts."""
        return self._get_sensor_value("battery_discharge_power")

    def set_grid_charge(self, enable):
        """Enable or disable grid charging."""
        entity_id = self._get_entity_for_service("grid_charge")
        service = "turn_on" if enable else "turn_off"

        if enable:
            logger.info("Enabling grid charge")
        else:
            logger.info("Disabling grid charge")

        self._service_call_with_retry(
            "switch",
            service,
            entity_id=entity_id,
        )

    def grid_charge_enabled(self):
        """Return True if grid charging is enabled."""
        try:
            entity_id = self._get_entity_for_service("grid_charge")
            response = self._api_request("get", f"/api/states/{entity_id}")
            if response and "state" in response:
                return response["state"] == "on"
            return False
        except ValueError as e:
            logger.warning(str(e))
            return False

    def set_inverter_time_segment(
        self,
        segment_id: int,
        batt_mode: str,
        start_time: str,
        end_time: str,
        enabled: bool,
    ) -> None:
        """Set the inverter time segment.

        Args:
            segment_id: Segment number (1-10)
            batt_mode: Battery mode ("load-first", "battery-first", or "grid-first")
            start_time: Start time in "HH:MM" format
            end_time: End time in "HH:MM" format
            enabled: Whether the segment is enabled
        """
        self._service_call_with_retry(
            "growatt_server",
            "update_time_segment",
            segment_id=segment_id,
            batt_mode=batt_mode,
            start_time=start_time,
            end_time=end_time,
            enabled=enabled,
        )

    def read_inverter_time_segments(self):
        """Read all time segments from the inverter with retry logic."""
        try:
            # Call the service and get the response
            result = self._service_call_with_retry(
                "growatt_server",
                "read_time_segments",
                return_response=True,  # Explicitly set return_response
            )

            # Check if the result contains 'service_response' with 'time_segments'
            if result and "service_response" in result:
                service_response = result["service_response"]
                if "time_segments" in service_response:
                    return service_response["time_segments"]

            # If the result doesn't match expected format, log and return empty list
            logger.warning(
                "Unexpected response format from read_tlx_inverter_time_segments"
            )
            return []

        except Exception as e:
            logger.warning("Failed to read time segments: %s", str(e))
            return []  # Return empty list instead of failing

    def set_test_mode(self, enabled):
        """Enable or disable test mode."""
        self.test_mode = enabled
        logger.info("%s test mode", "Enabled" if enabled else "Disabled")

    def get_l1_current(self):
        """Get the current load for L1."""
        return self._get_sensor_value("current_l1")

    def get_l2_current(self):
        """Get the current load for L2."""
        return self._get_sensor_value("current_l2")

    def get_l3_current(self):
        """Get the current load for L3."""
        return self._get_sensor_value("current_l3")

    def get_solar_forecast(self):
        """Get solar forecast data from Solcast integration."""
        # Determine which sensor key to use based on day_offset
        sensor_key = "solar_forecast_today"

        # Get entity ID from sensor config
        entity_id = self.sensors.get(sensor_key)
        if not entity_id:
            logger.warning(f"No entity ID configured for {sensor_key}")
            return [0.0] * 24  # Return zeros as fallback

        response = self._api_request("get", f"/api/states/{entity_id}")

        if not response or "attributes" not in response:
            logger.warning(
                "No attributes found for %s, using default values", entity_id
            )
            return [0.0] * 24  # Return zeros as fallback

        attributes = response["attributes"]
        hourly_data = attributes.get("detailedHourly")

        if not hourly_data:
            logger.warning(
                "No hourly data found in %s, using default values", entity_id
            )
            return [0.0] * 24  # Return zeros as fallback

        hourly_values = [0.0] * 24
        pv_field = "pv_estimate"

        for entry in hourly_data:
            # Handle period_start
            period_start = entry["period_start"]

            # If period_start is a string, parse the hour
            if isinstance(period_start, str):
                hour = int(period_start.split("T")[1].split(":")[0])
            else:
                # Assume it's already a datetime object
                hour = period_start.hour

            hourly_values[hour] = float(entry[pv_field])

        return hourly_values

    def _get_nordpool_prices(self, is_tomorrow=False):
        """Get Nordpool prices from Home Assistant sensor - simplified to just fetch raw data.

        The HA controller is now a thin data layer that just fetches sensor data.
        All complex logic (DST handling, timestamp validation, etc.) is handled
        by the PriceManager layer.

        Args:
            is_tomorrow: If True, get tomorrow's prices, otherwise today's

        Returns:
            list: List of hourly prices (may be 23, 24, or 25 hours for DST)

        Raises:
            ValueError: If prices are not available for the date
        """
        time_label = "tomorrow" if is_tomorrow else "today"
        try:
            # Determine which sensor to use
            sensor_key = (
                "nordpool_kwh_tomorrow" if is_tomorrow else "nordpool_kwh_today"
            )
            entity_id = self.sensors.get(sensor_key)
            if not entity_id:
                logger.warning(f"No entity ID configured for {sensor_key}")
                raise ValueError(f"Missing entity ID configuration for {sensor_key}")

            logger.debug(f"Fetching Nordpool prices for {time_label} from {entity_id}")

            # Get entity state
            entity_response = self._api_request("get", f"/api/states/{entity_id}")

            if not entity_response:
                logger.error(
                    f"Could not retrieve Nordpool sensor state for {time_label}"
                )
                raise ValueError(f"Nordpool prices for {time_label} are unavailable")

            # Access attributes from the response
            attributes = entity_response.get("attributes", {})

            # Try to get raw data from attributes first
            raw_data_key = "raw_tomorrow" if is_tomorrow else "raw_today"
            raw_data = attributes.get(raw_data_key)

            if raw_data:
                # Extract raw prices - let PriceManager handle DST and validation
                try:
                    processed_prices = [hour_data["value"] for hour_data in raw_data]
                    logger.debug(
                        f"Successfully extracted {len(processed_prices)} hourly prices from {raw_data_key}"
                    )
                    return processed_prices
                except (KeyError, TypeError) as e:
                    logger.warning(f"Invalid raw data format in {raw_data_key}: {e}")

            # Fallback to the regular array if raw data isn't available
            regular_data_key = "tomorrow" if is_tomorrow else "today"
            regular_prices = attributes.get(regular_data_key)

            if regular_prices and isinstance(regular_prices, list):
                logger.info(
                    f"Using '{regular_data_key}' attribute with {len(regular_prices)} hourly prices"
                )
                return regular_prices

            # Check if tomorrow's prices are valid (for tomorrow only)
            if is_tomorrow and attributes.get("tomorrow_valid") is False:
                logger.error(
                    "Tomorrow's prices are not yet available (tomorrow_valid=false)"
                )
                raise ValueError("Tomorrow's Nordpool prices are not yet available")

            # If we get here, no price data was found
            logger.error(
                f"Could not find price data for {time_label} in Nordpool sensor attributes"
            )
            logger.debug(f"Available attributes: {list(attributes.keys())}")
            raise ValueError(f"Nordpool prices for {time_label} are unavailable")

        except Exception as e:
            logger.error(f"Error fetching Nordpool prices for {time_label}: {e!s}")
            raise

    def get_nordpool_prices_today(self):
        """Get today's Nordpool prices from Home Assistant sensor."""
        return self._get_nordpool_prices(is_tomorrow=False)

    def get_nordpool_prices_tomorrow(self):
        """Get tomorrow's Nordpool prices from Home Assistant sensor."""
        return self._get_nordpool_prices(is_tomorrow=True)

    def get_sensor_data(self, sensors_list):
        """Get current sensor data via Home Assistant REST API.

        Note: This method only provides current sensor states, not historical data.
        Historical data is handled by InfluxDB integration in sensor_collector.py.

        Args:
            sensors_list: List of sensor names to fetch

        Returns:
            Dictionary with current sensor data in the same format as influxdb_helper
        """
        # Initialize result with proper format
        result = {"status": "success", "data": {}}

        try:
            # For each sensor in the list, get the current state
            for sensor in sensors_list:
                # Use unified entity resolution - require explicit configuration
                entity_id, _ = self._resolve_entity_id(sensor)

                # Get sensor state
                response = self._api_request("get", f"/api/states/{entity_id}")
                if response and "state" in response:
                    try:
                        # Store the value, converting to float for numeric sensors
                        value = float(response["state"])
                        result["data"][sensor] = value
                    except (ValueError, TypeError):
                        # For non-numeric states, store as is
                        result["data"][sensor] = response["state"]
                        logger.warning(
                            "Non-numeric state for sensor %s: %s",
                            sensor,
                            response["state"],
                        )

            # Check if we got any data
            if not result["data"]:
                result["status"] = "error"
                result["message"] = "No sensor data available"

            return result

        except Exception as e:
            logger.error("Error fetching sensor data: %s", str(e))
            return {"status": "error", "message": str(e)}

    def get_pv_power(self):
        """Get current solar PV power production in watts."""
        return self._get_sensor_value("pv_power")

    def get_import_power(self):
        """Get current grid import power in watts."""
        return self._get_sensor_value("import_power")

    def get_export_power(self):
        """Get current grid export power in watts."""
        return self._get_sensor_value("export_power")

    def get_local_load_power(self):
        """Get current home load power in watts."""
        return self._get_sensor_value("local_load_power")

    def get_output_power(self):
        """Get current output power in watts."""
        return self._get_sensor_value("output_power")

    def get_self_power(self):
        """Get current self power in watts."""
        return self._get_sensor_value("self_power")

    def get_system_power(self):
        """Get current system power in watts."""
        return self._get_sensor_value("system_power")

    def get_net_battery_power(self):
        """Get net battery power (positive = charging, negative = discharging) in watts."""
        charge_power = self.get_battery_charge_power()
        discharge_power = self.get_battery_discharge_power()
        return charge_power - discharge_power

    def get_net_grid_power(self):
        """Get net grid power (positive = importing, negative = exporting) in watts."""
        import_power = self.get_import_power()
        export_power = self.get_export_power()
        return import_power - export_power

    # Lifetime energy sensors (used by energy monitoring health checks)
    def get_battery_charged_lifetime(self):
        """Get lifetime total battery charged energy in kWh."""
        return self._get_sensor_value("lifetime_battery_charged")

    def get_battery_discharged_lifetime(self):
        """Get lifetime total battery discharged energy in kWh."""
        return self._get_sensor_value("lifetime_battery_discharged")

    def get_solar_production_lifetime(self):
        """Get lifetime total solar energy production in kWh."""
        return self._get_sensor_value("lifetime_solar_energy")

    def get_grid_import_lifetime(self):
        """Get lifetime total grid import energy in kWh."""
        return self._get_sensor_value("lifetime_import_from_grid")

    def get_grid_export_lifetime(self):
        """Get lifetime total grid export energy in kWh."""
        return self._get_sensor_value("lifetime_export_to_grid")

    def get_load_consumption_lifetime(self):
        """Get lifetime total load consumption energy in kWh."""
        return self._get_sensor_value("lifetime_load_consumption")

    def get_system_production_lifetime(self):
        """Get lifetime total system production energy in kWh."""
        return self._get_sensor_value("lifetime_system_production")

    def get_self_consumption_lifetime(self):
        """Get lifetime total self consumption energy in kWh."""
        return self._get_sensor_value("lifetime_self_consumption")
