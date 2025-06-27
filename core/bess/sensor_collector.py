"""
Robust SensorCollector - Clean sensor data collection from InfluxDB with strategic intent reconstruction.
"""

import logging
from datetime import datetime, time, timedelta
from typing import Any

from .energy_flow_calculator import EnergyFlowCalculator
from .influxdb_helper import get_sensor_data
from .models import EnergyFlow

logger = logging.getLogger(__name__)


class SensorCollector:
    """Collects sensor data from InfluxDB and calculates energy flows with strategic intent reconstruction."""

    def __init__(self, ha_controller, battery_capacity_kwh: float):
        """Initialize sensor collector."""
        self.ha_controller = ha_controller
        self.battery_capacity = battery_capacity_kwh
        self.energy_flow_calculator = EnergyFlowCalculator(battery_capacity_kwh)

        # Cumulative sensors we track
        self.cumulative_sensors = [
            "rkm0d7n04x_lifetime_total_all_batteries_charged",
            "rkm0d7n04x_lifetime_total_all_batteries_discharged",
            "rkm0d7n04x_lifetime_total_solar_energy",
            "rkm0d7n04x_lifetime_total_export_to_grid",
            "rkm0d7n04x_lifetime_total_load_consumption",
            "rkm0d7n04x_lifetime_import_from_grid",
            "rkm0d7n04x_statement_of_charge_soc",
            "rkm0d7n04x_lifetime_system_production",
            "rkm0d7n04x_lifetime_self_consumption",
            "zap263668_energy_meter",
        ]

        logger.info(
            "Initialized SensorCollector with %.1f kWh battery capacity",
            battery_capacity_kwh,
        )

    def analyze_strategic_intent_from_flows(self, flows: dict[str, float]) -> str:
        """Analyze strategic intent from reconstructed energy flows.

        This is the single source of truth for determining intent from sensor data.
        Used both during runtime recording and restart reconstruction.
        """
        battery_charged = flows.get("battery_charged", 0.0)
        battery_discharged = flows.get("battery_discharged", 0.0)
        solar_generated = flows.get("system_production", 0.0)
        home_consumed = flows.get("load_consumption", 0.0)
        grid_imported = flows.get("import_from_grid", 0.0)

        if battery_charged > 0.1:
            if grid_imported > solar_generated:
                return "GRID_CHARGING"  # More grid than solar available
            else:
                return "SOLAR_STORAGE"  # Primarily solar charging
        elif battery_discharged > 0.1:
            if battery_discharged > home_consumed:
                return "EXPORT_ARBITRAGE"
            else:
                return "LOAD_SUPPORT"
        return "IDLE"

    def collect_hour_flows(self, hour: int) -> EnergyFlow | None:
        """
        Collect energy flows for a specific hour with strategic intent reconstruction.
        
        Returns an EnergyFlow object containing all energy flow data for the hour.
        """
        if not 0 <= hour <= 23:
            logger.error("Invalid hour: %d", hour)
            return None

        try:
            # Check if this hour is complete
            now = datetime.now()
            if hour == now.hour:
                logger.debug(
                    "Hour %d is still in progress, cannot collect complete data", hour
                )
                return None
            elif hour > now.hour:
                logger.debug("Hour %d is in the future, cannot collect data", hour)
                return None

            # Get current hour data
            current_readings = self._get_hour_readings(hour)
            if not current_readings:
                logger.warning("No current readings for hour %d", hour)
                return None

            # Get previous hour data (yesterday's 23 for hour 0)
            if hour == 0:
                previous_readings = self._get_hour_readings(23, date_offset=-1)
            else:
                previous_readings = self._get_hour_readings(hour - 1)

            if not previous_readings:
                logger.warning("No previous readings for hour %d", hour)
                return None

            # Calculate flows using energy flow calculator - still returns dict
            flow_dict = self.energy_flow_calculator.calculate_hourly_flows(
                current_readings, previous_readings, hour
            )

            if not flow_dict:
                logger.warning("Failed to calculate flows for hour %d", hour)
                return None

            # Add SOC
            battery_soc = current_readings.get("rkm0d7n04x_statement_of_charge_soc", 10.0)
            battery_soe = (battery_soc / 100.0) * self.battery_capacity
            
            # Create EnergyFlow object
            energy_flow = EnergyFlow(
                hour=hour,
                timestamp=datetime.now(),
                battery_charged=flow_dict.get("battery_charged", 0.0),
                battery_discharged=flow_dict.get("battery_discharged", 0.0),
                system_production=flow_dict.get("system_production", 0.0),
                load_consumption=flow_dict.get("load_consumption", 0.0),
                export_to_grid=flow_dict.get("export_to_grid", 0.0),
                import_from_grid=flow_dict.get("import_from_grid", 0.0),
                grid_to_battery=flow_dict.get("grid_to_battery", 0.0),
                solar_to_battery=flow_dict.get("solar_to_battery", 0.0),
                self_consumption=flow_dict.get("self_consumption", 0.0),
                battery_soc=battery_soc,
                battery_soe=battery_soe,
            )
            
            # Add strategic intent reconstruction
            energy_flow.strategic_intent = self.analyze_strategic_intent_from_flows(flow_dict)

            logger.info(
                "Hour %d: Solar=%.1f, Load=%.1f, SOC=%.1f%%, Intent=%s",
                hour,
                energy_flow.system_production,
                energy_flow.load_consumption,
                energy_flow.battery_soc,
                energy_flow.strategic_intent,
            )

            return energy_flow

        except Exception as e:
            logger.error("Failed to collect hour flows for hour %d: %s", hour, e)
            return None

    def reconstruct_historical_flows(
        self, start_hour: int, end_hour: int
    ) -> dict[int, EnergyFlow]:
        """Reconstruct historical energy flows from InfluxDB with strategic intents."""
        reconstructed_flows = {}
        now = datetime.now()
        current_hour = now.hour
        current_minute = now.minute

        logger.info(
            "Reconstructing flows with intents from hour %d to %d (current time: %02d:%02d)",
            start_hour,
            end_hour,
            current_hour,
            current_minute,
        )

        # Adjust end_hour to only include complete hours
        actual_end_hour = self._get_safe_end_hour(
            end_hour, current_hour, current_minute
        )

        if actual_end_hour < start_hour:
            logger.info(
                "No complete hours available for reconstruction (adjusted end_hour: %d)",
                actual_end_hour,
            )
            return reconstructed_flows

        logger.debug(
            "Adjusted reconstruction range: %d to %d", start_hour, actual_end_hour
        )

        for hour in range(start_hour, actual_end_hour + 1):
            try:
                flows = self.collect_hour_flows(hour)
                if flows:
                    reconstructed_flows[hour] = flows
                    logger.debug(
                        "Hour %d: reconstructed successfully with intent %s",
                        hour,
                        flows.strategic_intent,
                    )
                else:
                    logger.warning("Hour %d: reconstruction failed", hour)

            except Exception as e:
                logger.error("Hour %d: reconstruction error: %s", hour, e)

        logger.info(
            "Reconstructed %d/%d hours successfully with strategic intents",
            len(reconstructed_flows),
            actual_end_hour - start_hour + 1,
        )

        return reconstructed_flows

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

    def get_current_battery_state(self) -> dict[str, Any] | None:
        """Get current battery SOC and energy content."""
        try:
            soc = self.ha_controller.get_battery_soc()
            if soc is None or not 0 <= soc <= 100:
                logger.warning("Invalid SOC: %s", soc)
                return None

            return {
                "soc_percent": soc,
                "energy_kwh": (soc / 100.0) * self.battery_capacity,
                "timestamp": datetime.now(),
            }

        except Exception as e:
            logger.error("Failed to get battery state: %s", e)
            return None

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
                result = get_sensor_data(self.cumulative_sensors, target_datetime)

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
        required_sensors = [
            "rkm0d7n04x_statement_of_charge_soc",
            "rkm0d7n04x_lifetime_total_load_consumption",
        ]

        missing_sensors = []
        for sensor in required_sensors:
            if sensor not in readings and f"sensor.{sensor}" not in readings:
                missing_sensors.append(sensor)

        if missing_sensors:
            logger.warning("Missing critical sensors: %s", missing_sensors)

        return readings

    def validate_hour_completeness(self, hour: int) -> bool:
        """Validate that an hour is complete and data should be available."""
        now = datetime.now()

        # Future hours are never complete
        if hour > now.hour:
            return False

        # Current hour is only complete if we're past minute 58
        if hour == now.hour:
            return now.minute >= 58

        # All other past hours should definitely be complete
        return True

    def get_soc_at_hour_start(self, hour: int) -> float:
        """Get SOC reading from start of specified hour."""
        readings = self._get_hour_readings(hour)
        if not readings:
            raise ValueError(f"No sensor readings available for hour {hour}")

        if "rkm0d7n04x_statement_of_charge_soc" not in readings:
            raise ValueError(f"SOC sensor data missing for hour {hour}")

        return readings["rkm0d7n04x_statement_of_charge_soc"]
