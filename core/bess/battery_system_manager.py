"""
Complete replacement for battery_system.py that preserves ALL functionality.

"""

import logging
from datetime import datetime, timedelta
from typing import Any

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
from .growatt_schedule import GrowattScheduleManager
from .ha_api_controller import HomeAssistantAPIController
from .health_check import run_system_health_checks
from .historical_data_store import HistoricalDataStore
from .models import DecisionData, EconomicData, PeriodData, infer_intent_from_flows
from .power_monitor import HomePowerMonitor
from .prediction_snapshot import PredictionSnapshotStore
from .price_manager import HomeAssistantSource, PriceManager, PriceSource
from .schedule_store import ScheduleStore
from .sensor_collector import SensorCollector
from .settings import BatterySettings, HomeSettings, PriceSettings
from .time_utils import TIMEZONE, format_period

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
        nordpool_config: dict | None = None,
    ):
        """Initialize with same interface as original BatterySystemManager."""

        # Initialize settings (preserve original defaults)
        self.battery_settings = BatterySettings()
        self.home_settings = HomeSettings()
        self.price_settings = PriceSettings()
        self._nordpool_config = nordpool_config or {}

        # Store controller reference
        self._controller = controller

        # Initialize core data stores with proper component separation
        self.historical_store = HistoricalDataStore(
            self.battery_settings.total_capacity
        )
        self.schedule_store = ScheduleStore()
        self.prediction_snapshot_store = PredictionSnapshotStore()

        # Initialize specialized components
        self.sensor_collector = SensorCollector(
            controller, self.battery_settings.total_capacity
        )

        # Initialize view builder
        self.daily_view_builder = DailyViewBuilder(
            self.historical_store,
            self.schedule_store,
            self.battery_settings,
        )

        # Initialize hardware interface with battery settings
        self._schedule_manager = GrowattScheduleManager(
            battery_settings=self.battery_settings
        )

        # Initialize price manager
        if not price_source:
            # Check if official Nordpool integration should be used
            nordpool_config = getattr(self, "_nordpool_config", None)
            if nordpool_config is None:
                nordpool_config = {}
            use_official = nordpool_config.get("use_official_integration", False)
            config_entry_id = nordpool_config.get("config_entry_id")

            if use_official and config_entry_id:
                # Use official Home Assistant Nordpool integration
                from .official_nordpool_source import OfficialNordpoolSource

                price_source = OfficialNordpoolSource(
                    controller,
                    config_entry_id,
                    vat_multiplier=self.price_settings.vat_multiplier,
                )
                logger.info("Using official Home Assistant Nordpool integration")
            else:
                # Use legacy sensor-based approach (current custom component)
                price_source = HomeAssistantSource(
                    controller, vat_multiplier=self.price_settings.vat_multiplier
                )
                logger.info("Using legacy/custom Nordpool sensor integration")

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
        self._initial_soe = None

        # Critical sensor failure tracking for graceful degradation
        self._critical_sensor_failures = []

        logger.debug("BatterySystemManager initialized")

    @property
    def controller(self) -> HomeAssistantAPIController:
        """Get the Home Assistant controller."""
        if self._controller is None:
            raise RuntimeError("Controller not initialized - system not started")
        return self._controller

    def _sync_soc_limits(self) -> None:
        """
        Sync SOC limits from config to inverter hardware.

        Config values are the single source of truth. This method ensures
        the inverter hardware matches the configured min/max SOC limits.
        Called during system startup.
        """
        logger.info("Syncing SOC limits from config to inverter...")

        # Sync minimum SOC (discharge stop)
        configured_min_soc = self.battery_settings.min_soc
        self.controller.set_discharge_stop_soc(configured_min_soc)
        logger.info(f"Set discharge_stop_soc to {configured_min_soc}%")

        # Sync maximum SOC (charge stop)
        configured_max_soc = self.battery_settings.max_soc
        self.controller.set_charge_stop_soc(configured_max_soc)
        logger.info(f"Set charge_stop_soc to {configured_max_soc}%")

        # Verify sync by reading back values
        actual_min_soc = self.controller.get_discharge_stop_soc()
        actual_max_soc = self.controller.get_charge_stop_soc()

        # Log verification results
        if (
            actual_min_soc == configured_min_soc
            and actual_max_soc == configured_max_soc
        ):
            logger.info(
                f"SOC limits verified: min={actual_min_soc}%, max={actual_max_soc}%"
            )
        else:
            logger.warning(
                f"SOC limit mismatch detected! "
                f"Configured: min={configured_min_soc}%, max={configured_max_soc}% | "
                f"Actual: min={actual_min_soc}%, max={actual_max_soc}%"
            )

    def start(self) -> None:
        """Start the system - preserves original functionality."""
        try:
            # Initialize monitors if controller available
            if self._controller:
                self._power_monitor = HomePowerMonitor(
                    self._controller,
                    home_settings=self.home_settings,
                    battery_settings=self.battery_settings,
                )

                # Run health check before we start using sensors
                self._run_health_check()

                # Sync SOC limits from config to inverter (config as master)
                self._sync_soc_limits()

                # Initialize schedule from inverter - preserves original logic
                self._initialize_tou_schedule_from_inverter()

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

            # Run optimization using DP algorithm with quarterly resolution
            optimization_result = self._run_optimization(
                optimization_period,
                optimization_data,
                prices,
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
                snapshot_timestamp=datetime.now(tz=TIMEZONE),
                optimization_period=optimization_period,
                daily_view=daily_view,
                growatt_schedule=growatt_schedule,
                predicted_daily_savings=optimization_result.economic_summary.grid_to_battery_solar_savings,
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

            inverter_segments = self._controller.read_inverter_time_segments()

            current_hour = datetime.now().hour
            self._schedule_manager.initialize_from_tou_segments(
                inverter_segments, current_hour
            )

        except Exception as e:
            logger.error(f"Failed to read current inverter schedule: {e}")

    def _fetch_and_initialize_historical_data(self) -> None:
        """Fetch and initialize historical data using quarterly resolution."""
        try:
            now = datetime.now(tz=TIMEZONE)
            current_period = now.hour * 4 + now.minute // 15

            logger.info(
                f"Fetching historical data - current period: {current_period} ({format_period(current_period)})"
            )

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
                            timestamp=datetime.now(tz=TIMEZONE),
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

            consumption_predictions = self._controller.get_estimated_consumption()
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

    def _handle_special_cases(self, period: int, prepare_next_day: bool) -> None:
        """Handle special cases like midnight transition."""
        if period == 0 and not prepare_next_day:
            try:
                if self._controller is not None:
                    current_soc = self._controller.get_battery_soc()
                    self._initial_soe = current_soc
                    logger.info(f"Setting initial SOC for day: {self._initial_soe}%")
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
        """Get price data - preserves original logic."""
        try:
            if prepare_next_day:
                price_entries = self._price_manager.get_tomorrow_prices()
                logger.info("Fetched tomorrow's price data")
            else:
                price_entries = self._price_manager.get_today_prices()

            if not price_entries:
                logger.warning("No prices available")
                return None, None

            prices = [entry["price"] for entry in price_entries]

            # Prices are quarterly (96 periods) - DP algorithm supports variable horizon
            # Handle DST transitions (quarterly)
            if len(prices) == 92:
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
                timestamp=datetime.now(tz=TIMEZONE),
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
            consumption_predictions = self.controller.get_estimated_consumption()
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
            predictions_consumption = self.controller.get_estimated_consumption()
            predictions_solar = self.controller.get_solar_forecast()

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

    def _run_optimization(
        self,
        optimization_period: int,
        optimization_data: dict[str, list[float]],
        prices: list[float],
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

            # Calculate buy and sell prices
            buy_prices = self._price_manager.get_buy_prices(raw_prices=remaining_prices)
            sell_prices = self._price_manager.get_sell_prices(
                raw_prices=remaining_prices
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

            # Convert period index to datetime
            # Period 0-95: today, 96-191: tomorrow, etc.
            day_offset = actual_period // 96  # Which day (0=today, 1=tomorrow, etc.)
            period_in_day = actual_period % 96  # Period within the day (0-95)
            period_hour = period_in_day // 4  # Hour within day (0-23)
            period_minute = (period_in_day % 4) * 15  # Minute (0, 15, 30, 45)

            # Create timestamp starting from today
            now = datetime.now()
            base_date = now.replace(
                hour=period_hour, minute=period_minute, second=0, microsecond=0
            )
            timestamp = base_date + timedelta(days=day_offset)

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

            for i, period_data in enumerate(period_data_list):
                target_period = optimization_period + i
                if target_period < 96:
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
                max(0, optimization_period - 1), min(96, optimization_period + 4)
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
            full_day_strategic_intents = ["IDLE"] * 96
            for i, period_data in enumerate(period_data_list):
                target_period = optimization_period + i
                if target_period < 96:
                    full_day_strategic_intents[target_period] = (
                        period_data.decision.strategic_intent
                    )

            # Store initial SOC in OptimizationResult for DailyViewBuilder
            if self._initial_soe is not None:
                result.input_data["initial_soe"] = self._initial_soe
            elif not prepare_next_day:
                current_soc = self._get_current_battery_soc()
                if current_soc is not None:
                    result.input_data["initial_soe"] = current_soc

            # Store in schedule store - now using OptimizationResult directly
            self.schedule_store.store_schedule(
                optimization_result=result,
                optimization_period=optimization_period,
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

            # Create Growatt schedule manager
            temp_growatt = GrowattScheduleManager(
                battery_settings=self.battery_settings
            )
            temp_growatt.strategic_intents = full_day_strategic_intents

            # Copy existing TOU intervals for past periods if not preparing next day
            if not prepare_next_day and hasattr(
                self._schedule_manager, "tou_intervals"
            ):
                for segment in self._schedule_manager.tou_intervals:
                    start_time_parts = segment["start_time"].split(":")
                    start_period = (
                        int(start_time_parts[0]) * 4 + int(start_time_parts[1]) // 15
                    )
                    if start_period < optimization_period:
                        temp_growatt.tou_intervals.append(segment.copy())

            # Create schedule with strategic intents
            effective_period = 0 if prepare_next_day else optimization_period
            logger.info(f"Creating Growatt schedule for period={effective_period}")
            temp_growatt.create_schedule(temp_schedule)

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
        temp_growatt: GrowattScheduleManager,
        optimization_period: int,
        temp_schedule: DPSchedule,
    ) -> tuple[bool, str]:
        """Determine if schedule should be applied based on TOU differences from current period onwards."""

        logger.info("Evaluating whether to apply new schedule at period %d", period)

        # Special case: preparing next day (runs at 23:55 for 00:00 start)
        if prepare_next_day:
            # Compare full day TOU settings for tomorrow (from start of day)
            schedules_differ, reason = self._schedule_manager.compare_schedules(
                other_schedule=temp_growatt, from_hour=0
            )

            logger.info(
                "DECISION for next day: %s - %s",
                "Apply" if schedules_differ else "Keep",
                reason,
            )
            return schedules_differ, f"Next day: {reason}"

        # Normal case: compare TOU settings from current period onwards
        try:
            # Convert period to hour for Growatt TOU comparison (hardware operates hourly)
            from_hour = period // 4
            schedules_differ, reason = self._schedule_manager.compare_schedules(
                other_schedule=temp_growatt, from_hour=from_hour
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
        temp_growatt: GrowattScheduleManager,
        reason: str,
        prepare_next_day: bool,
    ) -> None:
        """Apply schedule to hardware - preserves original TOU logic."""

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
            # Get TOU settings
            current_tou = getattr(self._schedule_manager, "tou_intervals", [])
            new_tou = temp_growatt.tou_intervals

            logger.info(
                "TOU comparison: Current=%d intervals, New=%d intervals",
                len(current_tou),
                len(new_tou),
            )

            # DIAGNOSTIC: Validate intervals before sending to inverter
            logger.info("Validating TOU intervals before sending to inverter...")
            temp_growatt.validate_tou_intervals_ordering(
                new_tou, "before_sending_to_inverter"
            )

            effective_period = 0 if prepare_next_day else period
            effective_hour = effective_period // 4

            # Find segments to disable and update
            to_disable = []
            to_update = []

            logger.info(
                "Analyzing TOU changes from period %d (hour %02d) onwards...",
                effective_period,
                effective_hour,
            )

            # CRITICAL FIX: When new schedule is empty, disable ALL current TOU segments
            # This prevents stale schedules from persisting across restarts
            if len(new_tou) == 0 and len(current_tou) > 0:
                logger.warning("=" * 80)
                logger.warning(
                    "Empty TOU schedule detected - CLEARING ALL %d existing TOU segments from inverter",
                    len(current_tou),
                )
                logger.warning(
                    "This happens when optimization determines NO profitable charging/discharging"
                )
                logger.warning("=" * 80)

                # Disable ALL current segments (past and future) to prevent stale schedules
                for current in current_tou:
                    if current.get(
                        "enabled", True
                    ):  # Only disable if currently enabled
                        disabled_segment = current.copy()
                        disabled_segment["enabled"] = False
                        to_disable.append(disabled_segment)
                        logger.info(
                            "Marking ALL segments for clearing: %s-%s %s (segment_id=%s)",
                            current["start_time"],
                            current["end_time"],
                            current["batt_mode"],
                            current.get("segment_id"),
                        )

                logger.info("Total segments marked for clearing: %d", len(to_disable))
            else:
                # Normal case: differential update (only update future segments)
                # Identify segments to disable
                for current in current_tou:
                    start_time_parts = current["start_time"].split(":")
                    start_hour = int(start_time_parts[0])
                    if (
                        start_hour >= effective_hour
                        or int(current["end_time"].split(":")[0]) >= effective_hour
                    ):
                        has_match = any(
                            segment["start_time"] == current["start_time"]
                            and segment["end_time"] == current["end_time"]
                            and segment["batt_mode"] == current["batt_mode"]
                            and segment["enabled"] == current["enabled"]
                            for segment in new_tou
                        )

                        if not has_match:
                            disabled_segment = current.copy()
                            disabled_segment["enabled"] = False
                            to_disable.append(disabled_segment)
                            logger.debug(
                                "Mark for disable: %s-%s %s",
                                current["start_time"],
                                current["end_time"],
                                current["batt_mode"],
                            )

            # Identify segments to add/update
            for segment in new_tou:
                start_hour = int(segment["start_time"].split(":")[0])
                if (
                    start_hour >= effective_hour
                    or int(segment["end_time"].split(":")[0]) >= effective_hour
                ):
                    existing_match = any(
                        current["start_time"] == segment["start_time"]
                        and current["end_time"] == segment["end_time"]
                        and current["batt_mode"] == segment["batt_mode"]
                        and current["enabled"] == segment["enabled"]
                        for current in current_tou
                    )

                    if not existing_match:
                        to_update.append(segment)
                        logger.debug(
                            "Mark for update: %s-%s %s",
                            segment["start_time"],
                            segment["end_time"],
                            segment["batt_mode"],
                        )

            # Check for overlaps and add to disable list
            for update_segment in to_update:
                update_start = int(update_segment["start_time"].split(":")[0])
                update_end = int(update_segment["end_time"].split(":")[0])

                for current_segment in current_tou:
                    if any(
                        d.get("segment_id") == current_segment.get("segment_id")
                        for d in to_disable
                    ):
                        continue
                    if not current_segment.get("enabled", True):
                        continue

                    current_start = int(current_segment["start_time"].split(":")[0])
                    current_end = int(current_segment["end_time"].split(":")[0])

                    if update_start <= current_end and update_end >= current_start:
                        if not any(
                            d.get("segment_id") == current_segment.get("segment_id")
                            for d in to_disable
                        ):
                            disabled_segment = current_segment.copy()
                            disabled_segment["enabled"] = False
                            to_disable.append(disabled_segment)

            # Apply updates to hardware
            if to_disable or to_update:
                logger.info(
                    "Updating %d segments, disabling %d segments",
                    len(to_update),
                    len(to_disable),
                )

                # Check if controller is available
                if self._controller is None:
                    logger.error("Cannot apply schedule: controller is not available")
                else:
                    # Disable first to avoid overlaps
                    for segment in to_disable:
                        try:
                            logger.info(
                                "HARDWARE: Disabling TOU segment %s: %s-%s %s",
                                segment.get("segment_id"),
                                segment["start_time"],
                                segment["end_time"],
                                segment["batt_mode"],
                            )
                            # Filter parameters to only include what the method accepts
                            inverter_params = {
                                "segment_id": segment["segment_id"],
                                "batt_mode": segment["batt_mode"],
                                "start_time": segment["start_time"],
                                "end_time": segment["end_time"],
                                "enabled": segment["enabled"],
                            }
                            self._controller.set_inverter_time_segment(
                                **inverter_params
                            )
                            logger.debug("SUCCESS: Segment disabled")
                        except Exception as e:
                            logger.error("FAILED: Failed to disable TOU segment: %s", e)

                    # Then update/add
                    for segment in to_update:
                        try:
                            logger.info(
                                "HARDWARE: Setting TOU segment %s: %s-%s %s",
                                segment.get("segment_id"),
                                segment["start_time"],
                                segment["end_time"],
                                segment["batt_mode"],
                            )
                            # Filter parameters to only include what the method accepts
                            inverter_params = {
                                "segment_id": segment["segment_id"],
                                "batt_mode": segment["batt_mode"],
                                "start_time": segment["start_time"],
                                "end_time": segment["end_time"],
                                "enabled": segment["enabled"],
                            }
                            self._controller.set_inverter_time_segment(
                                **inverter_params
                            )
                            logger.debug("SUCCESS: Segment updated")
                        except Exception as e:
                            logger.error("FAILED: Failed to update TOU segment: %s", e)
            else:
                logger.info("No TOU segment changes needed")

            # Update schedule manager
            self._schedule_manager = temp_growatt

            # CRITICAL: Clear corruption flag after successful hardware write
            if temp_growatt.corruption_detected:
                logger.info(
                    "✅ Corruption recovery complete - clearing corruption flag after successful hardware write"
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
            charge_rate = 100  # Full power for grid charging

        elif strategic_intent == "SOLAR_STORAGE":
            grid_charge = False
            discharge_rate = 0
            charge_rate = 100  # Full power for solar storage

        elif strategic_intent == "LOAD_SUPPORT":
            grid_charge = False
            discharge_rate = 100  # Full discharge for load support
            charge_rate = 0

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
            charge_rate = 0

        elif strategic_intent == "IDLE":
            grid_charge = False
            discharge_rate = 0
            charge_rate = 100  # Allow solar charging

        else:
            logger.warning(
                "Unknown strategic intent: %s, using IDLE defaults", strategic_intent
            )
            grid_charge = False
            discharge_rate = 0
            charge_rate = 100

        hour = period // 4
        logger.info(
            "Period %d (%02d:%02d): Intent=%s, Action=%.2f kWh (%.2f kW), ChargeRate=%d%%, DischargeRate=%d%%",
            period,
            hour,
            (period % 4) * 15,
            strategic_intent,
            battery_action_kwh,
            battery_action_kw,
            charge_rate,
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

    def _calculate_initial_cost_basis(self, current_period: int) -> float:
        """Calculate marginal cost of battery energy using historical data.

        This calculates the "value" of energy currently stored in the battery by
        tracking the actual costs paid to acquire that energy throughout the day.

        Algorithm:
        1. Iterate through all completed periods before current_period
        2. For charging periods: Add grid costs and cycle costs to running total
           - Solar charging: Only cycle cost (solar is free)
           - Grid charging: Buy price + cycle cost
        3. For discharging periods: Remove proportional cost from running total
           - Use weighted average cost per kWh in battery
           - Maintains FIFO-like cost accounting
        4. Final result: running_total_cost / running_energy = marginal cost per kWh

        Example:
            Period 10: Charged 5 kWh from grid at 1.5 SEK/kWh + 0.05 cycle cost
                       → running_cost = 7.75 SEK, running_energy = 5 kWh
            Period 15: Discharged 2 kWh
                       → avg_cost = 7.75/5 = 1.55 SEK/kWh
                       → running_cost = 4.65 SEK, running_energy = 3 kWh
            Period 20: Marginal cost = 4.65/3 = 1.55 SEK/kWh
                       → Only discharge if sell price > 1.55 SEK/kWh

        This ensures discharge decisions account for the actual acquisition cost
        of the energy, not just cycle wear.

        Args:
            current_period: Current period index (0-95)

        Returns:
            float: Marginal cost of battery energy in SEK/kWh
                  Falls back to cycle_cost_per_kwh if no historical data
        """
        # Get completed periods
        today_periods = self.historical_store.get_today_periods()
        completed_periods = [i for i, p in enumerate(today_periods) if p is not None]
        if not completed_periods:
            return self.battery_settings.cycle_cost_per_kwh

        running_energy = 0.0
        running_total_cost = 0.0

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
        now = datetime.now()
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
        now = datetime.now(tz=TIMEZONE)
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
            current_hour = datetime.now().hour
            settings = self._schedule_manager.get_hourly_settings(current_hour)
            charge_rate = settings.get("charge_rate", 0)

            if self._power_monitor:
                self._power_monitor.update_target_charging_power(charge_rate)
                self._power_monitor.adjust_battery_charging()

        except (AttributeError, ValueError, KeyError) as e:
            logger.error("Failed to adjust charging power: %s", str(e))

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

            logger.info("Settings updated successfully")

        except Exception as e:
            logger.error(f"Failed to update settings: {e}")
            raise SystemConfigurationError(message=f"Invalid settings: {e}") from e

    def _log_battery_system_config(self) -> None:
        """Log the current battery configuration - reproduces original functionality."""
        try:
            # Get energy data for consumption info (like original)
            predictions_consumption = self.controller.get_estimated_consumption()

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
    ║ Charge Cycle Cost                ║ {self.battery_settings.cycle_cost_per_kwh:>12.2f} SEK ║
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

        now = datetime.now(tz=TIMEZONE)
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
