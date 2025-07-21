"""
DailyViewBuilder - Creates complete 00-23 daily views combining actuals + predictions.

This module provides the DailyViewBuilder class that combines historical actual
data with current predictions to always provide a complete 24-hour view for
the UI and API. It also recalculates total daily savings from the combined data.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

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

        # Build complete 24-hour view
        hourly_data = []
        data_sources = []

        for hour in range(24):
            if hour < current_hour:
                hour_data = self._build_actual_hour_data(
                    hour, buy_price[hour], sell_price[hour]
                )
                data_sources.append("actual")
            else:
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
            h.economic.hourly_savings
            for h in hourly_data
            if h.data_source == "actual" and h.economic.hourly_savings is not None
        )
        predicted_savings = sum(
            h.economic.hourly_savings
            for h in hourly_data
            if h.data_source == "predicted" and h.economic.hourly_savings is not None
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

    def _validate_energy_flows(self, hourly_data: list[HourlyData]) -> None:
        """Validate energy flows for physical consistency"""
        for hour_data in hourly_data:
            try:
                # Energy balance validation logic
                solar = hour_data.energy.solar_production
                consumption = hour_data.energy.home_consumption
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
                        hour_data.hour,
                        balance_error,
                        total_generation,
                        total_consumption,
                    )

                # SOC validation logic
                # Convert SOE to SOC for display
                soc_start = (
                    hour_data.energy.battery_soe_start
                    / self.battery_settings.total_capacity
                ) * 100.0
                soc_end = (
                    hour_data.energy.battery_soe_end
                    / self.battery_settings.total_capacity
                ) * 100.0
                soc_change = soc_end - soc_start

                # All SOC validation calculations (unchanged)
                if battery_charge > 0:
                    expected_soc_change = (
                        battery_charge
                        * self.battery_settings.efficiency_charge
                        / self.battery_settings.total_capacity
                        * 100
                    )
                elif battery_discharge > 0:
                    expected_soc_change = -(
                        battery_discharge
                        / self.battery_settings.efficiency_discharge
                        / self.battery_settings.total_capacity
                        * 100
                    )
                else:
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

    def _build_actual_hour_data(
        self, hour: int, buy_price: float, sell_price: float
    ) -> HourlyData:
        """Build hour data from actual stored facts with properly calculated economic data."""

        event = self.historical_store.get_hour_record(hour)
        if not event:
            raise ValueError(
                f"No data for hour {hour} - validation should prevent this"
            )

        battery_action = event.energy.battery_charged - event.energy.battery_discharged

        updated_decision = DecisionData(
            strategic_intent=event.decision.strategic_intent,
            battery_action=battery_action,
        )

        # Calculate economic data manually since actual data doesn't store it
        # This is what the optimization would have calculated for this hour

        # Grid cost (net cost of grid interactions)
        grid_cost = (
            event.energy.grid_imported * buy_price
            - event.energy.grid_exported * sell_price
        )

        # Battery wear cost (only for charging, not discharging)
        battery_wear_cost = (
            event.energy.battery_charged * self.battery_settings.cycle_cost_per_kwh
        )

        # Total hourly cost = grid cost + battery wear cost
        battery_solar_cost = grid_cost + battery_wear_cost

        # Grid-only cost (no solar, no battery - just grid import for all consumption)
        grid_only_cost = event.energy.home_consumption * buy_price

        # Solar-only cost (solar + grid, no battery)
        direct_solar_to_home = min(
            event.energy.solar_production, event.energy.home_consumption
        )
        solar_excess = max(0, event.energy.solar_production - direct_solar_to_home)
        grid_needed = max(0, event.energy.home_consumption - direct_solar_to_home)

        solar_only_cost = (
            grid_needed * buy_price  # Pay for grid imports
            - solar_excess * sell_price  # Revenue from solar exports
        )

        # Calculate savings vs solar-only baseline (algorithm baseline)
        hourly_savings = grid_only_cost - solar_only_cost

        final_economic = EconomicData(
            buy_price=buy_price,
            sell_price=sell_price,
            grid_cost=grid_cost,  # FIXED: Set the separate grid cost field
            hourly_cost=battery_solar_cost,  # FIXED: Use correct field name
            hourly_savings=hourly_savings,  # FIXED: Use correct field name
            battery_cycle_cost=battery_wear_cost,
            grid_only_cost=grid_only_cost,
            solar_only_cost=solar_only_cost,
        )

        return HourlyData(
            hour=event.hour,
            energy=event.energy,
            timestamp=event.timestamp,
            data_source="actual",
            economic=final_economic,
            decision=updated_decision,
        )

    def _get_latest_hourly_soc(self) -> tuple[int, float]:
        """Get the hour and SOC of the most recent actual data point"""

        # Iterate backwards logic
        for hour in range(23, -1, -1):
            event = self.historical_store.get_hour_record(hour)
            if event:
                # Convert SOE to SOC for display
                soc_end = (
                    event.energy.battery_soe_end / self.battery_settings.total_capacity
                ) * 100.0
                return hour, soc_end

        # Fallback to initial SOC from schedule
        latest_schedule = self.schedule_store.get_latest_schedule()
        if latest_schedule and latest_schedule.optimization_result.input_data:
            initial_soc = latest_schedule.optimization_result.input_data.get(
                "initial_soc"
            )
            if initial_soc is not None:
                return -1, initial_soc

        # Error instead of default (no fallbacks per instructions)
        raise ValueError(
            "No actual battery state data available and no initial SOC in schedule"
        )

    def _build_predicted_hour_data(
        self, hour: int, buy_price: float, sell_price: float, current_hour: int
    ) -> HourlyData:
        """Build hour data from predicted schedule data - use optimization result as-is."""

        latest_schedule = self.schedule_store.get_latest_schedule()
        if latest_schedule is None:
            raise ValueError(
                f"No schedule available for hour {hour}, cannot create deterministic view"
            )

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
                raise ValueError(
                    f"Hour {hour} is out of range in optimization result (index {result_index})"
                )

            hour_result = hourly_data_list[result_index]

            # Just return the optimization result as-is
            # The optimization algorithm produced a coherent, mathematically consistent result
            return hour_result

        except Exception as e:
            logger.error(
                f"Error building predicted data for hour {hour} ({latest_schedule.get_optimization_range()}): {e}"
            )
            raise ValueError(
                f"Error processing optimization data for hour {hour}: {e}"
            ) from e

    def log_complete_daily_schedule(self, daily_view: DailyView) -> None:
        """Log complete 24-hour schedule table - HourlyData access."""
        lines = []

        # All header formatting
        lines.append(
            "╔═══════╦════════════╦═══════╦═══════╦═══════╦═══════╦═══════╦═══════╦════════╦═════════╦═══════╦═══════╦═══════╦═══════╦═══════╗"
        )
        lines.append(
            "║ Hour  ║   Prices   ║      Solar    ║ Grid  ║ Batt  ║ Home  ║ Grid  ║ Batt  ║Intent  ║SOC/SOE  ║ Base  ║Grid+  ║ Batt  ║ Total ║Savings║"
        )
        lines.append(
            "║       ║ Buy/Sell   ║   Generated   ║Import ║Dischg ║ Cons  ║Export ║Charge ║        ║  %/kWh  ║ Cost  ║Solar  ║ Wear  ║ Cost  ║  SEK  ║"
        )
        lines.append(
            "╠═══════╬════════════╬═══════╬═══════╬═══════╬═══════╬═══════╬═══════╬════════╬═════════╬═══════╬═══════╬═══════╬═══════╬═══════╣"
        )

        # Initialize all accumulation variables
        total_consumption = 0.0
        total_solar = 0.0
        total_grid_import = 0.0
        total_grid_export = 0.0
        total_battery_charge = 0.0
        total_battery_discharge = 0.0
        total_grid_only_cost = 0.0
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
        actual_grid_only_cost = 0.0
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
        predicted_grid_only_cost = 0.0
        predicted_optimized_cost = 0.0
        predicted_battery_cost = 0.0
        predicted_total_cost = 0.0
        predicted_savings = 0.0

        for hour_data in daily_view.hourly_data:
            # Use pre-calculated grid-only cost instead of recalculating
            grid_only_cost = hour_data.economic.grid_only_cost

            # Calculate total cost - hourly_cost already includes battery wear cost
            hour_total_cost = hour_data.economic.hourly_cost

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
                hour_data.decision.strategic_intent[:8]
                if hour_data.decision.strategic_intent
                else "IDLE"
            )

            # Format SOC/SOE display
            soe_kwh = hour_data.energy.battery_soe_end
            soc_percent = (soe_kwh / self.battery_settings.total_capacity) * 100.0
            soc_soe_display = f"{soc_percent:3.0f}/{soe_kwh:4.1f}"

            # Row formatting
            row = (
                f"║ {hour_data.hour:02d}:00{hour_marker}║ {hour_data.economic.buy_price:4.2f}/ {hour_data.economic.sell_price:4.2f} "
                f"║ {hour_data.energy.solar_production:5.1f} ║ {hour_data.energy.grid_imported:5.1f} ║ {hour_data.energy.battery_discharged:5.1f} ║"
                f" {hour_data.energy.home_consumption:5.1f} ║ {hour_data.energy.grid_exported:5.1f} ║ {hour_data.energy.battery_charged:5.1f} ║"
                f"{intent_short:8}║{soc_soe_display:9}║{grid_only_cost:6.2f} ║{hour_data.economic.hourly_cost:6.2f} ║{hour_data.economic.battery_cycle_cost:6.2f} ║{hour_total_cost:6.2f} ║{hour_data.economic.hourly_savings:6.2f} ║"
            )
            lines.append(row)

            # Accumulate combined totals
            total_consumption += hour_data.energy.home_consumption
            total_solar += hour_data.energy.solar_production
            total_grid_import += hour_data.energy.grid_imported
            total_grid_export += hour_data.energy.grid_exported
            total_battery_charge += hour_data.energy.battery_charged
            total_battery_discharge += hour_data.energy.battery_discharged
            total_grid_only_cost += grid_only_cost
            total_optimized_cost += hour_data.economic.hourly_cost
            total_battery_cost += hour_data.economic.battery_cycle_cost
            total_cost += hour_total_cost
            total_savings += hour_data.economic.hourly_savings

            # Accumulate split totals
            if hour_data.data_source == "actual":
                actual_consumption += hour_data.energy.home_consumption
                actual_solar += hour_data.energy.solar_production
                actual_grid_import += hour_data.energy.grid_imported
                actual_grid_export += hour_data.energy.grid_exported
                actual_battery_charge += hour_data.energy.battery_charged
                actual_battery_discharge += hour_data.energy.battery_discharged
                actual_grid_only_cost += grid_only_cost
                actual_optimized_cost += hour_data.economic.hourly_cost
                actual_battery_cost += hour_data.economic.battery_cycle_cost
                actual_total_cost += hour_total_cost
                actual_savings += hour_data.economic.hourly_savings
            else:  # predicted
                predicted_consumption += hour_data.energy.home_consumption
                predicted_solar += hour_data.energy.solar_production
                predicted_grid_import += hour_data.energy.grid_imported
                predicted_grid_export += hour_data.energy.grid_exported
                predicted_battery_charge += hour_data.energy.battery_charged
                predicted_battery_discharge += hour_data.energy.battery_discharged
                predicted_grid_only_cost += grid_only_cost
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
            f"{total_grid_only_cost:6.2f} ║{total_optimized_cost:6.2f} ║{total_battery_cost:6.2f} ║{total_cost:6.2f} ║{total_savings:6.2f} ║"
        )
        lines.append(
            "╚═══════╩════════════╩═══════╩═══════╩═══════╩═══════╩═══════╩═══════╩════════╩═════════╩═══════╩═══════╩═══════╩═══════╩═══════╝"
        )

        # Log all lines
        for line in lines:
            logger.info(line)

        # Log summary statistics
        logger.info(
            f"Daily energy summary: {total_solar:.1f} kWh solar, {total_consumption:.1f} kWh consumption, "
            f"{total_battery_charge:.1f} kWh charged, {total_battery_discharge:.1f} kWh discharged"
        )
        logger.info(
            f"Daily cost summary: {total_grid_only_cost:.2f} SEK grid-only, {total_cost:.2f} SEK optimized, "
            f"{total_savings:.2f} SEK savings"
        )
        logger.info(
            f"Actual vs Predicted: {daily_view.actual_hours_count} actual hours ({actual_savings:.2f} SEK), "
            f"{daily_view.predicted_hours_count} predicted hours ({predicted_savings:.2f} SEK)"
        )

    def _get_list_item(
        self, data_list: list | None, index: int, field_name: str, default=None
    ) -> float:
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
            if (
                latest_schedule
                and latest_schedule.optimization_result.input_data
                and "initial_soc" in latest_schedule.optimization_result.input_data
            ):
                return latest_schedule.optimization_result.input_data["initial_soc"]
            else:
                # Default fallback (should not happen with validation)
                raise ValueError(
                    "Cannot determine SOC for hour 0 - no initial_soc in schedule"
                )
        else:
            # For hours 1-23, get from previous hour's ending SOC
            prev_hour = hour - 1
            prev_data = self.historical_store.get_hour_record(prev_hour)

            if prev_data:
                # Found previous hour in historical data
                # Convert SOE to SOC for display
                return (
                    prev_data.energy.battery_soe_end
                    / self.battery_settings.total_capacity
                ) * 100.0
            else:
                # If no historical data, we need to calculate from the schedule
                raise ValueError(
                    f"No historical data for hour {prev_hour}, need to use schedule SOC"
                )
