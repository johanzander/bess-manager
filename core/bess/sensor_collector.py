"""
Robust SensorCollector - Clean sensor data collection from InfluxDB with strategic intent reconstruction.
"""

import logging
from datetime import datetime, timedelta

from .energy_flow_calculator import EnergyFlowCalculator
from .health_check import perform_health_check
from .influxdb_helper import get_sensor_data_batch
from .models import EnergyData

logger = logging.getLogger(__name__)


class SensorCollector:
    """Collects sensor data from InfluxDB and calculates energy flows with strategic intent reconstruction."""

    def __init__(self, ha_controller, battery_capacity_kwh: float):
        """Initialize sensor collector.

        Args:
            ha_controller: Home Assistant API controller
            battery_capacity_kwh: Battery capacity in kWh
        """
        self.ha_controller = ha_controller
        self.battery_capacity = battery_capacity_kwh
        self.energy_flow_calculator = EnergyFlowCalculator(
            battery_capacity_kwh, ha_controller
        )

        # Batch mode: fetch all periods in 1-2 queries instead of 176 (98% faster)
        self._batch_cache = {}  # {date: {period: {sensor: value}}}

        # Simple cache: last known cumulative sensor readings (for current - previous = delta)
        self._last_readings: dict[str, float] | None = None

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

    def collect_energy_data(self, period: int) -> EnergyData:
        """Collect sensor data for a period and create EnergyData with automatic detailed flows.

        Uses simple cache approach for runtime: current_live - cached_last = delta.
        During startup (cache empty), uses InfluxDB for both current and previous readings.

        Args:
            period: Period index (0-95 for normal day, can be 0-91 or 0-99 for DST)

        Returns:
            EnergyData for the specified period
        """
        if period < 0:
            raise ValueError(f"Invalid period: {period}. Must be non-negative.")

        # Check if this period is complete
        now = datetime.now()
        current_period = now.hour * 4 + now.minute // 15
        if period >= current_period:
            raise ValueError(
                f"Period {period} is still in progress or in the future, cannot collect complete data"
            )

        # Determine if we're doing historical backfill or runtime collection
        # Historical: period < current - 1 (collecting old data during startup)
        # Runtime: period == current - 1 (collecting just-completed period)
        is_historical_backfill = period < current_period - 1

        if is_historical_backfill:
            # HISTORICAL BACKFILL: Use InfluxDB for both current and previous readings
            logger.debug(
                f"Period {period}: Historical backfill (period < current-1) - using InfluxDB for both"
            )

            # Get current period readings from InfluxDB
            current_readings = self._get_period_readings(period, date_offset=0)
            if not current_readings:
                raise RuntimeError(
                    f"No InfluxDB data available for period {period}. Cannot calculate energy flows."
                )

            # Get previous period readings from InfluxDB
            if period == 0:
                # Period 0 needs yesterday's last period
                prev_period = 95
                date_offset = -1
            else:
                # All other periods need previous period from today
                prev_period = period - 1
                date_offset = 0

            previous_readings = self._get_period_readings(
                prev_period, date_offset=date_offset
            )
            if not previous_readings:
                raise RuntimeError(
                    f"No InfluxDB data available for period {prev_period} (date_offset={date_offset}). "
                    f"Cannot calculate delta for period {period}."
                )
        else:
            # RUNTIME COLLECTION: Use live sensors + cache
            logger.debug(
                f"Period {period}: Runtime collection (period == current-1) - using live sensors + cache"
            )

            # Get current sensor readings from live sensors (END of period)
            current_readings = self._get_period_readings_from_live_sensors()
            if not current_readings:
                raise RuntimeError(
                    f"No live sensor readings available for period {period}"
                )

            # Get previous readings: use cache if available, otherwise query InfluxDB
            if self._last_readings is None:
                logger.info(
                    f"Period {period}: First runtime collection, querying InfluxDB for previous period"
                )
                if period == 0:
                    prev_period = 95
                    date_offset = -1
                else:
                    prev_period = period - 1
                    date_offset = 0
                previous_readings = self._get_period_readings(
                    prev_period, date_offset=date_offset
                )
                if not previous_readings:
                    raise RuntimeError(
                        f"No InfluxDB data available for period {prev_period} (date_offset={date_offset})"
                    )
            else:
                # Use cached readings from previous period (START of period)
                previous_readings = self._last_readings

        # Calculate energy flows using existing calculator
        flow_dict = self.energy_flow_calculator.calculate_period_flows(
            current_readings, previous_readings
        )
        if not flow_dict:
            raise RuntimeError(f"Energy flow calculation failed for period {period}")

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

        # SOC Fallback Strategy:
        # InfluxDB returns None when SOC hasn't changed for a very long time, because InfluxDB
        # only stores data points when values change. If SOC has been stable, there's no new
        # data point in the requested time range. Without fallback, this would cause all
        # historical data collection to fail (since SOC is critical).
        #
        # Solution: When SOC is missing from InfluxDB, use the current live value from Home Assistant.
        # This is safe because if InfluxDB has no data, it means SOC hasn't changed, so the
        # current value IS the historical value.
        #
        # Impact: For periods where InfluxDB has no SOC data, all will use the same current value,
        # meaning battery_soe_start == battery_soe_end for those periods (which is correct when
        # SOC is stable).
        if battery_soc_end_key not in current_readings:
            logger.warning(
                f"Period {period}: SOC sensor '{battery_soc_end_key}' missing from InfluxDB, "
                "attempting to read current value from Home Assistant as fallback"
            )
            try:
                current_soc = self.ha_controller.get_battery_soc()
                current_readings[battery_soc_end_key] = current_soc
                logger.info(
                    f"Period {period}: Using current SOC from HA as fallback: {current_soc}%"
                )
            except Exception as e:
                raise KeyError(
                    f"Period {period}: Missing end SOC sensor '{battery_soc_end_key}' in current readings "
                    f"and failed to read from Home Assistant: {e}"
                ) from e

        # Check for SOC in previous readings, fallback to current value if missing
        if battery_soc_end_key not in previous_readings:
            logger.warning(
                f"Period {period}: SOC sensor '{battery_soc_end_key}' missing from previous InfluxDB readings, "
                "using current value from Home Assistant as fallback"
            )
            try:
                current_soc = self.ha_controller.get_battery_soc()
                previous_readings[battery_soc_end_key] = current_soc
                logger.info(
                    f"Period {period}: Using current SOC from HA for previous reading as fallback: {current_soc}%"
                )
            except Exception as e:
                raise KeyError(
                    f"Period {period}: Missing start SOC sensor '{battery_soc_end_key}' in previous readings "
                    f"and failed to read from Home Assistant: {e}"
                ) from e

        battery_soc_end = current_readings[battery_soc_end_key]
        battery_soc_start = previous_readings[battery_soc_end_key]

        # Validate SOC readings
        if not 0 <= battery_soc_start <= 100:
            raise ValueError(
                f"Period {period}: Invalid start SOC {battery_soc_start}%. Must be 0-100%."
            )

        if not 0 <= battery_soc_end <= 100:
            raise ValueError(
                f"Period {period}: Invalid end SOC {battery_soc_end}%. Must be 0-100%."
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

        logger.debug(
            "Collected EnergyData for period %d: SOE %.1f -> %.1f kWh, Solar: %.2f kWh, Load: %.2f kWh, Detailed flows auto-calculated",
            period,
            soe_start,
            soe_end,
            energy_data.solar_production,
            energy_data.home_consumption,
        )

        # Update cache with current readings for next period
        self._last_readings = current_readings
        logger.debug(
            f"Period {period}: Updated cache with current readings for next period"
        )

        return energy_data

    def _ensure_batch_data_loaded(self, target_date) -> bool:
        """Ensure batch data is loaded for the target date.

        Args:
            target_date: Date to load data for

        Returns:
            True if data was loaded successfully, False otherwise
        """
        # Check if already cached
        if target_date in self._batch_cache:
            return True

        # Fetch batch data
        logger.info(
            "Loading batch data for %s (%d sensors)",
            target_date.strftime("%Y-%m-%d"),
            len(self.cumulative_sensors),
        )

        result = get_sensor_data_batch(self.cumulative_sensors, target_date)

        if result.get("status") == "success":
            self._batch_cache[target_date] = result.get("data", {})
            logger.info(
                "Batch data loaded: %d periods for %s",
                len(self._batch_cache[target_date]),
                target_date.strftime("%Y-%m-%d"),
            )
            return True
        else:
            logger.warning(
                "Failed to load batch data for %s: %s",
                target_date.strftime("%Y-%m-%d"),
                result.get("message", "Unknown error"),
            )
            return False

    def _get_period_readings(
        self, period: int, date_offset: int = 0
    ) -> dict[str, float] | None:
        """Get sensor readings for specific period from InfluxDB.

        Args:
            period: Period index (0-95 for normal day)
            date_offset: Days offset (0=today, -1=yesterday, 1=tomorrow)

        Returns:
            Dictionary of sensor readings at period boundary, or None if unavailable
        """
        if period < 0:
            logger.error("Invalid period: %d", period)
            return None

        # Use InfluxDB batch mode
        now = datetime.now()
        target_date = now.date() + timedelta(days=date_offset)

        # Ensure batch data is loaded for this date
        if not self._ensure_batch_data_loaded(target_date):
            logger.error(
                "Failed to load batch data for %s", target_date.strftime("%Y-%m-%d")
            )
            return None

        # Get data from cache
        period_data = self._batch_cache.get(target_date, {}).get(period)
        if not period_data:
            logger.warning(
                "Period %d not found in batch cache for %s",
                period,
                target_date.strftime("%Y-%m-%d"),
            )
            return None

        logger.debug(
            "Period %d (offset %d): Using cached batch data (%d sensors)",
            period,
            date_offset,
            len(period_data),
        )

        # Normalize sensor readings
        return self._normalize_sensor_readings(period_data)

    def _get_period_readings_from_live_sensors(self) -> dict[str, float] | None:
        """Get current sensor readings from live HA API.

        Returns:
            Dictionary of sensor readings (cumulative values), or None if unavailable
        """
        readings = {}

        # Map sensor keys to ha_controller methods
        sensor_method_map = {
            "lifetime_battery_charged": "get_battery_charged_lifetime",
            "lifetime_battery_discharged": "get_battery_discharged_lifetime",
            "lifetime_solar_energy": "get_solar_production_lifetime",
            "lifetime_load_consumption": "get_load_consumption_lifetime",
            "lifetime_import_from_grid": "get_grid_import_lifetime",
            "lifetime_export_to_grid": "get_grid_export_lifetime",
            "lifetime_system_production": "get_system_production_lifetime",
            "lifetime_self_consumption": "get_self_consumption_lifetime",
            "ev_energy_meter": "get_ev_energy",
            "battery_soc": "get_battery_soc",
        }

        for sensor_key in self.cumulative_sensor_keys:
            method_name = sensor_method_map.get(sensor_key)
            if not method_name:
                logger.debug(f"No HA method mapped for sensor key: {sensor_key}")
                continue

            try:
                # Get the method from ha_controller
                method = getattr(self.ha_controller, method_name, None)
                if method is None:
                    logger.debug(f"Method {method_name} not found on ha_controller")
                    continue

                # Call the method to get current value
                value = method()
                if value is not None:
                    # Get entity ID for this sensor key
                    entity_id = self.ha_controller.resolve_sensor_for_influxdb(
                        sensor_key
                    )
                    if entity_id:
                        readings[entity_id] = float(value)
                        logger.debug(f"Live sensor {sensor_key} = {value}")

            except Exception as e:
                logger.warning(f"Failed to read live sensor {sensor_key}: {e}")
                continue

        if not readings:
            logger.error("No live sensor readings available")
            return None

        logger.debug(f"Read {len(readings)} live sensors from HA API")
        return self._normalize_sensor_readings(readings)

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
