"""
DailyViewBuilder - Creates complete 00-23 daily views combining actuals + predictions.

This module provides the DailyViewBuilder class that combines historical actual
data with current predictions to always provide a complete 24-hour view for
the UI and API. It also recalculates total daily savings from the combined data.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from core.bess.dp_battery_algorithm import HourlyData, calculate_hourly_costs

from .historical_data_store import HistoricalDataStore
from .schedule_store import ScheduleStore
from .settings import BatterySettings

logger = logging.getLogger(__name__)


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
    data_sources: list[str]  # ["actual", "predicted"



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
        battery_settings: BatterySettings,
    ):
        """Initialize the daily view builder.

        Args:
            historical_store: Store containing actual historical data
            schedule_store: Store containing optimization results
            battery_settings: Battery settings
        """
        self.historical_store = historical_store
        self.schedule_store = schedule_store
        self.battery_settings = battery_settings


    def build_daily_view(
        self, current_hour: int, buy_price: list[float], sell_price: list[float]
    ) -> DailyView:
        """Build complete 00-23 daily view"""
        logger.info(f"Building daily view for hour {current_hour}")

        if not 0 <= current_hour <= 23:
            raise ValueError(f"current_hour must be 0-23, got {current_hour}")

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

        # Fail hard if any actual hours are missing
        if missing_actual_hours:
            error_message = (
                f"Missing historical data for hours {missing_actual_hours}. "
                f"System cannot provide reliable daily view. "
                f"Check sensor data collection and InfluxDB connectivity."
            )
            logger.error(error_message)
            raise ValueError(error_message)

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
                hour_data = self._build_actual_hour_data(
                    hour, buy_price[hour], sell_price[hour]
                )
                data_sources.append("actual")
            else:
                # Build from optimization schedule
                hour_data = self._build_predicted_hour_data(
                    hour, buy_price[hour], sell_price[hour], current_hour
                )
                data_sources.append("predicted")

            hourly_data.append(hour_data)

        # Sort and validate
        hourly_data.sort(key=lambda x: x.hour)
        self._validate_energy_flows(hourly_data)

        # Calculate metrics
        actual_savings = sum(
            h.hourly_savings for h in hourly_data if h.data_source == "actual" and h.hourly_savings is not None
        )
        predicted_savings = sum(
            h.hourly_savings for h in hourly_data if h.data_source == "predicted" and h.hourly_savings is not None
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

    def _build_actual_hour_data(
        self, hour: int, buy_price: float, sell_price: float
    ) -> HourlyData:
        """Build hour data from actual stored facts using shared cost calculations."""
        # Get actual event data
        event = self.historical_store.get_hour_event(hour)
        assert event is not None, f"No data for hour {hour} - validation should prevent this"

        # Calculate battery_action based on charged/discharged values (positive for charging, negative for discharging)
        battery_action = event.battery_charged - event.battery_discharged

        # Create an HourlyData object with all available data
        hour_data = HourlyData(
            hour=hour,
            data_source="actual",
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumed=event.home_consumed,
            solar_generated=event.solar_generated,
            grid_imported=event.grid_imported,
            grid_exported=event.grid_exported,
            battery_charged=event.battery_charged,
            battery_discharged=event.battery_discharged,
            battery_soc_start=event.battery_soc_start,
            battery_soc_end=event.battery_soc_end,
            battery_action=battery_action,
            strategic_intent=getattr(event, "strategic_intent", "ACTUAL"), # TODO: Implement strategic intent handling
        )

        # Calculate costs using shared cost calculation logic and update the HourlyData object
        costs = calculate_hourly_costs(
            hour_data, 
            self.battery_settings.cycle_cost_per_kwh,
            self.battery_settings.efficiency_charge,
            self.battery_settings.efficiency_discharge
        )
        
        # Update the HourlyData object with cost results
        hour_data.hourly_cost = costs.battery_solar_cost
        hour_data.hourly_savings = costs.total_savings
        hour_data.battery_cycle_cost = costs.battery_wear_cost
        
        return hour_data

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
        if latest_schedule and latest_schedule.optimization_result.input_data:
            initial_soc = latest_schedule.optimization_result.input_data.get("initial_soc")
            if initial_soc is not None:
                return -1, initial_soc

        # If all else fails, use a default value
        logger.warning("No actual data or initial SOC found, using default 20%")
        return -1, 20.0  # 20% as a safe default

    def _build_predicted_hour_data(
        self, hour: int, buy_price: float, sell_price: float, current_hour: int
    ) -> HourlyData:
        """Build hour data from predicted schedule data using shared cost calculations with FIXED current hour SOC.
        
        This is a critical method that ensures correct SOC bridging between actual and predicted hours,
        validates battery actions against physical limits, and processes strategic intent.
        """
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

        # Extract data from optimization result structure
        try:
            # Work directly with OptimizationResult object
            optimization_result = latest_schedule.optimization_result
            hourly_data_list = optimization_result.hourly_data
            result_index = hour - start_hour
            
            if result_index < 0 or result_index >= len(hourly_data_list):
                raise ValueError(f"Hour {hour} is out of range in optimization result (index {result_index})")
            
            hour_result = hourly_data_list[result_index]
            
            # Extract critical data from optimization result
            battery_action = hour_result.battery_action or 0.0
            solar_production = hour_result.solar_generated
            home_consumption = hour_result.home_consumed
            grid_import = hour_result.grid_imported
            grid_export = hour_result.grid_exported
            
            # Validate battery action to ensure it's within physical limits
            max_possible_action = self.battery_settings.total_capacity
            if abs(battery_action) > max_possible_action:
                logger.warning(
                    f"Battery action for hour {hour} exceeds physical limits: {battery_action:.2f} kWh. "
                    f"Capping to {max_possible_action:.2f} kWh"
                )
                battery_action = max(
                    -max_possible_action, min(max_possible_action, battery_action)
                )

            # Calculate battery charge/discharge from action
            battery_charged = max(0, battery_action)      # kWh - positive part of action
            battery_discharged = max(0, -battery_action)  # kWh - magnitude of negative part
            
            # CONSISTENCY VALIDATION: Ensure action and charge/discharge values are consistent
            if abs(battery_action) > 0.01:  # Only check if there's significant action
                reconstructed_action = battery_charged - battery_discharged
                action_error = abs(battery_action - reconstructed_action)
                if action_error > 0.01:
                    logger.warning(
                        f"Hour {hour}: Battery action inconsistency - "
                        f"original={battery_action:.3f} kW, "
                        f"reconstructed={reconstructed_action:.3f} kW, "
                        f"error={action_error:.3f} kW"
                    )

            # CRITICAL FIX: Special handling for current hour SOC calculation
            if hour == current_hour:
                logger.info(f"=== CURRENT HOUR {hour} SOC CALCULATION ===")

                # Get previous hour's ending SOC
                if hour == 0:
                    # For hour 0, use initial SOC from optimization input data
                    prev_soc = optimization_result.input_data.get("initial_soc", 20.0)
                    logger.info(
                        f"Hour 0: Using initial SOC from schedule: {prev_soc:.1f}%"
                    )
                else:
                    # Try to get actual SOC from previous hour's historical data
                    prev_event = self.historical_store.get_hour_event(hour - 1)
                    if prev_event:
                        prev_soc = prev_event.battery_soc_end
                        logger.info(
                            f"Using actual SOC from hour {hour-1}: {prev_soc:.1f}%"
                        )
                    else:
                        # Fallback: calculate from optimization SOC if no historical data
                        logger.warning(
                            f"No historical data for hour {hour-1}, using optimization SOC"
                        )
                        if result_index > 0:
                            prev_hour_result = hourly_data_list[result_index - 1]
                            prev_soc = prev_hour_result.battery_soc_end
                        else:
                            prev_soc = optimization_result.input_data.get("initial_soc", 20.0)
                        logger.info(f"Using optimization SOC: {prev_soc:.1f}%")

                # Calculate SOC change from battery action with efficiency
                if battery_charged > 0:
                    soc_change = (
                        battery_charged
                        * self.battery_settings.efficiency_charge
                        / self.battery_settings.total_capacity
                    ) * 100
                    logger.info(
                        f"Charging: {battery_charged:.2f} kWh * {self.battery_settings.efficiency_charge} / {self.battery_settings.total_capacity} = +{soc_change:.1f}%"
                    )
                elif battery_discharged > 0:
                    # FIXED: Removed extra parentheses and negative sign application
                    soc_change = -(
                        battery_discharged
                        / self.battery_settings.efficiency_discharge
                        / self.battery_settings.total_capacity
                        * 100
                    )
                    logger.info(
                        f"Discharging: {battery_discharged:.2f} kWh / {self.battery_settings.efficiency_discharge} / {self.battery_settings.total_capacity} = {soc_change:.1f}%"
                    )
                else:
                    soc_change = 0
                    logger.info("No battery action, SOC change = 0%")

                # Calculate final SOC with constraints
                soc_percent = prev_soc + soc_change
                soc_percent = max(
                    self.battery_settings.min_soc, min(100.0, soc_percent)
                )

                logger.info(f"CURRENT HOUR {hour} CALCULATION:")
                logger.info(f"  Previous SOC: {prev_soc:.1f}%")
                logger.info(f"  Battery Action: {battery_action:.2f} kW")
                logger.info(f"  Battery Charged: {battery_charged:.2f} kWh")
                logger.info(f"  Battery Discharged: {battery_discharged:.2f} kWh")
                logger.info(f"  Charge Efficiency: {self.battery_settings.efficiency_charge:.3f}")
                logger.info(f"  Discharge Efficiency: {self.battery_settings.efficiency_discharge:.3f}")
                logger.info(f"  SOC Change: {soc_change:.1f}%")
                logger.info(f"  Final SOC: {soc_percent:.1f}%")
                logger.info("=== END CURRENT HOUR CALCULATION ===")

            else:
                # For predicted hours (not current), use the optimization SOC result
                soc_percent = hour_result.battery_soc_end

            # Determine SOC start using existing logic
            try:
                prev_soc_start = self._get_previous_hour_soc(hour)
            except ValueError as e:
                logger.warning(f"SOC bridge needed for hour {hour}: {e}")
                last_actual_hour, last_actual_soc = self._get_latest_hourly_soc()

                if hour > 0 and last_actual_hour >= 0:
                    logger.info(
                        f"Using SOC bridge from hour {last_actual_hour} ({last_actual_soc:.1f}%) to hour {hour}"
                    )

                    # Get efficiency values from input data if available
                    input_data = optimization_result.input_data
                    efficiency_charge = input_data.get(
                        "battery_charge_efficiency", 
                        self.battery_settings.efficiency_charge
                    )
                    efficiency_discharge = input_data.get(
                        "battery_discharge_efficiency", 
                        self.battery_settings.efficiency_discharge
                    )

                    # Calculate cumulative SOC changes for intervening hours
                    soc_change_total = 0
                    for bridge_hour in range(last_actual_hour + 1, hour):
                        bridge_index = bridge_hour - start_hour
                        if bridge_index < 0 or bridge_index >= len(hourly_data_list):
                            continue  # Skip hours outside optimization range

                        bridge_hour_result = hourly_data_list[bridge_index]
                        action = bridge_hour_result.battery_action or 0.0
                        
                        if action > 0:  # charging
                            # Charging: SOC increases by (input_energy x efficiency) ÷ capacity  
                            soc_change_total += (
                                action * efficiency_charge / self.battery_settings.total_capacity * 100
                            )
                        elif action < 0:  # discharging
                            # FIXED: Discharging: SOC decreases by (output_energy ÷ efficiency) ÷ capacity
                            # Since action is already negative, the result will be negative (SOC decrease)
                            soc_change_total += (
                                action / efficiency_discharge / self.battery_settings.total_capacity * 100
                            )
                        
                        logger.info(
                            f"Bridge hour {bridge_hour}: action={action:.2f} kW, "
                            f"efficiency_charge={efficiency_charge:.3f}, "
                            f"efficiency_discharge={efficiency_discharge:.3f}, "
                            f"cumulative_soc_change={soc_change_total:.2f}%"
                        )

                    prev_soc_start = min(100, max(0, last_actual_soc + soc_change_total))
                    logger.info(
                        f"SOC bridge calculation: {last_actual_soc:.1f}% + {soc_change_total:.1f}% = {prev_soc_start:.1f}%"
                    )
                else:
                    # If no prior actual data, use the SOC from optimization
                    if result_index > 0:
                        prev_hour_result = hourly_data_list[result_index - 1]
                        prev_soc_start = prev_hour_result.battery_soc_end
                    else:
                        prev_soc_start = optimization_result.input_data.get("initial_soc", 20.0)
                        
                    logger.info(
                        f"No actual data before hour {hour}, using optimization SOC: {prev_soc_start:.1f}%"
                    )

            # Create HourlyData for cost calculation
            hour_data = HourlyData(
                hour=hour,
                data_source="predicted",
                solar_generated=solar_production,
                home_consumed=home_consumption,
                grid_imported=grid_import,
                grid_exported=grid_export,
                battery_charged=battery_charged,
                battery_discharged=battery_discharged,
                buy_price=buy_price,
                sell_price=sell_price,
                battery_soc_start=prev_soc_start,
                battery_soc_end=soc_percent,
                battery_action=battery_action,
                strategic_intent=hour_result.strategic_intent or "IDLE",
                solar_to_home=hour_result.solar_to_home,
                solar_to_battery=hour_result.solar_to_battery,
                solar_to_grid=hour_result.solar_to_grid,
                grid_to_home=hour_result.grid_to_home,
                grid_to_battery=hour_result.grid_to_battery,
                battery_to_home=hour_result.battery_to_home,
                battery_to_grid=hour_result.battery_to_grid,
            )

            # Calculate costs using shared cost calculation logic and update the HourlyData object
            cost_results = calculate_hourly_costs(
                hour_data,
                self.battery_settings.cycle_cost_per_kwh,
                self.battery_settings.efficiency_charge,
                self.battery_settings.efficiency_discharge,
            )
            
            # Update the HourlyData object with cost results
            hour_data.hourly_cost = cost_results.battery_solar_cost
            hour_data.hourly_savings = cost_results.total_savings
            hour_data.battery_cycle_cost = cost_results.battery_wear_cost
            
            return hour_data

        except Exception as e:
            logger.error(
                f"Error building predicted data for hour {hour} ({latest_schedule.get_optimization_range()}): {e}"
            )
            raise ValueError(
                f"Error processing optimization data for hour {hour}: {e}"
            ) from e
        
    def _validate_energy_flows(self, hourly_data: list[HourlyData]) -> None:
        """Validate energy flows for physical consistency."""
        for hour_data in hourly_data:
            try:
                # Basic energy balance check
                solar = hour_data.solar_generated
                consumption = hour_data.home_consumed
                grid_import = hour_data.grid_imported
                grid_export = hour_data.grid_exported
                battery_charge = hour_data.battery_charged
                battery_discharge = hour_data.battery_discharged

                # Energy conservation: Solar + Grid Import + Battery Discharge = Home Consumption + Grid Export + Battery Charge
                energy_in = solar + grid_import + battery_discharge
                energy_out = consumption + grid_export + battery_charge

                energy_balance_error = abs(energy_in - energy_out)
                if energy_balance_error > 0.5:  # Allow for rounding errors
                    logger.warning(
                        "Hour %d: Energy balance error %.2f kWh (In: %.2f, Out: %.2f)",
                        hour_data.hour,
                        energy_balance_error,
                        energy_in,
                        energy_out,
                    )

                # FIXED SOC change validation with efficiency consideration
                soc_change = hour_data.battery_soc_end - hour_data.battery_soc_start

                # Calculate expected SOC change considering efficiency
                if battery_charge > 0 and battery_discharge > 0:
                    # Both charging and discharging in same hour (rare but possible)
                    charge_soc_change = (
                        battery_charge * self.battery_settings.efficiency_charge 
                        / self.battery_settings.total_capacity * 100
                    )
                    discharge_soc_change = (
                        battery_discharge / self.battery_settings.efficiency_discharge 
                        / self.battery_settings.total_capacity * 100
                    )
                    expected_soc_change = charge_soc_change - discharge_soc_change
                elif battery_charge > 0:
                    # Only charging
                    expected_soc_change = (
                        battery_charge * self.battery_settings.efficiency_charge 
                        / self.battery_settings.total_capacity * 100
                    )
                elif battery_discharge > 0:
                    # Only discharging  
                    expected_soc_change = -(
                        battery_discharge / self.battery_settings.efficiency_discharge 
                        / self.battery_settings.total_capacity * 100
                    )
                else:
                    # No battery action
                    expected_soc_change = 0.0

                soc_error = abs(soc_change - expected_soc_change)
                if soc_error > 2.0:  # Allow 2% error
                    logger.warning(
                        "Hour %d: SOC change mismatch %.1f%% vs expected %.1f%% (charge=%.2f, discharge=%.2f, eff_charge=%.3f, eff_discharge=%.3f)",
                        hour_data.hour,
                        soc_change,
                        expected_soc_change,
                        battery_charge,
                        battery_discharge,
                        self.battery_settings.efficiency_charge,
                        self.battery_settings.efficiency_discharge,
                    )

            except Exception as e:
                logger.warning(f"Validation error for hour {hour_data.hour}: {e}")

    def log_complete_daily_schedule(self, daily_view: DailyView) -> None:
        """Log complete 24-hour schedule table with total cost and SOC/SOE display."""

        lines = []
        lines.append("╔" + "=" * 127 + "╗")
        lines.append("║" + " " * 56 + "DAILY SCHEDULE" + " " * 57 + "║")
        lines.append(
            "╠═══════╦════════════╦═══════════════════════╦═══════════════════════╦══════════════════╦═══════════════════════════════════════╣"
        )
        lines.append(
            "║       ║            ║      Energy Input     ║     Energy Output     ║     Battery      ║        Costs & Savings                ║"
        )
        lines.append(
            "║  Hour ║  Buy/Sell  ╠═══════╦═══════╦═══════╬═══════╦═══════╦═══════╬════════╦═════════╬═══════╦═══════╦═══════╦═══════╦═══════╣"
        )
        lines.append(
            "║       ║   (SEK)    ║ Solar ║ Grid  ║Bat.Dis║ Home  ║ Export║Bat.Chg║ Intent ║ SOC/SOE ║  Base ║  Grid ║ B.Wear║ Total ║  Save ║"
        )
        lines.append(
            "║       ║            ║ (kWh) ║ (kWh) ║ (kWh) ║ (kWh) ║ (kWh) ║ (kWh) ║        ║  %/kWh  ║  Cost ║  Cost ║  Cost ║  Cost ║ (SEK) ║"
        )
        lines.append(
            "╠═══════╬════════════╬═══════╬═══════╬═══════╬═══════╬═══════╬═══════╬════════╬═════════╬═══════╬═══════╬═══════╬═══════╬═══════╣"
        )

        # Calculate totals
        total_consumption = 0.0
        total_solar = 0.0
        total_grid_import = 0.0
        total_grid_export = 0.0
        total_battery_charge = 0.0
        total_battery_discharge = 0.0
        total_base_cost = 0.0
        total_optimized_cost = 0.0
        total_battery_cost = 0.0
        total_cost = 0.0
        total_savings = 0.0

        # Split totals
        actual_consumption = 0.0
        actual_solar = 0.0
        actual_grid_import = 0.0
        actual_grid_export = 0.0
        actual_battery_charge = 0.0
        actual_battery_discharge = 0.0
        actual_base_cost = 0.0
        actual_optimized_cost = 0.0
        actual_battery_cost = 0.0
        actual_total_cost = 0.0
        actual_savings = 0.0

        predicted_consumption = 0.0
        predicted_solar = 0.0
        predicted_grid_import = 0.0
        predicted_grid_export = 0.0
        predicted_battery_charge = 0.0
        predicted_battery_discharge = 0.0
        predicted_base_cost = 0.0
        predicted_optimized_cost = 0.0
        predicted_battery_cost = 0.0
        predicted_total_cost = 0.0
        predicted_savings = 0.0

        for hour_data in daily_view.hourly_data:
            # Calculate base cost (grid-only scenario)
            base_cost = hour_data.home_consumed * hour_data.buy_price

            # Calculate total cost (grid + battery wear)
            hour_total_cost = hour_data.hourly_cost + hour_data.battery_cycle_cost

            # Mark current hour and predicted hours
            current_hour = datetime.now().hour
            if hour_data.data_source == "predicted":
                hour_marker = "★"
            elif hour_data.hour == current_hour:
                hour_marker = "*"
            else:
                hour_marker = " "

            # Format strategic intent (shortened to fit 8 chars)
            intent_short = (
                hour_data.strategic_intent[:8] if hour_data.strategic_intent else "IDLE"
            )

            # Format SOC/SOE display
            soe_kwh = (hour_data.battery_soc_end / 100.0) * self.battery_settings.total_capacity
            soc_soe_display = f"{hour_data.battery_soc_end:3.0f}/{soe_kwh:4.1f}"

            row = (
                f"║ {hour_data.hour:02d}:00{hour_marker}║ {hour_data.buy_price:4.2f}/ {hour_data.sell_price:4.2f} "
                f"║ {hour_data.solar_generated:5.1f} ║ {hour_data.grid_imported:5.1f} ║ {hour_data.battery_discharged:5.1f} ║"
                f" {hour_data.home_consumed:5.1f} ║ {hour_data.grid_exported:5.1f} ║ {hour_data.battery_charged:5.1f} ║"
                f"{intent_short:8}║{soc_soe_display:9}║{base_cost:6.2f} ║{hour_data.hourly_cost:6.2f} ║{hour_data.battery_cycle_cost:6.2f} ║{hour_total_cost:6.2f} ║{hour_data.hourly_savings:6.2f} ║"
            )
            lines.append(row)

            # Accumulate combined totals
            total_consumption += hour_data.home_consumed
            total_solar += hour_data.solar_generated
            total_grid_import += hour_data.grid_imported
            total_grid_export += hour_data.grid_exported
            total_battery_charge += hour_data.battery_charged
            total_battery_discharge += hour_data.battery_discharged
            total_base_cost += base_cost
            total_optimized_cost += hour_data.hourly_cost
            total_battery_cost += hour_data.battery_cycle_cost
            total_cost += hour_total_cost
            total_savings += hour_data.hourly_savings

            # Accumulate split totals
            if hour_data.data_source == "actual":
                actual_consumption += hour_data.home_consumed
                actual_solar += hour_data.solar_generated
                actual_grid_import += hour_data.grid_imported
                actual_grid_export += hour_data.grid_exported
                actual_battery_charge += hour_data.battery_charged
                actual_battery_discharge += hour_data.battery_discharged
                actual_base_cost += base_cost
                actual_optimized_cost += hour_data.hourly_cost
                actual_battery_cost += hour_data.battery_cycle_cost
                actual_total_cost += hour_total_cost
                actual_savings += hour_data.hourly_savings
            else:  # predicted
                predicted_consumption += hour_data.home_consumed
                predicted_solar += hour_data.solar_generated
                predicted_grid_import += hour_data.grid_imported
                predicted_grid_export += hour_data.grid_exported
                predicted_battery_charge += hour_data.battery_charged
                predicted_battery_discharge += hour_data.battery_discharged
                predicted_base_cost += base_cost
                predicted_optimized_cost += hour_data.hourly_cost
                predicted_battery_cost += hour_data.battery_cycle_cost
                predicted_total_cost += hour_total_cost
                predicted_savings += hour_data.hourly_savings

        # Totals row
        lines.append(
            "╠═══════╬════════════╬═══════╬═══════╬═══════╬═══════╬═══════╬═══════╬════════╬═════════╬═══════╬═══════╬═══════╬═══════╬═══════╣"
        )
        lines.append(
            f"║ TOTAL ║            ║ {total_solar:5.1f} ║ {total_grid_import:5.1f} ║ {total_battery_discharge:5.1f} ║"
            f" {total_consumption:5.1f} ║ {total_grid_export:5.1f} ║ {total_battery_charge:5.1f} ║        ║         ║"
            f"{total_base_cost:6.2f} ║{total_optimized_cost:6.2f} ║{total_battery_cost:6.2f} ║{total_cost:6.2f} ║{total_savings:6.2f} ║"
        )
        lines.append(
            "╚═══════╩════════════╩═══════╩═══════╩═══════╩═══════╩═══════╩════════╩═══════╩═════════╩═══════╩═══════╩═══════╩═══════╩═══════╝"
        )

        # Enhanced Summary
        savings_percent = (
            (total_savings / total_base_cost * 100) if total_base_cost > 0 else 0
        )
        actual_savings_percent = (
            (actual_savings / actual_base_cost * 100) if actual_base_cost > 0 else 0
        )
        predicted_savings_percent = (
            (predicted_savings / predicted_base_cost * 100)
            if predicted_base_cost > 0
            else 0
        )

        lines.append("      Summary:")
        lines.append(
            f"      Base case cost:           {total_base_cost:8.2f} SEK  (Actual: {actual_base_cost:6.2f} + Predicted: {predicted_base_cost:6.2f})"
        )
        lines.append(
            f"      Grid cost:                {total_optimized_cost:8.2f} SEK  (Actual: {actual_optimized_cost:6.2f} + Predicted: {predicted_optimized_cost:6.2f})"
        )
        lines.append(
            f"      Battery wear cost:        {total_battery_cost:8.2f} SEK  (Actual: {actual_battery_cost:6.2f} + Predicted: {predicted_battery_cost:6.2f})"
        )
        lines.append(
            f"      Total cost:               {total_cost:8.2f} SEK  (Actual: {actual_total_cost:6.2f} + Predicted: {predicted_total_cost:6.2f})"
        )
        lines.append(
            f"      Total savings:            {total_savings:8.2f} SEK  (Actual: {actual_savings:6.2f} + Predicted: {predicted_savings:6.2f})"
        )
        lines.append(
            f"      Savings percentage:         {savings_percent:6.1f} %    (Actual: {actual_savings_percent:5.1f}% + Predicted: {predicted_savings_percent:5.1f}%)"
        )
        lines.append(
            f"      Actual hours: {daily_view.actual_hours_count}, Predicted hours: {daily_view.predicted_hours_count}"
        )
        lines.append("      * = current hour | ★ = predicted hours")

        logger.info("\n%s", "\n".join(lines))

    def _get_list_item(self, data_list: list | None, index: int, field_name: str, default=None) -> float:
        """Get item from a list with proper error handling.
        
        Args:
            data_list: List to extract from
            index: Index to extract
            field_name: Name of field for error reporting
            default: Default value if extraction fails and default is not None
        
        Returns:
            float: Value from list or default
            
        Raises:
            ValueError if list is None or index out of bounds and no default is provided
        """
        if data_list is None:
            if default is not None:
                return default
            raise ValueError(f"Missing {field_name} list in schedule")
        
        if not isinstance(data_list, list):
            if default is not None:
                return default
            raise ValueError(f"{field_name} is not a list: {type(data_list)}")
        
        if not 0 <= index < len(data_list):
            if default is not None:
                return default
            raise ValueError(
                f"{field_name} index {index} out of bounds (0-{len(data_list)-1})"
            )
        
        value = data_list[index]
        if value is None:
            if default is not None:
                return default
            raise ValueError(f"{field_name}[{index}] is None")
        
        try:
            return float(value)
        except (ValueError, TypeError) as e:
            if default is not None:
                return default
            raise ValueError(f"Error parsing {field_name}[{index}]: {e}") from e

    def _get_previous_hour_soc(self, hour: int) -> float:
        """Get the start SOC for an hour from the ending SOC of the previous hour.
        
        Args:
            hour: Hour to get the starting SOC for
            
        Returns:
            float: Starting SOC percentage (0-100)
            
        Raises:
            ValueError if previous hour data is not available
        """
        if hour == 0:
            # Hour 0 needs special handling - get from latest schedule
            latest_schedule = self.schedule_store.get_latest_schedule()
            if latest_schedule and latest_schedule.optimization_result.input_data and "initial_soc" in latest_schedule.optimization_result.input_data:
                return latest_schedule.optimization_result.input_data["initial_soc"]
            else:
                # Default fallback (should not happen with validation)
                raise ValueError("Cannot determine SOC for hour 0 - no initial_soc in schedule")
        else:
            # For hours 1-23, get from previous hour's ending SOC
            prev_hour = hour - 1
            prev_data = self.historical_store.get_hour_event(prev_hour)
            
            if prev_data:
                # Found previous hour in historical data
                return prev_data.battery_soc_end
            else:
                # If no historical data, we need to calculate from the schedule
                raise ValueError(f"No historical data for hour {prev_hour}, need to use schedule SOC")