"""
Complete replacement for battery_system.py that preserves ALL functionality.

"""

import dataclasses
import json
import logging
import os
import statistics
from datetime import date, datetime, timedelta
from typing import Any

from . import time_utils
from .daily_view_builder import DailyView, DailyViewBuilder
from .dp_battery_algorithm import (
    OptimizationResult,
    optimize_battery_schedule,
    print_optimization_results,
)
from .dp_schedule import DPSchedule
from .exceptions import (
    SystemConfigurationError,
)
from .ha_api_controller import HomeAssistantAPIController
from .health_check import run_system_health_checks
from .historical_data_store import HistoricalDataStore
from .min_schedule import GrowattScheduleManager
from .models import (
    DecisionData,
    EconomicData,
    EconomicSummary,
    EnergyData,
    PeriodData,
    infer_intent_from_flows,
)
from .octopus_energy_source import OctopusEnergySource
from .power_monitor import HomePowerMonitor
from .prediction_snapshot import PredictionSnapshotStore
from .price_manager import HomeAssistantSource, PriceManager, PriceSource
from .runtime_failure_tracker import RuntimeFailureTracker
from .schedule_store import ScheduleStore
from .sensor_collector import SensorCollector
from .settings import (
    BatterySettings,
    HomeSettings,
    PriceSettings,
    TemperatureDeratingSettings,
    apply_temperature_derating,
)
from .sph_schedule import SphScheduleManager
from .time_utils import (
    format_period,
    get_period_count,
    period_index_to_timestamp,
)
from .weather import fetch_temperature_forecast

logger = logging.getLogger(__name__)


