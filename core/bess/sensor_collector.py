"""
Robust SensorCollector - Clean sensor data collection from InfluxDB with strategic intent reconstruction.
"""

import logging
from datetime import datetime, time, timedelta

from .energy_flow_calculator import EnergyFlowCalculator
from .health_check import perform_health_check
from .influxdb_helper import get_sensor_data
from .models import EnergyData

logger = logging.getLogger(__name__)


class SensorCollector:
    """Collects sensor data from InfluxDB and calculates energy flows with strategic intent reconstruction."""

    def __init__(self, ha_controller, battery_capacity_kwh: float):
        """Initialize sensor collector."""
        self.ha_controller = ha_controller
        self.battery_capacity = battery_capacity_kwh
        self.energy_flow_calculator = EnergyFlowCalculator(
            battery_capacity_kwh, ha_controller
        )

        # Cumulative sensors we track from InfluxDB
        # Use sensor keys instead of hardcoded entity IDs
        self.cumulative_sensor_keys = [
            "lifetime_battery_charged",
            "lifetime_battery_discharged",
            "lifetime_solar_energy",
            "lifetime_load_consumption",
            "lifetime_import_from_grid",
            "lifetime_export_to_grid",
            "lifetime_system_production",
            "lifetime_self_consumption",
            "ev_energy_meter",
            "battery_soc",
        ]

        # Resolve to actual entity IDs for InfluxDB queries
        self.cumulative_sensors = self._resolve_sensor_entity_ids()

    def _resolve_sensor_entity_ids(self) -> list[str]:
        """Resolve sensor keys to entity IDs using the controller's abstraction layer.

        Returns entity IDs in the format expected by InfluxDB (without 'sensor.' prefix).
        """
        resolved_ids = []
        for sensor_key in self.cumulative_sensor_keys:
            entity_id = self.ha_controller.resolve_sensor_for_influxdb(sensor_key)
            if entity_id:
                resolved_ids.append(entity_id)
                logger.debug(f"Resolved sensor key '{sensor_key}' to '{entity_id}'")
            else:
                # Sensor not configured - this is okay, just skip it
                logger.debug(f"Sensor key '{sensor_key}' not configured")
                continue
        logger.info(
            f"Resolved {len(resolved_ids)} sensor entity IDs for InfluxDB queries"
        )
        return resolved_ids

    def collect_energy_data(self, hour: int) -> EnergyData:
        """Collect sensor data and create EnergyData with automatic detailed flows."""

        if not 0 <= hour <= 23:
            raise ValueError(f"Invalid hour: {hour}. Must be 0-23.")

        # Check if this hour is complete
        now = datetime.now()
        if hour == now.hour:
            raise ValueError(
                f"Hour {hour} is still in progress, cannot collect complete data"
            )
        elif hour > now.hour:
            raise ValueError(f"Hour {hour} is in the future, cannot collect data")

        # Get current hour data (END of hour readings)
        current_readings = self._get_hour_readings(hour)
        if not current_readings:
            raise RuntimeError(f"No sensor readings available for hour {hour}")

        # Get previous hour data (START of hour readings)
        if hour == 0:
            previous_readings = self._get_hour_readings(23, date_offset=-1)
            if not previous_readings:
                raise RuntimeError(
                    "No sensor readings available for hour 23 of previous day (needed for hour 0 start SOC)"
                )
        else:
            previous_readings = self._get_hour_readings(hour - 1)
            if not previous_readings:
                raise RuntimeError(
                    f"No sensor readings available for hour {hour-1} (needed for hour {hour} start SOC)"
                )

        # Calculate energy flows using existing calculator
        flow_dict = self.energy_flow_calculator.calculate_hourly_flows(
            current_readings, previous_readings, hour
        )
        if not flow_dict:
            raise RuntimeError(f"Energy flow calculation failed for hour {hour}")

        # Extract BOTH SOC readings from sensors - NO DEFAULTS
        # Use abstraction layer to resolve battery SOC sensor entity ID (without 'sensor.' prefix)
        try:
            entity_id, _ = self.ha_controller._resolve_entity_id("battery_soc")
            if entity_id.startswith("sensor."):
                battery_soc_end_key = entity_id[7:]
            else:
                battery_soc_end_key = entity_id
        except ValueError as e:
            raise KeyError(
                "Battery SOC sensor key 'battery_soc' not configured in controller."
            ) from e

        if battery_soc_end_key not in current_readings:
            raise KeyError(
                f"Hour {hour}: Missing end SOC sensor '{battery_soc_end_key}' in current readings"
            )

        if battery_soc_end_key not in previous_readings:
            raise KeyError(
                f"Hour {hour}: Missing start SOC sensor '{battery_soc_end_key}' in previous readings"
            )

        battery_soc_end = current_readings[battery_soc_end_key]
        battery_soc_start = previous_readings[battery_soc_end_key]

        # Validate SOC readings
        if not 0 <= battery_soc_start <= 100:
            raise ValueError(
                f"Hour {hour}: Invalid start SOC {battery_soc_start}%. Must be 0-100%."
            )

        if not 0 <= battery_soc_end <= 100:
            raise ValueError(
                f"Hour {hour}: Invalid end SOC {battery_soc_end}%. Must be 0-100%."
            )

        # Convert SOC to SOE
        soe_start = (battery_soc_start / 100.0) * self.battery_capacity
        soe_end = (battery_soc_end / 100.0) * self.battery_capacity

        # Create EnergyData directly - detailed flows calculated automatically in __post_init__
        energy_data = EnergyData(
            solar_production=flow_dict.get("solar_production", 0.0),
            home_consumption=flow_dict.get("load_consumption", 0.0),
            battery_charged=flow_dict.get("battery_charged", 0.0),
            battery_discharged=flow_dict.get("battery_discharged", 0.0),
            grid_imported=flow_dict.get("import_from_grid", 0.0),
            grid_exported=flow_dict.get("export_to_grid", 0.0),
            battery_soe_start=soe_start,
            battery_soe_end=soe_end,
        )

        logger.info(
            "Collected EnergyData for hour %02d: SOE %.1f -> %.1f kWh, Solar: %.2f kWh, Load: %.2f kWh, Detailed flows auto-calculated",
            hour,
            soe_start,
            soe_end,
            energy_data.solar_production,
            energy_data.home_consumption,
        )

        return energy_data

    def _get_safe_end_hour(
        self, requested_end_hour: int, current_hour: int, current_minute: int
    ) -> int:
        """Determine the safe end hour for data collection based on current time."""

        # If we're in the first 5 minutes of an hour, the previous hour might not be complete
        if current_minute < 5:
            safe_end_hour = current_hour - 1 if current_hour > 0 else -1
        else:
            # We're far enough into the current hour that the previous hour should be complete
            safe_end_hour = current_hour - 1

        # Don't exceed the requested end hour
        safe_end_hour = min(safe_end_hour, requested_end_hour)

        # Handle day boundaries
        if safe_end_hour < 0:
            logger.debug(
                "No complete hours available yet (safe_end_hour: %d)", safe_end_hour
            )
            return -1

        logger.debug(
            "Safe end hour: %d (requested: %d, current: %02d:%02d)",
            safe_end_hour,
            requested_end_hour,
            current_hour,
            current_minute,
        )

        return safe_end_hour

    def _get_hour_readings(
        self, hour: int, date_offset: int = 0
    ) -> dict[str, float] | None:
        """Get sensor readings for specific hour from InfluxDB with robust time handling."""
        if hour < 0 or hour > 23:
            logger.error("Invalid hour: %d", hour)
            return None

        try:
            # Calculate target datetime with smart time selection
            now = datetime.now()
            today = now.date()
            target_date = today + timedelta(days=date_offset)

            # Smart target time selection
            target_time = self._get_safe_target_time(hour, date_offset, now)
            target_datetime = datetime.combine(target_date, target_time)

            logger.debug(
                "Querying InfluxDB for hour %d at %s (offset: %d)",
                hour,
                target_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                date_offset,
            )

            # Query InfluxDB with retry logic
            result = self._query_influxdb_with_retry(target_datetime)

            if not result or result.get("status") != "success":
                logger.warning(
                    "InfluxDB query failed for hour %d (offset %d): %s",
                    hour,
                    date_offset,
                    result.get("message", "Unknown error"),
                )
                return None

            data = result.get("data", {})
            if not data:
                logger.warning(
                    "No data returned for hour %d (offset %d)", hour, date_offset
                )
                return None

            # Convert to float and normalize naming
            readings = self._normalize_sensor_readings(data)

            logger.debug(
                "Hour %d (offset %d): %d sensors read successfully",
                hour,
                date_offset,
                len(readings),
            )
            return readings

        except Exception as e:
            logger.error("Error reading hour %d (offset %d): %s", hour, date_offset, e)
            return None

    def _get_safe_target_time(self, hour: int, date_offset: int, now: datetime) -> time:
        """Get a safe target time for querying sensor data."""

        # If we're asking for data from a different day, use end of hour
        if date_offset != 0:
            return time(hour=hour, minute=59, second=59)

        # If we're asking for data from today
        if hour < now.hour:
            # Past hour - use end of hour
            return time(hour=hour, minute=59, second=59)
        elif hour == now.hour:
            # Current hour - use current time minus a small buffer
            buffer_minutes = max(0, now.minute - 2)  # 2-minute buffer
            return time(hour=hour, minute=buffer_minutes, second=0)
        else:
            # Future hour - this shouldn't happen, but use current time as fallback
            logger.warning(
                "Requesting data for future hour %d, using current time", hour
            )
            return now.time()

    def _query_influxdb_with_retry(
        self, target_datetime: datetime, max_retries: int = 3
    ) -> dict:
        """Query InfluxDB with retry logic and fallback times."""

        for attempt in range(max_retries):
            try:
                # Use InfluxDB for historical data - this is what the system was designed for
                result = get_sensor_data(
                    self.cumulative_sensors, stop_time=target_datetime
                )

                if result and result.get("status") == "success" and result.get("data"):
                    return result

                # If no data, try a slightly earlier time (useful for incomplete hours)
                if attempt < max_retries - 1:
                    earlier_time = target_datetime - timedelta(
                        minutes=5 * (attempt + 1)
                    )
                    logger.debug(
                        "Attempt %d failed, trying earlier time: %s",
                        attempt + 1,
                        earlier_time.strftime("%H:%M:%S"),
                    )
                    target_datetime = earlier_time

            except Exception as e:
                logger.warning("InfluxDB query attempt %d failed: %s", attempt + 1, e)
                if attempt == max_retries - 1:
                    return {"status": "error", "message": str(e)}

        return {"status": "error", "message": "All retry attempts failed"}

    def _normalize_sensor_readings(self, data: dict) -> dict[str, float]:
        """Normalize sensor readings and handle data type conversion."""
        readings = {}

        for key, value in data.items():
            try:
                readings[key] = float(value)
                # Also store without "sensor." prefix for compatibility
                if key.startswith("sensor."):
                    readings[key[7:]] = float(value)
            except (ValueError, TypeError):
                logger.warning(
                    "Invalid value for sensor %s: %s (type: %s)",
                    key,
                    value,
                    type(value).__name__,
                )
                # Store as 0.0 for numeric sensors to prevent calculation errors
                readings[key] = 0.0
                if key.startswith("sensor."):
                    readings[key[7:]] = 0.0

        # Validate that we have the minimum required sensors
        # Check for required sensors using resolved entity IDs
        required_sensors = []
        required_keys = ["battery_soc", "lifetime_load_consumption"]
        for key in required_keys:
            entity_id = self.ha_controller.resolve_sensor_for_influxdb(key)
            if entity_id:
                required_sensors.append(entity_id)
            else:
                logger.warning(f"Required sensor key '{key}' not configured")

        missing_sensors = []
        for sensor in required_sensors:
            if sensor not in readings and f"sensor.{sensor}" not in readings:
                missing_sensors.append(sensor)

        if missing_sensors:
            logger.warning("Missing critical sensors: %s", missing_sensors)

        return readings

    def check_battery_health(self) -> dict:
        """Check battery monitoring health, with all sensors required for critical battery operation."""
        # Define required methods
        required_battery_methods = [
            "get_battery_soc",
            "get_battery_charge_power",
            "get_battery_discharge_power",
        ]

        # Define optional methods
        optional_battery_methods = []

        # Combine all methods for health check
        all_battery_methods = required_battery_methods + optional_battery_methods

        return perform_health_check(
            component_name="Battery Monitoring",
            description="Real-time battery state and power monitoring",
            is_required=True,
            controller=self.ha_controller,
            all_methods=all_battery_methods,
            required_methods=required_battery_methods,
        )

    def check_energy_health(self) -> dict:
        """Check energy monitoring health, with all sensors required except EV."""

        # Define required methods (critical for energy flow calculations)
        required_energy_methods = [
            "get_grid_import_lifetime",
            "get_grid_export_lifetime",
            "get_solar_production_lifetime",
            "get_load_consumption_lifetime",
            "get_battery_charged_lifetime",
            "get_battery_discharged_lifetime",
        ]

        # Define optional methods (nice-to-have but not critical)
        optional_energy_methods = [
            # "get_ev_energy",  # Optional - EV data not critical for basic operation
        ]

        # Combine all methods for health check
        all_energy_methods = required_energy_methods + optional_energy_methods

        return perform_health_check(
            component_name="Energy Monitoring",
            description="Tracks energy flows and consumption patterns",
            is_required=True,
            controller=self.ha_controller,
            all_methods=all_energy_methods,
            required_methods=required_energy_methods,
        )

    def check_prediction_health(self) -> dict:
        """Check prediction health, with no sensors required (nice-to-have for optimization)."""
        # Define required methods
        required_prediction_methods = []

        # Define optional methods
        optional_prediction_methods = [
            "get_estimated_consumption",
            "get_solar_forecast",
        ]

        # Combine all methods for health check
        all_prediction_methods = (
            required_prediction_methods + optional_prediction_methods
        )

        return perform_health_check(
            component_name="Energy Prediction",
            description="Solar and consumption forecasting for optimization",
            is_required=False,
            controller=self.ha_controller,
            all_methods=all_prediction_methods,
            required_methods=required_prediction_methods,
        )

    def check_health(self) -> list:
        """Check ALL sensor data collection capabilities - returns list of separate checks."""
        return [
            self.check_battery_health(),
            self.check_energy_health(),
            self.check_prediction_health(),
        ]
