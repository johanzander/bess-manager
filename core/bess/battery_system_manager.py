"""
Complete replacement for battery_system.py that preserves ALL functionality.

"""

import logging
from datetime import datetime
from typing import Any

from .daily_view_builder import DailyView, DailyViewBuilder
from .dp_battery_algorithm import optimize_battery_schedule, print_results_table
from .dp_schedule import DPSchedule
from .energy_flow_calculator import EnergyFlowCalculator
from .growatt_schedule import GrowattScheduleManager
from .health_check import run_system_health_checks
from .historical_data_store import HistoricalDataStore, HourlyEvent
from .power_monitor import HomePowerMonitor
from .price_manager import HomeAssistantSource, PriceManager
from .schedule_store import ScheduleStore
from .sensor_collector import SensorCollector
from .settings import BatterySettings, HomeSettings, PriceSettings

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

    def __init__(self, controller=None, price_source=None):
        """Initialize with same interface as original BatterySystemManager."""

        # Initialize settings (preserve original defaults)
        self.battery_settings = BatterySettings()
        self.home_settings = HomeSettings()
        self.price_settings = PriceSettings()

        # Store controller reference
        self._controller = controller

        # Initialize core data stores with proper component separation
        self.historical_store = HistoricalDataStore(
            self.battery_settings.total_capacity
        )
        self.schedule_store = ScheduleStore()

        # Initialize specialized components
        self.sensor_collector = SensorCollector(
            controller, self.battery_settings.total_capacity
        )
        self.energy_flow_calculator = EnergyFlowCalculator(
            self.battery_settings.total_capacity
        )

        # Initialize view builder
        self.daily_view_builder = DailyViewBuilder(
            self.historical_store,
            self.schedule_store,
            self.battery_settings.total_capacity,
            self.battery_settings.cycle_cost_per_kwh,
        )

        # Initialize hardware interface with battery settings
        self._schedule_manager = GrowattScheduleManager(battery_settings=self.battery_settings)

        # Initialize price manager
        if not price_source:
            price_source = HomeAssistantSource(controller)

        self._price_manager = PriceManager(
            price_source=price_source,
            markup_rate=self.price_settings.markup_rate,
            vat_multiplier=self.price_settings.vat_multiplier,
            additional_costs=self.price_settings.additional_costs,
            tax_reduction=self.price_settings.tax_reduction,
        )

        # Initialize monitors (created in start() if controller available)
        self._power_monitor = None
        self._battery_monitor = None

        # Current schedule tracking
        self._current_schedule = None
        self._initial_soc = None

        logger.info("BatterySystemManager initialized with strategic intent support")

    def start(self):
        """Start the system - preserves original functionality."""
        try:
            # Initialize monitors if controller available
            if self._controller:
                self._power_monitor = HomePowerMonitor(
                    self._controller,
                    home_settings=self.home_settings,
                    battery_settings=self.battery_settings,
                )

                # Initialize schedule from inverter - preserves original logic
                self._initialize_tou_schedule_from_inverter()

                # Initialize historical data - using improved sensor collector
                self._fetch_and_initialize_historical_data()

                # Fetch predictions
                self._fetch_predictions()

                # Run health check
                self._run_health_check()

            self.log_system_startup()
            logger.info("BatterySystemManager started successfully")

        except Exception as e:
            logger.error(f"Failed to start BatterySystemManager: {e}")
            raise

    def update_battery_schedule(
        self, hour: int, prepare_next_day: bool = False
    ) -> bool:
        """Main schedule update method"""

        # Input validation
        if not 0 <= hour <= 23:
            logger.error("Invalid hour: %d (must be 0-23)", hour)
            raise ValueError(f"Invalid hour: {hour} (must be 0-23)")

        if prepare_next_day:
            logger.info("Preparing schedule for next day at hour %02d:00", hour)
        else:
            logger.info("Updating battery schedule for hour %02d:00", hour)

        is_first_run = self._current_schedule is None

        try:
            # Handle special cases (midnight, next day prep)
            self._handle_special_cases(hour, prepare_next_day)

            # Get price data
            prices, price_entries = self._get_price_data(prepare_next_day)
            if not prices:
                logger.warning("Schedule update aborted: No price data available")
                return False

            # Update energy data for completed hour
            self._update_energy_data(hour, is_first_run, prepare_next_day)

            # Get current battery state
            current_soc = self._get_current_battery_soc()
            if current_soc is None:
                logger.error("Failed to get battery SOC")
                return False

            # Gather optimization data
            optimization_data_result = self._gather_optimization_data(
                hour, current_soc, prepare_next_day
            )

            if optimization_data_result is None:
                logger.error("Failed to gather optimization data")
                return False

            optimization_hour, optimization_data = optimization_data_result

            # Run optimization using DP algorithm with strategic intent capture
            optimization_result = self._run_optimization(
                optimization_hour,
                current_soc,
                optimization_data,
                prices,
                prepare_next_day,
            )

            # Create new schedule 
            schedule_result = self._create_updated_schedule(
                optimization_hour,
                optimization_result,
                prices,
                optimization_data,
                is_first_run,
                prepare_next_day,
            )

            temp_schedule, temp_growatt = schedule_result
            temp_growatt.current_hour = hour

            # Determine if we should apply the new schedule
            should_apply, reason = self._should_apply_schedule(
                is_first_run,
                hour,
                prepare_next_day,
                temp_growatt,
                optimization_hour,
                temp_schedule,
            )

            # Apply schedule if needed
            if should_apply:
                self._apply_schedule(
                    hour, temp_schedule, temp_growatt, reason, prepare_next_day
                )
            else:
                # Update current schedule even when TOU doesn't change
                self._current_schedule = temp_schedule      
                          
                # Ensure hourly settings exist even when TOU doesn't change
                if not self._schedule_manager.hourly_settings:
                    self._schedule_manager.hourly_settings = temp_growatt.hourly_settings
                    self._schedule_manager.strategic_intents = temp_growatt.strategic_intents

            # Apply current hour settings
            if not prepare_next_day:
                self._apply_hourly_schedule(hour)
                logger.info("Applied hourly settings for hour %02d:00", hour)

            self.log_battery_schedule()
            return True

        except Exception as e:
            logger.error(f"Failed to update battery schedule: {e}")
            return False

    def log_battery_schedule(self) -> None:
        if not self._current_schedule:
            logger.warning("No current schedule available for reporting")
            return

        daily_view = self.get_current_daily_view()
        self.daily_view_builder.log_complete_daily_schedule(daily_view)

        self._schedule_manager.log_current_TOU_schedule(
            "=== GROWATT TOU SCHEDULE ==="
        )
        self._schedule_manager.log_detailed_schedule(
            "=== GROWATT DETAILED SCHEDULE WITH STRATEGIC INTENTS ==="
        )

    def _initialize_tou_schedule_from_inverter(self):
        """Initialize schedule from current inverter settings."""
        try:
            logger.info("Reading current TOU schedule from inverter")
            inverter_segments = self._controller.read_inverter_time_segments()

            current_hour = datetime.now().hour
            self._schedule_manager.initialize_from_tou_segments(
                inverter_segments, current_hour
            )

        except Exception as e:
            logger.error(f"Failed to read current inverter schedule: {e}")

    def _fetch_and_initialize_historical_data(self):
        """DEBUG: Check if data is actually being stored."""
        try:
            current_hour, current_minute, today = self._get_current_time_info()
            end_hour = self._determine_historical_end_hour(current_hour, current_minute)

            if end_hour >= 0:
                historical_flows = self.sensor_collector.reconstruct_historical_flows(
                    0, end_hour
                )

                for hour, flows in historical_flows.items():
                    try:
                        self._record_historical_event(hour, flows)
                        logger.debug(f"Stored hour {hour}: {flows}")
                    except Exception as e:
                        logger.warning(f"Failed to record hour {hour}: {e}")

                # Verify storage
                completed_hours = self.historical_store.get_completed_hours()
                logger.info(
                    f"Historical store now contains {len(completed_hours)} hours: {completed_hours}"
                )

        except Exception as e:
            logger.error(f"Failed to initialize historical data: {e}")

    def _fetch_predictions(self):
        """Fetch consumption and solar predictions and store them."""
        try:
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

    def _get_consumption_predictions(self) -> list[float]:
        """Get consumption predictions directly from controller."""
        try:
            predictions = self._controller.get_estimated_consumption()
            if predictions and len(predictions) == 24:
                return predictions
        except Exception as e:
            logger.warning(f"Failed to get consumption predictions: {e}")

        return [4.0] * 24  # Default fallback

    def _get_solar_predictions(self) -> list[float]:
        """Get solar predictions directly from controller."""
        try:
            predictions = self._controller.get_solar_forecast()
            if predictions and len(predictions) == 24:
                return predictions
        except Exception as e:
            logger.warning(f"Failed to get solar predictions: {e}")

        return [0.0] * 24  # Default fallback

    def _handle_special_cases(self, hour: int, prepare_next_day: bool):
        """Handle special cases like midnight transition."""
        if hour == 0 and not prepare_next_day:
            try:
                current_soc = self._controller.get_battery_soc()
                self._initial_soc = current_soc
                logger.info(f"Setting initial SOC for day: {self._initial_soc}%")
            except Exception as e:
                logger.warning(f"Failed to get initial SOC: {e}")

        if prepare_next_day:
            logger.info("Preparing for next day - refreshing predictions")
            self._fetch_predictions()

    def _get_price_data(self, prepare_next_day: bool):
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

            # Handle DST transitions
            if len(prices) == 23:
                logger.info("Detected DST spring forward transition")
            elif len(prices) == 25:
                logger.info("Detected DST fall back transition")
            elif len(prices) != 24:
                logger.warning(f"Expected 24 prices but got {len(prices)}")

            return prices, price_entries

        except Exception as e:
            logger.error(f"Failed to fetch price data: {e}")
            return None, None

    def _update_energy_data(
        self, hour: int, is_first_run: bool, prepare_next_day: bool):
        """Track energy data collection with strategic intent."""
        logger.info(f"=== ENERGY DATA UPDATE DEBUG START ===")
        logger.info(f"Hour: {hour}, is_first_run: {is_first_run}, prepare_next_day: {prepare_next_day}")
        
        if not is_first_run and hour > 0 and not prepare_next_day:
            prev_hour = hour - 1
            logger.info(f"Should collect data for previous hour: {prev_hour}")

            try:
                logger.info(f"Calling sensor_collector.collect_hour_flows({prev_hour})")
                hourly_flows = self.sensor_collector.collect_hour_flows(prev_hour)
                
                if hourly_flows:
                    logger.info(f"SUCCESS: Got flows for hour {prev_hour} with intent {hourly_flows.get('strategic_intent', 'UNKNOWN')}")
                    logger.info(f"Calling _record_historical_event({prev_hour}, flows)")
                    self._record_historical_event(prev_hour, hourly_flows)
                    logger.info(f"SUCCESS: Recorded energy flows for hour {prev_hour}")
                    
                    # Verify it was actually stored
                    stored_event = self.historical_store.get_hour_event(prev_hour)
                    if stored_event:
                        logger.info(f"VERIFIED: Hour {prev_hour} data is now in historical store with intent {stored_event.strategic_intent}")
                    else:
                        logger.error(f"FAILED: Hour {prev_hour} data was NOT stored in historical store")
                else:
                    logger.error(f"FAILED: sensor_collector returned no flows for hour {prev_hour}")
                    
                    # Debug sensor collector state
                    logger.error(f"Sensor collector debug info:")
                    logger.error(f"  - Controller available: {self.sensor_collector._controller is not None}")

            except Exception as e:
                logger.error(f"EXCEPTION in data collection for hour {prev_hour}: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")

        else:
            logger.info(f"Skipping data collection: is_first_run={is_first_run}, hour={hour}, prepare_next_day={prepare_next_day}")

        # Log energy balance
        if not prepare_next_day:
            try:
                logger.info("Calling _log_energy_balance()")
                self._log_energy_balance()
            except Exception as e:
                logger.error(f"EXCEPTION in _log_energy_balance(): {e}")

        # Final check: what hours do we have stored?
        completed_hours = self.historical_store.get_completed_hours()
        logger.info(f"Historical store after update: {completed_hours}")
        logger.info(f"=== ENERGY DATA UPDATE DEBUG END ===")

    def _get_current_battery_soc(self) -> float | None:
        """Get current battery SOC with validation."""
        try:
            if self._controller:
                soc = self._controller.get_battery_soc()
                if soc is not None and 0 <= soc <= 100:
                    return soc
                else:
                    logger.warning(f"Invalid SOC from controller: {soc}")

            # Fallback to last known state
            latest_soc, _ = self.historical_store.get_latest_battery_state()
            return latest_soc

        except Exception as e:
            logger.error(f"Failed to get battery SOC: {e}")
            return None

    def _gather_optimization_data(
        self, hour: int, current_soc: float, prepare_next_day: bool
    ):
        """FIXED: Always return full 24-hour data combining actuals + predictions."""

        if not 0 <= hour <= 23:
            logger.error(f"Invalid hour: {hour}")
            return None

        current_soe = current_soc / 100.0 * self.battery_settings.total_capacity

        # Always build full 24-hour arrays
        consumption_data = [0.0] * 24
        solar_data = [0.0] * 24
        combined_soe = [current_soe] * 24
        combined_actions = [0.0] * 24
        solar_charged = [0.0] * 24

        if prepare_next_day:
            # For next day, use predictions only
            consumption_predictions = self._get_consumption_predictions()
            solar_predictions = self._get_solar_predictions()

            consumption_data = consumption_predictions
            solar_data = solar_predictions
            optimization_hour = 0

        else:
            # FIXED: For today, ALWAYS combine actuals for past hours + predictions for future
            completed_hours = self.historical_store.get_completed_hours()
            predictions_consumption = self._get_consumption_predictions()
            predictions_solar = self._get_solar_predictions()
            logger.info(f"Stored hours: {completed_hours}")

            for h in range(24):
                if h in completed_hours and h < hour:
                    # Use actual data for past hours
                    event = self.historical_store.get_hour_event(h)
                    if event:
                        consumption_data[h] = event.home_consumed
                        solar_data[h] = event.solar_generated
                        combined_soe[h] = (
                            event.battery_soc_end / 100.0
                        ) * self.battery_settings.total_capacity
                        combined_actions[h] = (
                            event.battery_charged - event.battery_discharged
                        )
                        solar_charged[h] = min(
                            event.battery_charged, event.solar_generated
                        )
                    else:
                        # Fallback to predictions if event missing
                        consumption_data[h] = (
                            predictions_consumption[h]
                            if h < len(predictions_consumption)
                            else 4.0
                        )
                        solar_data[h] = (
                            predictions_solar[h] if h < len(predictions_solar) else 0.0
                        )
                else:
                    # Use predictions for current and future hours
                    consumption_data[h] = (
                        predictions_consumption[h]
                        if h < len(predictions_consumption)
                        else 4.0
                    )
                    solar_data[h] = (
                        predictions_solar[h] if h < len(predictions_solar) else 0.0
                    )

            optimization_hour = hour

        # Ensure current hour has correct SOE
        combined_soe[optimization_hour] = current_soe

        optimization_data = {
            "full_consumption": consumption_data,
            "full_solar": solar_data,
            "combined_actions": combined_actions,
            "combined_soe": combined_soe,
            "solar_charged": solar_charged,
        }

        logger.debug(f"Optimization data prepared for hour {optimization_hour}")
        return optimization_hour, optimization_data

    def _run_optimization(
        self,
        optimization_hour: int,
        current_soc: float,
        optimization_data: dict,
        prices: list,
        prepare_next_day: bool,
    ):
        """Run optimization - now captures strategic intents."""

        try:
            current_soe = optimization_data["combined_soe"][optimization_hour]

            # Calculate initial cost basis
            if prepare_next_day:
                initial_cost_basis = self.battery_settings.cycle_cost_per_kwh
            else:
                initial_cost_basis = self._calculate_initial_cost_basis(
                    optimization_hour
                )

            # Get optimization portions
            remaining_prices = prices[optimization_hour:]
            remaining_consumption = optimization_data["full_consumption"][
                optimization_hour:
            ]
            remaining_solar = optimization_data["full_solar"][optimization_hour:]

            # Ensure array lengths match
            n_hours = len(remaining_prices)
            if len(remaining_consumption) != n_hours:
                if len(remaining_consumption) < n_hours:
                    remaining_consumption.extend(
                        [4.0] * (n_hours - len(remaining_consumption))
                    )
                else:
                    remaining_consumption = remaining_consumption[:n_hours]

            if len(remaining_solar) != n_hours:
                if len(remaining_solar) < n_hours:
                    remaining_solar.extend([0.0] * (n_hours - len(remaining_solar)))
                else:
                    remaining_solar = remaining_solar[:n_hours]

            logger.info(
                f"Running optimization for {n_hours} hours from hour {optimization_hour} with strategic intent capture"
            )

            # Calculate buy and sell prices
            buy_prices = self._price_manager.get_buy_prices(raw_prices=remaining_prices)
            sell_prices = self._price_manager.get_sell_prices(
                raw_prices=remaining_prices
            )

            # Run DP optimization with strategic intent capture
            result = optimize_battery_schedule(
                buy_price=buy_prices,
                sell_price=sell_prices,
                home_consumption=remaining_consumption,
                solar_production=remaining_solar,
                initial_soc=current_soe,
                battery_settings=self.battery_settings,
                initial_cost_basis=initial_cost_basis,
            )

            # Log strategic intent summary
            strategic_intents = result.get("strategic_intent", [])
            if strategic_intents:
                intent_counts = {}
                for intent in strategic_intents:
                    intent_counts[intent] = intent_counts.get(intent, 0) + 1
                logger.info(
                    f"Strategic decisions for hours {optimization_hour}-{optimization_hour + len(strategic_intents) - 1}: {intent_counts}"
                )

            # Print results table with strategic intents
            print_results_table(
                result["hourly_data"],
                result["economic_results"],
                result["input_data"]["buy_price"],
                result["input_data"]["sell_price"],
            )

            # Store full day data in result for UI
            if "input_data" in result:
                result["input_data"]["full_home_consumption"] = optimization_data[
                    "full_consumption"
                ]
                result["input_data"]["full_solar_production"] = optimization_data[
                    "full_solar"
                ]

            return result

        except Exception as e:
            logger.error(f"Optimization failed: {e}")
            return None

    def _create_updated_schedule(
        self,
        optimization_hour: int,
        result: dict,
        prices: list,
        optimization_data: dict,
        is_first_run: bool,
        prepare_next_day: bool,
    ):
        """Create updated schedule from optimization results with strategic intents."""

        try:
            logger.info("=== SCHEDULE CREATION DEBUG START ===")
            logger.info(
                f"optimization_hour: {optimization_hour}, prepare_next_day: {prepare_next_day}"
            )

            # Extract results including strategic intents
            hourly_data = result.get("hourly_data", {})
            strategic_intents = result.get("strategic_intent", [])

            logger.info("HOUR MAPPING DEBUG:")
            logger.info(f"  optimization_hour: {optimization_hour}")
            logger.info(f"  strategic_intents from DP: {strategic_intents}")
            logger.info(f"  len(strategic_intents): {len(strategic_intents)}")

            # Initialize full day arrays (24 hours) - these should start as the current state
            combined_actions = optimization_data["combined_actions"].copy()
            combined_soe = optimization_data["combined_soe"].copy()
            solar_charged = optimization_data["solar_charged"].copy()

            logger.info(f"Initial combined_actions length: {len(combined_actions)}")
            logger.info(f"Initial combined_soe length: {len(combined_soe)}")

            # CRITICAL FIX: Map optimization results to correct hours
            if "battery_action" in hourly_data:
                battery_actions = hourly_data["battery_action"]
                logger.info(
                    f"Got {len(battery_actions)} battery actions from optimization"
                )

                for i, action in enumerate(battery_actions):
                    target_hour = optimization_hour + i
                    if target_hour < 24:
                        logger.info(
                            f"  Mapping battery action index {i} (action={action:.1f}) to hour {target_hour}"
                        )
                        combined_actions[target_hour] = action
                    else:
                        logger.warning(
                            f"  Target hour {target_hour} out of range for battery action, skipping"
                        )

            if "state_of_charge" in hourly_data:
                soc_values = hourly_data["state_of_charge"]
                logger.info(f"Got {len(soc_values)} SOC values from optimization")

                for i, soc in enumerate(soc_values):
                    target_hour = optimization_hour + i
                    if target_hour < 24:
                        logger.info(
                            f"  Mapping SOC index {i} (SOC={soc:.1f}) to hour {target_hour}"
                        )
                        if soc <= 1.0:  # Convert percentage to kWh if needed
                            combined_soe[target_hour] = (
                                soc * self.battery_settings.total_capacity
                            )
                        else:
                            combined_soe[target_hour] = soc
                    else:
                        logger.warning(
                            f"  Target hour {target_hour} out of range for SOC, skipping"
                        )

            # CRITICAL FIX: Create strategic intents array for full day
            full_day_strategic_intents = ["IDLE"] * 24  # Initialize all hours as IDLE

            # Map optimization strategic intents to correct hours
            logger.info("Mapping strategic intents to full day:")
            for i, intent in enumerate(strategic_intents):
                target_hour = optimization_hour + i
                if target_hour < 24:
                    logger.info(
                        f"  Mapping strategic intent index {i} (intent={intent}) to hour {target_hour}"
                    )
                    full_day_strategic_intents[target_hour] = intent
                else:
                    logger.warning(
                        f"  Strategic intent target hour {target_hour} out of range, skipping"
                    )

            # ADD: Correct historical hours with actual strategic intents BEFORE creating schedules
            if not prepare_next_day:
                current_hour = datetime.now().hour
                for hour in range(min(current_hour, 24)):
                    if hour < len(full_day_strategic_intents):
                        event = self.historical_store.get_hour_event(hour)
                        if event and hasattr(event, 'strategic_intent'):
                            full_day_strategic_intents[hour] = event.strategic_intent
                            logger.debug(
                                f"Hour {hour}: Corrected intent from IDLE to '{event.strategic_intent}'"
                            )

            # Log final mapping verification
            export_hours = [
                h
                for h, intent in enumerate(full_day_strategic_intents)
                if intent == "EXPORT_ARBITRAGE"
            ]
            logger.info(f"EXPORT_ARBITRAGE mapped to hours: {export_hours}")

            # Store in schedule store
            self.schedule_store.store_schedule(
                algorithm_result=result,
                optimization_hour=optimization_hour,
                scenario="tomorrow" if prepare_next_day else "hourly",
            )

            # Create DPSchedule with corrected strategic intents
            temp_schedule = DPSchedule(
                actions=combined_actions,
                state_of_energy=combined_soe,
                prices=prices,
                cycle_cost=self.battery_settings.cycle_cost_per_kwh,
                hourly_consumption=optimization_data["full_consumption"],
                hourly_data=result.get("hourly_data", {}),
                summary=result.get("summary", {}),
                solar_charged=solar_charged,
                original_dp_results=result.copy(),
            )

            # CRITICAL FIX: Override the strategic intents in the schedule with corrected data
            temp_schedule.original_dp_results["strategic_intent"] = full_day_strategic_intents
            temp_schedule.strategic_intents = full_day_strategic_intents

            # Verify the schedule has correct intents
            logger.info(
                f"Created schedule with {len(temp_schedule.strategic_intents)} strategic intents"
            )
            export_hours_final = [
                h
                for h, intent in enumerate(temp_schedule.strategic_intents)
                if intent == "EXPORT_ARBITRAGE"
            ]
            logger.info(
                f"Final EXPORT_ARBITRAGE hours in schedule: {export_hours_final}"
            )

            # Create Growatt schedule manager with strategic intents
            temp_growatt = GrowattScheduleManager(battery_settings=self.battery_settings)

            # IMPORTANT: Set the corrected strategic intents BEFORE creating the schedule
            temp_growatt.strategic_intents = full_day_strategic_intents

            # Copy existing TOU intervals for past hours if not preparing next day
            if not prepare_next_day and hasattr(
                self._schedule_manager, "tou_intervals"
            ):
                for segment in self._schedule_manager.tou_intervals:
                    start_hour = int(segment["start_time"].split(":")[0])
                    if start_hour < optimization_hour:
                        temp_growatt.tou_intervals.append(segment.copy())

            effective_hour = 0 if prepare_next_day else optimization_hour
            temp_growatt.current_hour = effective_hour

            # Create schedule with strategic intents - this is the key change!
            logger.info(
                f"Creating Growatt schedule with current_hour={temp_growatt.current_hour}"
            )
            temp_growatt.create_schedule(temp_schedule)

            # Verify Growatt schedule has correct intents
            growatt_export_hours = []
            for hour in range(24):
                settings = temp_growatt.get_hourly_settings(hour)
                if settings.get("strategic_intent") == "EXPORT_ARBITRAGE":
                    growatt_export_hours.append(hour)
            logger.info(
                f"Growatt schedule EXPORT_ARBITRAGE hours: {growatt_export_hours}"
            )

            if prepare_next_day:
                logger.info("Prepared next day's schedule with strategic intents")
            else:
                logger.info(
                    f"Updated schedule from hour {optimization_hour:02d}:00 with strategic intents"
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
        hour: int,
        prepare_next_day: bool,
        temp_growatt,
        optimization_hour: int,
        temp_schedule,
    ):
        """Determine if schedule should be applied based on TOU differences from current hour onwards."""
        
        logger.info("Evaluating whether to apply new schedule at hour %d", hour)

        # Special case: preparing next day (runs at 23:55 for 00:00 start)
        if prepare_next_day:
            # Compare full day TOU settings for tomorrow
            self._schedule_manager.current_hour = 0  # Compare from start of day
            temp_growatt.current_hour = 0
            
            schedules_differ, reason = self._schedule_manager.compare_schedules(
                other_schedule=temp_growatt, from_hour=0
            )
            
            logger.info("DECISION for next day: %s - %s", "Apply" if schedules_differ else "Keep", reason)
            return schedules_differ, f"Next day: {reason}"

        # Normal case: compare TOU settings from current hour onwards
        try:
            self._schedule_manager.current_hour = hour
            temp_growatt.current_hour = hour

            schedules_differ, reason = self._schedule_manager.compare_schedules(
                other_schedule=temp_growatt, from_hour=hour
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
        hour: int,
        temp_schedule,
        temp_growatt,
        reason: str,
        prepare_next_day: bool,
    ):
        """Apply schedule to hardware - preserves original TOU logic."""

        logger.info("=" * 80)
        logger.info("=== SCHEDULE APPLICATION START ===")
        logger.info(
            "Hour: %02d, Reason: %s, Next day: %s", hour, reason, prepare_next_day
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

            effective_hour = 0 if prepare_next_day else hour

            # Find segments to disable and update
            to_disable = []
            to_update = []

            logger.info(
                "Analyzing TOU changes from hour %02d onwards...", effective_hour
            )

            # Identify segments to disable
            for current in current_tou:
                start_hour = int(current["start_time"].split(":")[0])
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
                        self._controller.set_inverter_time_segment(**segment)
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
                        self._controller.set_inverter_time_segment(**segment)
                        logger.debug("SUCCESS: Segment updated")
                    except Exception as e:
                        logger.error("FAILED: Failed to update TOU segment: %s", e)
            else:
                logger.info("No TOU segment changes needed")

            # Update schedule manager
            temp_growatt.current_hour = hour
            self._schedule_manager = temp_growatt

            # Apply current hour settings
            if not prepare_next_day:
                self._apply_hourly_schedule(hour)

            logger.info("Schedule applied successfully")

        except Exception as e:
            logger.error("Failed to apply schedule: %s", e)
            raise

    def _apply_hourly_schedule(self, hour: int):
        """Apply hourly settings with proper charge/discharge power rates."""
        logger.info("=== APPLY HOURLY SCHEDULE ===")

        # Get schedule settings for current hour
        settings = self._schedule_manager.get_hourly_settings(hour)

        # Log strategic context with power information
        strategic_intent = settings["strategic_intent"]
        battery_action_kw = settings["battery_action_kw"]
        charge_rate = settings.get("charge_rate", 0)
        discharge_rate = settings["discharge_rate"]
        
        logger.info(
            "Strategic context: Intent=%s, Action=%.2f kW, ChargeRate=%d%%, DischargeRate=%d%%",
            strategic_intent,
            battery_action_kw,
            charge_rate,
            discharge_rate,
        )

        # Apply grid charge setting
        grid_charge_value = settings["grid_charge"]
        logger.info(
            "HARDWARE: Setting grid charge to %s for hour %02d:00",
            grid_charge_value,
            hour,
        )
        self._controller.set_grid_charge(grid_charge_value)

        # Apply charging power rate (when grid charging is enabled)
        if grid_charge_value and charge_rate > 0:
            logger.info(
                "HARDWARE: Setting charging power rate to %d%% for hour %02d:00",
                charge_rate,
                hour,
            )
            self._controller.set_charging_power_rate(charge_rate)

        # Apply discharge power rate
        logger.info(
            "HARDWARE: Setting discharge power rate to %d%% for hour %02d:00",
            discharge_rate,
            hour,
        )
        self._controller.set_discharging_power_rate(discharge_rate)


    def _record_historical_event(self, hour: int, flows: dict):
        """Record historical event from energy flows with cost data and strategic intent."""
        try:
            battery_soc_end = flows.get("battery_soc", 10.0)

            # Calculate start SOC
            previous_event = (
                self.historical_store.get_hour_event(hour - 1) if hour > 0 else None
            )
            if previous_event:
                battery_soc_start = previous_event.battery_soc_end
            else:
                battery_charge = flows.get("battery_charged", 0.0)
                battery_discharge = flows.get("battery_discharged", 0.0)
                net_delta_kwh = battery_charge - battery_discharge
                net_delta_percent = (
                    net_delta_kwh / self.battery_settings.total_capacity
                ) * 100.0
                battery_soc_start = max(0, battery_soc_end - net_delta_percent)

            # Get price for this hour
            today_prices = self._price_manager.get_today_prices()
            if hour < len(today_prices):
                buy_price = today_prices[hour].get("buyPrice", 1.0)

            # Calculate cost scenarios
            home_consumed = flows.get("load_consumption", 0.0)
            solar_generated = flows.get("system_production", 0.0)
            grid_imported = flows.get("import_from_grid", 0.0)
            grid_exported = flows.get("export_to_grid", 0.0)

            # Grid-only cost (baseline)
            base_cost = home_consumed * buy_price

            # Solar-only cost (with solar, no battery)
            direct_solar = min(home_consumed, solar_generated)
            grid_needed = max(0, home_consumed - direct_solar)
            solar_excess = max(0, solar_generated - direct_solar)
            solar_only_cost = (
                grid_needed * buy_price - solar_excess * buy_price * 0.6
            )

            # Optimized cost (actual with battery + solar)
            optimized_cost = (
                grid_imported * buy_price
                - grid_exported * buy_price * 0.6
            )

            # Calculate savings breakdown without capping
            solar_savings = base_cost - solar_only_cost
            battery_savings = solar_only_cost - optimized_cost
            hourly_savings = (
                base_cost - optimized_cost
            )  # Total savings (solar + battery)

            # Use strategic intent from SensorCollector (already calculated)
            strategic_intent = flows.get("strategic_intent", "IDLE")

            event = HourlyEvent(
                hour=hour,
                timestamp=datetime.now(),
                battery_soc_start=battery_soc_start,
                battery_soc_end=battery_soc_end,
                solar_generated=solar_generated,
                home_consumed=home_consumed,
                grid_imported=grid_imported,
                grid_exported=grid_exported,
                battery_charged=flows.get("battery_charged", 0.0),
                battery_discharged=flows.get("battery_discharged", 0.0),
                # Cost data
                base_cost=base_cost,
                solar_only_cost=solar_only_cost,
                optimized_cost=optimized_cost,
                hourly_savings=hourly_savings,
                solar_savings=solar_savings,
                battery_savings=battery_savings,
                buy_price=buy_price,
                strategic_intent=strategic_intent,
            )

            self.historical_store.record_hour_completion(event)

        except Exception as e:
            logger.error(f"Failed to record event for hour {hour}: {e}")
            
    def _calculate_initial_cost_basis(self, current_hour: int) -> float:
        """Calculate cost basis using the same logic as the energy balance table."""
        try:
            current_soc = self._get_current_battery_soc()
            current_soe = (current_soc / 100.0) * self.battery_settings.total_capacity
        except Exception as e:
            logger.warning(f"Failed to get current SOC: {e}")
            return self.battery_settings.cycle_cost_per_kwh

        if current_soe <= self.battery_settings.reserved_capacity + 0.1:
            return 0.0

        completed_hours = self.historical_store.get_completed_hours()

        if not completed_hours:
            return self.battery_settings.cycle_cost_per_kwh

        running_energy = 0.0
        running_total_cost = 0.0

        for hour in sorted(completed_hours):
            if hour >= current_hour:
                continue

            event = self.historical_store.get_hour_event(hour)
            if not event:
                continue

            # Get price for this hour
            today_prices = self._price_manager.get_today_prices()
            hour_price = (
                today_prices[hour]["buyPrice"] if hour < len(today_prices) else 1.0
            )

            # Handle charging using the SAME logic as _log_energy_balance()
            if event.battery_charged > 0:
                # Use the same simple calculation as the energy balance table
                solar_to_battery = min(event.battery_charged, event.solar_generated)
                grid_to_battery = max(0, event.battery_charged - solar_to_battery)

                # Calculate costs
                solar_cost = solar_to_battery * self.battery_settings.cycle_cost_per_kwh
                grid_cost = grid_to_battery * (
                    hour_price + self.battery_settings.cycle_cost_per_kwh
                )

                new_energy_cost = solar_cost + grid_cost
                running_total_cost += new_energy_cost
                running_energy += event.battery_charged

                logger.info(
                    f"Hour {hour:02d}: Charged {event.battery_charged:.2f} kWh "
                    f"(Solar: {solar_to_battery:.2f} @ {self.battery_settings.cycle_cost_per_kwh:.3f}, "
                    f"Grid: {grid_to_battery:.2f} @ {hour_price + self.battery_settings.cycle_cost_per_kwh:.3f}) "
                    f"Running avg: {running_total_cost/running_energy:.3f} SEK/kWh"
                )

            # Handle discharging
            if event.battery_discharged > 0:
                if running_energy > 0:
                    # Calculate proportional cost to remove (weighted average cost)
                    avg_cost_per_kwh = running_total_cost / running_energy
                    discharged_cost = (
                        min(event.battery_discharged, running_energy) * avg_cost_per_kwh
                    )

                    # Remove proportional cost and energy
                    running_total_cost = max(0, running_total_cost - discharged_cost)
                    running_energy = max(0, running_energy - event.battery_discharged)

                    logger.debug(
                        f"Hour {hour:02d}: Discharged {event.battery_discharged:.2f} kWh "
                        f"@ {avg_cost_per_kwh:.3f} SEK/kWh, "
                        f"removed {discharged_cost:.3f} SEK cost"
                    )

                    if running_energy <= 0.1:
                        running_total_cost = 0.0
                        running_energy = 0.0

        if running_energy > 0.1:
            cost_basis = running_total_cost / running_energy
            logger.info(f"Final cost basis: {cost_basis:.3f} SEK/kWh")
            return cost_basis

        return self.battery_settings.cycle_cost_per_kwh

    def _get_current_time_info(self):
        """Get current time information."""
        now = datetime.now()
        return now.hour, now.minute, now.date()

    def _determine_historical_end_hour(self, current_hour, current_minute):
        """Determine end hour for historical data collection."""
        if current_minute < 5:
            return current_hour - 1 if current_hour > 0 else 0
        return current_hour

    def _run_health_check(self):
        """Run system health check."""
        try:
            logger.info("Running system health check...")
            health_results = run_system_health_checks(self)

            logger.info("System Health Check Results:")
            logger.info("=" * 80)

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

            logger.info("=" * 80)
            return health_results

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"status": "ERROR", "checks": []}

    def get_current_schedule(self) -> dict[str, Any]:
        """Get current schedule data for display (does not run optimization)."""
        if not self._current_schedule:
            logger.warning("No current schedule available")
            return None
        
        return self._current_schedule.get_schedule_data()

    def _get_today_price_data(self):
        """Get today's price data for reports and views."""
        try:
            today_prices = self._price_manager.get_today_prices()
            return [p["buyPrice"] for p in today_prices]
        except Exception as e:
            logger.warning(f"Failed to get today's price data: {e}")
            return [1.0] * 24

    @property
    def price_manager(self):
        """Getter for price_manager to ensure API compatibility."""
        return self._price_manager

    def get_historical_events(self) -> list:
        """Get all historical events for frontend analytics."""
        completed_hours = self.historical_store.get_completed_hours()
        logger.info(f"Stored hours: {completed_hours}")
        events = []

        for hour in completed_hours:
            event = self.historical_store.get_hour_event(hour)
            if event:
                events.append(
                    {
                        "hour": event.hour,
                        "timestamp": event.timestamp.isoformat(),
                        "battery_soc_start": event.battery_soc_start,
                        "battery_soc_end": event.battery_soc_end,
                        "solar_generated": event.solar_generated,
                        "home_consumed": event.home_consumed,
                        "grid_imported": event.grid_imported,
                        "grid_exported": event.grid_exported,
                        "battery_charged": event.battery_charged,
                        "battery_discharged": event.battery_discharged,
                        "battery_net_change": event.battery_net_change,
                        # ADD camelCase versions
                        "batterySOCStart": event.battery_soc_start,
                        "batterySOCEnd": event.battery_soc_end,
                        "solarGenerated": event.solar_generated,
                        "homeConsumed": event.home_consumed,
                        "gridImported": event.grid_imported,
                        "gridExported": event.grid_exported,
                        "batteryCharged": event.battery_charged,
                        "batteryDischarged": event.battery_discharged,
                        "batteryNetChange": event.battery_net_change,
                    }
                )

        return events

    # 2. Missing: get_optimization_history() - used by decision insights
    def get_optimization_history(self) -> list:
        """Get all optimization decisions for frontend analytics."""
        schedules = self.schedule_store.get_all_schedules_today()
        decisions = []

        for schedule in schedules:
            context = schedule.algorithm_result.get("optimization_context", {})
            econ_results = schedule.algorithm_result.get("economic_results", {})

            decisions.append(
                {
                    "timestamp": schedule.timestamp.isoformat(),
                    "optimization_hour": schedule.optimization_hour,
                    "scenario": schedule.created_for_scenario,
                    "initial_soc_percent": context.get("initial_soc_percent"),
                    "cost_basis_sek_per_kwh": context.get("cost_basis_sek_per_kwh"),
                    "predicted_savings": econ_results.get(
                        "base_to_battery_solar_savings", 0
                    ),
                    "horizon_hours": context.get("optimization_horizon_hours"),
                    # ADD camelCase versions
                    "optimizationHour": schedule.optimization_hour,
                    "initialSOCPercent": context.get("initial_soc_percent"),
                    "costBasisSekPerKwh": context.get("cost_basis_sek_per_kwh"),
                    "predictedSavings": econ_results.get(
                        "base_to_battery_solar_savings", 0
                    ),
                    "horizonHours": context.get("optimization_horizon_hours"),
                }
            )

        return decisions

    def get_current_daily_view(self) -> DailyView:
        """Ensure historical data is properly included for frontend."""
        current_hour = datetime.now().hour

        today_prices = self._price_manager.get_today_prices()
        buy_price = [p["buyPrice"] for p in today_prices]
        sell_price = [p["sellPrice"] for p in today_prices]

        # Build daily view with explicit current hour
        return self.daily_view_builder.build_daily_view(current_hour, buy_price, sell_price)


    def get_daily_savings_report(self) -> dict[str, Any]:
        """Complete savings report with economic scenarios."""
        try:
            daily_view = self.daily_view_builder.build_daily_view(
                current_hour=datetime.now().hour,
                price_data=self._get_today_price_data(),
            )

            # Convert to old format with economic scenarios
            return self._convert_daily_view_to_savings_report(daily_view)

        except Exception as e:
            logger.error(f"Failed to get savings report: {e}")
            raise ValueError(f"Failed to get savings report: {e}") from e

    def _convert_daily_view_to_savings_report(
            self, daily_view: DailyView
        ) -> dict[str, Any]:
            """Convert to old format - snake_case only."""

            hourly_data = []
            for hour_data in daily_view.hourly_data:
                # Calculate derived values expected by frontend
                default_consumption = hour_data.home_consumed
                solar_production = hour_data.solar_generated
                direct_solar = min(default_consumption, solar_production)
                export_solar = max(0, solar_production - direct_solar)
                import_from_grid = max(0, default_consumption - direct_solar)

                hour_entry = {
                    "hour": str(hour_data.hour),
                    "price": hour_data.buy_price,
                    "consumption": hour_data.home_consumed,
                    "battery_level": hour_data.battery_soc_end,
                    "action": hour_data.battery_action or 0,
                    "grid_cost": hour_data.grid_imported * hour_data.buy_price,
                    "battery_cost": 0.0,
                    "total_cost": hour_data.hourly_cost,
                    "base_cost": hour_data.home_consumed * hour_data.buy_price,
                    "savings": hour_data.hourly_savings,
                    "hourly_cost": hour_data.hourly_cost,
                    "hourly_savings": hour_data.hourly_savings,
                    "solar_production": solar_production,
                    "direct_solar": direct_solar,
                    "export_solar": export_solar,
                    "import_from_grid": import_from_grid,
                    "solar_only_cost": import_from_grid * hour_data.buy_price,
                    "solar_savings": (hour_data.home_consumed - import_from_grid) * hour_data.buy_price,
                    "grid_only_cost": hour_data.home_consumed * hour_data.buy_price,
                    "battery_savings": hour_data.hourly_savings,
                    "battery_grid_consumption": hour_data.grid_imported,
                    "battery_charge": hour_data.battery_charged,
                    "battery_discharge": hour_data.battery_discharged,
                    "grid_import": hour_data.grid_imported,
                    "grid_exported": hour_data.grid_exported,
                    "grid_imported": hour_data.grid_imported,
                    "grid_export": hour_data.grid_exported,
                    "data_source": hour_data.data_source,
                    "battery_soc_start": hour_data.battery_soc_start,
                    "solar_to_battery": min(hour_data.battery_charged, hour_data.solar_generated),
                    "grid_to_battery": max(0, hour_data.battery_charged - min(hour_data.battery_charged, hour_data.solar_generated)),
                    "solar_charged": min(hour_data.battery_charged, hour_data.solar_generated),
                    "effective_diff": (hour_data.buy_price - hour_data.buy_price * 0.6) * 0.85 - 0.4,
                    "opportunity_score": 0.8,
                }
                hourly_data.append(hour_entry)

            # Calculate summary
            total_solar = sum(h["solar_production"] for h in hourly_data)
            total_consumption = sum(h["consumption"] for h in hourly_data)
            total_battery_charge = sum(h["battery_charge"] for h in hourly_data)
            total_battery_discharge = sum(h["battery_discharge"] for h in hourly_data)
            total_grid_import = sum(h["grid_import"] for h in hourly_data)
            total_grid_export = sum(h["grid_export"] for h in hourly_data)
            avg_price = sum(h["price"] for h in hourly_data) / len(hourly_data) if hourly_data else 1.0

            # Economic scenarios
            grid_only_cost = total_consumption * avg_price
            solar_only_cost = max(0, total_consumption - total_solar) * avg_price
            battery_solar_cost = total_grid_import * avg_price - total_grid_export * avg_price * 0.8

            solar_savings = grid_only_cost - solar_only_cost
            battery_savings = solar_only_cost - battery_solar_cost
            total_savings = solar_savings + battery_savings

            summary = {
                "base_cost": grid_only_cost,
                "optimized_cost": battery_solar_cost,
                "grid_costs": total_grid_import * avg_price,
                "battery_costs": 0,
                "savings": total_savings,
                "grid_only_cost": grid_only_cost,
                "solar_only_cost": solar_only_cost,
                "battery_solar_cost": battery_solar_cost,
                "solar_only_savings": solar_savings,
                "arbitrage_savings": battery_savings,
                "battery_savings": battery_savings,
                "total_solar_production": total_solar,
                "total_battery_charge": total_battery_charge,
                "total_battery_discharge": total_battery_discharge,
                "total_grid_import": total_grid_import,
                "total_grid_export": total_grid_export,
                "total_direct_solar": sum(h["direct_solar"] for h in hourly_data),
                "total_excess_solar": sum(h["export_solar"] for h in hourly_data),
                "cycle_count": total_battery_discharge / 15.0,
                "avg_buy_price": avg_price,
                "avg_sell_price": avg_price * 0.8,
                "total_daily_savings": daily_view.total_daily_savings,
                "actual_savings_so_far": daily_view.actual_savings_so_far,
                "predicted_remaining_savings": daily_view.predicted_remaining_savings,
                "actual_hours": daily_view.actual_hours_count,
                "predicted_hours": daily_view.predicted_hours_count,
                "total_consumption": total_consumption,
                "total_charge_from_solar": sum(h["solar_to_battery"] for h in hourly_data),
                "total_charge_from_grid": sum(h["grid_to_battery"] for h in hourly_data),
                "estimated_battery_cycles": total_battery_discharge / self.battery_settings.total_capacity,
            }

            return {
                "hourly_data": hourly_data,
                "summary": summary,
                "enhanced_summary": summary,
                "energy_profile": {
                    "consumption": [h["consumption"] for h in hourly_data],
                    "solar": [h["solar_production"] for h in hourly_data],
                    "battery_soc": [h["battery_level"] for h in hourly_data],
                    "actual_hours": daily_view.actual_hours_count,
                },
            }

    def adjust_charging_power(self):
        """FIXED: Adjust charging power based on house consumption."""
        try:
            self._power_monitor.adjust_battery_charging()
        except (AttributeError, ValueError, KeyError) as e:
            logger.error("Failed to adjust charging power: %s", str(e))


    def get_settings(self) -> dict[str, Any]:
        """Get settings - preserves original interface."""
        return {
            "battery": self.battery_settings.asdict(),
            "consumption": {"defaultHourly": 4.0, "estimatedConsumption": 4.0},
            "totalConsumption": {"defaultHourly": 4.0, "estimatedConsumption": 4.0},
            "home": self.home_settings.asdict(),
            "price": self.price_settings.asdict(),
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
            raise ValueError(f"Invalid settings: {e}") from e

    def _log_battery_system_config(self):
        """Log the current battery configuration - reproduces original functionality."""
        try:
            # Get energy data for consumption info (like original)
            predictions_consumption = self._get_consumption_predictions()

            # Get current SOC
            if self._controller:
                current_soc = self._controller.get_battery_soc()
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

    def _log_energy_balance(self):
        """FIXED: Generate energy balance from historical store with proper formatting."""
        completed_hours = self.historical_store.get_completed_hours()

        if not completed_hours:
            logger.info("No completed hours for energy balance")
            return [], {}

        hourly_data = []
        totals = {
            "total_solar": 0.0,
            "total_consumption": 0.0,
            "total_grid_import": 0.0,
            "total_grid_export": 0.0,
            "total_battery_charged": 0.0,
            "total_battery_discharged": 0.0,
            "battery_net_change": 0.0,
            "hours_recorded": len(completed_hours),
        }

        for hour in sorted(completed_hours):
            event = self.historical_store.get_hour_event(hour)
            if event:
                hourly_item = {
                    "hour": hour,
                    "solar_production": event.solar_generated,
                    "home_consumption": event.home_consumed,
                    "grid_import": event.grid_imported,
                    "grid_export": event.grid_exported,
                    "battery_charged": event.battery_charged,
                    "battery_discharged": event.battery_discharged,
                    "battery_soc_end": event.battery_soc_end,
                    "battery_net_change": event.battery_charged
                    - event.battery_discharged,
                }

                totals["total_solar"] += event.solar_generated
                totals["total_consumption"] += event.home_consumed
                totals["total_grid_import"] += event.grid_imported
                totals["total_grid_export"] += event.grid_exported
                totals["total_battery_charged"] += event.battery_charged
                totals["total_battery_discharged"] += event.battery_discharged

                hourly_data.append(hourly_item)

        totals["battery_net_change"] = (
            totals["total_battery_charged"] - totals["total_battery_discharged"]
        )

        # Format and log energy balance table
        self._format_and_log_energy_balance(hourly_data, totals)

        return hourly_data, totals

    def _format_and_log_energy_balance(self, hourly_data, totals):
        """Format and log energy balance table with predictions indicator."""
        if not hourly_data:
            logger.info("No energy data to display")
            return

        current_hour = datetime.now().hour

        # Create table header
        lines = [
            "\n╔════════════════════════════════════════════════════════════════════════════════════════════════════════╗",
            "║                                          Energy Balance Report                                         ║",
            "╠════════╦══════════════════════════╦══════════════════════════╦══════════════════════════════════╦══════╣",
            "║        ║       Energy Input       ║       Energy Output      ║           Battery Flows          ║      ║",
            "║  Hour  ╠════════╦════════╦════════╬════════╦════════╦════════╬════════╦════════╦════════╦═══════╣ SOC  ║",
            "║        ║ Solar  ║ Grid   ║ Total  ║ Home   ║ Export ║ Aux.   ║ Charge ║Dischrge║Solar->B║ Grid  ║ (%)  ║",
            "╠════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬═══════╬══════╣",
        ]

        # Add hourly data rows
        for data in hourly_data:
            energy_in = data["grid_import"] + data["solar_production"]
            #            energy_out_value = data['home_consumption'] + data['grid_export']

            # Estimate solar to battery (simplified)
            solar_to_battery = min(data["battery_charged"], data["solar_production"])
            grid_to_battery = max(0, data["battery_charged"] - solar_to_battery)

            # Mark predictions with ★
            indicator = "★" if data["hour"] >= current_hour else " "

            row = (
                f"║ {data['hour']:02d}:00{indicator} "
                f"║ {data['solar_production']:>5.1f}  "
                f"║ {data['grid_import']:>5.1f}  "
                f"║ {energy_in:>6.1f} "
                f"║ {data['home_consumption']:>5.1f}  "
                f"║ {data['grid_export']:>5.1f}  "
                f"║ {0.0:>5.1f}  "  # Aux load
                f"║ {data['battery_charged']:>5.1f}  "
                f"║ {data['battery_discharged']:>5.1f}  "
                f"║ {solar_to_battery:>5.1f}  "
                f"║ {grid_to_battery:>5.1f} "
                f"║ {data['battery_soc_end']:>4.0f} ║"
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
        """FIXED: Log system startup information - reproduces original functionality."""
        try:
            # Log battery configuration
            self._log_battery_system_config()

            # Log energy balance using the new components
            self._log_energy_balance()

            # Log current schedule if available
#            if self._current_schedule:
#                self._current_schedule.log_schedule()
#            else:
#                logger.info("No current schedule available to log.")

        except Exception as e:
            logger.error(f"Failed to log system startup: {e}")

    def log_energy_flows_api(self, hour_range=None) -> tuple[list[dict], dict]:
        """Get energy flows report for API."""
        hourly_data = []
        totals = {
            "total_solar": 0.0,
            "total_consumption": 0.0,
            "total_grid_import": 0.0,
            "total_grid_export": 0.0,
            "total_battery_charged": 0.0,
            "total_battery_discharged": 0.0,
            "battery_net_change": 0.0,
            "hours_recorded": 0,
        }

        completed_hours = self.historical_store.get_completed_hours()
        logger.info(f"Stored hours: {completed_hours}")
        if hour_range:
            start_hour, end_hour = hour_range
            completed_hours = [
                h for h in completed_hours if start_hour <= h <= end_hour
            ]

        for hour in sorted(completed_hours):
            event = self.historical_store.get_hour_event(hour)
            if not event:
                continue

            hourly_item = {
                "hour": hour,
                "solar_production": event.solar_generated,
                "home_consumption": event.home_consumed,
                "grid_import": event.grid_imported,
                "grid_export": event.grid_exported,
                "battery_charged": event.battery_charged,
                "battery_discharged": event.battery_discharged,
                "battery_soc_end": event.battery_soc_end,
                "battery_net_change": event.battery_charged - event.battery_discharged,
            }

            totals["total_solar"] += event.solar_generated
            totals["total_consumption"] += event.home_consumed
            totals["total_grid_import"] += event.grid_imported
            totals["total_grid_export"] += event.grid_exported
            totals["total_battery_charged"] += event.battery_charged
            totals["total_battery_discharged"] += event.battery_discharged

            hourly_data.append(hourly_item)

        totals["battery_net_change"] = (
            totals["total_battery_charged"] - totals["total_battery_discharged"]
        )
        totals["hours_recorded"] = len(hourly_data)

        logger.info(
            "Energy flows report: %d hours, %.2f kWh solar, %.2f kWh consumption, %.2f kWh battery net",
            totals["hours_recorded"],
            totals["total_solar"],
            totals["total_consumption"],
            totals["battery_net_change"],
        )

        return hourly_data, totals

    def get_full_day_energy_profile(self, current_hour: int) -> dict:
        """Get full day energy profile."""
        try:
            daily_view = self.get_current_daily_view()

            profile = {
                "hours": list(range(24)),
                "solar_production": [h.solar_generated for h in daily_view.hourly_data],
                "home_consumption": [h.home_consumed for h in daily_view.hourly_data],
                "grid_import": [h.grid_imported for h in daily_view.hourly_data],
                "grid_export": [h.grid_exported for h in daily_view.hourly_data],
                "battery_charged": [h.battery_charged for h in daily_view.hourly_data],
                "battery_discharged": [
                    h.battery_discharged for h in daily_view.hourly_data
                ],
                "battery_soc": [h.battery_soc_end for h in daily_view.hourly_data],
                "data_sources": [h.data_source for h in daily_view.hourly_data],
            }

            return profile

        except Exception as e:
            logger.error("Failed to get energy profile: %s", e)
            return {
                "hours": list(range(24)),
                "solar_production": [0] * 24,
                "home_consumption": [4] * 24,
                "grid_import": [4] * 24,
                "grid_export": [0] * 24,
                "battery_charged": [0] * 24,
                "battery_discharged": [0] * 24,
                "battery_soc": [50] * 24,
                "data_sources": ["predicted"] * 24,
            }