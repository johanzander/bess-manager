"""
Robust SensorCollector - Clean sensor data collection with strategic intent reconstruction.

Historical per-period data is read from Home Assistant's recorder via
``ha_recorder_helper`` (#722). Runtime collection uses live sensors plus the
in-process ``PowerSampleBuffer`` (#387).
"""

import logging
from datetime import timedelta
from typing import ClassVar

from . import time_utils
from .energy_flow_calculator import EnergyFlowCalculator
from .exceptions import HistoricalDataUnavailableError
from .ha_recorder_helper import get_power_sensor_data_batch, get_sensor_data_batch
from .health_check import perform_health_check
from .models import EnergyData
from .power_sample_buffer import PowerSampleBuffer
from .settings import BatterySettings

logger = logging.getLogger(__name__)


class SensorCollector:
    """Collects sensor data from Home Assistant and calculates energy flows with strategic intent reconstruction."""

    def __init__(self, ha_controller, battery_settings: BatterySettings):
        """Initialize sensor collector.

        Args:
            ha_controller: Home Assistant API controller
            battery_settings: Battery settings reference (shared, always up-to-date)
        """
        self.ha_controller = ha_controller
        self.battery_settings = battery_settings
        self.energy_flow_calculator = EnergyFlowCalculator(
            battery_settings, ha_controller
        )

        # Batch mode: fetch all periods in 1-2 queries instead of 176 (98% faster)
        self._batch_cache = {}  # {date: {period: {sensor: value}}}
        self._batch_cache_loaded_on = (
            {}
        )  # {date: date_loaded} - tracks when each batch was loaded

        # Simple cache: last known cumulative sensor readings (for current - previous = delta)
        self._last_readings: dict[str, float] | None = None

        # Cumulative sensors we track from the HA recorder.
        # Only the 5 core energy sensors + battery_soc are collected.
        # load_consumption, system_production, and self_consumption are
        # derived by EnergyFlowCalculator from these 5 core sensors.
        self.cumulative_sensor_keys = [
            "lifetime_battery_charged",
            "lifetime_battery_discharged",
            "lifetime_solar_energy",
            "lifetime_import_from_grid",
            "lifetime_export_to_grid",
            "battery_soc",
        ]

        # Resolve to actual entity IDs for recorder queries
        self.cumulative_sensors = self._resolve_sensor_entity_ids()

        # Power sensors (W) for high-resolution gap-filling
        # Maps power sensor keys to the same flow names used by energy_flow_calculator
        self.power_sensor_flow_map: dict[str, str] = {
            "pv_power": "solar_production",
            "local_load_power": "load_consumption",
            "import_power": "import_from_grid",
            "export_power": "export_to_grid",
            "battery_charge_power": "battery_charged",
            "battery_discharge_power": "battery_discharged",
        }
        self.power_sensors = self._resolve_power_sensor_ids()
        self._power_batch_cache: dict = {}  # {date: {period: {sensor: kwh_value}}}
        self._power_batch_cache_loaded_on: dict = {}

        # Live power-sample buffer for in-process runtime gap-fill (#387)
        self._power_sample_buffer = PowerSampleBuffer()

    def _resolve_sensor_entity_ids(self) -> list[str]:
        """Resolve sensor keys to entity IDs using the controller's abstraction layer.

        Returns entity IDs without the 'sensor.' prefix, as the recorder helper expects.
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
            f"Resolved {len(resolved_ids)} sensor entity IDs for recorder queries"
        )
        return resolved_ids

    def re_resolve_sensors(self) -> None:
        """Re-resolve sensor entity IDs from the controller.

        Called after wizard setup applies new sensor configuration so that
        recorder backfill uses the correct entity IDs instead of the empty
        lists built at startup before sensors were configured.
        """
        self.cumulative_sensors = self._resolve_sensor_entity_ids()
        self.power_sensors = self._resolve_power_sensor_ids()
        self.energy_flow_calculator.rebuild_sensor_mapping()

    def _shared_signed_power_entities(self) -> set[str]:
        """Entity IDs that back more than one power flow key.

        Some platforms publish one signed sensor where BESS wants two
        directional readings — battery power on native SolaX / Huawei (#542),
        grid power on Solis / Huawei (#475/#438) — so both keys resolve to the
        same entity and HAApiController splits the live reading by sign.

        That split is impossible here: the recorder returns a period *mean* of the
        entity, in which charge and discharge (or import and export) have
        already cancelled into one number. Such entities are therefore
        excluded from the recorder power path entirely rather than being
        attributed to whichever flow ``power_sensor_flow_map`` happens to
        iterate last. The live PowerSampleBuffer path (#387) still covers
        these installs — it samples through the sign-splitting getters.
        """
        seen: dict[str, int] = {}
        for sensor_key in self.power_sensor_flow_map:
            entity_id = self.ha_controller.resolve_sensor_for_influxdb(sensor_key)
            if entity_id:
                seen[entity_id] = seen.get(entity_id, 0) + 1
        return {entity_id for entity_id, count in seen.items() if count > 1}

    def _resolve_power_sensor_ids(self) -> list[str]:
        """Resolve power sensor keys to entity IDs for the recorder.

        Returns list of entity IDs (without 'sensor.' prefix).
        """
        shared = self._shared_signed_power_entities()
        resolved_ids = []
        for sensor_key in self.power_sensor_flow_map:
            entity_id = self.ha_controller.resolve_sensor_for_influxdb(sensor_key)
            if entity_id in shared:
                logger.info(
                    "Power sensor key '%s' resolves to shared signed entity "
                    "'%s' — excluded from HA recorder gap-fill (direction is not "
                    "recoverable from a period mean); live sampling still "
                    "covers it",
                    sensor_key,
                    entity_id,
                )
            elif entity_id:
                resolved_ids.append(entity_id)
                logger.debug(
                    f"Resolved power sensor key '{sensor_key}' to '{entity_id}'"
                )
            else:
                logger.debug(f"Power sensor key '{sensor_key}' not configured")
        logger.info(
            f"Resolved {len(resolved_ids)} power sensor entity IDs for gap-filling"
        )
        return resolved_ids

    def collect_energy_data(self, period: int) -> EnergyData:
        """Collect sensor data for a period and create EnergyData with automatic detailed flows.

        Uses simple cache approach for runtime: current_live - cached_last = delta.
        During startup (cache empty), uses the HA recorder for both current and previous readings.

        Args:
            period: Period index (0-95 for normal day, can be 0-91 or 0-99 for DST)

        Returns:
            EnergyData for the specified period
        """
        if period < 0:
            raise ValueError(f"Invalid period: {period}. Must be non-negative.")

        # Check if this period is complete
        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15
        if period >= current_period:
            raise ValueError(
                f"Period {period} is still in progress or in the future, cannot collect complete data"
            )

        # Determine if we're doing historical backfill or runtime collection
        # Historical: period < current - 1 (collecting old data during startup)
        # Runtime: period == current - 1 (collecting just-completed period)
        # Also treat as historical if no cache exists (startup/restart) - using live
        # sensors for the last completed period would include energy from the
        # currently in-progress period, inflating the last period's data
        is_historical_backfill = (
            period < current_period - 1 or self._last_readings is None
        )

        if is_historical_backfill:
            # HISTORICAL BACKFILL: Use the HA recorder for both current and previous readings
            logger.debug(
                f"Period {period}: Historical backfill (period < current-1) - using the HA recorder for both"
            )

            # Get current period readings from the HA recorder
            current_readings = self._get_period_readings(period, date_offset=0)
            if not current_readings:
                raise HistoricalDataUnavailableError(
                    f"No recorder history available for period {period}. Cannot calculate energy flows."
                )

            # Get previous period readings from the HA recorder
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
                raise HistoricalDataUnavailableError(
                    f"No recorder history available for period {prev_period} (date_offset={date_offset}). "
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

            # Get previous readings: use cache if available, otherwise query the HA recorder
            if self._last_readings is None:
                logger.info(
                    f"Period {period}: First runtime collection, querying the HA recorder for previous period"
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
                    raise HistoricalDataUnavailableError(
                        f"No recorder history available for period {prev_period} (date_offset={date_offset})"
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

        # Gap-filling: when cumulative sensors show zero energy (due to 0.1 kWh resolution),
        # use power (W) sensors which report every ~5 minutes for much higher resolution.
        # Historical backfill sources this from the HA recorder (below); runtime collection uses
        # a live PowerSampleBuffer instead (see the runtime branch further down in this
        # method) so the 15-minute production path never depends on the recorder (#387).
        energy_flow_keys = [
            "solar_production",
            "load_consumption",
            "import_from_grid",
            "export_to_grid",
            "battery_charged",
            "battery_discharged",
        ]
        all_energy_zero = all(
            abs(flow_dict.get(key, 0.0)) < 0.001 for key in energy_flow_keys
        )
        if all_energy_zero and is_historical_backfill:
            target_date = time_utils.today()
            power_flows = self._get_power_based_flows(period, target_date)
            if power_flows:
                for key in energy_flow_keys:
                    if key in power_flows and power_flows[key] > 0.001:
                        flow_dict[key] = power_flows[key]
                logger.info(
                    "Period %d: Gap-filled from HA recorder power sensors: %s",
                    period,
                    {k: f"{v:.4f}" for k, v in power_flows.items() if v > 0.001},
                )
        elif not is_historical_backfill:
            buffer_estimate = self._power_sample_buffer.consume(period)
            if all_energy_zero:
                if buffer_estimate:
                    # Every cumulative-counter delta read zero for this period,
                    # which proves the true energy for each flow is under the
                    # counter's 0.1 kWh tick resolution (a real reading >= 0.1
                    # kWh would have registered on the counter itself). The
                    # buffer's average-of-however-many-samples estimate has no
                    # coverage guarantee, so clamp it to just under that
                    # resolution ceiling before it can flow into cost-basis /
                    # savings calculations (#387 final review).
                    clamped_estimate = {
                        key: min(value, 0.1 - 0.001)
                        for key, value in buffer_estimate.items()
                    }
                    for key in energy_flow_keys:
                        if key in clamped_estimate and clamped_estimate[key] > 0.001:
                            flow_dict[key] = clamped_estimate[key]
                    logger.info(
                        "Period %d: Gap-filled from live power-sample buffer: %s",
                        period,
                        {
                            k: f"{v:.4f}"
                            for k, v in clamped_estimate.items()
                            if v > 0.001
                        },
                    )
            elif buffer_estimate:
                logger.debug(
                    "Period %d: counter vs power-sample estimate: %s",
                    period,
                    {
                        k: f"{flow_dict.get(k, 0.0):.4f} vs {buffer_estimate.get(k, 0.0):.4f}"
                        for k in energy_flow_keys
                        if k in buffer_estimate
                    },
                )

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
        # The recorder returns no sample when SOC hasn't changed for a very long time, because the recorder
        # only stores data points when values change. If SOC has been stable, there's no new
        # data point in the requested time range. Without fallback, this would cause all
        # historical data collection to fail (since SOC is critical).
        #
        # Solution: When SOC is missing from the HA recorder, use the current live value from Home Assistant.
        # This is safe because if the recorder has no data, it means SOC hasn't changed, so the
        # current value IS the historical value.
        #
        # Impact: For periods where the recorder has no SOC data, all will use the same current value,
        # meaning battery_soe_start == battery_soe_end for those periods (which is correct when
        # SOC is stable).
        if battery_soc_end_key not in current_readings:
            logger.warning(
                f"Period {period}: SOC sensor '{battery_soc_end_key}' missing from the HA recorder, "
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
                f"Period {period}: SOC sensor '{battery_soc_end_key}' missing from previous recorder readings, "
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
        soe_start = (battery_soc_start / 100.0) * self.battery_settings.total_capacity
        soe_end = (battery_soc_end / 100.0) * self.battery_settings.total_capacity

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

        For PAST dates (yesterday or earlier), the batch is re-fetched if it was loaded
        on a different day than today. This prevents stale cache issues when the system
        runs continuously across midnight - the batch loaded on Jan 15 at 23:45 would
        miss data from 23:45-23:59, but on Jan 16 we need complete Jan 15 data.

        Args:
            target_date: Date to load data for

        Returns:
            True if data was loaded successfully, False otherwise
        """
        today = time_utils.today()

        # Check if already cached
        if target_date in self._batch_cache:
            # For past dates, verify the cache was loaded TODAY (after the day ended)
            # This ensures we have complete data for that day
            if target_date < today:
                loaded_on = self._batch_cache_loaded_on.get(target_date)
                if loaded_on != today:
                    logger.info(
                        "Invalidating stale batch cache for %s (loaded on %s, today is %s)",
                        target_date.strftime("%Y-%m-%d"),
                        loaded_on.strftime("%Y-%m-%d") if loaded_on else "unknown",
                        today.strftime("%Y-%m-%d"),
                    )
                    del self._batch_cache[target_date]
                    if target_date in self._batch_cache_loaded_on:
                        del self._batch_cache_loaded_on[target_date]
                else:
                    return True
            else:
                # For today, invalidate empty caches so we retry after
                # transient recorder failures (e.g. first boot).
                if not self._batch_cache.get(target_date):
                    logger.info(
                        "Invalidating empty batch cache for today %s",
                        target_date.strftime("%Y-%m-%d"),
                    )
                    del self._batch_cache[target_date]
                    if target_date in self._batch_cache_loaded_on:
                        del self._batch_cache_loaded_on[target_date]
                else:
                    return True

        # Fetch batch data
        logger.info(
            "Loading batch data for %s (%d sensors)",
            target_date.strftime("%Y-%m-%d"),
            len(self.cumulative_sensors),
        )

        result = get_sensor_data_batch(
            self.ha_controller, self.cumulative_sensors, target_date
        )

        if result.get("status") == "success":
            data = result.get("data", {})
            if not data:
                logger.warning(
                    "Batch data for %s returned no periods — the recorder has "
                    "no history for these sensors in that range.",
                    target_date.strftime("%Y-%m-%d"),
                )
                # Cache the empty result so we don't retry the same failing
                # query for every period in the backfill loop.  The quarterly
                # scheduler will naturally re-fetch once the cache expires.
                self._batch_cache[target_date] = {}
                self._batch_cache_loaded_on[target_date] = today
                return False
            self._batch_cache[target_date] = data
            self._batch_cache_loaded_on[target_date] = today
            logger.info(
                "Batch data loaded: %d periods for %s (loaded on %s)",
                len(self._batch_cache[target_date]),
                target_date.strftime("%Y-%m-%d"),
                today.strftime("%Y-%m-%d"),
            )
            return True
        else:
            logger.warning(
                "Failed to load batch data for %s: %s",
                target_date.strftime("%Y-%m-%d"),
                result.get("message", "Unknown error"),
            )
            # Cache the failure so we don't hammer the recorder on every period.
            self._batch_cache[target_date] = {}
            self._batch_cache_loaded_on[target_date] = today
            return False

    def _ensure_power_batch_loaded(self, target_date) -> bool:
        """Load power sensor batch data for a date (lazy, cached like cumulative batch).

        Returns:
            True if data was loaded successfully, False otherwise
        """
        today = time_utils.today()

        if target_date in self._power_batch_cache:
            if target_date < today:
                loaded_on = self._power_batch_cache_loaded_on.get(target_date)
                if loaded_on != today:
                    del self._power_batch_cache[target_date]
                    if target_date in self._power_batch_cache_loaded_on:
                        del self._power_batch_cache_loaded_on[target_date]
                else:
                    return True
            else:
                return True

        if not self.power_sensors:
            logger.debug("No power sensors configured, skipping power batch load")
            return False

        logger.info(
            "Loading power sensor batch for %s (%d sensors)",
            target_date.strftime("%Y-%m-%d"),
            len(self.power_sensors),
        )

        result = get_power_sensor_data_batch(
            self.ha_controller, self.power_sensors, target_date
        )

        if result.get("status") == "success":
            data = result.get("data", {})
            if not data:
                logger.warning(
                    "Power sensor batch for %s returned no periods", target_date
                )
                return False
            self._power_batch_cache[target_date] = data
            self._power_batch_cache_loaded_on[target_date] = today
            logger.info(
                "Power sensor batch loaded: %d periods for %s",
                len(data),
                target_date.strftime("%Y-%m-%d"),
            )
            return True
        else:
            logger.warning(
                "Failed to load power sensor batch for %s: %s",
                target_date.strftime("%Y-%m-%d"),
                result.get("message", "Unknown error"),
            )
            return False

    def _build_power_entity_to_flow_map(self) -> dict[str, str]:
        """Build mapping from power sensor entity IDs (with sensor. prefix) to flow names.

        Returns:
            Dict mapping "sensor.entity_id" -> flow_name
        """
        shared = self._shared_signed_power_entities()
        entity_to_flow = {}
        for sensor_key, flow_name in self.power_sensor_flow_map.items():
            entity_id = self.ha_controller.resolve_sensor_for_influxdb(sensor_key)
            if entity_id and entity_id not in shared:
                entity_to_flow[f"sensor.{entity_id}"] = flow_name
        return entity_to_flow

    def _get_power_based_flows(
        self, period: int, target_date
    ) -> dict[str, float] | None:
        """Get energy flows for a period computed from power (W) sensors.

        Returns flow dict compatible with energy_flow_calculator output, or None if unavailable.
        """
        if not self._ensure_power_batch_loaded(target_date):
            return None

        period_data = self._power_batch_cache.get(target_date, {}).get(period)
        if not period_data:
            return None

        entity_to_flow = self._build_power_entity_to_flow_map()

        flows = {}
        for entity_key, kwh_value in period_data.items():
            flow_name = entity_to_flow.get(entity_key)
            if flow_name:
                flows[flow_name] = kwh_value

        if not flows:
            return None

        logger.debug(
            "Period %d: Power-based flows: %s",
            period,
            {k: f"{v:.4f}" for k, v in flows.items()},
        )
        return flows

    def _get_period_readings(
        self, period: int, date_offset: int = 0
    ) -> dict[str, float] | None:
        """Get sensor readings for a specific period from the HA recorder.

        Args:
            period: Period index (0-95 for normal day)
            date_offset: Days offset (0=today, -1=yesterday, 1=tomorrow)

        Returns:
            Dictionary of sensor readings at period boundary, or None if unavailable
        """
        if period < 0:
            logger.error("Invalid period: %d", period)
            return None

        # Use recorder batch mode
        now = time_utils.now()
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

        # Map sensor keys to ha_controller methods (only core sensors)
        sensor_method_map = {
            "lifetime_battery_charged": "get_battery_charged_lifetime",
            "lifetime_battery_discharged": "get_battery_discharged_lifetime",
            "lifetime_solar_energy": "get_solar_production_lifetime",
            "lifetime_import_from_grid": "get_grid_import_lifetime",
            "lifetime_export_to_grid": "get_grid_export_lifetime",
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

    # Power sensor key -> direct live-reading getter on ha_controller. Reading
    # each sensor individually (kilobyte-sized single-entity requests) is far
    # cheaper at this once-a-minute cadence than the full-instance
    # `_fetch_all_states()` dump (potentially megabytes, every entity in the
    # HA instance) used elsewhere for one-off entity discovery (#387 final
    # review).
    _POWER_SENSOR_GETTERS: ClassVar[dict[str, str]] = {
        "pv_power": "get_pv_power",
        "local_load_power": "get_local_load_power",
        "import_power": "get_import_power",
        "export_power": "get_export_power",
        "battery_charge_power": "get_battery_charge_power",
        "battery_discharge_power": "get_battery_discharge_power",
    }

    def sample_live_power(self) -> None:
        """Record one live power-sensor sample into the rolling buffer.

        Called every minute by the scheduler. No-ops if no power sensors are
        configured. A missing/invalid individual entity is skipped without
        raising - the buffer just records whichever sensors succeeded this
        poll.
        """
        if not self.power_sensors:
            return

        readings: dict[str, float] = {}
        for sensor_key, flow_name in self.power_sensor_flow_map.items():
            getter_name = self._POWER_SENSOR_GETTERS.get(sensor_key)
            if not getter_name:
                continue
            try:
                getter = getattr(self.ha_controller, getter_name)
                value = getter()
                if value is None:
                    continue
                readings[flow_name] = float(value)
            except Exception as e:
                logger.debug(
                    "Skipping power sample for %s: %s",
                    sensor_key,
                    e,
                )

        if not readings:
            return

        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15
        self._power_sample_buffer.record(current_period, readings)

    def warm_readings_cache(self) -> None:
        """Seed _last_readings from live HA sensors.

        Call this after pre-seeding the historical store (e.g. from a debug log
        replay) so that the first runtime collection has a valid baseline to
        compute deltas against, instead of falling back to the recorder.
        """
        readings = self._get_period_readings_from_live_sensors()
        if readings:
            self._last_readings = readings
            logger.info(
                "Sensor readings cache warmed from live sensors (%d sensors)",
                len(readings),
            )
        else:
            logger.warning(
                "warm_readings_cache: no live sensor readings available — runtime collection will fall back to the recorder"
            )

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
                    "Skipping sensor %s with invalid value: %s (type: %s)",
                    key,
                    value,
                    type(value).__name__,
                )

        # Validate that we have the minimum required sensors
        # Check for required sensors using resolved entity IDs
        required_sensors = []
        required_keys = ["battery_soc"]
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
        return perform_health_check(
            component_name="Battery Monitoring",
            description="Real-time battery state and power monitoring",
            is_required=True,
            controller=self.ha_controller,
            all_methods=[
                "get_battery_soc",
                "get_battery_charge_power",
                "get_battery_discharge_power",
            ],
        )

    def check_energy_health(self) -> dict:
        """Check energy monitoring health, with all sensors required."""
        return perform_health_check(
            component_name="Energy Monitoring",
            description="Tracks energy flows and consumption patterns",
            is_required=True,
            controller=self.ha_controller,
            all_methods=[
                "get_grid_import_lifetime",
                "get_grid_export_lifetime",
                "get_solar_production_lifetime",
                "get_load_consumption_lifetime",
                "get_battery_charged_lifetime",
                "get_battery_discharged_lifetime",
            ],
        )

    def check_prediction_health(self, consumption_strategy: str = "sensor") -> dict:
        """Check prediction health for the active consumption strategy.

        Only validates the ``get_estimated_consumption`` sensor when the
        ``sensor`` strategy is active — other strategies (fixed,
        load_power_7d_avg, ha_statistics) do not rely on that HA sensor.

        Under the ``sensor`` strategy that sensor is *required*: every
        optimization run reads it and aborts without it, so no schedule can
        ever be built and the dashboard sits on "Initializing" indefinitely
        (#558). The solar forecast stays optional under every strategy, so
        only the consumption method is named as required.
        """
        all_methods = ["get_solar_forecast"]
        sensor_strategy_active = consumption_strategy == "sensor"
        if sensor_strategy_active:
            all_methods = ["get_estimated_consumption", *all_methods]

        required_methods = (
            ["get_estimated_consumption"] if sensor_strategy_active else []
        )

        # The consumption overlay (#428) is not a strategy, so it is keyed off
        # configuration rather than the active strategy. Once configured it is
        # required: every optimization run reads it, and a malformed one stops
        # schedules being built, so the user needs to see it here rather than
        # in a failed run.
        empty_list_is_ok = set()
        if self.ha_controller.is_sensor_configured("consumption_overlay"):
            all_methods = [*all_methods, "get_consumption_overlay_blocks"]
            required_methods = [*required_methods, "get_consumption_overlay_blocks"]
            # Declaring no blocks is the normal state on an ordinary day, so
            # an empty list here is a healthy reading rather than a missing one.
            empty_list_is_ok.add("get_consumption_overlay_blocks")

        return perform_health_check(
            component_name="Energy Prediction",
            description="Solar and consumption forecasting for optimization",
            is_required=bool(required_methods),
            controller=self.ha_controller,
            all_methods=all_methods,
            required_methods=required_methods or None,
            empty_list_is_ok=empty_list_is_ok or None,
        )

    def check_health(self, consumption_strategy: str = "sensor") -> list:
        """Check ALL sensor data collection capabilities - returns list of separate checks."""
        return [
            self.check_battery_health(),
            self.check_energy_health(),
            self.check_prediction_health(consumption_strategy),
        ]
