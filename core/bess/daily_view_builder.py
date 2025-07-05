"""
DailyViewBuilder - Creates complete 00-23 daily views combining actuals + predictions.

This module provides the DailyViewBuilder class that combines historical actual
data with current predictions to always provide a complete 24-hour view for
the UI and API. It also recalculates total daily savings from the combined data.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from core.bess.dp_battery_algorithm import calculate_hourly_costs
from core.bess.models import DecisionData, EconomicData, EnergyData, HourlyData

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
            raise ValueError("No optimization schedule available - system cannot provide daily view")

        (schedule_start_hour, schedule_end_hour,) = latest_schedule.get_optimization_range()
        logger.info(f"Latest schedule covers hours {schedule_start_hour}-{schedule_end_hour}")

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

        # Build complete 24-hour view
        hourly_data = []
        data_sources = []

        for hour in range(24):
            if hour < current_hour:
                hour_data = self._build_actual_hour_data(hour, buy_price[hour], sell_price[hour])
                data_sources.append("actual")
            else:
                hour_data = self._build_predicted_hour_data(hour, buy_price[hour], sell_price[hour], current_hour)
                data_sources.append("predicted")

            hourly_data.append(hour_data)

        # Sort and validate 
        hourly_data.sort(key=lambda x: x.hour)
        self._validate_energy_flows_new(hourly_data)

        # Calculate metrics 
        actual_savings = sum(
            h.economic.hourly_savings for h in hourly_data 
            if h.data_source == "actual" and h.economic.hourly_savings is not None
        )
        predicted_savings = sum(
            h.economic.hourly_savings for h in hourly_data 
            if h.data_source == "predicted" and h.economic.hourly_savings is not None
        )

        daily_view = DailyView(
            date=datetime.now(),
            current_hour=current_hour,
            hourly_data=hourly_data,
            total_daily_savings=actual_savings + predicted_savings,
            actual_savings_so_far=actual_savings,
            predicted_remaining_savings=predicted_savings,
            actual_hours_count=len([h for h in hourly_data if h.data_source == "actual"]),
            predicted_hours_count=len([h for h in hourly_data if h.data_source == "predicted"]),
            data_sources=data_sources,
        )

        self.log_complete_daily_schedule(daily_view)
        return daily_view


    def _validate_energy_flows_new(self, hourly_data: list[HourlyData]) -> None:
        """Validate energy flows for physical consistency """
        for hour_data in hourly_data:
            try:
                # Energy balance validation logic 
                solar = hour_data.energy.solar_generated
                consumption = hour_data.energy.home_consumed
                grid_import = hour_data.energy.grid_imported
                grid_export = hour_data.energy.grid_exported
                battery_charge = hour_data.energy.battery_charged
                battery_discharge = hour_data.energy.battery_discharged

                # All validation logic (unchanged calculations)
                total_generation = solar + grid_import + battery_discharge
                total_consumption = consumption + grid_export + battery_charge
                balance_error = abs(total_generation - total_consumption)
                
                if balance_error > 0.1:  # Allow 0.1 kWh error
                    logger.warning(
                        "Hour %d: Energy balance error %.2f kWh (gen=%.2f, cons=%.2f)",
                        hour_data.hour, balance_error, total_generation, total_consumption
                    )

                # SOC validation logic 
                soc_start = hour_data.energy.battery_soc_start
                soc_end = hour_data.energy.battery_soc_end
                soc_change = soc_end - soc_start

                # All SOC validation calculations (unchanged)
                if battery_charge > 0:
                    expected_soc_change = (
                        battery_charge * self.battery_settings.efficiency_charge 
                        / self.battery_settings.total_capacity * 100
                    )
                elif battery_discharge > 0:
                    expected_soc_change = -(
                        battery_discharge / self.battery_settings.efficiency_discharge 
                        / self.battery_settings.total_capacity * 100
                    )
                else:
                    expected_soc_change = 0.0

                soc_error = abs(soc_change - expected_soc_change)
                if soc_error > 2.0:  # Allow 2% error
                    logger.warning(
                        "Hour %d: SOC change mismatch %.1f%% vs expected %.1f%% (charge=%.2f, discharge=%.2f, eff_charge=%.3f, eff_discharge=%.3f)",
                        hour_data.hour, soc_change, expected_soc_change, battery_charge, battery_discharge,
                        self.battery_settings.efficiency_charge, self.battery_settings.efficiency_discharge,
                    )

            except Exception as e:
                logger.warning(f"Validation error for hour {hour_data.hour}: {e}")


    def _build_actual_hour_data(
        self, hour: int, buy_price: float, sell_price: float
    ) -> HourlyData:
        """Build hour data from actual stored facts """
        
        event = self.historical_store.get_hour_record(hour)
        if not event:
            raise ValueError(f"No data for hour {hour} - validation should prevent this")

        battery_action = event.energy.battery_charged - event.energy.battery_discharged

        updated_decision = DecisionData(
            strategic_intent=event.decision.strategic_intent,
            battery_action=battery_action
        )
        
        new_hourly_data = HourlyData(
            hour=event.hour,
            energy=event.energy,
            timestamp=event.timestamp,
            data_source="actual",
            economic=EconomicData(
                buy_price=buy_price,
                sell_price=sell_price,
                hourly_cost=0.0,
                hourly_savings=0.0,
                battery_cycle_cost=0.0
            ),
            decision=updated_decision
        )

        # calculate_hourly_costs accepts HourlyData directly
        costs = calculate_hourly_costs( # TODO: Change signature of function so we dont need this bizarre temp object to calculate costs
            new_hourly_data, 
            self.battery_settings.cycle_cost_per_kwh,
            self.battery_settings.efficiency_charge,
            self.battery_settings.efficiency_discharge
        )
        
        final_economic = EconomicData(
            buy_price=buy_price,
            sell_price=sell_price,
            hourly_cost=costs.battery_solar_cost,
            hourly_savings=costs.total_savings,
            battery_cycle_cost=costs.battery_wear_cost,
            solar_only_cost=costs.solar_only_cost, 
        )
        
        return HourlyData(
            hour=event.hour,
            energy=event.energy,
            timestamp=event.timestamp,
            data_source="actual",
            economic=final_economic,
            decision=updated_decision
        )


    def _get_latest_hourly_soc(self) -> tuple[int, float]:
        """Get the hour and SOC of the most recent actual data point"""
        
        # Iterate backwards logic 
        for hour in range(23, -1, -1):
            event = self.historical_store.get_hour_record(hour)
            if event:
                return hour, event.energy.battery_soc_end

        # Fallback to initial SOC from schedule
        latest_schedule = self.schedule_store.get_latest_schedule()
        if latest_schedule and latest_schedule.optimization_result.input_data:
            initial_soc = latest_schedule.optimization_result.input_data.get("initial_soc")
            if initial_soc is not None:
                return -1, initial_soc

        # Error instead of default (no fallbacks per instructions)
        raise ValueError("No actual battery state data available and no initial SOC in schedule")


    def _build_predicted_hour_data(
        self, hour: int, buy_price: float, sell_price: float, current_hour: int
    ) -> HourlyData:
        """Build hour data from predicted schedule data - HourlyData only."""
        
        latest_schedule = self.schedule_store.get_latest_schedule()
        if latest_schedule is None:
            raise ValueError(f"No schedule available for hour {hour}, cannot create deterministic view")

        start_hour, end_hour = latest_schedule.get_optimization_range()
        if not (start_hour <= hour <= end_hour):
            raise ValueError(
                f"Latest schedule doesn't cover hour {hour} (range {start_hour}-{end_hour}), cannot create deterministic view"
            )

        try:
            optimization_result = latest_schedule.optimization_result
            hourly_data_list = optimization_result.hourly_data
            result_index = hour - start_hour
            
            if result_index < 0 or result_index >= len(hourly_data_list):
                raise ValueError(f"Hour {hour} is out of range in optimization result (index {result_index})")
            
            hour_result = hourly_data_list[result_index]
            
            battery_action = hour_result.decision.battery_action or 0.0
            solar_production = hour_result.energy.solar_generated
            home_consumption = hour_result.energy.home_consumed
            grid_import = hour_result.energy.grid_imported
            grid_export = hour_result.energy.grid_exported
            
            max_possible_action = self.battery_settings.total_capacity
            if abs(battery_action) > max_possible_action:
                logger.warning(
                    f"Battery action for hour {hour} exceeds physical limits: {battery_action:.2f} kWh. "
                    f"Capping to {max_possible_action:.2f} kWh"
                )
                battery_action = max(-max_possible_action, min(max_possible_action, battery_action))

            battery_charged = max(0, battery_action)
            battery_discharged = max(0, -battery_action)
            
            if abs(battery_action) > 0.01:
                reconstructed_action = battery_charged - battery_discharged
                action_error = abs(battery_action - reconstructed_action)
                if action_error > 0.01:
                    logger.warning(
                        f"Hour {hour}: Battery action inconsistency - "
                        f"original={battery_action:.3f} kW, "
                        f"reconstructed={reconstructed_action:.3f} kW, "
                        f"error={action_error:.3f} kW"
                    )

            if hour == current_hour:
                logger.info(f"=== CURRENT HOUR {hour} SOC CALCULATION ===")

                if hour == 0:
                    prev_soc = optimization_result.input_data.get("initial_soc", 20.0)
                    logger.info(f"Hour 0: Using initial SOC from schedule: {prev_soc:.1f}%")
                else:
                    prev_event = self.historical_store.get_hour_record(hour - 1)
                    if prev_event:
                        prev_soc = prev_event.energy.battery_soc_end
                        logger.info(f"Using actual SOC from hour {hour-1}: {prev_soc:.1f}%")
                    else:
                        prev_soc = hour_result.energy.battery_soc_start
                        logger.warning(
                            f"No historical data for hour {hour-1}, using optimization SOC: {prev_soc:.1f}%"
                        )

                prev_soc_start = prev_soc
            else:
                prev_soc_start = hour_result.energy.battery_soc_start

            soc_percent = hour_result.energy.battery_soc_end

            energy_data = EnergyData(
                solar_generated=solar_production,
                home_consumed=home_consumption,
                grid_imported=grid_import,
                grid_exported=grid_export,
                battery_charged=battery_charged,
                battery_discharged=battery_discharged,
                battery_soc_start=prev_soc_start,
                battery_soc_end=soc_percent,
                solar_to_home=hour_result.energy.solar_to_home,
                solar_to_battery=hour_result.energy.solar_to_battery,
                solar_to_grid=hour_result.energy.solar_to_grid,
                grid_to_home=hour_result.energy.grid_to_home,
                grid_to_battery=hour_result.energy.grid_to_battery,
                battery_to_home=hour_result.energy.battery_to_home,
                battery_to_grid=hour_result.energy.battery_to_grid,
            )

            decision_data = DecisionData(
                strategic_intent=hour_result.decision.strategic_intent or "IDLE",
                battery_action=battery_action
            )

            new_hourly_data = HourlyData(
                hour=hour,
                energy=energy_data,
                timestamp=hour_result.timestamp,
                data_source="predicted",
                economic=EconomicData(
                    buy_price=buy_price,
                    sell_price=sell_price,
                    hourly_cost=0.0,
                    hourly_savings=0.0,
                    battery_cycle_cost=0.0
                ),
                decision=decision_data
            )

            # calculate_hourly_costs accepts HourlyData directly
            cost_results = calculate_hourly_costs(
                new_hourly_data,
                self.battery_settings.cycle_cost_per_kwh,
                self.battery_settings.efficiency_charge,
                self.battery_settings.efficiency_discharge,
            )
            
            final_economic_data = EconomicData(
                buy_price=buy_price,
                sell_price=sell_price,
                hourly_cost=cost_results.battery_solar_cost,
                hourly_savings=cost_results.total_savings,
                battery_cycle_cost=cost_results.battery_wear_cost
            )
            
            return HourlyData(
                hour=hour,
                energy=energy_data,
                timestamp=hour_result.timestamp,
                data_source="predicted",
                economic=final_economic_data,
                decision=decision_data
            )

        except Exception as e:
            logger.error(f"Error building predicted data for hour {hour} ({latest_schedule.get_optimization_range()}): {e}")
            raise ValueError(f"Error processing optimization data for hour {hour}: {e}") from e

        
    def _validate_energy_flows(self, hourly_data: list[HourlyData]) -> None:
        """Validate energy flows for physical consistency."""
        for hour_data in hourly_data:
            try:
                # Basic energy balance check
                solar = hour_data.energy.solar_generated
                consumption = hour_data.energy.home_consumed
                grid_import = hour_data.energy.grid_imported
                grid_export = hour_data.energy.grid_exported
                battery_charge = hour_data.energy.battery_charged
                battery_discharge = hour_data.energy.battery_discharged

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
        """Log complete 24-hour schedule table - HourlyData access."""
        lines = []
        
        # All header formatting
        lines.append("╔═══════╦════════════╦═══════╦═══════╦═══════╦═══════╦═══════╦═══════╦════════╦═════════╦═══════╦═══════╦═══════╦═══════╦═══════╗")
        lines.append("║ Hour  ║   Prices   ║      Solar    ║ Grid  ║ Batt  ║ Home  ║ Grid  ║ Batt  ║Intent  ║SOC/SOE  ║ Base  ║Grid+  ║ Batt  ║ Total ║Savings║")
        lines.append("║       ║ Buy/Sell   ║   Generated   ║Import ║Dischg ║ Cons  ║Export ║Charge ║        ║  %/kWh  ║ Cost  ║Solar  ║ Wear  ║ Cost  ║  SEK  ║")
        lines.append("╠═══════╬════════════╬═══════╬═══════╬═══════╬═══════╬═══════╬═══════╬════════╬═════════╬═══════╬═══════╬═══════╬═══════╬═══════╣")

        # Initialize all accumulation variables
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

        # Split totals for actual vs predicted
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
            # Calculate base cost 
            base_cost = hour_data.energy.home_consumed * hour_data.economic.buy_price

            # Calculate total cost 
            hour_total_cost = hour_data.economic.hourly_cost + hour_data.economic.battery_cycle_cost

            # Mark current hour and predicted hours
            current_hour = datetime.now().hour
            if hour_data.data_source == "predicted":
                hour_marker = "★"
            elif hour_data.hour == current_hour:
                hour_marker = "*"
            else:
                hour_marker = " "

            # Format strategic intent 
            intent_short = (
                hour_data.decision.strategic_intent[:8] if hour_data.decision.strategic_intent else "IDLE"
            )

            # Format SOC/SOE display 
            soe_kwh = (hour_data.energy.battery_soc_end / 100.0) * self.battery_settings.total_capacity
            soc_soe_display = f"{hour_data.energy.battery_soc_end:3.0f}/{soe_kwh:4.1f}"

            # Row formatting 
            row = (
                f"║ {hour_data.hour:02d}:00{hour_marker}║ {hour_data.economic.buy_price:4.2f}/ {hour_data.economic.sell_price:4.2f} "
                f"║ {hour_data.energy.solar_generated:5.1f} ║ {hour_data.energy.grid_imported:5.1f} ║ {hour_data.energy.battery_discharged:5.1f} ║"
                f" {hour_data.energy.home_consumed:5.1f} ║ {hour_data.energy.grid_exported:5.1f} ║ {hour_data.energy.battery_charged:5.1f} ║"
                f"{intent_short:8}║{soc_soe_display:9}║{base_cost:6.2f} ║{hour_data.economic.hourly_cost:6.2f} ║{hour_data.economic.battery_cycle_cost:6.2f} ║{hour_total_cost:6.2f} ║{hour_data.economic.hourly_savings:6.2f} ║"
            )
            lines.append(row)

            # Accumulate combined totals 
            total_consumption += hour_data.energy.home_consumed
            total_solar += hour_data.energy.solar_generated
            total_grid_import += hour_data.energy.grid_imported
            total_grid_export += hour_data.energy.grid_exported
            total_battery_charge += hour_data.energy.battery_charged
            total_battery_discharge += hour_data.energy.battery_discharged
            total_base_cost += base_cost
            total_optimized_cost += hour_data.economic.hourly_cost
            total_battery_cost += hour_data.economic.battery_cycle_cost
            total_cost += hour_total_cost
            total_savings += hour_data.economic.hourly_savings

            # Accumulate split totals 
            if hour_data.data_source == "actual":
                actual_consumption += hour_data.energy.home_consumed
                actual_solar += hour_data.energy.solar_generated
                actual_grid_import += hour_data.energy.grid_imported
                actual_grid_export += hour_data.energy.grid_exported
                actual_battery_charge += hour_data.energy.battery_charged
                actual_battery_discharge += hour_data.energy.battery_discharged
                actual_base_cost += base_cost
                actual_optimized_cost += hour_data.economic.hourly_cost
                actual_battery_cost += hour_data.economic.battery_cycle_cost
                actual_total_cost += hour_total_cost
                actual_savings += hour_data.economic.hourly_savings
            else:  # predicted
                predicted_consumption += hour_data.energy.home_consumed
                predicted_solar += hour_data.energy.solar_generated
                predicted_grid_import += hour_data.energy.grid_imported
                predicted_grid_export += hour_data.energy.grid_exported
                predicted_battery_charge += hour_data.energy.battery_charged
                predicted_battery_discharge += hour_data.energy.battery_discharged
                predicted_base_cost += base_cost
                predicted_optimized_cost += hour_data.economic.hourly_cost
                predicted_battery_cost += hour_data.economic.battery_cycle_cost
                predicted_total_cost += hour_total_cost
                predicted_savings += hour_data.economic.hourly_savings

        # All remaining table formatting and logging (unchanged)
        lines.append(
            "╠═══════╬════════════╬═══════╬═══════╬═══════╬═══════╬═══════╬═══════╬════════╬═════════╬═══════╬═══════╬═══════╬═══════╬═══════╣"
        )
        lines.append(
            f"║ TOTAL ║            ║ {total_solar:5.1f} ║ {total_grid_import:5.1f} ║ {total_battery_discharge:5.1f} ║"
            f" {total_consumption:5.1f} ║ {total_grid_export:5.1f} ║ {total_battery_charge:5.1f} ║        ║         ║"
            f"{total_base_cost:6.2f} ║{total_optimized_cost:6.2f} ║{total_battery_cost:6.2f} ║{total_cost:6.2f} ║{total_savings:6.2f} ║"
        )
        lines.append(
            "╚═══════╩════════════╩═══════╩═══════╩═══════╩═══════╩═══════╩═══════╩════════╩═════════╩═══════╩═══════╩═══════╩═══════╩═══════╝"
        )

        # Log all lines
        for line in lines:
            logger.info(line)

        # Log summary statistics
        logger.info(f"Daily energy summary: {total_solar:.1f} kWh solar, {total_consumption:.1f} kWh consumption, "
                   f"{total_battery_charge:.1f} kWh charged, {total_battery_discharge:.1f} kWh discharged")
        logger.info(f"Daily cost summary: {total_base_cost:.2f} SEK base, {total_cost:.2f} SEK optimized, "
                   f"{total_savings:.2f} SEK savings")
        logger.info(f"Actual vs Predicted: {daily_view.actual_hours_count} actual hours ({actual_savings:.2f} SEK), "
                   f"{daily_view.predicted_hours_count} predicted hours ({predicted_savings:.2f} SEK)")

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
            prev_data = self.historical_store.get_hour_record(prev_hour)
            
            if prev_data:
                # Found previous hour in historical data
                return prev_data.battery_soc_end
            else:
                # If no historical data, we need to calculate from the schedule
                raise ValueError(f"No historical data for hour {prev_hour}, need to use schedule SOC")