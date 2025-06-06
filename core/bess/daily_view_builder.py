"""
DailyViewBuilder - Creates complete 00-23 daily views combining actuals + predictions.

This module provides the DailyViewBuilder class that combines historical actual
data with current predictions to always provide a complete 24-hour view for
the UI and API. It also recalculates total daily savings from the combined data.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from .historical_data_store import HistoricalDataStore, HourlyEvent
from .schedule_store import ScheduleStore

logger = logging.getLogger(__name__)


@dataclass
class HourlyData:
    """Complete data for one hour - either actual or predicted."""

    hour: int
    data_source: str  # "actual" or "predicted"

    # Core energy flows (kWh)
    solar_generated: float
    home_consumed: float
    grid_imported: float
    grid_exported: float
    battery_charged: float
    battery_discharged: float

    # Battery state
    battery_soc_start: float  # %
    battery_soc_end: float  # %

    # Economic data
    electricity_price: float  # SEK/kWh
    hourly_cost: float  # SEK - Cost of solar+battery scenario (from optimized_cost)
    hourly_savings: (
        float  # SEK - Total savings (solar+battery): base_cost - optimized_cost
    )

    # Battery action (for predicted hours)
    battery_action: float | None = None  # kW (from optimization)

    # Battery cycle cost (SEK)
    battery_cycle_cost: float = 0.0


@dataclass
class DailyView:
    """Complete 00-23 view combining actual and predicted data."""

    date: datetime
    current_hour: int
    hourly_data: list[HourlyData]  # Always 24 hours

    # Summary metrics
    total_daily_savings: float  # SEK
    actual_savings_so_far: float  # SEK (from completed hours)
    predicted_remaining_savings: float  # SEK (from future hours)

    # Data source breakdown
    actual_hours_count: int
    predicted_hours_count: int
    data_sources: list[str]  # ["actual", "actual", "predicted", ...]

    def get_hour_data(self, hour: int) -> HourlyData | None:
        """Get data for a specific hour.

        Args:
            hour: Hour to retrieve (0-23)

        Returns:
            Optional[HourlyData]: Data for the hour, or None if invalid hour
        """
        if not 0 <= hour <= 23:
            return None
        return self.hourly_data[hour]

    def get_actual_hours(self) -> list[HourlyData]:
        """Get all hours with actual data."""
        return [h for h in self.hourly_data if h.data_source == "actual"]

    def get_predicted_hours(self) -> list[HourlyData]:
        """Get all hours with predicted data."""
        return [h for h in self.hourly_data if h.data_source == "predicted"]


class DailyViewBuilder:
    """Builds complete daily views combining historical actuals and current predictions.

    This class takes actual data from HistoricalDataStore and predicted data from
    ScheduleStore to create a complete 24-hour view. It also recalculates total
    daily savings by combining actual and predicted scenarios.
    """

    def __init__(
        self,
        historical_store: HistoricalDataStore,
        schedule_store: ScheduleStore,
        battery_capacity_kwh: float,
        battery_cycle_cost_per_kwh: float,
    ):
        """Initialize the daily view builder.

        Args:
            historical_store: Store containing actual historical data
            schedule_store: Store containing optimization results
            battery_capacity_kwh: Total battery capacity for calculations
            battery_cycle_cost_per_kwh: Cost per kWh for battery cycles
        """
        self.historical_store = historical_store
        self.schedule_store = schedule_store
        self.battery_capacity = battery_capacity_kwh
        self.battery_cycle_cost = battery_cycle_cost_per_kwh

        logger.info(
            "Initialized DailyViewBuilder with %.1f kWh battery capacity, %.2f SEK/kWh cycle cost",
            battery_capacity_kwh,
            battery_cycle_cost_per_kwh,
        )

    def build_daily_view(self, current_hour: int, price_data: list[float]) -> DailyView:
        """Build complete 00-23 daily view - DETERMINISTIC, no fallbacks."""
        if not 0 <= current_hour <= 23:
            raise ValueError(f"current_hour must be 0-23, got {current_hour}")

        if not price_data or len(price_data) < 24:
            raise ValueError(
                f"24-hour price_data is required, got {len(price_data) if price_data else 0} hours"
            )

        logger.info(f"Building daily view for hour {current_hour}")

        # Get latest schedule and validate coverage
        latest_schedule = self.schedule_store.get_latest_schedule()
        if not latest_schedule:
            raise ValueError(
                "No optimization schedule available - system cannot provide daily view"
            )

        (
            schedule_start_hour,
            schedule_end_hour,
        ) = latest_schedule.get_optimization_range()
        logger.info(
            f"Latest schedule covers hours {schedule_start_hour}-{schedule_end_hour}"
        )

        # Validate we have required data for ALL hours
        missing_actual_hours = []
        missing_predicted_hours = []

        for hour in range(24):
            if hour < current_hour:
                # Past hours MUST have actual data
                if not self.historical_store.has_data_for_hour(hour):
                    missing_actual_hours.append(hour)
            else:
                # Future hours MUST be covered by schedule
                if not (schedule_start_hour <= hour <= schedule_end_hour):
                    missing_predicted_hours.append(hour)

        # FAIL FAST if any data is missing
        if missing_actual_hours:
            raise ValueError(
                f"Missing historical data for hours {missing_actual_hours}. "
                f"System cannot provide reliable daily view. "
                f"Check sensor data collection and InfluxDB connectivity."
            )

        if missing_predicted_hours:
            raise ValueError(
                f"Missing optimization data for hours {missing_predicted_hours}. "
                f"Schedule only covers {schedule_start_hour}-{schedule_end_hour}. "
                f"System cannot provide complete daily view."
            )

        # If we get here, we have complete data - build deterministically
        hourly_data = []
        data_sources = []

        for hour in range(24):
            if hour < current_hour:
                # Build from actual historical data
                hour_data = self._build_actual_hour_data(hour, price_data[hour])
                data_sources.append("actual")
            else:
                # Build from optimization schedule
                hour_data = self._build_predicted_hour_data(
                    hour, price_data[hour], current_hour
                )
                data_sources.append("predicted")

            hourly_data.append(hour_data)

        # Sort and validate
        hourly_data.sort(key=lambda x: x.hour)
        self._validate_energy_flows(hourly_data)

        # Calculate metrics
        actual_savings = sum(
            h.hourly_savings for h in hourly_data if h.data_source == "actual"
        )
        predicted_savings = sum(
            h.hourly_savings for h in hourly_data if h.data_source == "predicted"
        )

        daily_view = DailyView(
            date=datetime.now(),
            current_hour=current_hour,
            hourly_data=hourly_data,
            total_daily_savings=actual_savings + predicted_savings,
            actual_savings_so_far=actual_savings,
            predicted_remaining_savings=predicted_savings,
            actual_hours_count=len(
                [h for h in hourly_data if h.data_source == "actual"]
            ),
            predicted_hours_count=len(
                [h for h in hourly_data if h.data_source == "predicted"]
            ),
            data_sources=data_sources,
        )

        self.log_complete_daily_schedule(daily_view)
        return daily_view

    def _build_actual_hour_data(self, hour: int, price: float) -> HourlyData:
        """Use saved optimization cost data from historical events without fallbacks."""
        event = self.historical_store.get_hour_event(hour)

        if event is None:
            logger.error(
                f"No actual data for hour {hour}, cannot create deterministic view"
            )
            raise ValueError(
                f"Missing actual data for hour {hour}, cannot create deterministic view"
            )

        # Check for required fields to ensure deterministic operation
        required_fields = [
            "solar_generated",
            "home_consumed",
            "grid_imported",
            "grid_exported",
            "battery_charged",
            "battery_discharged",
            "battery_soc_start",
            "battery_soc_end",
            "base_cost",
            "optimized_cost",
            "hourly_savings",
            "electricity_price",
        ]

        for field in required_fields:
            if not hasattr(event, field) or getattr(event, field) is None:
                logger.error(
                    f"Missing required field '{field}' in actual data for hour {hour}"
                )
                raise ValueError(
                    f"Missing required field '{field}' in actual data for hour {hour}"
                )

        # hourly_savings represents total savings with both solar and battery: base_cost - optimized_cost
        logger.debug(
            f"Found actual data for hour {hour}: Solar={event.solar_generated:.1f}, Load={event.home_consumed:.1f}, SOC={event.battery_soc_end:.1f}%, Total Savings={event.hourly_savings:.2f}"
        )

        # Calculate battery_action from charge/discharge data
        # Positive for charging, negative for discharging
        battery_action = 0.0
        if event.battery_charged > 0:
            battery_action = event.battery_charged
        elif event.battery_discharged > 0:
            battery_action = -event.battery_discharged

        # Calculate battery cycle cost (both charge and discharge contribute to wear)
        battery_throughput = event.battery_charged + event.battery_discharged
        battery_cycle_cost = battery_throughput * self.battery_cycle_cost

        return HourlyData(
            hour=hour,
            data_source="actual",
            solar_generated=event.solar_generated,
            home_consumed=event.home_consumed,
            grid_imported=event.grid_imported,
            grid_exported=event.grid_exported,
            battery_charged=event.battery_charged,
            battery_discharged=event.battery_discharged,
            battery_soc_start=event.battery_soc_start,
            battery_soc_end=event.battery_soc_end,
            electricity_price=event.electricity_price,
            hourly_cost=event.optimized_cost,  # solar+battery cost (full optimization)
            hourly_savings=event.hourly_savings,  # total savings (solar+battery): base_cost - optimized_cost
            battery_action=battery_action,  # Calculated from charge/discharge
            battery_cycle_cost=battery_cycle_cost,  # Added battery cycle cost
        )

    def _get_list_item(self, lst: list, index: int, name: str):
        """Get item from list with proper error handling."""
        if not isinstance(lst, list):
            raise ValueError(f"Expected a list for {name}, got {type(lst)}")
        if not (0 <= index < len(lst)):
            raise ValueError(
                f"Index {index} out of range for {name} (length: {len(lst) if lst else 0})"
            )
        return lst[index]

    def _get_latest_hourly_soc(self) -> tuple[int, float]:
        """Get the hour and SOC of the most recent actual data point.

        This is used to bridge the gap between actual and predicted data.

        Returns:
            Tuple[int, float]: The hour and SOC of the most recent actual data point
        """
        # Iterate backwards from hour 23 to find the most recent actual data
        for hour in range(23, -1, -1):
            event = self.historical_store.get_hour_event(hour)
            if event:
                return hour, event.battery_soc_end

        # If no actual data is found, use the initial SOC from the schedule
        latest_schedule = self.schedule_store.get_latest_schedule()
        if latest_schedule and "initial_soc" in latest_schedule.algorithm_result:
            return -1, latest_schedule.algorithm_result["initial_soc"]

        # If all else fails, use a default value
        logger.warning("No actual data or initial SOC found, using default 20%")
        return -1, 20.0  # 20% as a safe default

    def _build_predicted_hour_data(
        self, hour: int, price: float, current_hour: int
    ) -> HourlyData:
        """Build hour data from predicted schedule data with proper SOC/SOE conversion."""
        # Get latest schedule that covers this hour
        latest_schedule = self.schedule_store.get_latest_schedule()

        if latest_schedule is None:
            logger.error(
                f"No schedule available for hour {hour}, cannot create deterministic view"
            )
            raise ValueError(
                f"No schedule available for hour {hour}, cannot create deterministic view"
            )

        # Check if this schedule covers the requested hour
        start_hour, end_hour = latest_schedule.get_optimization_range()
        if not (start_hour <= hour <= end_hour):
            logger.error(
                f"Latest schedule doesn't cover hour {hour} (range {start_hour}-{end_hour}), cannot create deterministic view"
            )
            raise ValueError(
                f"Latest schedule doesn't cover hour {hour} (range {start_hour}-{end_hour}), cannot create deterministic view"
            )

        # Extract data from algorithm result
        try:
            hourly_data = latest_schedule.algorithm_result["hourly_data"]

            # Calculate index in the algorithm result (since it may not start from hour 0)
            result_index = hour - start_hour

            # Extract values with proper error handling - no fallbacks for deterministic operation
            battery_action_list = hourly_data.get("battery_action")
            if not battery_action_list:
                raise ValueError(f"Missing 'battery_action' data for hour {hour}")
            battery_action = self._get_list_item(
                battery_action_list, result_index, "battery_action"
            )

            # Check if full 24-hour data is available in input_data (used in restart scenario)
            input_data = latest_schedule.algorithm_result.get("input_data", {})

            # Get consumption from appropriate source
            if "full_home_consumption" in input_data and hour < len(
                input_data["full_home_consumption"]
            ):
                home_consumption = input_data["full_home_consumption"][hour]
            else:
                home_consumption_list = hourly_data.get("home_consumption")
                if not home_consumption_list:
                    raise ValueError(f"Missing home consumption data for hour {hour}")
                home_consumption = self._get_list_item(
                    home_consumption_list, result_index, "home_consumption"
                )

            # Get solar from appropriate source
            if "full_solar_production" in input_data and hour < len(
                input_data["full_solar_production"]
            ):
                solar_production = input_data["full_solar_production"][hour]
            else:
                solar_production_list = hourly_data.get("solar_production")
                if not solar_production_list:
                    raise ValueError(f"Missing solar production data for hour {hour}")
                solar_production = self._get_list_item(
                    solar_production_list, result_index, "solar_production"
                )

            # Get grid flows with no fallbacks
            grid_import_list = hourly_data.get("grid_import")
            grid_export_list = hourly_data.get("grid_export")
            soc_list = hourly_data.get("state_of_charge")

            if not grid_import_list:
                raise ValueError(f"Missing grid import data for hour {hour}")
            if not grid_export_list:
                raise ValueError(f"Missing grid export data for hour {hour}")
            if not soc_list:
                raise ValueError(f"Missing state of charge data for hour {hour}")

            grid_import = self._get_list_item(
                grid_import_list, result_index, "grid_import"
            )
            grid_export = self._get_list_item(
                grid_export_list, result_index, "grid_export"
            )

            # CRITICAL FIX: Get SOE in kWh and convert to SOC in %
            soe_kwh = self._get_list_item(soc_list, result_index, "state_of_charge")
            soc_percent = (soe_kwh / self.battery_capacity) * 100

            # Validate battery action to ensure it's within physical limits
            max_possible_action = self.battery_capacity
            if abs(battery_action) > max_possible_action:
                logger.warning(
                    f"Battery action for hour {hour} exceeds physical limits: {battery_action:.2f} kWh. Capping to {max_possible_action:.2f} kWh"
                )
                battery_action = max(
                    -max_possible_action, min(max_possible_action, battery_action)
                )

            # Calculate battery charge/discharge from action
            battery_charged = max(0, battery_action)
            battery_discharged = max(0, -battery_action)

            # Calculate battery cycle cost (both charge and discharge contribute to wear)
            battery_throughput = battery_charged + battery_discharged
            battery_cycle_cost = battery_throughput * self.battery_cycle_cost

            # Get the hourly cost directly from the algorithm result
            hourly_cost_list = hourly_data.get("battery_solar_hourly_cost")
            if not hourly_cost_list:
                raise ValueError(f"Missing hourly cost data for hour {hour}")
            hourly_cost = self._get_list_item(
                hourly_cost_list, result_index, "hourly_cost"
            )

            # Get base cost directly from the algorithm result
            base_cost_list = hourly_data.get("base_case_hourly_cost")
            if not base_cost_list:
                raise ValueError(f"Missing base case cost data for hour {hour}")
            base_cost = self._get_list_item(base_cost_list, result_index, "base_cost")

            # Calculate savings directly
            hourly_savings = base_cost - hourly_cost

            # Determine SOC start - handle the transition from actual to predicted more robustly
            try:
                # First try the standard method which uses the previous hour's data
                prev_soc = self._get_previous_hour_soc(hour)
            except ValueError as e:
                # If that fails, use the latest actual hour's SOC as a bridge
                logger.warning(f"SOC bridge needed for hour {hour}: {e}")
                last_actual_hour, last_actual_soc = self._get_latest_hourly_soc()

                if hour > 0 and last_actual_hour >= 0:
                    # We have some actual data - use it as a starting point
                    logger.info(
                        f"Using SOC bridge from hour {last_actual_hour} ({last_actual_soc:.1f}%) to hour {hour}"
                    )

                    # Get efficiency values from input data if available
                    input_data = latest_schedule.algorithm_result.get("input_data", {})
                    efficiency_charge = input_data.get(
                        "battery_charge_efficiency", 0.95
                    )
                    efficiency_discharge = input_data.get(
                        "battery_discharge_efficiency", 0.95
                    )

                    # Starting from the known hour, trace forward using the schedule data
                    curr_soc = last_actual_soc
                    for h in range(last_actual_hour + 1, hour):
                        # Find the action for this hour in the schedule
                        idx = h - start_hour
                        if 0 <= idx < len(battery_action_list):
                            action = battery_action_list[idx]
                            # Calculate SOC update using charge/discharge from this action
                            if action > 0:  # Charging
                                curr_soc += (
                                    action * efficiency_charge / self.battery_capacity
                                ) * 100
                            elif action < 0:  # Discharging
                                curr_soc -= (
                                    abs(action)
                                    / efficiency_discharge
                                    / self.battery_capacity
                                ) * 100

                    prev_soc = curr_soc
                else:
                    # No actual data at all, use initial SOC from schedule
                    prev_soc = latest_schedule.algorithm_result.get("initial_soc", 20.0)
                    logger.info(f"Using initial SOC {prev_soc:.1f}% for hour {hour}")

            # DEBUG: Log the unit conversion for problematic hours
            if hour in [18, 19, 20]:
                logger.info(
                    f"Hour {hour} conversion: SOE={soe_kwh:.1f} kWh → SOC={soc_percent:.1f}%"
                )
                logger.info(
                    f"Hour {hour}: Prev SOC={prev_soc:.1f}%, Action={battery_action:.1f} kWh"
                )

            return HourlyData(
                hour=hour,
                data_source="predicted",
                solar_generated=solar_production,
                home_consumed=home_consumption,
                grid_imported=grid_import,
                grid_exported=grid_export,
                battery_charged=battery_charged,
                battery_discharged=battery_discharged,
                battery_soc_start=prev_soc,
                battery_soc_end=soc_percent,  # CRITICAL: Use converted percentage, not raw kWh
                electricity_price=price,
                hourly_cost=hourly_cost,
                hourly_savings=hourly_savings,
                battery_action=battery_action,
                battery_cycle_cost=battery_cycle_cost,
            )

        except Exception as e:
            logger.error(f"Error extracting predicted data for hour {hour}: {e}")
            raise ValueError(f"Error extracting predicted data for hour {hour}") from e

    def _calculate_actual_hour_savings(self, event: HourlyEvent, price: float) -> float:
        """Calculate savings for an actual hour compared to no-battery scenario.

        Args:
            event: Actual hour event
            price: Electricity price for the hour

        Returns:
            float: Estimated savings in SEK for this hour (grid_only - solar_battery)
        """
        # Always use total savings directly from the event
        # hourly_savings represents total savings (with solar + battery): base_cost - optimized_cost

        # Check that the required field exists before using it
        if not hasattr(event, "hourly_savings"):
            logger.error(f"Missing 'hourly_savings' field in hour event {event.hour}")
            raise ValueError(
                f"Missing 'hourly_savings' field in hour event {event.hour}"
            )

        # Use the hourly_savings field directly - only one deterministic path
        return event.hourly_savings

    def _get_previous_hour_soc(self, hour: int) -> float:
        """Get SOC from previous hour - SIMPLE AND RELIABLE."""

        if hour == 0:
            # Hour 0 needs initial SOC from schedule
            latest_schedule = self.schedule_store.get_latest_schedule()
            if latest_schedule and "initial_soc" in latest_schedule.algorithm_result:
                return latest_schedule.algorithm_result["initial_soc"]
            raise ValueError("Missing initial SOC for hour 0")

        # For any other hour, try to get SOC from previous hour's actual data
        prev_hour = hour - 1
        prev_event = self.historical_store.get_hour_event(prev_hour)

        if prev_event:
            # Found actual data for previous hour - USE IT
            logger.debug(
                f"Using actual SOC from hour {prev_hour}: {prev_event.battery_soc_end}%"
            )
            return prev_event.battery_soc_end

        # If no actual data for previous hour, this means we're in predicted territory
        # and need to chain predicted hours together

        # Find the most recent actual hour before this one
        last_actual_hour = prev_hour
        while last_actual_hour >= 0:
            actual_event = self.historical_store.get_hour_event(last_actual_hour)
            if actual_event:
                # Found the bridge point - this is our last known actual SOC
                logger.info(
                    f"Found actual bridge at hour {last_actual_hour}: SOC={actual_event.battery_soc_end}%"
                )

                # Now we need to calculate forward from this actual hour to the previous hour
                # using the optimization schedule
                latest_schedule = self.schedule_store.get_latest_schedule()
                if (
                    not latest_schedule
                    or "hourly_data" not in latest_schedule.algorithm_result
                ):
                    raise ValueError(
                        f"Cannot determine SOC for hour {hour}: Missing schedule data"
                    )

                start_hour, _ = latest_schedule.get_optimization_range()
                hourly_data = latest_schedule.algorithm_result["hourly_data"]

                if "state_of_charge" not in hourly_data:
                    raise ValueError(
                        f"Cannot determine SOC for hour {hour}: Missing state_of_charge in schedule"
                    )

                # Get the SOC from the optimization result for the previous hour
                target_index = prev_hour - start_hour
                soc_list = hourly_data["state_of_charge"]

                if 0 <= target_index < len(soc_list):
                    # The optimization returns SOE in kWh, convert to SOC in %
                    soe_kwh = soc_list[target_index]
                    soc_percent = (soe_kwh / self.battery_capacity) * 100

                    logger.info(
                        f"Using predicted SOC for hour {prev_hour}: SOE={soe_kwh:.1f}kWh → SOC={soc_percent:.1f}%"
                    )
                    return soc_percent
                else:
                    raise ValueError(
                        f"Cannot determine SOC for hour {hour}: Index {target_index} out of range"
                    )

            last_actual_hour -= 1

        # If we get here, we couldn't find any actual data
        raise ValueError(
            f"Cannot determine SOC for hour {hour}: No actual data found to bridge from"
        )

    def _validate_energy_flows(self, hourly_data):
        """Validate energy flows across all hours to ensure proper balance.

        This method checks that energy conservation laws are followed:
        1. Energy in = Energy out + battery net change
        2. Battery net change = battery_charged - battery_discharged
        3. Solar energy is properly allocated (solar to home, battery, grid)

        Args:
            hourly_data: List of 24 HourlyData objects
        """
        logger.info("Validating energy flows for daily view")

        total_input = 0
        total_output = 0
        total_battery_net = 0

        # Collect hourly data for validation
        for hour_data in hourly_data:
            # Calculate energy flows for this hour
            energy_in = hour_data.grid_imported + hour_data.solar_generated
            energy_out = hour_data.home_consumed + hour_data.grid_exported
            battery_net = hour_data.battery_charged - hour_data.battery_discharged

            # Log imbalances for debugging
            if abs(energy_in - energy_out - battery_net) > 0.1:
                logger.warning(
                    "Hour %02d energy imbalance: in=%.2f, out=%.2f, battery=%.2f, diff=%.2f",
                    hour_data.hour,
                    energy_in,
                    energy_out,
                    battery_net,
                    energy_in - energy_out - battery_net,
                )

            # Accumulate for daily totals
            total_input += energy_in
            total_output += energy_out
            total_battery_net += battery_net

        # Log overall energy balance
        logger.info(
            "Daily energy balance: input=%.2f kWh, output=%.2f kWh, battery_net=%.2f kWh, diff=%.2f kWh",
            total_input,
            total_output,
            total_battery_net,
            total_input - total_output - total_battery_net,
        )

        # If there's a significant overall imbalance (>1% of total or >0.1 kWh), log a warning
        if abs(total_input - total_output - total_battery_net) > max(
            0.01 * total_input, 0.1
        ):
            logger.warning(
                "Daily energy imbalance detected: %.2f kWh (%.1f%% of total input)",
                total_input - total_output - total_battery_net,
                100
                * (total_input - total_output - total_battery_net)
                / max(0.1, total_input),
            )

    def log_complete_daily_schedule(self, daily_view: DailyView) -> None:
        """Log complete 24-hour schedule table with correct cost scenarios.

        This version builds the log as a string and logs it all at once.
        """
        lines = []
        lines.append("╔" + "=" * 92 + "╗")
        lines.append("║" + " " * 30 + "COMPLETE DAILY SCHEDULE" + " " * 39 + "║")
        lines.append(
            "╠════╦════════════╦═════╦══════╦╦═════╦══════╦══════╦════╦═══════╦══════╦══════╦══════╦══════╣"
        )
        lines.append(
            "║ Hr ║  Buy/Sell  ║Cons.║ Base ║║Sol. ║Sol→B ║Gr→B  ║SoC ║ Act.  ║ Opt. ║B.Cst ║ Tot. ║ Save ║"
        )
        lines.append(
            "╠════╬════════════╬═════╬══════╬╬═════╬══════╬══════╬════╬═══════╬══════╬══════╬══════╬══════╣"
        )

        # Calculate totals
        total_consumption = 0.0
        total_solar = 0.0
        total_base_cost = 0.0
        total_optimized_cost = 0.0
        total_battery_cost = 0.0
        total_savings = 0.0
        total_battery_charge = 0.0
        total_battery_discharge = 0.0

        for hour_data in daily_view.hourly_data:
            # Calculate base cost (grid-only scenario)
            base_cost = hour_data.home_consumed * hour_data.electricity_price

            # Calculate derived values
            sell_price = hour_data.electricity_price * 0.6
            solar_to_battery = min(hour_data.battery_charged, hour_data.solar_generated)
            grid_to_battery = max(0, hour_data.battery_charged - solar_to_battery)

            # Mark predictions with indicator
            indicator = "★" if hour_data.data_source == "predicted" else " "

            # Format battery action with visual indicator
            battery_action = hour_data.battery_action or 0
            action_str = f"{abs(battery_action):4.1f}"
            if battery_action > 0.01:
                action_str += "↑"  # Charging
            elif battery_action < -0.01:
                action_str += "↓"  # Discharging
            else:
                action_str += "-"  # Idle

            # Format row with BASE COST and OPTIMIZED COST
            row = (
                f"║ {hour_data.hour:02d}{indicator}║ {hour_data.electricity_price:4.2f}/ {sell_price:4.2f} "
                f"║ {hour_data.home_consumed:4.1f}║ {base_cost:5.2f}║"  # BASE cost (grid-only)
                f"║ {hour_data.solar_generated:4.1f}║ {solar_to_battery:5.1f}║ {grid_to_battery:5.1f}║"
                f"{hour_data.battery_soc_end:4.0f}║ {action_str:^6}║ "
                f"{hour_data.hourly_cost:5.2f}║ {hour_data.battery_cycle_cost:5.2f}║ "  # Grid + Battery cost
                f"{hour_data.hourly_cost + hour_data.battery_cycle_cost:5.2f}║ {hour_data.hourly_savings:5.2f}║"
            )
            lines.append(row)

            # Accumulate totals
            total_consumption += hour_data.home_consumed
            total_solar += hour_data.solar_generated
            total_base_cost += base_cost
            total_optimized_cost += hour_data.hourly_cost
            total_battery_cost += hour_data.battery_cycle_cost
            total_savings += hour_data.hourly_savings
            total_battery_charge += hour_data.battery_charged
            total_battery_discharge += hour_data.battery_discharged

        # Totals row
        lines.append(
            "╠════╬════════════╬═════╬══════╬╬═════╬══════╬══════╬════╬═══════╬══════╬══════╬══════╬══════╣"
        )
        lines.append(
            f"║TOT ║            ║ {total_consumption:4.1f}║{total_base_cost:6.2f}║"
            f"║ {total_solar:4.1f}║ {0.0:5.1f}║ {0.0:5.1f}║    ║"
            f"C:{total_battery_charge:4.1f} ║ {total_optimized_cost:5.2f}║ {total_battery_cost:5.2f}║ {total_optimized_cost + total_battery_cost:5.2f}║ {total_savings:5.2f}║"
        )
        lines.append(
            f"║    ║            ║     ║      ║║     ║      ║      ║    ║"
            f"D:{total_battery_discharge:4.1f} ║      ║      ║      ║      ║"
        )
        lines.append(
            "╚════╩════════════╩═════╩══════╩╩═════╩══════╩══════╩════╩═══════╩══════╩══════╩══════╩══════╝"
        )

        # Summary
        total_cost = total_optimized_cost + total_battery_cost
        # Use the full savings calculation without capping
        savings_percent = (
            (total_savings / total_base_cost * 100) if total_base_cost > 0 else 0
        )

        lines.append("      Summary:")
        lines.append(f"      Base case cost:           {total_base_cost:.2f} SEK")
        lines.append(f"      Grid cost:                {total_optimized_cost:.2f} SEK")
        lines.append(f"      Battery wear cost:        {total_battery_cost:.2f} SEK")
        lines.append(f"      Total cost:               {total_cost:.2f} SEK")
        lines.append(f"      Total savings:            {total_savings:.2f} SEK")
        lines.append(f"      Savings percentage:         {savings_percent:.1f} %")
        lines.append(
            f"      Actual hours: {daily_view.actual_hours_count}, Predicted hours: {daily_view.predicted_hours_count}"
        )

        logger.info("\n%s", "\n".join(lines))
