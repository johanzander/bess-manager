"""Main facade for managing the battery system.

This module provides the `BatterySystemManager` class, which acts as the main
facade for managing the battery system. It integrates various components such as
the energy manager, price manager, schedule manager, power monitor,
battery monitor to provide a cohesive interface for managing
the battery system.

The `BatterySystemManager` class provides functionality to:
- Initialize and configure system components with default values.
- Optimize battery charge/discharge schedules based on electricity prices and
  consumption predictions.
- Update system state and apply schedules for specific hours.
- Verify inverter settings and adjust charging power based on house consumption.
- Prepare and apply schedules for the current or next day.
- Get and update system settings.

Components integrated by `BatterySystemManager`:
- `ElectricityPriceManager`: Manages electricity price data from various sources.
- `EnergyManager`: Centralized management of all energy-related data and predictions.
- `GrowattScheduleManager`: Manages and applies schedules to the Growatt inverter.
- `HomePowerMonitor`: Monitors and adjusts home power consumption.
- `BatteryMonitor`: Monitors battery state and verifies system settings.

Price Sources:
- `HANordpoolSource`: Fetches Nordpool electricity prices from Home Assistant integration.
- `NordpoolAPISource`: Fetches Nordpool electricity prices directly from Nordpool API.
- Other sources can be integrated as needed.

Home Assistant Controller:
- The `HomeAssistantController` is used to interact with a Home Assistant system,
  providing both Growatt inverter control as well as real-time data on consumption,
  battery state, etc.

Error Handling Strategy:
- Critical initialization errors raise specific exceptions
- Integration points with external systems use targeted exception handling
- Data validation occurs at entry points with clear validation criteria
- Fallback behaviors are implemented for non-critical errors
- All errors are logged with appropriate context

Example usage #1: pyscript + Home Assistant
- Initialize BatterySystemManager with Home Assistant Controller
    `system = BatterySystemManager(controller=ha_controller)`
- Start the system, must be called after initialization
    `system.start()`
- Run on startup (to apply schedule for current day)
    `system.update_battery_schedule(current_hour)`
- Run hourly adaptation (every hour, starting at 00:00)
    `system.update_battery_schedule(current_hour)`
- Prepare schedule for next day (run at 23:55)
    `system.update_battery_schedule(current_hour, prepare_next_day=True)`
- Verify inverter settings (every 15 minutes)
    `system.verify_inverter_settings(current_hour)`
- Monitor power usage (every 5 minutes)
    `system.adjust_charging_power()`

Example usage #2: FastAPI backend + Nordpool API
- Initialize BatterySystemManager with Nordpool API price source
    `system = BatterySystemManager(controller=None, price_source=NordpoolAPISource())`
- Get settings
    `settings = system.get_settings()`
- Update settings
    `system.update_settings(new_settings)`
- Return optimized schedule for specific date
    `schedule = system.create_schedule("2022-01-01")`
"""

from datetime import datetime
import logging

from .algorithms import optimize_battery
from .battery_monitor import BatteryMonitor
from .energy_manager import EnergyManager
from .growatt_schedule import GrowattScheduleManager
from .power_monitor import HomePowerMonitor
from .price_manager import ElectricityPriceManager, HANordpoolSource
from .schedule import Schedule
from .settings import BatterySettings, ConsumptionSettings, HomeSettings, PriceSettings

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