class BatterySystemManager:
    """
    Complete replacement for the original BatterySystemManager.

    This implementation:
    - Preserves ALL original functionality
    - Maintains the exact same API and interface
    - Implements proper component separation
    - Fixes all broken functionality in minimal implementations
    - Can be used as a drop-in replacement
    """

    def __init__(
        self,
        controller: HomeAssistantAPIController | None = None,
        price_source: PriceSource | None = None,
        energy_provider_config: dict | None = None,
        addon_options: dict | None = None,
    ):
        """Initialize with same interface as original BatterySystemManager."""

        # Initialize settings (preserve original defaults)
        self.battery_settings = BatterySettings()
        self.home_settings = HomeSettings()
        self.price_settings = PriceSettings()
        self._energy_provider_config = energy_provider_config or {}
        self._addon_options = addon_options or {}

        # Initialize temperature derating (opt-in, disabled by default)
        self.temperature_derating = TemperatureDeratingSettings()
        self.temperature_derating.from_ha_config(self._addon_options)

        # Store controller reference
        self._controller = controller

        # Initialize core data stores with proper component separation
        self.historical_store = HistoricalDataStore(self.battery_settings)
        self.schedule_store = ScheduleStore()
        self.prediction_snapshot_store = PredictionSnapshotStore()

        # Initialize specialized components
        self.sensor_collector = SensorCollector(controller, self.battery_settings)

        # Initialize view builder
        self.daily_view_builder = DailyViewBuilder(
            self.historical_store,
            self.schedule_store,
            self.battery_settings,
        )

        # Initialize hardware interface with battery settings
        self._schedule_manager: GrowattScheduleManager | SphScheduleManager = (
            self._create_schedule_manager()
        )

        # Initialize price manager
        if not price_source:
            price_source = self._create_price_source(controller)

        self._price_manager = PriceManager(
            price_source=price_source,
            markup_rate=self.price_settings.markup_rate,
            vat_multiplier=self.price_settings.vat_multiplier,
            additional_costs=self.price_settings.additional_costs,
            tax_reduction=self.price_settings.tax_reduction,
            area=self.price_settings.area,
        )

        # Initialize monitors (created in start() if controller available)
        self._power_monitor = None

        # Current schedule tracking
        self._current_schedule = None
        self._initial_soc_pct = None  # SOC at midnight (%), set at period 0

        # Discharge inhibit tracking
        self._desired_discharge_rate: int = 0   # Rate from schedule before inhibit
        self._last_applied_discharge_rate: int = 0  # Last rate written to inverter

        # Prediction caches (populated by _fetch_predictions)
        self._consumption_predictions: list[float] | None = None
        self._solar_predictions: list[float] | None = None

        # Critical sensor failure tracking for graceful degradation
        self._critical_sensor_failures = []

        self._runtime_failure_tracker = RuntimeFailureTracker()

        # Inject failure tracker into controller if available
        if self._controller:
            self._controller.failure_tracker = self._runtime_failure_tracker

        logger.debug("BatterySystemManager initialized")

    @property
    def controller(self) -> HomeAssistantAPIController:
        """Get the Home Assistant controller."""
        if self._controller is None:
            raise RuntimeError("Controller not initialized - system not started")
        return self._controller

    def _create_schedule_manager(self) -> "GrowattScheduleManager | SphScheduleManager":
        """Create a schedule manager instance matching the configured inverter type."""
        _inverter_type = self._addon_options.get("growatt", {}).get(
            "inverter_type", "MIN"
        )
        if _inverter_type == "SPH":
            return SphScheduleManager(battery_settings=self.battery_settings)
        return GrowattScheduleManager(battery_settings=self.battery_settings)

    def _create_price_source(self, controller) -> PriceSource:
        """Create the appropriate price source based on energy_provider config.

        Supports three price providers:
        - "nordpool": Legacy custom Nordpool sensor component
        - "nordpool_official": Official HA Nordpool integration via service calls
        - "octopus": Octopus Energy Agile tariff via HA event entities

        Args:
            controller: HomeAssistantAPIController instance

        Returns:
            Configured PriceSource instance
        """
        config = self._energy_provider_config
        provider = config["provider"]

        if provider == "octopus":
            octopus_config = config["octopus"]
            price_source = OctopusEnergySource(
                ha_controller=controller,
                import_today_entity=octopus_config["import_today_entity"],
                import_tomorrow_entity=octopus_config["import_tomorrow_entity"],
                export_today_entity=octopus_config["export_today_entity"],
                export_tomorrow_entity=octopus_config["export_tomorrow_entity"],
            )
            logger.info("Using Octopus Energy Agile tariff price source")
            return price_source

        if provider == "nordpool_official":
            nordpool_official_config = config["nordpool_official"]
            config_entry_id = nordpool_official_config["config_entry_id"]
            from .official_nordpool_source import OfficialNordpoolSource

            price_source = OfficialNordpoolSource(
                controller,
                config_entry_id,
                vat_multiplier=self.price_settings.vat_multiplier,
            )
            logger.info("Using official Home Assistant Nordpool integration")
            return price_source

        if provider == "nordpool":
            nordpool_config = config["nordpool"]
            logger.info("Using legacy/custom Nordpool sensor integration")
            return HomeAssistantSource(
                controller,
                vat_multiplier=self.price_settings.vat_multiplier,
                today_entity=nordpool_config["today_entity"],
                tomorrow_entity=nordpool_config["tomorrow_entity"],
            )

        raise SystemConfigurationError(
            message=f"Unknown energy provider: {provider!r}. Must be 'nordpool', 'nordpool_official', or 'octopus'."
        )

    def _sync_soc_limits(self) -> None:
        """Sync SOC limits from config to inverter hardware.

        Delegates to the schedule manager which handles the inverter-specific
        mechanism (entity writes for MIN, service calls for SPH).
        Config values are the single source of truth.
        """
        logger.info("Syncing SOC limits from config to inverter...")
        try:
            self._schedule_manager.sync_soc_limits(self.controller)
        except Exception as e:
            logger.warning(
                "Could not sync SOC limits to inverter at startup "
                "(inverter may be temporarily unreachable): %s. "
                "Inverter will retain its current limits. System startup will continue.",
                e,
            )

    def start(self) -> None:
        """Start the system - preserves original functionality."""
        try:
            if self._controller:
                # Initialize power monitor only when feature is enabled
                if self.home_settings.power_monitoring_enabled:
                    self._power_monitor = HomePowerMonitor(
                        self._controller,
                        home_settings=self.home_settings,
                        battery_settings=self.battery_settings,
                    )

                # Run health check before we start using sensors
                self._run_health_check()

                # Initialize schedule from inverter before SOC sync so cached
                # periods are available (required for SPH write-back)
                self._initialize_tou_schedule_from_inverter()

                # Sync SOC limits from config to inverter (config as master)
                self._sync_soc_limits()

                # Initialize historical data - using improved sensor collector
                self._fetch_and_initialize_historical_data()

                # Fetch predictions
                self._fetch_predictions()

            self.log_system_startup()
            logger.info("BatterySystemManager started successfully")

        except Exception as e:
            logger.error(f"Failed to start BatterySystemManager: {e}")
            raise

    def update_battery_schedule(
        self, current_period: int, prepare_next_day: bool = False
    ) -> bool:
        """Main schedule update method for quarterly resolution"""

        # Input validation (no upper bound due to DST transitions)
        if current_period < 0:
            logger.error("Invalid period: %d (must be non-negative)", current_period)
            raise SystemConfigurationError(
                message=f"Invalid period: {current_period} (must be non-negative)"
            )

        if prepare_next_day:
            logger.info(
                "Preparing schedule for next day at period %d (%s)",
                current_period,
                format_period(current_period),
            )
        else:
            logger.info(
                "Updating battery schedule for period %d (%s)",
                current_period,
                format_period(current_period),
            )

        is_first_run = self._current_schedule is None

        try:
            # Handle special cases (midnight, next day prep)
            self._handle_special_cases(current_period, prepare_next_day)

            # Get price data
            prices, price_entries = self._get_price_data(prepare_next_day)
            if not prices:
                logger.warning("Schedule update aborted: No price data available")
                return False

            # Update energy data for completed period
            self._update_energy_data(current_period, is_first_run, prepare_next_day)

            # Get current battery state
            current_soc = self._get_current_battery_soc()
            if current_soc is None:
                logger.error("Failed to get battery SOC")
                return False

            # Gather optimization data
            optimization_data_result = self._gather_optimization_data(
                current_period, current_soc, prepare_next_day, len(prices)
            )

            if optimization_data_result is None:
                logger.error("Failed to gather optimization data")
                return False

            optimization_period, optimization_data = optimization_data_result

            # Run optimization using DP algorithm
            optimization_result = self._run_optimization(
                optimization_period,
                optimization_data,
                prices,
                price_entries,
                prepare_next_day,
            )

            if optimization_result is None:
                logger.error("Failed to optimize battery schedule")
                return False

            # Create new schedule
            schedule_result = self._create_updated_schedule(
                optimization_period,
                optimization_result,
                prices,
                optimization_data,
                is_first_run,
                prepare_next_day,
            )

            if schedule_result is None:
                logger.error("Failed to create updated schedule")
                return False

            temp_schedule, temp_growatt = schedule_result

            # Determine if we should apply the new schedule
            should_apply, reason = self._should_apply_schedule(
                is_first_run,
                current_period,
                prepare_next_day,
                temp_growatt,
                optimization_period,
                temp_schedule,
            )

            # Apply schedule if needed
            if should_apply:
                self._apply_schedule(
                    current_period,
                    temp_schedule,
                    temp_growatt,
                    reason,
                    prepare_next_day,
                )
            else:
                # Update current schedule even when TOU doesn't change
                self._current_schedule = temp_schedule
                self._schedule_manager = (
                    temp_growatt  # Update manager with new schedule
                )

            # Capture prediction snapshot after schedule is applied
            if not prepare_next_day:
                self._capture_prediction_snapshot(
                    optimization_period=optimization_period,
                    optimization_result=optimization_result,
                )

            # Apply current period settings
            if not prepare_next_day:
                self._apply_period_schedule(current_period)
                logger.info(
                    "Applied period settings for period %d (%s)",
                    current_period,
                    format_period(current_period),
                )

            self.log_battery_schedule(current_period)
            return True

        except Exception as e:
            logger.error(f"Failed to update battery schedule: {e}")
            return False

    def log_battery_schedule(self, current_period: int) -> None:
        """Log the current battery schedule."""
        if not self._current_schedule:
            logger.warning("No current schedule available for reporting")
            return

        # Log Growatt TOU schedule and detailed schedule
        self._schedule_manager.log_current_TOU_schedule("=== GROWATT TOU SCHEDULE ===")
        self._schedule_manager.log_detailed_schedule(
            "=== GROWATT DETAILED SCHEDULE ==="
        )

    def _capture_prediction_snapshot(
        self,
        optimization_period: int,
        optimization_result: OptimizationResult,
    ) -> None:
        """Capture snapshot of predictions and actuals using DailyView.

        Args:
            optimization_period: Period when optimization ran (0-95)
            optimization_result: Result from DP optimization
        """
        try:
            # Build daily view (merges actuals + predictions)
            daily_view = self.daily_view_builder.build_daily_view(optimization_period)

            # Get current Growatt schedule
            growatt_schedule = self._schedule_manager.tou_intervals.copy()

            # Store snapshot
            self.prediction_snapshot_store.store_snapshot(
                snapshot_timestamp=time_utils.now(),
                optimization_period=optimization_period,
                daily_view=daily_view,
                growatt_schedule=growatt_schedule,
                predicted_daily_savings=(
                    optimization_result.economic_summary.grid_to_battery_solar_savings
                    if optimization_result.economic_summary
                    else 0.0
                ),
            )

            logger.debug(
                "Captured prediction snapshot at period %d with %d TOU intervals",
                optimization_period,
                len(growatt_schedule),
            )

        except Exception as e:
            logger.warning(f"Failed to capture prediction snapshot: {e}")

    def _initialize_tou_schedule_from_inverter(self) -> None:
        """Initialize schedule from current inverter settings."""
        try:
            logger.info("Reading current TOU schedule from inverter")

            if self._controller is None:
                logger.error(
                    "Controller is not available for reading inverter segments"
                )
                return

            current_hour = time_utils.now().hour
            self._schedule_manager.read_and_initialize_from_hardware(
                self._controller, current_hour
            )

        except Exception as e:
            logger.error(f"Failed to read current inverter schedule: {e}")

    @staticmethod
    def _period_data_from_dict(d: dict) -> PeriodData:
        """Deserialize a PeriodData from a dict produced by dataclasses.asdict()."""
        energy_init_fields = {f.name for f in dataclasses.fields(EnergyData) if f.init}
        energy = EnergyData(**{k: v for k, v in d["energy"].items() if k in energy_init_fields})

        economic_fields = {f.name for f in dataclasses.fields(EconomicData) if f.init}
        economic = EconomicData(**{k: v for k, v in d["economic"].items() if k in economic_fields})

        decision_fields = {f.name for f in dataclasses.fields(DecisionData) if f.init}
        decision = DecisionData(**{k: v for k, v in d["decision"].items() if k in decision_fields})

        ts_raw = d["timestamp"]
        ts = datetime.fromisoformat(ts_raw) if ts_raw else None

        return PeriodData(
            period=d["period"],
            energy=energy,
            timestamp=ts,
            data_source=d["data_source"],
            economic=economic,
            decision=decision,
        )

    def _load_historical_seed(self, current_period: int) -> bool:
        """Seed the historical store from BESS_HISTORICAL_SEED_FILE if set.

        Returns True if seeding succeeded and InfluxDB backfill should be skipped.
        """
        seed_file = os.environ.get("BESS_HISTORICAL_SEED_FILE", "")
        if not seed_file:
            return False

        try:
            with open(seed_file, encoding="utf-8") as f:
                periods: list = json.load(f)
        except Exception as e:
            logger.warning("Failed to load historical seed file '%s': %s", seed_file, e)
            return False

        loaded = 0
        for entry in periods:
            if entry is None:
                continue
            try:
                period_data = self._period_data_from_dict(entry)
                if period_data.period < current_period:
                    self.historical_store.record_period(period_data.period, period_data)
                    loaded += 1
            except Exception as e:
                logger.warning("Skipping malformed seed period: %s", e)

        logger.info("Historical seed loaded: %d periods from '%s'", loaded, seed_file)
        return loaded > 0

    def _fetch_and_initialize_historical_data(self) -> None:
        """Fetch and initialize historical data using quarterly resolution."""
        try:
            now = time_utils.now()
            current_period = now.hour * 4 + now.minute // 15

            logger.info(
                f"Fetching historical data - current period: {current_period} ({format_period(current_period)})"
            )

            if current_period > 0 and self._load_historical_seed(current_period):
                self.sensor_collector.warm_readings_cache()
                return

            if current_period > 0:
                # Get prices once for all periods (fetch outside loop to avoid repeated API calls)
                try:
                    buy_prices, sell_prices = self.price_manager.get_available_prices()
                except Exception as e:
                    logger.warning(f"Could not get prices for historical data: {e}")
                    buy_prices, sell_prices = [], []

                # Collect quarterly data for all completed periods
                for period in range(0, current_period):
                    try:
                        # Collect cumulative sensor readings at period boundary (calculate deltas for energy flows)
                        period_energy_data = self.sensor_collector.collect_energy_data(
                            period
                        )

                        # Calculate economic data using pre-fetched prices
                        if period < len(buy_prices):
                            buy_price = buy_prices[period]
                            sell_price = sell_prices[period]

                            # Calculate battery cycle cost based on actual charging
                            battery_cycle_cost_sek = (
                                period_energy_data.battery_charged
                                * self.battery_settings.cycle_cost_per_kwh
                            )

                            # Use standard economic calculation from EconomicData
                            economic_data = EconomicData.from_energy_data(
                                energy_data=period_energy_data,
                                buy_price=buy_price,
                                sell_price=sell_price,
                                battery_cycle_cost=battery_cycle_cost_sek,
                            )
                        else:
                            # Period beyond available prices
                            economic_data = EconomicData(
                                buy_price=0.0, sell_price=0.0, hourly_savings=0.0
                            )

                        # Store period data with both planned and observed intents
                        # Get DP-planned intent (authoritative) if available
                        planned_intent = self._get_planned_intent_for_period(period)
                        # Infer observed intent from actual flows
                        battery_power = period_energy_data.battery_net_change
                        observed = infer_intent_from_flows(
                            battery_power, period_energy_data
                        )

                        period_data = PeriodData(
                            period=period,  # For backward compatibility, still called 'hour'
                            energy=period_energy_data,
                            timestamp=time_utils.now(),
                            data_source="actual",
                            economic=economic_data,
                            decision=DecisionData(
                                strategic_intent=planned_intent or "IDLE",
                                observed_intent=observed,
                            ),
                        )
                        self.historical_store.record_period(period, period_data)

                        logger.debug(
                            f"Stored period {period} ({format_period(period)}): Solar={period_energy_data.solar_production:.3f} kWh, "
                            f"SOC={period_energy_data.battery_soe_start:.1f}%→{period_energy_data.battery_soe_end:.1f}%"
                        )

                    except Exception as e:
                        logger.warning(
                            f"Failed to collect/store data for period {period} ({format_period(period)}): {e}"
                        )

                # Verify storage using period-based API
                completed_periods = [
                    p
                    for p in range(current_period)
                    if self.historical_store.get_period(p) is not None
                ]

                if completed_periods:
                    # Show the time range covered (start of first period to end of last period)
                    first_period = completed_periods[0]
                    last_period = completed_periods[-1]
                    # Last period END time is 15 minutes after its start
                    last_period_end = last_period + 1
                    logger.info(
                        f"Historical store now contains {len(completed_periods)} periods: "
                        f"{format_period(first_period)} to {format_period(last_period_end)}"
                    )
                else:
                    logger.info("No periods stored in historical store")
            else:
                logger.info("No completed periods, no historical data to fetch")

        except Exception as e:
            logger.error(f"Failed to initialize historical data: {e}")

    def _fetch_predictions(self) -> None:
        """Fetch consumption and solar predictions and store them."""
        try:
            if self._controller is None:
                logger.warning("Cannot fetch predictions: controller is not available")
                return

            consumption_predictions = self._get_consumption_forecast()
            solar_predictions = self._controller.get_solar_forecast()

            # Store the predictions (this was missing!)
            if consumption_predictions:
                self._consumption_predictions = consumption_predictions
                logger.debug(
                    "Fetched consumption predictions: %s",
                    [round(value, 1) for value in consumption_predictions],
                )
            else:
                logger.warning(
                    "Invalid consumption predictions format, keeping defaults"
                )

            if solar_predictions:
                self._solar_predictions = solar_predictions
                logger.info(
                    "Fetched solar predictions: %s",
                    [round(value, 1) for value in solar_predictions],
                )
            else:
                logger.warning("Invalid solar predictions format, keeping defaults")

        except Exception as e:
            logger.warning(f"Failed to fetch predictions: {e}")

    def _get_consumption_forecast(self) -> list[float]:
        """Get consumption forecast based on the configured strategy.

        Dispatches to the appropriate data source based on
        home_settings.consumption_strategy.

        Returns:
            List of 96 float values (kWh per 15-minute period).
        """
        strategy = self.home_settings.consumption_strategy

        if strategy == "sensor":
            return self.controller.get_estimated_consumption()

        if strategy == "fixed":
            quarterly = self.home_settings.default_hourly / 4.0
            return [quarterly] * 96

        if strategy == "influxdb_7d_avg":
            return self._get_influxdb_7d_avg_forecast()

        raise ValueError(f"Unknown consumption_strategy: '{strategy}'")

    def _get_influxdb_7d_avg_forecast(self) -> list[float]:
        """Get consumption forecast from InfluxDB 7-day average profile.

        Queries InfluxDB for the past 7 days of the local_load_power sensor
        and returns the 96-value weekly average profile (kWh per 15-min period).
        """
        from .influxdb_helper import get_power_sensor_data_batch

        sensors_config = self._addon_options.get("sensors", {})
        target_sensor = sensors_config.get("local_load_power", "")
        if not target_sensor:
            raise ValueError(
                "influxdb_7d_avg strategy requires 'local_load_power' sensor configured"
            )

        # Strip 'sensor.' prefix if present — get_power_sensor_data_batch adds it
        if target_sensor.startswith("sensor."):
            target_sensor = target_sensor[len("sensor.") :]

        today = time_utils.today()
        day_profiles: list[list[float]] = []

        for days_back in range(1, 8):
            target_date = today - timedelta(days=days_back)
            result = get_power_sensor_data_batch([target_sensor], target_date)

            if result["status"] != "success":
                logger.warning(
                    "Failed to fetch power data for %s: %s",
                    target_date,
                    result.get("message", "unknown error"),
                )
                continue

            period_data = result["data"]
            sensor_key = f"sensor.{target_sensor}"
            profile = [0.0] * 96
            periods_found = 0
            for period in range(96):
                if period in period_data and sensor_key in period_data[period]:
                    profile[period] = period_data[period][sensor_key]
                    periods_found += 1

            if periods_found >= 48:  # At least half a day of data
                day_profiles.append(profile)
                logger.debug("Got %d periods for %s", periods_found, target_date)

        if not day_profiles:
            logger.warning(
                "No valid historical data for influxdb_7d_avg strategy, "
                "falling back to fixed consumption"
            )
            quarterly = self.home_settings.default_hourly / 4.0
            return [quarterly] * 96

        # Average across all valid days
        avg_profile = [
            sum(p[i] for p in day_profiles) / len(day_profiles) for i in range(96)
        ]

        total_kwh = sum(avg_profile)
        logger.info(
            "InfluxDB 7-day average profile: %.1f kWh/day from %d days of data",
            total_kwh,
            len(day_profiles),
        )

        return avg_profile

    def _handle_special_cases(self, period: int, prepare_next_day: bool) -> None:
        """Handle special cases like midnight transition."""
        if period == 0 and not prepare_next_day:
            try:
                if self._controller is not None:
                    current_soc = self._controller.get_battery_soc()
                    self._initial_soc_pct = current_soc
                    logger.info(
                        f"Setting initial SOC for day: {self._initial_soc_pct}%"
                    )
                else:
                    logger.warning(
                        "Cannot get initial SOC: controller is not available"
                    )
            except Exception as e:
                logger.warning(f"Failed to get initial SOC: {e}")

        if prepare_next_day:
            logger.info(
                "Preparing for next day - clearing historical store and refreshing predictions"
            )
            # Clear historical store to prevent yesterday's data from appearing as today's future data
            self.historical_store.clear()
            self.prediction_snapshot_store.clear()
            self._fetch_predictions()

    def _get_price_data(
        self, prepare_next_day: bool
    ) -> tuple[list[float] | None, list[dict[str, Any]] | None]:
        """Get price data in 15-minute (quarterly) resolution.

        All price sources return 96 quarterly periods per day. Sources with
        coarser raw data (e.g. Octopus 30-min) expand internally.

        When prepare_next_day=False, attempts to extend today's prices with
        tomorrow's data for improved end-of-day optimization. The extended
        horizon is capped at 192 periods (2 days).
        """
        try:
            if prepare_next_day:
                price_entries = self._price_manager.get_tomorrow_prices()
                logger.info("Fetched tomorrow's price data")
            else:
                price_entries = self._price_manager.get_today_prices()

                # Extend with tomorrow's prices when available
                tomorrow_entries = self._price_manager.get_tomorrow_prices()
                if tomorrow_entries:
                    price_entries = price_entries + tomorrow_entries
                    logger.info(
                        "Extended price horizon with %d tomorrow entries (total: %d)",
                        len(tomorrow_entries),
                        len(price_entries),
                    )

            if not price_entries:
                logger.warning("No prices available")
                return None, None

            # Cap at 192 periods (2 days maximum)
            if len(price_entries) > 192:
                price_entries = price_entries[:192]
                logger.info("Capped price entries at 192 periods (2 days)")

            prices = [entry["price"] for entry in price_entries]

            # Validate quarterly period count (handles DST: 92, 96, or 100)
            today_period_count = get_period_count(
                time_utils.today()
            )
            if not prepare_next_day and len(prices) > today_period_count:
                logger.info(
                    "Extended horizon: %d periods (%d today + %d tomorrow)",
                    len(prices),
                    today_period_count,
                    len(prices) - today_period_count,
                )
            elif len(prices) == 92:
                logger.info(
                    "Detected DST spring forward transition (92 quarterly periods)"
                )
            elif len(prices) == 100:
                logger.info("Detected DST fall back transition (100 quarterly periods)")
            elif len(prices) != 96:
                logger.warning(f"Expected 96 quarterly prices but got {len(prices)}")

            return prices, price_entries

        except Exception as e:
            logger.error(f"Failed to fetch price data: {e}")
            return None, None

    def _update_energy_data(
        self, period: int, is_first_run: bool, prepare_next_day: bool
    ) -> None:
        """Track energy data collection with strategic intent."""
        logger.info(
            f"Period: {period} ({format_period(period)}), is_first_run: {is_first_run}, prepare_next_day: {prepare_next_day}"
        )

        if not is_first_run and period > 0 and not prepare_next_day:
            prev_period = period - 1
            logger.info(
                f"Collecting data for previous period: {prev_period} ({format_period(prev_period)})"
            )

            # Use sensor collector to get complete energy data with detailed flows
            # Uses live sensors for current data (fast)
            # Falls back to InfluxDB for historical data at startup/restart
            energy_data = self.sensor_collector.collect_energy_data(prev_period)

            logger.info(
                f"Collected energy data for period {prev_period} ({format_period(prev_period)}) - "
                f"Solar: {energy_data.solar_production:.3f} kWh, "
                f"Load: {energy_data.home_consumption:.3f} kWh, "
                f"SOC: {energy_data.battery_soe_start:.1f}% → {energy_data.battery_soe_end:.1f}%"
            )

            # Get prices for this period
            buy_prices, sell_prices = self.price_manager.get_available_prices()
            if 0 <= prev_period < len(buy_prices):
                buy_price = buy_prices[prev_period]
                sell_price = sell_prices[prev_period]

                # Calculate battery cycle cost based on actual charging
                battery_cycle_cost_sek = (
                    energy_data.battery_charged
                    * self.battery_settings.cycle_cost_per_kwh
                )

                # Calculate economic data from actual energy flows
                economic_data = EconomicData.from_energy_data(
                    energy_data=energy_data,
                    buy_price=buy_price,
                    sell_price=sell_price,
                    battery_cycle_cost=battery_cycle_cost_sek,
                )
            else:
                # Period beyond available prices
                economic_data = EconomicData(
                    buy_price=0.0, sell_price=0.0, hourly_savings=0.0
                )

            # Store using period-based API with both planned and observed intents
            # Get DP-planned intent (authoritative) if available
            planned_intent = self._get_planned_intent_for_period(prev_period)
            # Infer observed intent from actual flows
            battery_power = energy_data.battery_net_change
            observed = infer_intent_from_flows(battery_power, energy_data)

            period_data = PeriodData(
                period=prev_period,
                energy=energy_data,
                timestamp=time_utils.now(),
                data_source="actual",
                economic=economic_data,
                decision=DecisionData(
                    strategic_intent=planned_intent or "IDLE",
                    observed_intent=observed,
                ),
            )
            self.historical_store.record_period(prev_period, period_data)
            logger.info(
                f"Recorded energy data for period {prev_period} ({format_period(prev_period)})"
            )

            # Verify storage
            stored_data = self.historical_store.get_period(prev_period)
            if stored_data:
                logger.info(
                    f"Verified: Period {prev_period} stored with intent {stored_data.decision.strategic_intent}"
                )
            else:
                raise RuntimeError(
                    f"Failed to store energy data for period {prev_period}"
                )

        else:
            logger.info(
                f"Skipping data collection: is_first_run={is_first_run}, period={period}, prepare_next_day={prepare_next_day}"
            )

        # Log energy balance
        if not prepare_next_day:
            self._log_energy_balance()

        # Final check: what periods do we have stored?
        today_periods = self.historical_store.get_today_periods()
        completed_periods = [i for i, p in enumerate(today_periods) if p is not None]
        if completed_periods:
            first_period = completed_periods[0]
            last_period = completed_periods[-1]
            # Last period END time is 15 minutes after its start
            last_period_end = last_period + 1
            logger.info(
                f"Historical store: {len(completed_periods)} periods "
                f"({format_period(first_period)} to {format_period(last_period_end)})"
            )
        else:
            logger.info("Historical store: no periods stored yet")

    def _get_planned_intent_for_period(self, period: int) -> str | None:
        """Get the DP-planned strategic intent for a period.

        First checks in-memory schedule store, then falls back to persisted intents
        (for restart recovery when schedule store is empty but disk has data).

        Args:
            period: Period index (0-95)

        Returns:
            Strategic intent string if available, None otherwise
        """
        # First try the in-memory schedule store
        latest_schedule = self.schedule_store.get_latest_schedule()
        if latest_schedule is not None:
            result = latest_schedule.optimization_result
            if result.period_data:
                opt_period = latest_schedule.optimization_period

                # Check if this period is within the optimization range
                if opt_period <= period < opt_period + len(result.period_data):
                    index = period - opt_period
                    period_data = result.period_data[index]
                    return period_data.decision.strategic_intent

        # Fall back to persisted intents (loaded from disk on startup)
        return self.schedule_store.get_persisted_intent(period)

    def _get_current_battery_soc(self) -> float | None:
        """Get current battery SOC with validation."""
        try:
            if self._controller:
                soc = self._controller.get_battery_soc()
                if soc is not None and 0 <= soc <= 100:
                    return soc
                else:
                    logger.warning(f"Invalid SOC from controller: {soc}")

            # TODO: Remove this fallback - it appears to never be used in practice
            # If we reach here, the controller failed to provide valid SOC
            logger.warning(
                "Controller failed to provide valid SOC. This fallback code path "
                "should be investigated and potentially removed if never used."
            )
            return None  # Return None to indicate failure rather than using unreliable fallback

        except Exception as e:
            logger.error(f"Failed to get battery SOC: {e}")
            return None

    def _gather_optimization_data(
        self, period: int, current_soc: float, prepare_next_day: bool, period_count: int
    ) -> tuple[int, dict[str, list[float]]] | None:
        """Always return full period data combining actuals + predictions with correct SOC progression.

        Args:
            period: Current period index
            current_soc: Current state of charge (%)
            prepare_next_day: Whether preparing for next day
            period_count: Number of periods in the day (handles DST: 92, 96, or 100)
        """

        if period < 0:
            logger.error(f"Invalid period: {period} (must be non-negative)")
            return None

        current_soe = current_soc / 100.0 * self.battery_settings.total_capacity

        # Build arrays dynamically based on period_count (handles DST)
        consumption_data = [0.0] * period_count
        solar_data = [0.0] * period_count
        combined_soe = [0.0] * period_count
        combined_actions = [0.0] * period_count
        solar_charged = [0.0] * period_count

        if prepare_next_day:
            # For next day, use predictions only
            consumption_predictions = self._get_consumption_forecast()
            solar_predictions = self.controller.get_solar_forecast()

            consumption_data = consumption_predictions
            solar_data = solar_predictions

            # Initialize all periods with minimal SOC for next day
            initial_soe = self.battery_settings.min_soe_kwh
            combined_soe = [initial_soe] * period_count

            optimization_period = 0

        else:
            # For today, properly calculate SOC progression
            today_periods = self.historical_store.get_today_periods()
            completed_periods = [
                i for i, p in enumerate(today_periods) if p is not None
            ]
            predictions_consumption = self._get_consumption_forecast()
            predictions_solar = self.controller.get_solar_forecast()

            # Extend predictions for tomorrow when horizon exceeds today
            if period_count > len(predictions_consumption):
                # Consumption: repeat today's uniform pattern for tomorrow
                tomorrow_consumption = predictions_consumption.copy()
                predictions_consumption = predictions_consumption + tomorrow_consumption
                logger.info(
                    "Extended consumption predictions to %d periods for tomorrow horizon",
                    len(predictions_consumption),
                )

            if period_count > len(predictions_solar):
                # Solar: use tomorrow's forecast if available, else zeros
                try:
                    tomorrow_solar = self.controller.get_solar_forecast_tomorrow()
                    logger.info(
                        "Extended solar predictions with tomorrow's forecast (%d periods)",
                        len(tomorrow_solar),
                    )
                except SystemConfigurationError:
                    tomorrow_date = date.today() + timedelta(days=1)
                    tomorrow_solar = [0.0] * get_period_count(tomorrow_date)
                    logger.info(
                        "Tomorrow's solar forecast unavailable, using zeros for extended horizon"
                    )
                predictions_solar = predictions_solar + tomorrow_solar

            # Track running SOC for proper progression
            running_soe = current_soe

            for p in range(period_count):
                if p in completed_periods and p < period:
                    # Use actual data for past periods
                    event = self.historical_store.get_period(p)
                    if event:
                        consumption_data[p] = event.energy.home_consumption
                        solar_data[p] = event.energy.solar_production
                        combined_soe[p] = event.energy.battery_soe_end
                        combined_actions[p] = (
                            event.energy.battery_charged
                            - event.energy.battery_discharged
                        )
                        solar_charged[p] = min(
                            event.energy.battery_charged, event.energy.solar_production
                        )
                        # Update running SOE to the end state of this period
                        running_soe = combined_soe[p]
                    else:
                        # Fallback to predictions if event missing
                        consumption_data[p] = (
                            predictions_consumption[p]
                            if p < len(predictions_consumption)
                            else 1.0
                        )
                        solar_data[p] = (
                            predictions_solar[p] if p < len(predictions_solar) else 0.0
                        )
                        # Use the last known SOE for missing data
                        combined_soe[p] = running_soe
                else:
                    # Use predictions for current and future periods
                    consumption_data[p] = (
                        predictions_consumption[p]
                        if p < len(predictions_consumption)
                        else 1.0
                    )
                    solar_data[p] = (
                        predictions_solar[p] if p < len(predictions_solar) else 0.0
                    )

                    # Set correct SOE for optimization starting point
                    if p == period:
                        # This is the optimization starting period - use current SOE
                        combined_soe[p] = current_soe
                        running_soe = current_soe
                    else:
                        # For other future periods, use running SOE (will be updated by optimization)
                        combined_soe[p] = running_soe

            optimization_period = period

        # Ensure current period has correct SOE
        if not prepare_next_day:
            combined_soe[optimization_period] = current_soe

        optimization_data = {
            "full_consumption": consumption_data,
            "full_solar": solar_data,
            "combined_actions": combined_actions,
            "combined_soe": combined_soe,
            "solar_charged": solar_charged,
        }

        logger.debug(f"Optimization data prepared for period {optimization_period}")
        logger.debug(
            f"SOE progression check - Period {period-1}: {combined_soe[period-1]:.1f}, Period {period}: {combined_soe[period]:.1f}"
        )

        return optimization_period, optimization_data

    def _calculate_terminal_value(
        self, buy_prices: list[float], optimization_period: int
    ) -> float:
        """Calculate terminal value per kWh for the DP optimization.

        When the horizon already extends past today (i.e. tomorrow's prices are
        included), return 0.0 since the DP has explicit future data. Otherwise,
        estimate value from the median buy price adjusted for efficiency
        and cycle cost.

        Using the median avoids inflating the terminal value with peak prices.

        Args:
            buy_prices: Full buy price array (from optimization_period onwards)
            optimization_period: Current optimization starting period

        Returns:
            Terminal value per kWh (floored at 0.0)
        """
        today_period_count = get_period_count(
            time_utils.today()
        )
        remaining_today = today_period_count - optimization_period
        total_horizon = len(buy_prices)

        # If horizon extends past today, DP has explicit tomorrow data
        if total_horizon > remaining_today:
            logger.info(
                "Horizon extends past today (%d > %d remaining), terminal value = 0.0",
                total_horizon,
                remaining_today,
            )
            return 0.0

        # Estimate terminal value using median (resistant to peak price outliers)
        if not buy_prices:
            return 0.0

        median_price = statistics.median(buy_prices)
        terminal_value = (
            median_price * self.battery_settings.efficiency_discharge
            - self.battery_settings.cycle_cost_per_kwh
        )
        terminal_value = max(0.0, terminal_value)

        logger.info(
            "Terminal value: %.3f/kWh (median_price=%.3f, efficiency=%.2f, cycle_cost=%.3f)",
            terminal_value,
            median_price,
            self.battery_settings.efficiency_discharge,
            self.battery_settings.cycle_cost_per_kwh,
        )
        return terminal_value

    def _get_temperature_derated_charge_limits(
        self, num_periods: int
    ) -> list[float] | None:
        """Get per-period max charge power limits based on temperature forecast.

        When temperature derating is enabled, fetches the weather forecast and
        applies the configured derating curve to produce per-period charge limits.

        Args:
            num_periods: Number of 15-minute periods to produce limits for.

        Returns:
            List of max charge power values (kW) per period, or None if derating
            is disabled.

        Raises:
            RuntimeError: If the weather forecast cannot be fetched (propagated
                from fetch_temperature_forecast).
        """
        if not self.temperature_derating.enabled:
            return None

        weather_entity = self.temperature_derating.weather_entity
        if not weather_entity:
            logger.warning(
                "Temperature derating enabled but weather_entity not configured "
                "- skipping derating"
            )
            return None

        # Get timezone from time_utils (set at startup from HA config)
        timezone_str = str(time_utils.TIMEZONE)

        temperatures = fetch_temperature_forecast(
            ha_url=self.controller.base_url,
            ha_token=self.controller.token,
            weather_entity=weather_entity,
            timezone=timezone_str,
            num_periods=num_periods,
        )

        derated_limits = apply_temperature_derating(
            max_charge_power_kw=self.battery_settings.max_charge_power_kw,
            temperatures=temperatures,
            derating_curve=self.temperature_derating.derating_curve,
        )

        # Log summary for diagnostics
        min_temp = min(temperatures)
        max_temp = max(temperatures)
        min_power = min(derated_limits)
        max_power = max(derated_limits)
        logger.info(
            f"Temperature derating active: temp range {min_temp:.1f}-{max_temp:.1f}°C, "
            f"charge power range {min_power:.1f}-{max_power:.1f}kW "
            f"(nominal {self.battery_settings.max_charge_power_kw:.1f}kW)"
        )

        return derated_limits

    def _run_optimization(
        self,
        optimization_period: int,
        optimization_data: dict[str, list[float]],
        prices: list[float],
        price_entries: list[dict[str, Any]],
        prepare_next_day: bool,
    ) -> OptimizationResult | None:
        """Run optimization - now returns OptimizationResult directly."""

        try:
            current_soe = optimization_data["combined_soe"][optimization_period]

            # Calculate initial cost basis
            if prepare_next_day:
                initial_cost_basis = self.battery_settings.cycle_cost_per_kwh
            else:
                initial_cost_basis = self._calculate_initial_cost_basis(
                    optimization_period
                )

            # Get optimization portions (slice from current period)
            remaining_prices = prices[optimization_period:]
            remaining_consumption = optimization_data["full_consumption"][
                optimization_period:
            ]
            remaining_solar = optimization_data["full_solar"][optimization_period:]

            # Ensure array lengths match
            n_periods = len(remaining_prices)
            if len(remaining_consumption) != n_periods:
                if len(remaining_consumption) < n_periods:
                    remaining_consumption.extend(
                        [1.0] * (n_periods - len(remaining_consumption))
                    )
                else:
                    remaining_consumption = remaining_consumption[:n_periods]

            if len(remaining_solar) != n_periods:
                if len(remaining_solar) < n_periods:
                    remaining_solar.extend([0.0] * (n_periods - len(remaining_solar)))
                else:
                    remaining_solar = remaining_solar[:n_periods]

            logger.info(
                f"Running optimization for {n_periods} periods from {format_period(optimization_period)}"
            )

            # Get buy and sell prices from pre-calculated price entries
            # This preserves direct sell prices from sources like Octopus Energy
            remaining_entries = price_entries[optimization_period:]
            buy_prices = [entry["buyPrice"] for entry in remaining_entries]
            sell_prices = [entry["sellPrice"] for entry in remaining_entries]

            # Calculate terminal value for end-of-horizon energy valuation
            terminal_value = self._calculate_terminal_value(
                buy_prices, optimization_period
            )

            # Get temperature-based charge power limits if derating is enabled.
            # The returned list is already sized for n_periods (the remaining horizon).
            max_charge_power_per_period = self._get_temperature_derated_charge_limits(
                n_periods
            )

            # Run DP optimization with strategic intent capture - returns OptimizationResult directly
            result = optimize_battery_schedule(
                buy_price=buy_prices,
                sell_price=sell_prices,
                home_consumption=remaining_consumption,
                solar_production=remaining_solar,
                initial_soe=current_soe,
                battery_settings=self.battery_settings,
                initial_cost_basis=initial_cost_basis,
                period_duration_hours=0.25,  # Always quarterly after normalization in _get_price_data
                terminal_value_per_kwh=terminal_value,
                currency=self.home_settings.currency,
                max_charge_power_per_period=max_charge_power_per_period,
            )

            # Add timestamps to period data (algorithm is time-agnostic, operates on relative indices)
            self._add_timestamps_to_period_data(result, optimization_period)

            # Print results table with strategic intents
            print_optimization_results(result, buy_prices, sell_prices)

            # Store full day data in result for UI
            result.input_data["full_home_consumption"] = optimization_data[
                "full_consumption"
            ]
            result.input_data["full_solar_production"] = optimization_data["full_solar"]

            return result

        except Exception as e:
            logger.error(f"Optimization failed: {e}")
            return None

    def _add_timestamps_to_period_data(
        self, result: OptimizationResult, optimization_period: int
    ) -> None:
        """
        Add timestamps and correct period indices in period data after optimization.

        The DP algorithm is time-agnostic and operates on relative period indices (0 to horizon-1).
        This method maps those relative indices to actual timestamps and period indices based on optimization_period.

        Args:
            result: OptimizationResult containing period_data with relative periods (0, 1, 2, ...) and None timestamps
            optimization_period: The actual period index where optimization started (0-95 for today, 96-191 for tomorrow, etc.)
        """
        for i, period_data in enumerate(result.period_data):
            # Calculate actual period index
            actual_period = optimization_period + i

            # Convert period index to timezone-aware timestamp using DST-safe utility
            timestamp = period_index_to_timestamp(actual_period)

            # Update the period_data with correct period index and timestamp (dataclass is mutable)
            period_data.period = actual_period
            period_data.timestamp = timestamp

    def _create_updated_schedule(
        self,
        optimization_period: int,
        result: OptimizationResult,
        prices: list[float],
        optimization_data: dict[str, list[float]],
        is_first_run: bool,
        prepare_next_day: bool,
    ) -> tuple[DPSchedule, GrowattScheduleManager] | None:
        """Create updated schedule from OptimizationResult with strategic intents and CORRECT SOC mapping."""

        try:
            logger.info("=== SCHEDULE CREATION DEBUG START ===")
            logger.info(
                f"optimization_period: {optimization_period} ({format_period(optimization_period)}), prepare_next_day: {prepare_next_day}"
            )

            # Extract PeriodData (actually period data) directly from OptimizationResult
            period_data_list = result.period_data

            # Start with the optimization_data SOE values (which have correct progression)
            combined_soe = optimization_data["combined_soe"].copy()
            combined_actions = optimization_data["combined_actions"].copy()
            solar_charged = optimization_data["solar_charged"].copy()

            logger.info(
                f"Initial SOE from optimization_data: {combined_soe[optimization_period:optimization_period+3]}"
            )

            # Only update the periods that were actually optimized
            logger.info(
                f"Got {len(period_data_list)} period data objects from optimization"
            )

            # Use actual array length for DST safety (92/96/100 periods)
            num_periods = len(combined_soe)
            for i, period_data in enumerate(period_data_list):
                target_period = optimization_period + i
                if target_period < num_periods:
                    logger.debug(
                        f"  Mapping period data index {i} (action={period_data.decision.battery_action:.1f}) to period {target_period}"
                    )
                    combined_actions[target_period] = (
                        period_data.decision.battery_action or 0.0
                    )
                    # Store the SOE directly (it's already in the correct format from period data)
                    combined_soe[target_period] = period_data.energy.battery_soe_end

            # Log the corrected SOE progression
            logger.info("CORRECTED SOE progression:")
            for p in range(
                max(0, optimization_period - 1),
                min(num_periods, optimization_period + 4),
            ):
                soc_percent = (
                    combined_soe[p] / self.battery_settings.total_capacity
                ) * 100
                action = combined_actions[p]
                logger.info(
                    f"  Period {p}: SOE={combined_soe[p]:.1f}kWh ({soc_percent:.1f}%), Action={action:.1f}kW"
                )

            # Create strategic intents array from OptimizationResult
            # DP intents are authoritative - do NOT override with inferred intents from historical data
            # (that causes feedback loop: export → inferred EXPORT_ARBITRAGE → grid_first mode → more export)
            #
            # IMPORTANT: Preserve previous strategic intents for past periods (0 to optimization_period-1)
            # to avoid the "majority IDLE" bug where updating at :45 (period 3 of an hour) causes
            # periods 0,1,2 to default to IDLE, flipping the hourly intent and dropping TOU coverage.
            if (
                self._schedule_manager.strategic_intents
                and len(self._schedule_manager.strategic_intents) >= optimization_period
            ):
                # Preserve previous intents for past periods
                full_day_strategic_intents = (
                    self._schedule_manager.strategic_intents.copy()
                )
                logger.debug(
                    f"Preserving {optimization_period} past strategic intents from previous schedule"
                )
            else:
                # First run of the day or no previous schedule - initialize to IDLE
                # Use get_period_count() to handle DST (92/96/100 periods)
                today = time_utils.today()
                num_periods = get_period_count(today)
                full_day_strategic_intents = ["IDLE"] * num_periods
                logger.debug(
                    f"No previous strategic intents available, initializing {num_periods} periods to IDLE"
                )

            # Fill in optimized periods from the new optimization result
            for i, period_data in enumerate(period_data_list):
                target_period = optimization_period + i
                if target_period < len(full_day_strategic_intents):
                    full_day_strategic_intents[
                        target_period
                    ] = period_data.decision.strategic_intent

            # Store initial SOE (kWh) in OptimizationResult for DailyViewBuilder.
            # _initial_soc_pct and _get_current_battery_soc() return SOC percent (0-100);
            # convert to kWh before storing so input_data["initial_soe"] is always kWh.
            total_cap = self.battery_settings.total_capacity
            if self._initial_soc_pct is not None:
                result.input_data["initial_soe"] = (
                    self._initial_soc_pct / 100.0 * total_cap
                )
            elif not prepare_next_day:
                current_soc = self._get_current_battery_soc()
                if current_soc is not None:
                    result.input_data["initial_soe"] = current_soc / 100.0 * total_cap

            # Store in schedule store - now using OptimizationResult directly
            self.schedule_store.store_schedule(
                optimization_result=result,
                optimization_period=optimization_period,
            )

            # Truncate all arrays to today's period count before creating DPSchedule.
            # The optimizer may have used an extended horizon (up to 192 periods) to make
            # better decisions for today, but DPSchedule and GrowattScheduleManager are
            # day-centric and the Growatt inverter has no date awareness in TOU segments.
            if not prepare_next_day:
                today_period_count = get_period_count(
                    time_utils.today()
                )
                if len(combined_soe) > today_period_count:
                    logger.info(
                        "Truncating schedule arrays from %d to %d periods (today only)",
                        len(combined_soe),
                        today_period_count,
                    )
                    combined_soe = combined_soe[:today_period_count]
                    combined_actions = combined_actions[:today_period_count]
                    solar_charged = solar_charged[:today_period_count]
                    prices = prices[:today_period_count]
                    optimization_data["full_consumption"] = optimization_data[
                        "full_consumption"
                    ][:today_period_count]
                    optimization_data["full_solar"] = optimization_data["full_solar"][
                        :today_period_count
                    ]

            # Recalculate EconomicSummary scoped to today only.
            # The DP algorithm computes economic_summary over the full extended horizon
            # (up to 192 periods), which inflates profitability gate and prediction snapshots.
            if not prepare_next_day:
                today_period_count = get_period_count(
                    time_utils.today()
                )
                today_result_count = today_period_count - optimization_period
                today_result_periods = period_data_list[:today_result_count]
                today_base_cost = sum(
                    pd.economic.grid_only_cost for pd in today_result_periods
                )
                today_optimized_cost = sum(
                    pd.economic.hourly_cost for pd in today_result_periods
                )
                today_charged = sum(
                    pd.energy.battery_charged for pd in today_result_periods
                )
                today_discharged = sum(
                    pd.energy.battery_discharged for pd in today_result_periods
                )
                today_savings = today_base_cost - today_optimized_cost

                result.economic_summary = EconomicSummary(
                    grid_only_cost=today_base_cost,
                    solar_only_cost=today_base_cost,
                    battery_solar_cost=today_optimized_cost,
                    grid_to_solar_savings=0.0,
                    grid_to_battery_solar_savings=today_savings,
                    solar_to_battery_solar_savings=today_savings,
                    grid_to_battery_solar_savings_pct=(
                        (today_savings / today_base_cost) * 100
                        if today_base_cost > 0
                        else 0
                    ),
                    total_charged=today_charged,
                    total_discharged=today_discharged,
                )

            # Create DPSchedule with corrected SOE and strategic intents
            # Convert EconomicSummary to dict for DPSchedule
            if result.economic_summary is None:
                raise ValueError(
                    "OptimizationResult missing economic_summary - algorithm should always provide this"
                )

            summary_dict = {
                "grid_only_cost": result.economic_summary.grid_only_cost,
                "solar_only_cost": result.economic_summary.solar_only_cost,
                "battery_solar_cost": result.economic_summary.battery_solar_cost,
                "grid_to_solar_savings": result.economic_summary.grid_to_solar_savings,
                "grid_to_battery_solar_savings": result.economic_summary.grid_to_battery_solar_savings,
                "solar_to_battery_solar_savings": result.economic_summary.solar_to_battery_solar_savings,
                "grid_to_battery_solar_savings_pct": result.economic_summary.grid_to_battery_solar_savings_pct,
                "total_charged": result.economic_summary.total_charged,
                "total_discharged": result.economic_summary.total_discharged,
            }

            temp_schedule = DPSchedule(
                actions=combined_actions,
                state_of_energy=combined_soe,  # This now has correct SOE progression
                prices=prices,
                cycle_cost=self.battery_settings.cycle_cost_per_kwh,
                hourly_consumption=optimization_data["full_consumption"],
                hourly_data={
                    "strategic_intent": full_day_strategic_intents
                },  # Simplified for DPSchedule compatibility
                summary=summary_dict,  # Now properly converted to dict
                solar_charged=solar_charged,
                original_dp_results={
                    "strategic_intent": full_day_strategic_intents
                },  # Store strategic intents
            )

            # Override the strategic intents in the schedule with corrected data
            temp_schedule.strategic_intents = full_day_strategic_intents

            # Create schedule manager matching current inverter type
            temp_growatt: GrowattScheduleManager | SphScheduleManager = (
                self._create_schedule_manager()
            )
            temp_growatt.strategic_intents = full_day_strategic_intents

            # Create schedule with rolling window — only future periods get TOU segments
            effective_period = 0 if prepare_next_day else optimization_period
            previous_tou = (
                []
                if prepare_next_day
                else self._schedule_manager.active_tou_intervals.copy()
            )
            logger.info(f"Creating Growatt schedule for period={effective_period}")
            temp_growatt.create_schedule(
                temp_schedule,
                current_period=effective_period,
                previous_tou_intervals=previous_tou,
            )

            return temp_schedule, temp_growatt

        except Exception as e:
            import traceback

            logger.error(f"Failed to create schedule: {e}")
            logger.error(f"Trace: {traceback.format_exc()}")
            return None

    def _should_apply_schedule(
        self,
        is_first_run: bool,
        period: int,
        prepare_next_day: bool,
        temp_growatt: GrowattScheduleManager | SphScheduleManager,
        optimization_period: int,
        temp_schedule: DPSchedule,
    ) -> tuple[bool, str]:
        """Determine if schedule should be applied based on TOU differences from current period onwards."""

        logger.info("Evaluating whether to apply new schedule at period %d", period)

        # Special case: preparing next day (runs at 23:55 for 00:00 start)
        if prepare_next_day:
            # Compare full day TOU settings for tomorrow (from start of day)
            schedules_differ, reason = self._schedule_manager.compare_schedules(
                other_schedule=temp_growatt, from_period=0
            )

            logger.info(
                "DECISION for next day: %s - %s",
                "Apply" if schedules_differ else "Keep",
                reason,
            )
            return schedules_differ, f"Next day: {reason}"

        # Normal case: compare TOU settings from current period onwards
        try:
            schedules_differ, reason = self._schedule_manager.compare_schedules(
                other_schedule=temp_growatt, from_period=period
            )

            if schedules_differ:
                logger.info("DECISION: Apply schedule - %s", reason)
            else:
                logger.info("DECISION: Keep current schedule - %s", reason)

            return schedules_differ, reason

        except Exception as e:
            logger.warning("Schedule comparison failed: %s, applying new schedule", e)
            return True, f"Schedule comparison error: {e}"

    def _apply_schedule(
        self,
        period: int,
        temp_schedule: DPSchedule,
        temp_growatt: GrowattScheduleManager | SphScheduleManager,
        reason: str,
        prepare_next_day: bool,
    ) -> None:
        """Apply schedule to hardware."""

        logger.info("=" * 80)
        logger.info("=== SCHEDULE APPLICATION START ===")
        logger.info(
            "Period: %d (%s), Reason: %s, Next day: %s",
            period,
            format_period(period),
            reason,
            prepare_next_day,
        )
        logger.info("=" * 80)

        logger.info("Schedule update required: %s", reason)
        self._current_schedule = temp_schedule

        try:
            current_tou = self._schedule_manager.active_tou_intervals
            effective_period = 0 if prepare_next_day else period

            if self._controller is None:
                logger.error("Cannot apply schedule: controller is not available")
            else:
                temp_growatt.write_schedule_to_hardware(
                    self._controller, effective_period, current_tou
                )

            # Update schedule manager
            self._schedule_manager = temp_growatt

            # Clear corruption flag after successful hardware write
            if temp_growatt.corruption_detected:
                logger.info(
                    "Corruption recovery complete - clearing corruption flag after successful hardware write"
                )
                temp_growatt.corruption_detected = False

            # Apply current period settings
            if not prepare_next_day:
                self._apply_period_schedule(period)

            logger.info("Schedule applied successfully")

        except Exception as e:
            logger.error("Failed to apply schedule: %s", e)
            raise

    def _apply_period_schedule(self, period: int) -> None:
        """Apply period settings with proper charge/discharge power rates.

        Uses per-period strategic intent for full quarterly resolution control.
        """

        # Get current period's strategic intent (quarterly resolution)
        if period >= len(self._schedule_manager.strategic_intents):
            logger.warning(
                "Period %d exceeds strategic intents length %d",
                period,
                len(self._schedule_manager.strategic_intents),
            )
            return

        strategic_intent = self._schedule_manager.strategic_intents[period]

        # Get battery action for this specific period
        # Note: actions now store energy (kWh) per period, convert to power (kW)
        battery_action_kwh = 0.0
        battery_action_kw = 0.0
        if (
            self._schedule_manager.current_schedule
            and self._schedule_manager.current_schedule.actions
        ):
            if period < len(self._schedule_manager.current_schedule.actions):
                battery_action_kwh = self._schedule_manager.current_schedule.actions[
                    period
                ]
                # Convert kWh to kW: power = energy / time
                # Calculate period duration from number of periods per day
                num_periods = len(self._schedule_manager.current_schedule.actions)
                period_duration_hours = 24.0 / num_periods
                battery_action_kw = battery_action_kwh / period_duration_hours

        # Determine charge/discharge rates based on period's strategic intent
        if strategic_intent == "GRID_CHARGING":
            grid_charge = True
            discharge_rate = 0

        elif strategic_intent == "SOLAR_STORAGE":
            grid_charge = False
            discharge_rate = 0

        elif strategic_intent == "LOAD_SUPPORT":
            grid_charge = False
            discharge_rate = 100  # Full discharge for load support

        elif strategic_intent == "EXPORT_ARBITRAGE":
            grid_charge = False
            # Calculate discharge rate from battery action
            if battery_action_kw < -0.01:  # Discharging
                discharge_power_pct = (
                    abs(battery_action_kw)
                    / self.battery_settings.max_discharge_power_kw
                    * 100
                )
                discharge_rate = min(100, max(0, int(discharge_power_pct)))
            else:
                discharge_rate = 0

        elif strategic_intent == "IDLE":
            grid_charge = False
            discharge_rate = 0

        else:
            logger.warning(
                "Unknown strategic intent: %s, using IDLE defaults", strategic_intent
            )
            grid_charge = False
            discharge_rate = 0

        # Store the schedule's desired discharge rate before inhibit check so that
        # apply_discharge_inhibit() can restore it when the inhibit sensor clears.
        self._desired_discharge_rate = discharge_rate

        # Check discharge inhibit (e.g. EV actively charging during Tibber grid award)
        if discharge_rate > 0:
            if self.controller.get_discharge_inhibit_active():
                logger.info(
                    "Period %d: Discharge inhibited by external sensor — setting discharge rate to 0%%",
                    period,
                )
                discharge_rate = 0

        hour = period // 4
        logger.info(
            "Period %d (%02d:%02d): Intent=%s, Action=%.2f kWh (%.2f kW), DischargeRate=%d%%",
            period,
            hour,
            (period % 4) * 15,
            strategic_intent,
            battery_action_kwh,
            battery_action_kw,
            discharge_rate,
        )

        # Apply grid charge setting
        logger.debug(
            "HARDWARE: Setting grid charge to %s for period %d",
            grid_charge,
            period,
        )
        self.controller.set_grid_charge(grid_charge)

        # Apply charging power rate (when grid charging is enabled)
        self.adjust_charging_power()

        # Apply discharge power rate
        logger.info(
            "HARDWARE: Setting discharge power rate to %d%% for period %d",
            discharge_rate,
            period,
        )
        self.controller.set_discharging_power_rate(discharge_rate)
        self._last_applied_discharge_rate = discharge_rate

    def _calculate_initial_cost_basis(self, current_period: int) -> float:
        """Calculate marginal cost of battery energy using historical data.

        This calculates the "value" of energy currently stored in the battery by
        tracking the actual costs paid to acquire that energy throughout the day.

        Algorithm:
        1. Initialize with pre-existing battery energy from first recorded period
           - Assign cycle_cost to this energy (unknown acquisition cost)
        2. Iterate through all completed periods before current_period
        3. For charging periods: Add grid costs and cycle costs to running total
           - Solar charging: Only cycle cost (solar is free)
           - Grid charging: Buy price + cycle cost
        4. For discharging periods: Remove proportional cost from running total
           - Use weighted average cost per kWh in battery
           - Maintains FIFO-like cost accounting
        5. Final result: running_total_cost / running_energy = marginal cost per kWh

        Example (using 0.5/kWh cycle cost, 2.5/kWh grid price):
            Start of day: Battery has 4.2 kWh at cycle_cost (0.5/kWh)
                       → running_cost = 2.10, running_energy = 4.2 kWh
            Period 8:  Charged 0.6 kWh from grid at 2.5/kWh + 0.5 cycle cost
                       → running_cost = 2.10 + 1.80 = 3.90
                       → running_energy = 4.8 kWh
                       → cost_basis = 3.90/4.8 = 0.81/kWh
            Period 15: Discharged 2 kWh
                       → avg_cost = 3.90/4.8 = 0.81/kWh
                       → running_cost = 2.28, running_energy = 2.8 kWh

        This ensures discharge decisions account for the actual acquisition cost
        of the energy, not just cycle wear.

        Args:
            current_period: Current period index (0-95)

        Returns:
            float: Marginal cost of battery energy per kWh
                  Falls back to cycle_cost_per_kwh if no historical data
        """
        # Get completed periods
        today_periods = self.historical_store.get_today_periods()
        completed_periods = [i for i, p in enumerate(today_periods) if p is not None]
        if not completed_periods:
            return self.battery_settings.cycle_cost_per_kwh

        # Initialize with pre-existing battery energy from the first recorded period.
        # This energy was already in the battery at the start of tracking (e.g., from
        # overnight). We assign it a cost basis of cycle_cost since we don't know its
        # original acquisition cost. Without this, the cost basis calculation ignores
        # pre-existing energy and produces inflated values when small amounts of
        # expensive energy are added to a battery that already has significant charge.
        first_period_idx = min(completed_periods)
        first_event = self.historical_store.get_period(first_period_idx)
        assert first_event is not None, "First period must exist"

        initial_soe = first_event.energy.battery_soe_start
        running_energy = initial_soe
        running_total_cost = initial_soe * self.battery_settings.cycle_cost_per_kwh

        for period in sorted(completed_periods):
            if period >= current_period:
                continue

            event = self.historical_store.get_period(period)
            if not event:
                continue

            # Handle charging using stored facts
            if event.energy.battery_charged > 0:
                # Simple calculation using stored energy flows
                solar_to_battery = min(
                    event.energy.battery_charged, event.energy.solar_production
                )
                grid_to_battery = max(
                    0, event.energy.battery_charged - solar_to_battery
                )

                # Calculate costs using same logic as everywhere else
                solar_cost = solar_to_battery * self.battery_settings.cycle_cost_per_kwh
                grid_cost = grid_to_battery * (
                    event.economic.buy_price + self.battery_settings.cycle_cost_per_kwh
                )

                new_energy_cost = solar_cost + grid_cost
                running_total_cost += new_energy_cost
                running_energy += event.energy.battery_charged

            # Handle discharging
            if event.energy.battery_discharged > 0:
                if running_energy > 0:
                    # Calculate proportional cost to remove (weighted average cost)
                    avg_cost_per_kwh = running_total_cost / running_energy
                    discharged_cost = (
                        min(event.energy.battery_discharged, running_energy)
                        * avg_cost_per_kwh
                    )

                    # Remove proportional cost and energy
                    running_total_cost = max(0, running_total_cost - discharged_cost)
                    running_energy = max(
                        0, running_energy - event.energy.battery_discharged
                    )

                    if running_energy <= 0.1:
                        running_total_cost = 0.0
                        running_energy = 0.0

        if running_energy > 0.1:
            cost_basis = running_total_cost / running_energy
            return cost_basis

        return self.battery_settings.cycle_cost_per_kwh

    def _get_current_time_info(self) -> tuple[int, int, Any]:
        """Get current time information."""
        now = time_utils.now()
        return now.hour, now.minute, now.date()

    def _determine_historical_end_hour(
        self, current_hour: int, current_minute: int
    ) -> int:
        """Determine end hour for historical data collection."""
        if current_minute < 5:
            return current_hour - 1 if current_hour > 0 else 0
        return current_hour

    def _run_health_check(self) -> dict[str, Any]:
        """Run system health check."""
        try:
            logger.info("Running system health check...")
            health_results = run_system_health_checks(self)

            # Cache results for dashboard (avoid re-running on every page load)
            self._cached_health_results = health_results

            logger.info("System Health Check Results:")
            logger.info("=" * 40)

            for component in health_results["checks"]:
                status_indicator = (
                    "✓"
                    if component["status"] == "OK"
                    else ("✗" if component["status"] == "ERROR" else "!")
                )
                required_indicator = (
                    "[REQUIRED]" if component.get("required", False) else "[OPTIONAL]"
                )

                logger.info(
                    f"{status_indicator} {required_indicator} {component['name']}: {component['status']}"
                )

                if component["status"] != "OK":
                    logger.info("-" * 40)
                    for check in component["checks"]:
                        if check["status"] != "OK":
                            entity_str = (
                                f" ({check['entity_id']})"
                                if check.get("entity_id")
                                else ""
                            )
                            logger.info(
                                f"  - {check['name']}{entity_str}: {check['status']} - {check['error'] or 'No specific error'}"
                            )
                    logger.info("-" * 40)

            logger.info("=" * 40)

            # Check for critical failures but don't abort startup - allow graceful degradation
            critical_failures = []
            for component in health_results["checks"]:
                if component.get("required", False) and component["status"] == "ERROR":
                    critical_failures.append(component["name"])

            if critical_failures:
                logger.error(
                    f"⚠️ SYSTEM DEGRADED: Critical sensor failures detected in required components: {', '.join(critical_failures)}"
                )
                logger.error(
                    "⚠️ System will start in degraded mode. Some functionality may not work correctly."
                )
                logger.error(
                    "⚠️ Please fix sensor configuration for full functionality."
                )
                # Store critical failures for UI to display
                self._critical_sensor_failures = critical_failures
            else:
                logger.info(
                    "✓ All required sensors are functional - system fully operational"
                )
                self._critical_sensor_failures = []
            return health_results

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            # Don't crash the system, allow degraded mode operation
            self._critical_sensor_failures = ["System Health Check"]
            return {"status": "ERROR", "checks": []}

    def has_critical_sensor_failures(self) -> bool:
        """Check if the system has critical sensor failures (degraded mode)."""
        return len(self._critical_sensor_failures) > 0

    def get_critical_sensor_failures(self) -> list[str]:
        """Get list of critical components with sensor failures."""
        return self._critical_sensor_failures.copy()

    def get_cached_health_results(self) -> dict[str, Any] | None:
        """Get cached health check results from startup (avoids re-running expensive checks)."""
        return getattr(self, "_cached_health_results", None)

    def get_runtime_failures(self) -> list:
        """Get all active (non-dismissed) runtime API failures.

        Returns:
            List of RuntimeFailure objects sorted by timestamp (newest first)
        """
        return self._runtime_failure_tracker.get_active_failures()

    def dismiss_runtime_failure(self, failure_id: str) -> None:
        """Dismiss a specific runtime failure notification.

        Args:
            failure_id: UUID of the failure to dismiss

        Raises:
            ValueError: If failure ID not found
        """
        self._runtime_failure_tracker.dismiss_failure(failure_id)

    def dismiss_all_runtime_failures(self) -> int:
        """Dismiss all active runtime failures.

        Returns:
            Number of failures dismissed
        """
        return self._runtime_failure_tracker.dismiss_all()

    def _get_today_price_data(self) -> list[float]:
        """Get today's price data for reports and views."""
        try:
            today_prices = self._price_manager.get_today_prices()
            return [p["buyPrice"] for p in today_prices]
        except Exception as e:
            logger.warning(f"Failed to get today's price data: {e}")
            return [1.0] * 24

    @property
    def price_manager(self) -> PriceManager:
        """Getter for price_manager to ensure API compatibility."""
        return self._price_manager

    def get_current_daily_view(self, current_period: int | None = None) -> DailyView:
        """Get daily view for specified or current period.

        The period index determines the split between actual (before) and predicted (after) data.

        Args:
            current_period: Period index (0-95) to get daily view for. If None, uses current system time.
                           Determines which periods are marked as actual vs predicted.

        Returns:
            DailyView: Complete daily view with quarterly periods combining actual and predicted data

        Raises:
            SystemConfigurationError: If current_period is not in valid range 0-95
        """
        # Calculate current period from current time if not provided
        now = time_utils.now()
        if current_period is None:
            current_period = now.hour * 4 + now.minute // 15
        else:
            # Validate period range
            if not 0 <= current_period <= 95:
                raise SystemConfigurationError(
                    message=f"current_period must be 0-95, got {current_period}"
                )

        # Build daily view with current period
        return self.daily_view_builder.build_daily_view(current_period)

    def adjust_charging_power(self) -> None:
        """Adjust charging power based on house consumption."""
        try:
            # Get current hour settings to ensure power monitor uses the correct target
            current_hour = time_utils.now().hour
            settings = self._schedule_manager.get_hourly_settings(current_hour)
            charge_rate = settings.get("charge_rate", 0)

            if self._power_monitor:
                self._power_monitor.update_target_charging_power(charge_rate)
                self._power_monitor.adjust_battery_charging()

        except (AttributeError, ValueError, KeyError) as e:
            logger.error("Failed to adjust charging power: %s", str(e))

    def apply_discharge_inhibit(self) -> None:
        """React to discharge inhibit sensor changes within ~1 minute.

        Called every minute by the scheduler. Compares the current inhibit sensor
        state against the last applied discharge rate and writes to the inverter
        only when the state has actually changed, avoiding unnecessary Modbus writes.
        """
        inhibit_active = self.controller.get_discharge_inhibit_active()
        target_rate = 0 if inhibit_active else self._desired_discharge_rate

        if target_rate == self._last_applied_discharge_rate:
            return

        if inhibit_active:
            logger.info(
                "Discharge inhibit became active — suppressing discharge (was %d%%)",
                self._last_applied_discharge_rate,
            )
        else:
            logger.info(
                "Discharge inhibit released — restoring discharge rate to %d%%",
                self._desired_discharge_rate,
            )

        self.controller.set_discharging_power_rate(target_rate)
        self._last_applied_discharge_rate = target_rate

    def get_settings(self):
        """Get settings - return dataclasses directly for API layer conversion."""
        return {
            "battery": self.battery_settings,
            "home": self.home_settings,
            "price": self.price_settings,
        }

    def update_settings(self, settings: dict[str, Any]) -> None:
        """Update settings - preserves original interface."""
        try:
            if "battery" in settings:
                self.battery_settings.update(**settings["battery"])

            if "home" in settings:
                self.home_settings.update(**settings["home"])

            if "price" in settings:
                self.price_settings.update(**settings["price"])
                self._price_manager.markup_rate = self.price_settings.markup_rate
                self._price_manager.vat_multiplier = self.price_settings.vat_multiplier
                self._price_manager.additional_costs = (
                    self.price_settings.additional_costs
                )
                self._price_manager.tax_reduction = self.price_settings.tax_reduction
                self._price_manager.area = self.price_settings.area
                self._price_manager.clear_cache()

            logger.info("Settings updated successfully")

        except Exception as e:
            logger.error(f"Failed to update settings: {e}")
            raise SystemConfigurationError(message=f"Invalid settings: {e}") from e

    def _log_battery_system_config(self) -> None:
        """Log the current battery configuration - reproduces original functionality."""
        try:
            # Use already-fetched predictions — avoids triggering a heavy pipeline
            # (InfluxDB query or ML inference) just for a log message
            assert self._consumption_predictions is not None
            predictions_consumption = self._consumption_predictions

            # Get current SOC
            if self._controller:
                current_soc = self.controller.get_battery_soc()
            else:
                current_soc = self.battery_settings.min_soc

            min_consumption = min(predictions_consumption)
            max_consumption = max(predictions_consumption)
            avg_consumption = sum(predictions_consumption) / 24

            config_str = f"""
    ╔═════════════════════════════════════════════════════╗
    ║          Battery Schedule Prediction Data           ║
    ╠══════════════════════════════════╦══════════════════╣
    ║ Parameter                        ║ Value            ║
    ╠══════════════════════════════════╬══════════════════╣
    ║ Total Capacity                   ║ {self.battery_settings.total_capacity:>12.1f} kWh ║
    ║ Reserved Capacity                ║ {self.battery_settings.total_capacity * (self.battery_settings.min_soc / 100):>12.1f} kWh ║
    ║ Usable Capacity                  ║ {self.battery_settings.total_capacity * (1 - self.battery_settings.min_soc / 100):>12.1f} kWh ║
    ║ Max Charge/Discharge Power       ║ {self.battery_settings.max_discharge_power_kw:>12.1f} kW  ║
    ║ Charge Cycle Cost                ║ {self.battery_settings.cycle_cost_per_kwh:>12.2f} {self.home_settings.currency:>3s} ║
    ╠══════════════════════════════════╬══════════════════╣
    ║ Initial SOE                      ║ {self.battery_settings.total_capacity * (current_soc / 100):>12.1f} kWh ║
    ║ Charging Power Rate              ║ {self.battery_settings.charging_power_rate:>12.1f} %   ║
    ║ Charging Power                   ║ {(self.battery_settings.charging_power_rate / 100) * self.battery_settings.max_charge_power_kw:>12.1f} kW  ║
    ║ Min Hourly Consumption           ║ {min_consumption:>12.1f} kWh ║
    ║ Max Hourly Consumption           ║ {max_consumption:>12.1f} kWh ║
    ║ Avg Hourly Consumption           ║ {avg_consumption:>12.1f} kWh ║
    ╚══════════════════════════════════╩══════════════════╝"""
            logger.info(config_str)

        except Exception as e:
            logger.error(f"Failed to log battery system config: {e}")

    def _log_energy_balance(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Generate energy balance from historical store with quarterly detail.

        Logs all completed quarter-hour periods with HH:MM formatting.
        No aggregation - shows full 15-minute resolution data.

        Returns:
            tuple: (period_data, totals) where period_data contains all completed periods
        """
        # Get all completed periods
        today_periods = self.historical_store.get_today_periods()
        completed_periods = [i for i, p in enumerate(today_periods) if p is not None]

        if not completed_periods:
            logger.info("No completed periods for energy balance")
            return [], {}

        period_data = []
        totals = {
            "total_solar": 0.0,
            "total_consumption": 0.0,
            "total_grid_import": 0.0,
            "total_grid_export": 0.0,
            "total_battery_charged": 0.0,
            "total_battery_discharged": 0.0,
            "battery_net_change": 0.0,
            "periods_recorded": len(completed_periods),
        }

        # Log each quarter-hour period with HH:MM formatting
        for period in sorted(completed_periods):
            period_info = self.historical_store.get_period(period)
            if period_info:
                period_item = {
                    "period": period,
                    "time": format_period(period),  # Shows as "14:45"
                    "solar_production": period_info.energy.solar_production,
                    "home_consumption": period_info.energy.home_consumption,
                    "grid_import": period_info.energy.grid_imported,
                    "grid_export": period_info.energy.grid_exported,
                    "battery_charged": period_info.energy.battery_charged,
                    "battery_discharged": period_info.energy.battery_discharged,
                    "battery_soe_end": period_info.energy.battery_soe_end,
                    "battery_net_change": (
                        period_info.energy.battery_charged
                        - period_info.energy.battery_discharged
                    ),
                }

                totals["total_solar"] += period_info.energy.solar_production
                totals["total_consumption"] += period_info.energy.home_consumption
                totals["total_grid_import"] += period_info.energy.grid_imported
                totals["total_grid_export"] += period_info.energy.grid_exported
                totals["total_battery_charged"] += period_info.energy.battery_charged
                totals[
                    "total_battery_discharged"
                ] += period_info.energy.battery_discharged

                period_data.append(period_item)

        totals["battery_net_change"] = (
            totals["total_battery_charged"] - totals["total_battery_discharged"]
        )

        # Format and log energy balance table
        self._format_and_log_energy_balance(period_data, totals)

        return period_data, totals

    def _format_and_log_energy_balance(
        self, period_data: list[dict[str, Any]], totals: dict[str, Any]
    ) -> None:
        """Format and log energy balance table with quarterly period detail.

        Args:
            period_data: List of period dictionaries with 'period', 'time', and energy fields
            totals: Dictionary of total energy values
        """
        if not period_data:
            logger.info("No energy data to display")
            return

        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15

        # Create table header
        lines = [
            "\n╔════════════════════════════════════════════════════════════════════════════════════════════════════════╗",
            "║                                    Energy Balance Report (15-min periods)                              ║",
            "╠════════╦══════════════════════════╦══════════════════════════╦══════════════════════════════════╦══════╣",
            "║        ║       Energy Input       ║       Energy Output      ║           Battery Flows          ║      ║",
            "║  Time  ╠════════╦════════╦════════╬════════╦════════╦════════╬════════╦════════╦════════╦═══════╣ SOC  ║",
            "║        ║ Solar  ║ Grid   ║ Total  ║ Home   ║ Export ║ Aux.   ║ Charge ║Dischrge║Solar->B║ Grid  ║ (%)  ║",
            "╠════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬═══════╬══════╣",
        ]

        # Add period data rows
        for data in period_data:
            energy_in = data["grid_import"] + data["solar_production"]

            # Estimate solar to battery (simplified)
            solar_to_battery = min(data["battery_charged"], data["solar_production"])
            grid_to_battery = max(0, data["battery_charged"] - solar_to_battery)

            # Mark predictions with ★ (periods >= current_period)
            indicator = "★" if data["period"] >= current_period else " "

            # Convert SOE (kWh) to SOC (%) for display
            battery_soc_end = (
                data["battery_soe_end"] / self.battery_settings.total_capacity
            ) * 100.0

            row = (
                f"║ {data['time']}{indicator} "
                f"║ {data['solar_production']:>5.2f}  "
                f"║ {data['grid_import']:>5.2f}  "
                f"║ {energy_in:>6.2f} "
                f"║ {data['home_consumption']:>5.2f}  "
                f"║ {data['grid_export']:>5.2f}  "
                f"║ {0.0:>5.2f}  "  # Aux load
                f"║ {data['battery_charged']:>5.2f}  "
                f"║ {data['battery_discharged']:>5.2f}  "
                f"║ {solar_to_battery:>5.2f}  "
                f"║ {grid_to_battery:>5.2f} "
                f"║ {battery_soc_end:>4.0f} ║"
            )
            lines.append(row)

        # Add totals and close table
        lines.extend(
            [
                "╠════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬═══════╬══════╣",
                f"║ TOTAL  ║ {totals['total_solar']:>5.1f}  ║ {totals['total_grid_import']:>5.1f}  ║ {totals['total_solar'] + totals['total_grid_import']:>6.1f} "
                f"║ {totals['total_consumption']:>5.1f}  ║ {totals['total_grid_export']:>5.1f}  ║ {0.0:>5.1f}  "
                f"║ {totals['total_battery_charged']:>5.1f}  ║ {totals['total_battery_discharged']:>5.1f}  ║ {0.0:>5.1f}  ║ {0.0:>5.1f} ║      ║",
                "╚════════╩════════╩════════╩════════╩════════╩════════╩════════╩════════╩════════╩════════╩═══════╩══════╝",
                "\nEnergy Balance Summary (★ indicates predicted values):",
                f"  Total Energy In: {totals['total_solar'] + totals['total_grid_import']:.2f} kWh",
                f"  Total Energy Out: {totals['total_consumption'] + totals['total_grid_export']:.2f} kWh",
                f"  Battery Net Change: {totals['battery_net_change']:.2f} kWh",
                "",
            ]
        )

        logger.info("\n".join(lines))

    def log_system_startup(self) -> None:
        """Log system startup information"""
        try:
            # Log battery configuration
            self._log_battery_system_config()

            # Log energy balance using the new components
            self._log_energy_balance()

        except Exception as e:
            logger.error(f"Failed to log system startup: {e}")
