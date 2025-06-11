"""Home Assistant REST API Controller.

This controller provides the same interface as HomeAssistantController
but uses the REST API instead of direct pyscript access.
"""

import logging
import time

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

    def __init__(self, base_url="", token=None, sensor_config=None) -> None:
        """Initialize the Controller with Home Assistant API access.

        Args:
            base_url: Base URL of Home Assistant (default: "http://supervisor/core")
            token: Long-lived access token for Home Assistant
            sensor_config: Sensor configuration mapping from options.json

        """
        self.base_url = base_url
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
        # List of operations that modify state (write operations)
        write_operations = [
            ("growatt_server", "update_tlx_inverter_time_segment"),
            ("switch", "turn_on"),
            ("switch", "turn_off"),
            ("number", "set_value"),
        ]

        # List of operations that return data
        read_operations = [("growatt_server", "read_tlx_inverter_time_segments")]

        # Only block write operations in test mode
        is_write_operation = (service_domain, service_name) in write_operations
        is_read_operation = (service_domain, service_name) in read_operations

        # Test mode only blocks write operations, never read operations
        if self.test_mode and is_write_operation:
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
        if json_data.pop("return_response", is_read_operation):
            query_params["return_response"] = "true"

        # Remove 'blocking' from payload
        json_data.pop("blocking", True)

        # Modify URL to include query parameters if needed
        if query_params:
            import urllib.parse

            path += "?" + urllib.parse.urlencode(query_params)

        # Make API call
        return self._api_request("post", path, json=json_data)

    def get_sensor_value(self, sensor_name):
        """Get value from any sensor by name."""
        try:
            # First, check if this key exists in our sensor config
            if sensor_name in self.sensors:
                # Use the configured entity ID
                entity_id = self.sensors[sensor_name]
                logger.debug(
                    f"Using configured entity ID '{entity_id}' for sensor '{sensor_name}'"
                )
            elif "." in sensor_name:
                # This is already a full entity ID
                entity_id = sensor_name
                logger.debug(f"Using direct entity ID: {entity_id}")
            else:
                # Fall back to default format
                entity_id = f"sensor.{sensor_name}"
                logger.debug(f"Using default entity ID format: {entity_id}")

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
        avg_consumption = self.get_sensor_value("48h_avg_grid_import") / 1000
        return [avg_consumption] * 24

    def get_solar_generation_today(self):
        """Get the current solar generation reading (cumulative for today)."""
        return self.get_sensor_value("solar_production_today")

    def get_current_consumption(self):
        """Get the current hour's home consumption in kWh."""
        return self.get_sensor_value("1h_avg_grid_import")

    def get_battery_charge_today(self):
        """Get total battery charging for today in kWh."""
        return self.get_sensor_value("battery_charged_today")

    def get_battery_discharge_today(self):
        """Get total battery discharging for today in kWh."""
        return self.get_sensor_value("battery_discharged_today")

    def get_self_consumption_today(self):
        """Get total solar self-consumption for today in kWh."""
        return self.get_sensor_value("self_consumption_today")

    def get_export_to_grid_today(self):
        """Get total export to grid for today in kWh."""
        return self.get_sensor_value("export_to_grid_today")

    def get_load_consumption_today(self):
        """Get total home load consumption for today in kWh."""
        return self.get_sensor_value("load_consumption_today")

    def get_import_from_grid_today(self):
        """Get total import from grid for today in kWh."""
        return self.get_sensor_value("import_from_grid_today")

    def get_grid_to_battery_today(self):
        """Get total grid to battery charging for today in kWh."""
        return self.get_sensor_value("batteries_charged_from_grid_today")

    def get_ev_energy_today(self):
        """Get total EV charging energy for today in kWh."""
        return self.get_sensor_value("ev_energy_today")

    def get_battery_soc(self):
        """Get the battery state of charge (SOC)."""
        return self.get_sensor_value("battery_soc")

    def get_charge_stop_soc(self):
        """Get the charge stop state of charge (SOC)."""
        return self.get_sensor_value("battery_charge_stop_soc")

    def set_charge_stop_soc(self, charge_stop_soc):
        """Set the charge stop state of charge (SOC)."""
        self._service_call_with_retry(
            "number",
            "set_value",
            entity_id=self.sensors.get("battery_charge_stop_soc"),
            value=charge_stop_soc,
        )

    def get_discharge_stop_soc(self):
        """Get the discharge stop state of charge (SOC)."""
        return self.get_sensor_value("battery_discharge_stop_soc")

    def set_discharge_stop_soc(self, discharge_stop_soc):
        """Set the discharge stop state of charge (SOC)."""
        self._service_call_with_retry(
            "number",
            "set_value",
            entity_id=self.sensors.get("battery_discharge_stop_soc"),
            value=discharge_stop_soc,
        )

    def get_charging_power_rate(self):
        """Get the charging power rate."""
        return self.get_sensor_value("battery_charging_power_rate")

    def set_charging_power_rate(self, rate):
        """Set the charging power rate."""
        self._service_call_with_retry(
            "number",
            "set_value",
            entity_id=self.sensors.get("battery_charging_power_rate"),
            value=rate,
        )

    def get_discharging_power_rate(self):
        """Get the discharging power rate."""
        return self.get_sensor_value("battery_discharging_power_rate")

    def set_discharging_power_rate(self, rate):
        """Set the discharging power rate."""
        self._service_call_with_retry(
            "number",
            "set_value",
            entity_id=self.sensors.get("battery_discharging_power_rate"),
            value=rate,
        )

    def get_battery_charge_power(self):
        """Get current battery charging power in watts."""
        return self.get_sensor_value("battery_charge_power")

    def get_battery_discharge_power(self):
        """Get current battery discharging power in watts."""
        return self.get_sensor_value("battery_discharge_power")

    def set_grid_charge(self, enable):
        """Enable or disable grid charging."""
        service = "turn_on" if enable else "turn_off"

        if enable:
            logger.info("Enabling grid charge")
        else:
            logger.info("Disabling grid charge")

        self._service_call_with_retry(
            "switch",
            service,
            entity_id=self.sensors.get("grid_charge"),
        )

    def grid_charge_enabled(self):
        """Return True if grid charging is enabled."""
        # Use the sensor config to get the correct entity ID
        entity_id = self.sensors.get("grid_charge")
        if not entity_id:
            logger.warning("No entity ID configured for grid_charge")
            return False

        response = self._api_request("get", f"/api/states/{entity_id}")
        if response and "state" in response:
            return response["state"] == "on"
        return False

    def set_inverter_time_segment(
        self,
        segment_id,
        batt_mode,
        start_time,
        end_time,
        enabled,
    ):
        """Set the inverter time segment with retry logic."""
        # Convert batt_mode if it's a string name to integer for API
        batt_mode_val = batt_mode
        if isinstance(batt_mode, str):
            # Map string mode names to integers if needed by API
            mode_map = {"load-first": 0, "battery-first": 1, "grid-first": 2}
            if batt_mode in mode_map:
                batt_mode_val = mode_map[batt_mode]

        self._service_call_with_retry(
            "growatt_server",
            "update_tlx_inverter_time_segment",
            segment_id=segment_id,
            batt_mode=batt_mode_val,
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
                "read_tlx_inverter_time_segments",
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
        return self.get_sensor_value("current_l1")

    def get_l2_current(self):
        """Get the current load for L2."""
        return self.get_sensor_value("current_l2")

    def get_l3_current(self):
        """Get the current load for L3."""
        return self.get_sensor_value("current_l3")

    def get_solar_forecast(self, day_offset=0, confidence_level="estimate"):
        """Get solar forecast data from Solcast integration."""
        # Determine which sensor key to use based on day_offset
        sensor_key = "solar_forecast_today"
        if day_offset == 1:
            sensor_key = "solar_forecast_tomorrow"

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
        pv_field = f"pv_{confidence_level}"

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
        try:
            # Determine which sensor to use
            sensor_key = (
                "nordpool_kwh_tomorrow" if is_tomorrow else "nordpool_kwh_today"
            )
            entity_id = self.sensors.get(sensor_key)
            if not entity_id:
                logger.warning(f"No entity ID configured for {sensor_key}")
                raise ValueError(f"Missing entity ID configuration for {sensor_key}")

            time_label = "tomorrow" if is_tomorrow else "today"
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

    # --- Energy Manager Methods ---
    # These methods are specifically for supporting the EnergyManager class

    def get_sensor_data(self, sensors_list, end_time=None):
        """Get sensor data for each hour of today with incremental values for cumulative sensors.

        This replaces the influxdb_helper.get_sensor_data function to use the REST API instead.

        Args:
            sensors_list: List of sensor names to fetch
            end_time: Optional datetime to fetch states for

        Returns:
            Dictionary with sensor data in the same format as influxdb_helper

        """
        # Initialize result with proper format
        result = {"status": "success", "data": {}}

        try:
            # For each sensor in the list, get the current state
            for sensor in sensors_list:
                # Check if it's a full entity_id or a short name
                if "." in sensor:
                    entity_id = sensor
                else:
                    # Use the mapping if available, otherwise build entity_id
                    entity_id = self.sensors.get(sensor, f"sensor.{sensor}")

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