class BatterySystemManager:
    """Facade for battery system management."""

    def __init__(self, controller=None, price_source=None) -> None:
        """Initialize system components.

        Args:
            controller: Home Assistant controller (optional)
            price_source: Price data source (optional)

        Raises:
            ValueError: If critical settings are invalid
            AttributeError: If required controller methods are missing

        """
        # Initialize settings
        self.battery_settings = BatterySettings()
        self.consumption_settings = ConsumptionSettings()
        self.home_settings = HomeSettings()
        self.price_settings = PriceSettings()
        self._current_schedule = None
        self._initial_soc = None
        self._power_monitor = None
        self._battery_monitor = None

        # Initialize controller
        self._controller = controller

        # Initialize components
        self._energy_manager = EnergyManager(
            ha_controller=self._controller,
            total_capacity=self.battery_settings.total_capacity,
            min_soc=self.battery_settings.min_soc,
            default_consumption=self.consumption_settings.default_hourly,
        )

        # Initialize with null schedule
        self._schedule_manager = GrowattScheduleManager()

        if price_source is None:
            price_source = HANordpoolSource(controller)
        self._price_manager = ElectricityPriceManager(source=price_source)

        logger.info("BatterySystemManager initialization complete")

    def start(self):
        """Start the system.

        This method initializes all components and prepares the system for operation.
        It should be called after initialization to ensure all components are ready.

        Raises:
            ValueError: If critical settings are invalid
            AttributeError: If required controller methods are missing

        """

        self._power_monitor = HomePowerMonitor(
            self._controller,
            home_settings=self.home_settings,
            battery_settings=self.battery_settings,
        )

        self._battery_monitor = BatteryMonitor(
            self._controller,
            self._schedule_manager,
            home_settings=self.home_settings,
            battery_settings=self.battery_settings,
        )

        # Try to read current schedule from inverter at startup
        self._initialize_tou_schedule_from_inverter()
        self._energy_manager.fetch_and_initialize_historical_data()
        self._energy_manager.fetch_predictions()
        self.log_system_startup()
        logger.info("BatterySystemManager started")

    def _initialize_tou_schedule_from_inverter(self):
        """Initialize schedule from current inverter settings.

        This method attempts to read the current TOU schedule from the inverter
        and initialize the schedule manager with those settings. It includes
        appropriate error handling to ensure system initialization continues
        even if this operation fails.
        """
        try:
            logger.info("Reading current TOU schedule from inverter")
            inverter_segments = self._controller.read_inverter_time_segments()

            if inverter_segments:
                # Initialize GrowattScheduleManager with the current TOU segments
                current_hour = datetime.now().hour
                self._schedule_manager.initialize_from_tou_segments(
                    inverter_segments, current_hour
                )
            else:
                logger.warning("No TOU segments returned from inverter")
        except (AttributeError, ValueError) as e:
            # AttributeError: Controller missing required method
            # ValueError: Invalid data returned from inverter
            logger.error("Failed to read current inverter schedule: %s", str(e))
        except TimeoutError as e:
            # Specifically handle timeout issues
            logger.error("Timeout connecting to inverter: %s", str(e))
        except KeyError as e:
            # Handle missing keys in returned data
            logger.error("Malformed data from inverter, missing key: %s", str(e))

    def _compare_schedules(self, temp_growatt, from_hour, temp_schedule=None):
        """Compare schedules from given hour onwards.

        This method implements a detailed comparison between the current schedule and
        a new potential schedule. The comparison focuses on changes that would affect
        future operation, particularly:

        1. Solar charging differences (high priority - affects energy economics)
        2. TOU interval differences (affects battery mode settings)
        3. Hourly setting differences (affects grid charge and discharge behavior)

        The comparison is limited to hours from 'from_hour' onwards, since past hours
        have already been executed and cannot be changed.

        Args:
            temp_growatt: Temporary GrowattScheduleManager to compare with current
            from_hour: Hour to start comparison from
            temp_schedule: Temporary Schedule object for additional checks

        Returns:
            (bool, str): (True if schedules differ, reason for difference)

        """
        # If no current schedule, they differ
        if not self._current_schedule:
            return True, "No current schedule"

        # CRITICAL CHECK: Explicitly check for solar charging
        # Solar charging is prioritized because it significantly affects the
        # energy economics of battery operation
        if temp_schedule and hasattr(temp_schedule, "solar_charged"):
            temp_solar = sum(temp_schedule.solar_charged)
            if temp_solar > 0:
                # Check if current schedule has solar_charged
                current_solar = 0
                if (
                    hasattr(self._current_schedule, "solar_charged")
                    and self._current_schedule.solar_charged
                ):
                    current_solar = sum(self._current_schedule.solar_charged)

                if temp_solar != current_solar:
                    logger.info(
                        "Solar charging difference detected: new=%.1f kWh, current=%.1f kWh",
                        temp_solar,
                        current_solar,
                    )
                    return (
                        True,
                        f"Solar charging changed: {current_solar:.1f} -> {temp_solar:.1f} kWh",
                    )

        # First compare TOU intervals that affect remaining hours
        # TOU intervals control the battery mode (battery-first, load-first, etc.)
        new_tou = temp_growatt.get_daily_TOU_settings()
        current_tou = self._schedule_manager.get_daily_TOU_settings()

        if len(new_tou) != len(current_tou):
            return True, "Different number of TOU intervals"

        # Compare TOU intervals that could affect remaining hours
        i = 0
        while i < len(new_tou):
            # Convert interval times to hours for comparison
            start_hour = int(new_tou[i]["start_time"].split(":")[0])
            if (
                start_hour >= from_hour
            ):  # Only check intervals that could affect remaining hours
                if (
                    new_tou[i]["start_time"] != current_tou[i]["start_time"]
                    or new_tou[i]["end_time"] != current_tou[i]["end_time"]
                    or new_tou[i]["batt_mode"] != current_tou[i]["batt_mode"]
                ):
                    return True, f"TOU interval {i} differs"
            i += 1

        # Then compare hourly settings (grid charge and discharge settings)
        # for each future hour
        i = from_hour
        while i < 24:
            new_settings = temp_growatt.get_hourly_settings(i)
            current_settings = self._schedule_manager.get_hourly_settings(i)

            if (
                new_settings["grid_charge"] != current_settings["grid_charge"]
                or new_settings["discharge_rate"] != current_settings["discharge_rate"]
            ):
                return True, f"Hour {i} settings differ"
            i += 1

        # If we get here, no relevant differences were found
        return False, "Schedules match"

    def update_battery_schedule(
        self, hour: int, prepare_next_day: bool = False
    ) -> bool:
        """Unified schedule management function that handles all scheduling scenarios.

        This is the main entry point for schedule management. It handles:
        1. Regular hourly updates
        2. Midnight transitions
        3. Next day preparation

        Args:
            hour: Current hour (0-23)
            prepare_next_day: Flag indicating if preparing for next day

        Returns:
            bool: True if schedule update was successful

        Raises:
            ValueError: If hour is invalid (outside 0-23)

        """
        # Input validation
        if not 0 <= hour <= 23:
            logger.error("Invalid hour: %d (must be 0-23)", hour)
            raise ValueError(f"Invalid hour: {hour} (must be 0-23)")

        if prepare_next_day:
            logger.info("Preparing schedule for next day at hour %02d:00 ", hour)
        else:
            logger.info("Updating battery schedule for hour %02d:00 ", hour)

        # Determine if this is first run
        is_first_run = self._current_schedule is None

        # Handle special cases (midnight or prepare_next_day)
        self._handle_special_cases(hour, prepare_next_day)

        # Get price data and battery state
        prices, price_entries = self._get_price_data(prepare_next_day)
        if not prices:
            logger.warning("Schedule update aborted: No price data available")
            return False

        # Update energy data if needed
        self._update_energy_data(hour, is_first_run, prepare_next_day)

        # Get current battery state
        try:
            current_soc = self._controller.get_battery_soc()
        except (AttributeError, ValueError) as e:
            logger.error("Failed to get battery SOC: %s", str(e))
            return False

        # Gather optimization data - examining the return type
        optimization_data_result = self._gather_optimization_data(
            hour, current_soc, prepare_next_day
        )

        if optimization_data_result is None:
            logger.error("Failed to gather optimization data")
            return False

        optimization_hour, optimization_data = optimization_data_result

        # Run optimization
        optimization_result = self._run_optimization(
            optimization_hour,
            current_soc,
            optimization_data,
            prices,
            prepare_next_day,
        )

        if optimization_result is None:
            logger.error("Optimization failed")
            return False

        # Create new schedule
        schedule_result = self._create_updated_schedule(
            optimization_hour,
            optimization_result,
            prices,
            optimization_data,
            is_first_run,
            prepare_next_day,
        )

        if schedule_result is None:
            logger.error("Failed to create schedule")
            return False

        temp_schedule, temp_growatt = schedule_result

        # Set the current hour in the Growatt schedule manager
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
            try:
                self._apply_schedule(
                    hour, temp_schedule, temp_growatt, reason, prepare_next_day
                )
            except (ValueError, KeyError, AttributeError) as e:
                logger.error("Failed to apply schedule: %s", str(e))
                return False
            except TimeoutError as e:
                logger.error("Timeout when applying schedule: %s", str(e))
                return False

        # Always apply the current hour's settings when not preparing for next day
        if not prepare_next_day:
            try:
                self._apply_hourly_schedule(hour)
                logger.info("Applied hourly settings for hour %02d:00", hour)
            except (ValueError, KeyError, AttributeError) as e:
                logger.error("Failed to apply hourly settings: %s", str(e))
                return False
            except TimeoutError as e:
                logger.error("Timeout when applying hourly settings: %s", str(e))
                return False

        return True

    def _handle_special_cases(self, hour: int, prepare_next_day: bool):
        """Handle special cases like midnight transition or next day preparation.

        Args:
            hour: Current hour (0-23)
            prepare_next_day: Flag indicating if preparing for next day

        """
        # For hour 0, store initial SOC (midnight case)
        if hour == 0 and not prepare_next_day:
            try:
                current_soc = self._controller.get_battery_soc()
                self._initial_soc = current_soc
                logger.info("Setting initial SOC for day: %s%%", self._initial_soc)
            except (AttributeError, ValueError) as e:
                logger.warning("Failed to get initial SOC: %s", str(e))

            # Fetch new predictions at midnight
            self._energy_manager.fetch_predictions()

        # Always fetch new predictions when preparing for next day
        if prepare_next_day:
            # Reset energy data for next day
            self._energy_manager.reset_daily_data()
            # Fetch new predictions
            self._energy_manager.fetch_predictions()

    def _get_price_data(self, prepare_next_day: bool):
        """Get price data for today or tomorrow.

        This method retrieves price data from the price manager with appropriate
        error handling. It handles both success and failure cases explicitly.

        Args:
            prepare_next_day: Flag indicating if we're preparing for next day

        Returns:
            tuple: (prices list, price entries) or (None, None) if prices not available

        """
        # Get price data (today's or tomorrow's)
        try:
            if prepare_next_day:
                price_entries = self._price_manager.get_tomorrow_prices()
                logger.info("Fetched tomorrow's price data for scheduling")
            else:
                price_entries = self._price_manager.get_today_prices()
        except (ValueError, KeyError) as e:
            # Value/Key errors indicate missing or invalid data
            logger.error(
                "Failed to fetch price data: %s",
                str(e),
            )
            return None, None
        except TimeoutError as e:
            # Timeout indicates connection issues
            logger.error("Timeout fetching price data: %s", str(e))
            return None, None

        # Validate we got price data
        if not price_entries:
            logger.warning("No prices available")
            return None, None

        # Extract prices based on settings
        prices = []
        try:
            for entry in price_entries:
                if not self.price_settings.use_actual_price:
                    prices.append(entry["price"])
                else:
                    prices.append(entry["buyPrice"])
        except (KeyError, TypeError) as e:
            # Be specific about what failed
            logger.error(
                "Price entries have invalid format: %s",
                str(e),
            )
            return None, None

        # Handle DST transitions (23 or 25 hours)
        expected_hours = 24
        if len(prices) == 23:
            logger.info("Detected DST spring forward transition - day has 23 hours")
            expected_hours = 23
        elif len(prices) == 25:
            logger.info("Detected DST fall back transition - day has 25 hours")
            expected_hours = 25

        # Validate number of prices
        if len(prices) != expected_hours:
            logger.warning(
                "Expected %d prices but got %d, using available prices",
                expected_hours,
                len(prices),
            )

        return prices, price_entries

    def _update_energy_data(
        self, hour: int, is_first_run: bool, prepare_next_day: bool
    ):
        """Update energy manager with data for the completed hour.

        Args:
            hour: Current hour
            is_first_run: Flag indicating if this is the first run
            prepare_next_day: Flag indicating if we're preparing for next day

        """
        # Skip if first run, hour 0, or preparing for next day
        if not is_first_run and hour > 0 and not prepare_next_day:
            prev_hour = hour - 1
            # Check if we already processed this hour
            last_processed_hour = getattr(
                self._energy_manager, "_last_processed_hour", None
            )
            if last_processed_hour != prev_hour:
                try:
                    self._energy_manager.update_hour_data(prev_hour)
                except (ValueError, AttributeError, KeyError) as e:
                    logger.warning("Failed to update hour data: %s", str(e))
            else:
                logger.info("Hour %02d already processed, skipping update", prev_hour)

        # Log energy balance if not preparing for next day
        if not prepare_next_day:
            try:
                self._energy_manager.log_energy_balance()
            except (AttributeError, ValueError) as e:
                logger.warning("Failed to log energy balance: %s", str(e))

    def _gather_optimization_data(
        self, hour: int, current_soc: float, prepare_next_day: bool
    ):
        """Gather data needed for optimization.

        This method collects all the data required for the optimization algorithm,
        including consumption and solar predictions, current battery state, and
        historical data. It includes validation and error handling to ensure
        the optimization process receives complete and valid data.

        Args:
            hour: Current hour
            current_soc: Current battery state of charge
            prepare_next_day: Flag indicating if we're preparing for next day

        Returns:
            tuple: (optimization_hour, optimization_data) or None if data gathering fails

        """
        # Validate inputs to avoid downstream errors
        if not 0 <= hour <= 23:
            logger.error("Invalid hour: %d (must be 0-23)", hour)
            return None

        logger.debug(
            "_gather_optimization_data: Input current_soc: %.1f%%", current_soc
        )

        if not 0 <= current_soc <= 100:
            logger.warning(
                "Suspicious SOC value: %.1f%%, clamping to valid range", current_soc
            )
            # Continue anyway but with clamped value
            current_soc = max(0, min(100, current_soc))

        # Calculate current battery energy
        current_soe = current_soc / 100.0 * self.battery_settings.total_capacity
        logger.debug(
            "_gather_optimization_data: calculated current_soe: %.1f kWh", current_soe
        )

        # Get energy data based on whether we're preparing for today or tomorrow
        if prepare_next_day:
            # For next day, we need to get predictions from the energy manager
            try:
                consumption_predictions = (
                    self._energy_manager.get_consumption_predictions()
                )
                solar_predictions = self._energy_manager.get_solar_predictions()
            except (AttributeError, ValueError) as e:
                # If methods don't exist yet, use temporary default values
                logger.warning(
                    "Energy manager missing prediction methods, using defaults: %s",
                    str(e),
                )
                consumption_predictions = [
                    self.consumption_settings.default_hourly
                ] * 24
                solar_predictions = [0.0] * 24

            # Validate prediction lengths
            if len(consumption_predictions) != 24:
                logger.warning(
                    "Invalid consumption prediction length: %d, extending to 24 hours",
                    len(consumption_predictions),
                )
                # Extend or truncate to 24 hours
                if len(consumption_predictions) < 24:
                    consumption_predictions.extend(
                        [self.consumption_settings.default_hourly]
                        * (24 - len(consumption_predictions))
                    )
                else:
                    consumption_predictions = consumption_predictions[:24]

            if len(solar_predictions) != 24:
                logger.warning(
                    "Invalid solar prediction length: %d, extending to 24 hours",
                    len(solar_predictions),
                )
                # Extend or truncate to 24 hours
                if len(solar_predictions) < 24:
                    solar_predictions.extend([0.0] * (24 - len(solar_predictions)))
                else:
                    solar_predictions = solar_predictions[:24]

            energy_profile = {
                "consumption": consumption_predictions,
                "solar": solar_predictions,
                "battery_soc": [current_soc] * 24,
                "battery_soe": [current_soe] * 24,
            }
            optimization_hour = 0  # Optimize all 24 hours
        else:
            # Get combined energy data for optimization
            try:
                energy_profile = self._energy_manager.get_full_day_energy_profile(hour)
            except (AttributeError, ValueError, KeyError) as e:
                logger.error("Failed to get combined energy data: %s", str(e))
                return None

            optimization_hour = hour  # Only optimize from current hour

        # Initialize arrays with the CURRENT battery state rather than zeros
        optimization_data = {
            "full_consumption": energy_profile["consumption"],
            "full_solar": energy_profile["solar"],
            "combined_actions": [0.0] * 24,
            # Initialize with current energy
            "combined_soe": [current_soe] * 24,
            "solar_charged": [0.0] * 24,
        }

        # For today's schedule, copy existing actions/SOE for past hours
        # FIRST approach: Use current schedule if available
        if self._current_schedule is not None and not prepare_next_day:
            self._copy_historical_data_from_schedule(
                optimization_data, optimization_hour
            )
        # SECOND approach - reconstruct from energy manager if no schedule
        elif not prepare_next_day:
            self._reconstruct_historical_data_from_energy_manager(
                optimization_data, optimization_hour
            )

        # Make sure the current hour has the correct SOE value
        # Prioritize historical SOE data for current hour if available
        try:
            if (
                not prepare_next_day
                and hasattr(self._energy_manager, "has_hour_data")
                and self._energy_manager.has_hour_data(hour)
            ):
                # Use historical SOE from energy manager for current hour
                hour_data = self._energy_manager.get_energy_data(hour)
                if hour_data:
                    optimization_data["combined_soe"][hour] = hour_data["battery_soe"]
                    logger.debug(
                        "Using historical battery_soe for hour %d: %.1f kWh",
                        hour,
                        hour_data["battery_soe"],
                    )
            else:
                # Use real-time SOC reading if historical data not available
                optimization_data["combined_soe"][hour] = current_soe
                logger.debug(
                    "Using current_soe for hour %d: %.1f kWh", hour, current_soe
                )
        except (AttributeError, KeyError, ValueError) as e:
            # Fall back to current SOE if has_hour_data method is missing or fails
            logger.warning(
                "Failed to get historical SOE for hour %d: %s, using current value",
                hour,
                str(e),
            )
            optimization_data["combined_soe"][hour] = current_soe
            logger.debug(
                "After exception, using current_soe for hour %d: %.1f kWh",
                hour,
                current_soe,
            )

        logger.debug(
            "Final SOE for hour %d in combined_soe: %.1f kWh",
            hour,
            optimization_data["combined_soe"][hour],
        )

        return optimization_hour, optimization_data

    def _copy_historical_data_from_schedule(self, optimization_data, optimization_hour):
        """Copy historical data from current schedule for past hours.

        Args:
            optimization_data: Dictionary to update with historical data
            optimization_hour: Current optimization hour

        """
        try:
            for i in range(optimization_hour):
                if i < len(self._current_schedule.actions):
                    optimization_data["combined_actions"][i] = (
                        self._current_schedule.actions[i]
                    )
                if i < len(self._current_schedule.state_of_energy):
                    optimization_data["combined_soe"][i] = (
                        self._current_schedule.state_of_energy[i]
                    )
                if hasattr(self._current_schedule, "solar_charged") and i < len(
                    self._current_schedule.solar_charged
                ):
                    optimization_data["solar_charged"][i] = (
                        self._current_schedule.solar_charged[i]
                    )
        except (IndexError, AttributeError) as e:
            logger.warning("Failed to copy historical data from schedule: %s", str(e))
            # Continue with default values already in optimization_data

    def _reconstruct_historical_data_from_energy_manager(
        self, optimization_data, optimization_hour
    ):
        """Reconstruct historical data from energy manager for past hours.

        Args:
            optimization_data: Dictionary to update with historical data
            optimization_hour: Current optimization hour

        """
        # If no schedule exists (e.g., during restart), reconstruct past actions from energy data
        logger.info("Reconstructing past battery actions from energy data")

        try:
            # Get processed hours safely
            processed_hours = self._energy_manager.get_processed_hours()

            for i in range(optimization_hour):
                if i in processed_hours:
                    # Get data for this hour safely
                    try:
                        hour_data = self._energy_manager.get_energy_data(i)
                    except AttributeError as e:
                        logger.warning(
                            "Energy manager doesn't have get_energy_data method: %s",
                            str(e),
                        )
                        continue

                    if hour_data:
                        # Calculate net action (positive for charging, negative for discharging)
                        net_action = (
                            hour_data["battery_charge"] - hour_data["battery_discharge"]
                        )
                        optimization_data["combined_actions"][i] = net_action

                        # Get battery state of energy
                        optimization_data["combined_soe"][i] = hour_data["battery_soe"]

                        # Get solar charged
                        optimization_data["solar_charged"][i] = hour_data[
                            "solar_to_battery"
                        ]
        except (AttributeError, KeyError, ValueError) as e:
            logger.warning("Failed to reconstruct historical data: %s", str(e))
            # Continue with default values already in optimization_data

    def _run_optimization(
        self,
        optimization_hour: int,
        current_soc: float,
        optimization_data: dict,
        prices: list,
        prepare_next_day: bool,
    ):
        # Extract the correct SOE from optimization_data
        current_soe = optimization_data["combined_soe"][optimization_hour]
        # Convert to SOC percentage
        current_soc = (current_soe / self.battery_settings.total_capacity) * 100.0

        """Run the battery optimization algorithm."""
        try:
            logger.debug("_run_optimization: Input current_soc: %.1f%%", current_soc)
            logger.debug(
                "_run_optimization: SOE for hour %d in optimization_data: %.1f kWh",
                optimization_hour,
                optimization_data["combined_soe"][optimization_hour],
            )

            # Get the optimization portion of the calculation
            remaining_prices = prices[optimization_hour:]
            n_hours = len(remaining_prices)

            logger.info(
                "Running optimization for %d hours starting from hour %d",
                n_hours,
                optimization_hour,
            )

            # Ensure all arrays have exactly the same length to prevent errors
            remaining_consumption = optimization_data["full_consumption"][
                optimization_hour : optimization_hour + n_hours
            ]
            remaining_solar = optimization_data["full_solar"][
                optimization_hour : optimization_hour + n_hours
            ]

            # Verify array lengths match
            if len(remaining_consumption) != n_hours:
                logger.warning(
                    "Consumption array length mismatch (%d vs %d), correcting",
                    len(remaining_consumption),
                    n_hours,
                )
                if len(remaining_consumption) < n_hours:
                    # Extend with default consumption
                    default = self.consumption_settings.default_hourly
                    remaining_consumption.extend(
                        [default] * (n_hours - len(remaining_consumption))
                    )
                else:
                    # Truncate
                    remaining_consumption = remaining_consumption[:n_hours]

            if len(remaining_solar) != n_hours:
                logger.warning(
                    "Solar array length mismatch (%d vs %d), correcting",
                    len(remaining_solar),
                    n_hours,
                )
                if len(remaining_solar) < n_hours:
                    # Extend with zeros
                    remaining_solar.extend([0.0] * (n_hours - len(remaining_solar)))
                else:
                    # Truncate
                    remaining_solar = remaining_solar[:n_hours]

            # Calculate cost basis for stored energy (if needed and not preparing for next day)
            virtual_stored_energy = None
            if not prepare_next_day:
                virtual_stored_energy = self._calculate_stored_energy_cost_basis(
                    optimization_hour, prices, current_soc
                )

            # Select appropriate cycle cost based on price model
            # Default value (without VAT)
            cycle_cost = self.battery_settings.cycle_cost
            if self.price_settings.use_actual_price:
                # If using retail prices with VAT, apply VAT to cycle cost
                cycle_cost = cycle_cost * self.price_settings.vat_multiplier

            # Run optimization for remaining hours
            return optimize_battery(
                prices=remaining_prices,
                total_capacity=self.battery_settings.total_capacity,
                reserved_capacity=self.battery_settings.reserved_capacity,
                cycle_cost=self.battery_settings.cycle_cost,
                hourly_consumption=remaining_consumption,
                max_charge_power_kw=(self.battery_settings.charging_power_rate / 100)
                * self.battery_settings.max_charge_power_kw,
                min_profit_threshold=self.price_settings.min_profit,
                initial_soc=current_soc,
                solar_charged=remaining_solar,
                virtual_stored_energy=virtual_stored_energy,
            )
        except (ValueError, IndexError, KeyError) as e:
            logger.error("Optimization failed: %s", str(e))
            return None

    def _calculate_stored_energy_cost_basis(self, hour, prices, current_soc):
        """Calculate cost basis of energy currently in the battery.

        This method determines the economic value of energy already stored in the battery,
        accounting for different sources (grid vs solar) and their associated costs.

        The calculation follows these steps:
        1. Determine energy available above reserved capacity
        2. Calculate the ratio of solar vs grid energy in the battery
        3. Assign different cost bases to solar and grid energy:
        - Grid energy: conservative estimate of acquisition price + discharge cost portion
        - Solar energy: only discharge cost portion (no acquisition cost)
        4. Calculate weighted average cost based on these ratios

        This allows the optimization to make economically sound decisions about when
        to discharge existing stored energy versus charging new energy.

        Args:
            hour: Current hour (0-23)
            prices: List of hourly electricity prices
            current_soc: Current battery state of charge (%)

        Returns:
            dict or None: Virtual stored energy data for optimization, or None if not applicable

        """
        try:
            current_soe = current_soc / 100.0 * self.battery_settings.total_capacity
            available_energy = current_soe - self.battery_settings.reserved_capacity

            # Skip for hour 0 or if battery is nearly empty
            if available_energy < 0.5:
                return None

            # Get information about current battery composition
            solar_ratio = 0.0

            # Use energy manager to estimate solar vs grid ratio in the battery
            # Collect solar and grid charging data
            solar_charged_today = 0.0
            grid_charged_today = 0.0

            try:
                processed_hours = self._energy_manager.get_processed_hours()
                for h in processed_hours:
                    if h < hour:  # Only consider hours before current hour
                        hour_data = self._energy_manager.get_energy_data(h)
                        if hour_data:
                            solar_charged_today += hour_data["solar_to_battery"]
                            grid_charged_today += hour_data["grid_to_battery"]
            except (AttributeError, KeyError, IndexError) as e:
                logger.warning(
                    "Failed to get solar/grid ratio data: %s, using default ratio",
                    str(e),
                )
                # Default to 20/80 ratio if data unavailable - conservative estimate
                solar_charged_today = 1.0
                grid_charged_today = 4.0

            total_charged = solar_charged_today + grid_charged_today

            if total_charged > 0:
                solar_ratio = min(1.0, max(0.0, solar_charged_today / total_charged))

            grid_ratio = 1.0 - solar_ratio

            # Calculate separate cost bases
            # Only discharge portion of cycle cost
            discharge_only_cost = self.battery_settings.cycle_cost * 0.5

            # For grid energy, use a more conservative estimate of historical cost
            # Improved: Use a lower percentile of past prices (e.g., 25th percentile)
            # rather than average, to better represent likely charging prices
            past_prices = prices[:hour] if hour > 0 else prices

            # Sort prices and use a lower percentile (25th) as our cost basis estimate
            sorted_prices = sorted(past_prices)
            quarter_idx = max(0, len(sorted_prices) // 4)
            low_price_estimate = (
                sorted_prices[quarter_idx] if sorted_prices else min(prices)
            )

            # Never use a price higher than 50% of the range
            max_reasonable_price = (min(prices) + max(prices)) / 2
            avg_grid_price = min(low_price_estimate, max_reasonable_price)

            # For grid energy, use estimated acquisition cost plus discharge cost
            grid_cost_basis = avg_grid_price + discharge_only_cost

            # For solar energy, only battery wear cost
            solar_energy = available_energy * solar_ratio
            solar_cost_basis = discharge_only_cost

            # Calculate weighted average cost
            grid_energy = available_energy * grid_ratio
            weighted_cost = (
                (grid_energy * grid_cost_basis + solar_energy * solar_cost_basis)
                / available_energy
                if available_energy > 0
                else 0
            )

            logger.info(
                "Battery content: Grid: %.1f%%, Solar: %.1f%%",
                grid_ratio * 100,
                solar_ratio * 100,
            )
            logger.info(
                "Cost basis: Grid: %.3f, Solar: %.3f, Weighted: %.3f",
                grid_cost_basis,
                solar_cost_basis,
                weighted_cost,
            )

            # Create virtual storage with accurate cost basis
            virtual_stored_energy = {
                "amount": available_energy,
                "price": weighted_cost,
                "is_blended_cost": True,  # Flag that this already includes discharge cost
                "solar_ratio": solar_ratio,  # Add this for optimization enhancement
            }

            logger.info(
                "Economic analysis: Stored energy cost basis is %.3f SEK/kWh",
                weighted_cost,
            )

            # NEW: Log potential profitable discharge opportunities for this stored energy
            profitable_hours = []
            for h, price in enumerate(prices):
                if price > weighted_cost:
                    profit = price - weighted_cost
                    profitable_hours.append((h, price, profit))

            if profitable_hours:
                logger.debug("Profitable discharge opportunities for stored energy:")
                for h, price, profit in sorted(
                    profitable_hours, key=lambda x: x[2], reverse=True
                ):
                    logger.debug(
                        "  Hour %02d:00 - Price: %.3f - Profit: %.3f", h, price, profit
                    )
            else:
                logger.info(
                    "No profitable discharge opportunities found for stored energy"
                )

        except (ValueError, ZeroDivisionError) as e:
            logger.warning("Failed to calculate stored energy cost basis: %s", str(e))
            return None
        else:
            return virtual_stored_energy

    def _create_updated_schedule(
        self,
        optimization_hour: int,
        result: dict,
        prices: list,
        optimization_data: dict,
        is_first_run: bool,
        prepare_next_day: bool,
    ):
        """Create a new schedule from optimization results.

        Args:
            optimization_hour: Hour optimization started from
            result: Optimization results
            prices: List of electricity prices
            optimization_data: Dictionary containing optimization data
            is_first_run: Flag indicating if this is the first run
            prepare_next_day: Flag indicating if we're preparing for next day

        Returns:
            tuple: (schedule, growatt_schedule_manager) or None if creation fails

        """
        try:
            # Create schedule from combined results as before
            combined_actions = optimization_data["combined_actions"]
            combined_soe = optimization_data["combined_soe"]
            solar_charged = optimization_data["solar_charged"]

            # Add optimized actions to the combined array
            for i in range(len(result["actions"])):
                if optimization_hour + i < 24:
                    combined_actions[optimization_hour + i] = result["actions"][i]

            # For hour 0, always use the current SOC reading
            # For other hours, use the value from optimization_data if available
            if optimization_hour == 0:
                current_soc = self._controller.get_battery_soc()
                combined_soe[optimization_hour] = (
                    current_soc / 100.0
                ) * self.battery_settings.total_capacity
            # For other hours, don't overwrite existing SOE values from optimization_data

            # Add future SOE values from optimization results
            for i in range(1, len(result["state_of_energy"])):
                if optimization_hour + i < 24:
                    combined_soe[optimization_hour + i] = result["state_of_energy"][i]

            # Add solar predictions from optimization
            if "solar_charged" in result:
                for i in range(len(result["solar_charged"])):
                    if optimization_hour + i < 24:
                        solar_charged[optimization_hour + i] = result["solar_charged"][
                            i
                        ]

            # Create schedule from combined results
            temp_schedule = Schedule()
            temp_schedule.set_optimization_results(
                actions=combined_actions,
                state_of_energy=combined_soe,
                prices=prices,
                cycle_cost=self.battery_settings.cycle_cost,
                hourly_consumption=optimization_data["full_consumption"],
                solar_charged=solar_charged,
            )

            if prepare_next_day:
                logger.info("Prepared next day's schedule")
            else:
                logger.info(
                    "Updated schedule from hour %02d:00",
                    optimization_hour,
                )

            temp_schedule.log_schedule()

            # Create new Growatt schedule manager
            temp_growatt = GrowattScheduleManager()

            # Special case for prepare_next_day - start with clean slate
            if (
                not prepare_next_day
                and self._schedule_manager
                and hasattr(self._schedule_manager, "tou_intervals")
            ):
                # Copy existing TOU intervals for past hours
                for segment in self._schedule_manager.tou_intervals:
                    start_hour = int(segment["start_time"].split(":")[0])
                    # If this segment starts before the optimization hour, keep it
                    if start_hour < optimization_hour:
                        temp_growatt.tou_intervals.append(segment.copy())

            # For prepare_next_day, set optimization_hour = 0 to create full schedule
            effective_hour = 0 if prepare_next_day else optimization_hour

            # Now create the schedule with current hour
            temp_growatt.create_schedule(temp_schedule, current_hour=effective_hour)
        except (KeyError, IndexError, ValueError, AttributeError) as e:
            logger.error("Failed to create schedule: %s", str(e))
            return None
        else:
            return temp_schedule, temp_growatt

    def _should_apply_schedule(
        self,
        is_first_run: bool,
        hour: int,
        prepare_next_day: bool,
        temp_growatt,
        optimization_hour: int,
        temp_schedule,
    ):
        """Determine if the new schedule should be applied.

        This method implements the decision logic to determine whether a new schedule
        should replace the current one. The logic follows these priorities:

        1. Always apply on first run (no existing schedule)
        2. Always apply at midnight (hour 0) to start a new day fresh
        3. Always apply when preparing for next day
        4. Apply if solar charging has significantly changed (affects energy economics)
        5. Apply if any future TOU intervals or hourly settings differ

        The comparison focuses on changes that affect future hours - past hours
        are already executed and cannot be changed.

        Args:
            is_first_run: Flag indicating if this is the first run
            hour: Current hour
            prepare_next_day: Flag indicating if we're preparing for next day
            temp_growatt: Temporary Growatt schedule manager
            optimization_hour: Hour optimization started from
            temp_schedule: Temporary schedule

        Returns:
            tuple: (should_apply, reason)
                - should_apply: Boolean indicating if schedule should be applied
                - reason: String explanation of why schedule is being applied or not

        """
        # Log current and new schedules for debugging
        logger.info("Evaluating whether to apply new schedule at hour %d", hour)

        if self._schedule_manager:
            self._schedule_manager.log_current_TOU_schedule(
                "=== CURRENT TOU INTERVALS ==="
            )
            self._schedule_manager.log_detailed_schedule(
                "=== CURRENT DETAILED SCHEDULE ==="
            )
        else:
            logger.info("No current schedule exists")

        temp_growatt.log_current_TOU_schedule("=== NEW TOU INTERVALS ===")
        temp_growatt.log_detailed_schedule("=== NEW DETAILED SCHEDULE ===")

        # Always apply on first run, at midnight, or when preparing for next day
        if is_first_run or hour == 0 or prepare_next_day:
            if is_first_run:
                reason = "First run"
                logger.info("Decision: Apply schedule - Reason: %s", reason)
            elif hour == 0:
                reason = "New day"
                logger.info("Decision: Apply schedule - Reason: %s", reason)
            else:
                reason = "Preparing for next day"
                logger.info("Decision: Apply schedule - Reason: %s", reason)
            return True, reason

        # First check for solar charging changes - this takes priority as it
        # directly affects the energy economics of the battery operation
        if temp_schedule and hasattr(temp_schedule, "solar_charged"):
            temp_solar = sum(temp_schedule.solar_charged)
            if temp_solar > 0:
                # Check if current schedule has solar_charged
                current_solar = 0
                if (
                    hasattr(self._current_schedule, "solar_charged")
                    and self._current_schedule.solar_charged
                ):
                    current_solar = sum(self._current_schedule.solar_charged)

                if temp_solar != current_solar:
                    logger.info(
                        "Decision: Apply schedule - Solar charging changed: %.1f kWh -> %.1f kWh",
                        current_solar,
                        temp_solar,
                    )
                    return (
                        True,
                        f"Solar charging changed: {current_solar:.1f} -> {temp_solar:.1f} kWh",
                    )

        # Set current hour in both schedule managers to ensure fair comparison
        self._schedule_manager.current_hour = hour
        temp_growatt.current_hour = hour

        # Use compare_schedules method to check for differences in TOU intervals
        # and hourly settings for future hours only
        try:
            schedules_differ, reason = self._schedule_manager.compare_schedules(
                other_schedule=temp_growatt, from_hour=optimization_hour
            )

            if schedules_differ:
                logger.info("Decision: Apply schedule - %s", reason)
            else:
                logger.info("Decision: Keep current schedule - %s", reason)

            return schedules_differ, reason

        except (AttributeError, KeyError, IndexError, ValueError) as e:
            logger.warning(
                "Schedule comparison failed: %s, applying new schedule", str(e)
            )
            return True, f"Schedule comparison error: {e!s}"

    def _apply_schedule(
        self,
        hour: int,
        temp_schedule,
        temp_growatt,
        reason: str,
        prepare_next_day: bool,
    ):
        """Apply the new schedule.

        Args:
            hour: Current hour
            temp_schedule: New schedule to apply
            temp_growatt: New Growatt schedule manager
            reason: Reason for applying the schedule
            prepare_next_day: Flag indicating if we're preparing for next day

        Raises:
            ValueError: If TOU segment settings are invalid
            KeyError: If required TOU segment keys are missing
            TimeoutError: If communication with inverter times out

        """
        logger.info("Schedule update required: %s", reason)
        self._current_schedule = temp_schedule

        # For prepare_next_day, we'll update the entire schedule
        effective_hour = 0 if prepare_next_day else hour

        # Get current TOU settings
        current_tou = []
        if self._schedule_manager:
            current_tou = self._schedule_manager.tou_intervals

        # Get new TOU settings
        new_tou = temp_growatt.tou_intervals

        # Find segments that need to be disabled or modified
        to_disable = []
        to_update = []

        # First, identify segments to disable
        for current in current_tou:
            start_hour = int(current["start_time"].split(":")[0])
            # Only consider segments that affect future hours
            if (
                start_hour >= effective_hour
                or int(current["end_time"].split(":")[0]) >= effective_hour
            ):
                # Check if this segment exists in new_tou with the same settings
                has_match = False
                for segment in new_tou:
                    if (
                        segment["start_time"] == current["start_time"]
                        and segment["end_time"] == current["end_time"]
                        and segment["batt_mode"] == current["batt_mode"]
                        and segment["enabled"] == current["enabled"]
                    ):
                        has_match = True
                        # Prefer to reuse the segment ID if possible
                        segment["segment_id"] = current["segment_id"]
                        break

                if not has_match:
                    # Segment no longer needed
                    disabled_segment = current.copy()
                    disabled_segment["enabled"] = False
                    to_disable.append(disabled_segment)

        # Then, identify segments to add or update
        for segment in new_tou:
            start_hour = int(segment["start_time"].split(":")[0])
            if (
                start_hour >= effective_hour
                or int(segment["end_time"].split(":")[0]) >= effective_hour
            ):
                # Check if this segment exists in current_tou with the same settings
                existing_match = False
                for current in current_tou:
                    if (
                        current["start_time"] == segment["start_time"]
                        and current["end_time"] == segment["end_time"]
                        and current["batt_mode"] == segment["batt_mode"]
                        and current["enabled"] == segment["enabled"]
                    ):
                        existing_match = True
                        break

                if not existing_match:
                    # New or modified segment
                    to_update.append(segment)

        # Check for time range overlaps with existing segments
        potentially_conflicting = []

        for update_segment in to_update:
            update_start = int(update_segment["start_time"].split(":")[0])
            update_end = int(update_segment["end_time"].split(":")[0])

            for current_segment in current_tou:
                # Skip segments we're already planning to disable
                already_in_disable_list = False
                for d in to_disable:
                    if d["segment_id"] == current_segment["segment_id"]:
                        already_in_disable_list = True
                        break

                if already_in_disable_list:
                    continue

                # Skip disabled segments
                if not current_segment["enabled"]:
                    continue

                current_start = int(current_segment["start_time"].split(":")[0])
                current_end = int(current_segment["end_time"].split(":")[0])

                # Check for overlap
                if update_start <= current_end and update_end >= current_start:
                    # This is a potential conflict
                    potentially_conflicting.append(current_segment)
                    # Add to disable list if not already there
                    already_in_disable_list = False
                    for d in to_disable:
                        if d["segment_id"] == current_segment["segment_id"]:
                            already_in_disable_list = True
                            break

                    if not already_in_disable_list:
                        disabled_segment = current_segment.copy()
                        disabled_segment["enabled"] = False
                        to_disable.append(disabled_segment)

        # Apply updates
        if to_disable or to_update:
            logger.info(
                "Updating %d segments, disabling %d segments",
                len(to_update),
                len(to_disable),
            )

            # Disable segments first to avoid time overlaps
            for segment in to_disable:
                self._controller.set_inverter_time_segment(**segment)

            # Then update/add segments
            for segment in to_update:
                self._controller.set_inverter_time_segment(**segment)
        else:
            logger.info("No TOU segment changes needed")

        # Set current hour in the new Growatt manager
        temp_growatt.current_hour = hour

        # Replace schedule manager with the new one
        self._schedule_manager = temp_growatt

        # Apply the current hour's settings (unless preparing for next day)
        if not prepare_next_day:
            self._apply_hourly_schedule(hour)

        logger.info("Schedule applied successfully")

    def _apply_hourly_schedule(self, hour):
        """Apply schedule settings for specific hour.

        Args:
            hour: Hour to apply settings for (0-23)

        Raises:
            AttributeError: If controller methods are missing
            ValueError: If invalid settings are provided
            TimeoutError: If communication with inverter times out

        """
        # Input validation
        if not 0 <= hour <= 23:
            logger.error("Invalid hour: %d", hour)
            raise ValueError(f"Invalid hour: {hour}")

        # Get or create schedule
        if not self._current_schedule:
            logger.info("Creating new schedule")
            self._current_schedule = self.create_schedule()

        # Get settings from schedule manager
        settings = self._schedule_manager.get_hourly_settings(hour)

        # Apply grid charge setting - only if different from current state
        try:
            current_grid_charge = self._controller.grid_charge_enabled()
            if settings["grid_charge"] != current_grid_charge:
                logger.info(
                    "Changing grid charge from %s to %s for hour %02d:00",
                    current_grid_charge,
                    settings["grid_charge"],
                    hour,
                )
                self._controller.set_grid_charge(settings["grid_charge"])
            else:
                logger.debug(
                    "Grid charge already in correct state (%s) for hour %02d:00",
                    settings["grid_charge"],
                    hour,
                )
        except (AttributeError, ValueError) as e:
            logger.error("Failed to set grid charge: %s", str(e))
            raise

        # Apply discharge rate - only if different from current state
        discharge_rate = int(settings["discharge_rate"])
        try:
            current_discharge_rate = self._controller.get_discharging_power_rate()
            if discharge_rate != current_discharge_rate:
                logger.info(
                    "Changing discharge rate from %d%% to %d%% for hour %02d:00",
                    current_discharge_rate,
                    discharge_rate,
                    hour,
                )
                self._controller.set_discharging_power_rate(discharge_rate)
            else:
                logger.debug(
                    "Discharge rate already in correct state (%d%%) for hour %02d:00",
                    discharge_rate,
                    hour,
                )
        except (AttributeError, ValueError) as e:
            logger.error("Failed to set discharge rate: %s", str(e))
            raise

    def verify_inverter_settings(self, hour):
        """Verify inverter settings match schedule.

        Args:
            hour: Current hour (0-23)

        """
        try:
            self._battery_monitor.check_system_state(hour)
        except (AttributeError, ValueError, KeyError) as e:
            logger.error("Failed to verify inverter settings: %s", str(e))

    def adjust_charging_power(self):
        """Adjust charging power based on house consumption."""
        try:
            self._power_monitor.adjust_battery_charging()
        except (AttributeError, ValueError, KeyError) as e:
            logger.error("Failed to adjust charging power: %s", str(e))

    def get_settings(self) -> dict:
        """Get all current settings."""
        return {
            "battery": self.battery_settings.asdict(),
            "consumption": self.consumption_settings.asdict(),
            "totalConsumption": self.consumption_settings.asdict(),
            "home": self.home_settings.asdict(),
            "price": self.price_settings.asdict(),
        }

    def update_settings(self, settings: dict) -> None:
        """Update settings from dictionary.

        Args:
            settings: Dictionary containing settings to update.
                     Can include 'battery', 'consumption', 'home', and 'price' sections.

        Raises:
            ValueError: If settings contain invalid values
            KeyError: If settings dictionary is malformed

        """
        try:
            if "battery" in settings:
                self.battery_settings.update(**settings["battery"])

            if "consumption" in settings:
                self.consumption_settings.update(**settings["consumption"])

            if "home" in settings:
                self.home_settings.update(**settings["home"])

            if "price" in settings:
                self.price_settings.update(**settings["price"])
                self._price_manager.update_settings(**settings["price"])
        except (ValueError, KeyError, TypeError) as e:
            logger.error("Failed to update settings: %s", str(e))
            raise ValueError(f"Invalid settings: {e!s}") from e

    def _log_battery_system_config(self):
        """Log the current battery configuration."""
        # Get energy data for consumption info
        try:
            energy_data = self._energy_manager.get_full_day_energy_profile(0)
            predictions = energy_data["consumption"]

            if self._controller:
                current_soc = self._controller.get_battery_soc()
            else:
                current_soc = self.battery_settings.min_soc

            min_consumption = min(predictions)
            max_consumption = max(predictions)
            avg_consumption = sum(predictions) / 24

            config_str = f"""
\n╔═════════════════════════════════════════════════════╗
║          Battery Schedule Prediction Data           ║
╠══════════════════════════════════╦══════════════════╣
║ Parameter                        ║ Value            ║
╠══════════════════════════════════╬══════════════════╣
║ Total Capacity                   ║ {self.battery_settings.total_capacity:>12.1f} kWh ║
║ Reserved Capacity                ║ {self.battery_settings.total_capacity * (self.battery_settings.min_soc / 100):>12.1f} kWh ║
║ Usable Capacity                  ║ {self.battery_settings.total_capacity * (1 - self.battery_settings.min_soc / 100):>12.1f} kWh ║
║ Max Charge/Discharge Power       ║ {self.battery_settings.max_charge_power_kw:>12.1f} kW  ║
║ Charge Cycle Cost                ║ {self.battery_settings.cycle_cost:>12.2f} SEK ║
╠══════════════════════════════════╬══════════════════╣
║ Use Actual Price                 ║ {self.price_settings.use_actual_price!s:>15}  ║
║ Inital SOE                       ║ {self.battery_settings.total_capacity * (current_soc / 100):>12.1f} kWh ║
║ Charging Power Rate              ║ {self.battery_settings.charging_power_rate:>12.1f} %   ║
║ Charging Power                   ║ {(self.battery_settings.charging_power_rate / 100) * self.battery_settings.max_charge_power_kw:>12.1f} kW  ║
║ Min Hourly Consumption           ║ {min_consumption:>12.1f} kWh ║
║ Max Hourly Consumption           ║ {max_consumption:>12.1f} kWh ║
║ Avg Hourly Consumption           ║ {avg_consumption:>12.1f} kWh ║
╚══════════════════════════════════╩══════════════════╝\n"""
            logger.info(config_str)
        except (AttributeError, ValueError, KeyError, ZeroDivisionError) as e:
            logger.error("Failed to log battery system config: %s", str(e))

    def log_system_startup(self):
        """Generate comprehensive system startup report.

        This logs the current system state, settings, and energy balance
        upon system startup, providing a complete snapshot of the system.
        """
        try:
            # Log system settings
            self._log_battery_system_config()

            # Log energy state and report
            self._energy_manager.log_energy_balance()

            # Check for schedule
            if self._current_schedule:
                self._current_schedule.log_schedule()

        except (AttributeError, ValueError, KeyError) as e:
            logger.error("Failed to log system startup: %s", str(e))

    def create_schedule(self, price_entries=None, price_date=None) -> Schedule:
        """Prepare schedule for today or a specific date.

        Args:
            price_entries: Optional price entries
            price_date: Optional date to create schedule for

        Returns:
            Schedule: The created schedule

        Raises:
            ValueError: If prices are unavailable or schedule creation fails

        """
        schedule = None
        try:
            if price_entries is None:
                if price_date:
                    logger.debug(
                        "No prices provided, fetching prices for %s", price_date
                    )
                    price_entries = self._price_manager.get_prices(price_date)
                else:
                    logger.debug("No prices provided, fetching today's prices")
                    price_entries = self._price_manager.get_today_prices()

            # Get current SOC from controller if available
            if self._controller is not None:
                current_soc = self._controller.get_battery_soc()
                logger.info("Using current battery SOC: %.1f%%", current_soc)
            else:
                current_soc = self.battery_settings.min_soc
                logger.info(
                    "No controller available, using default SOC: %.1f%%", current_soc
                )

            # Select appropriate prices and adjust cycle cost for optimization
            use_raw_prices = not self.price_settings.use_actual_price
            prices = []
            for entry in price_entries:
                if use_raw_prices:
                    prices.append(entry["price"])
                else:
                    prices.append(entry["buyPrice"])

            # Get combined energy data with actual consumption where available
            current_hour = datetime.now().hour
            energy_profile = self._energy_manager.get_full_day_energy_profile(
                current_hour
            )
            hourly_consumption = energy_profile["consumption"]
            hourly_solar = energy_profile["solar"]
            self._energy_manager.log_energy_balance()

            # Gather optimization data
            optimization_data = {
                "full_consumption": hourly_consumption,
                "full_solar": hourly_solar,
                "combined_actions": [0.0] * 24,
                "combined_soe": [
                    current_soc / 100.0 * self.battery_settings.total_capacity
                ]
                * 24,
                "solar_charged": [0.0] * 24,
            }

            # Run optimization for entire day (optimization_hour=0)
            optimization_result = self._run_optimization(
                optimization_hour=0,
                current_soc=current_soc,
                optimization_data=optimization_data,
                prices=prices,
                prepare_next_day=False,
            )

            if not optimization_result:
                logger.error("Optimization failed to produce valid results")
            else:
                # Create schedule from results
                schedule = Schedule()
                schedule.set_optimization_results(
                    actions=optimization_result["actions"],
                    state_of_energy=optimization_result["state_of_energy"],
                    prices=prices,
                    cycle_cost=self.battery_settings.cycle_cost,
                    hourly_consumption=hourly_consumption,
                    solar_charged=optimization_result.get("solar_charged", [0.0] * 24),
                )

                schedule.log_schedule()
                self._schedule_manager.create_schedule(schedule)
                self._current_schedule = schedule
        except (ValueError, KeyError, AttributeError) as e:
            logger.error("Failed to create schedule: %s", str(e))
            raise ValueError(f"Failed to create schedule: {e!s}") from e
        else:
            if schedule is None:
                raise ValueError("Optimization failed to produce valid results")
            return schedule
