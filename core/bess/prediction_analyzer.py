"""PredictionAnalyzer - Analyzes deviations between predictions and actuals.

Compares snapshots of predictions against actual outcomes to identify what
changed and why predictions deviated from reality.
"""

import logging
from dataclasses import dataclass

from core.bess.daily_view_builder import DailyView
from core.bess.prediction_snapshot import PredictionSnapshot

logger = logging.getLogger(__name__)


@dataclass
class PeriodDeviation:
    """Deviation analysis for a single period."""

    period: int

    # Predicted values (from snapshot's DailyView)
    predicted_battery_action: float  # kWh (charge - discharge)
    predicted_consumption: float  # kWh
    predicted_solar: float  # kWh
    predicted_grid_import: float  # kWh
    predicted_grid_export: float  # kWh
    predicted_savings: float  # in configured currency

    # Actual values (from current DailyView)
    actual_battery_action: float  # kWh
    actual_consumption: float  # kWh
    actual_solar: float  # kWh
    actual_grid_import: float  # kWh
    actual_grid_export: float  # kWh
    actual_savings: float  # in configured currency

    # Deviations (actual - predicted)
    battery_action_deviation: float  # kWh
    consumption_deviation: float  # kWh
    solar_deviation: float  # kWh
    grid_import_deviation: float  # kWh
    grid_export_deviation: float  # kWh
    savings_deviation: float  # in configured currency

    deviation_type: str  # "CONSUMPTION_HIGHER", "SOLAR_LOWER", etc.


@dataclass
class SnapshotComparison:
    """Comparison between snapshot predictions and current actuals."""

    reference_snapshot: PredictionSnapshot
    current_daily_view: DailyView
    period_deviations: list[PeriodDeviation]

    # Aggregate metrics (comparison window only: snapshot_period to current actual_count)
    total_predicted_savings: float  # in configured currency
    total_actual_savings: float  # in configured currency
    savings_deviation: float  # in configured currency

    primary_deviation_cause: str  # "consumption", "solar", "battery_control"

    # Full-day savings breakdown at snapshot time (actuals + predicted = total)
    snapshot_total_savings: float
    snapshot_actual_savings: float
    snapshot_predicted_savings: float

    # Full-day savings breakdown now (actuals + predicted = total)
    current_total_savings: float
    current_actual_savings: float
    current_predicted_savings: float

    # Schedule comparison
    predicted_growatt_schedule: list[dict]  # TOU intervals from snapshot
    current_growatt_schedule: list[dict]  # Current TOU intervals


class PredictionAnalyzer:
    """Analyzes deviations between predictions and actuals."""

    def compare_snapshot_to_current(
        self,
        snapshot: PredictionSnapshot,
        current_daily_view: DailyView,
        current_growatt_schedule: list[dict],
    ) -> SnapshotComparison:
        """Compare snapshot predictions vs current actuals.

        Args:
            snapshot: Historical snapshot with predictions
            current_daily_view: Current daily view with actuals
            current_growatt_schedule: Current TOU intervals

        Returns:
            SnapshotComparison with period-by-period deviations
        """
        period_deviations = []
        snapshot_periods = snapshot.daily_view.periods
        current_periods = current_daily_view.periods

        # Compare periods that have actual data now
        # (from snapshot optimization_period to current actual_count)
        start_period = snapshot.optimization_period
        end_period = current_daily_view.actual_count

        total_predicted_savings = 0.0
        total_actual_savings = 0.0

        # Track deviation magnitudes for identifying primary cause
        total_battery_dev = 0.0
        total_consumption_dev = 0.0
        total_solar_dev = 0.0

        for period_idx in range(start_period, min(end_period, len(current_periods))):
            if period_idx >= len(snapshot_periods) or period_idx >= len(
                current_periods
            ):
                continue

            snapshot_period = snapshot_periods[period_idx]
            current_period = current_periods[period_idx]

            # Skip if either period is missing data
            if not snapshot_period or not current_period:
                continue

            # Extract predicted values (what snapshot thought would happen)
            predicted_battery_action = self._calculate_battery_action(snapshot_period)
            predicted_consumption = snapshot_period.energy.home_consumption
            predicted_solar = snapshot_period.energy.solar_production
            predicted_grid_import = snapshot_period.energy.grid_imported
            predicted_grid_export = snapshot_period.energy.grid_exported
            predicted_savings = snapshot_period.economic.hourly_savings

            # Extract actual values (what actually happened)
            actual_battery_action = self._calculate_battery_action(current_period)
            actual_consumption = current_period.energy.home_consumption
            actual_solar = current_period.energy.solar_production
            actual_grid_import = current_period.energy.grid_imported
            actual_grid_export = current_period.energy.grid_exported
            actual_savings = current_period.economic.hourly_savings

            # Calculate deviations
            battery_dev = actual_battery_action - predicted_battery_action
            consumption_dev = actual_consumption - predicted_consumption
            solar_dev = actual_solar - predicted_solar
            grid_import_dev = actual_grid_import - predicted_grid_import
            grid_export_dev = actual_grid_export - predicted_grid_export
            savings_dev = actual_savings - predicted_savings

            # Classify deviation type based on magnitude
            deviation_type = self._classify_deviation(
                battery_dev, consumption_dev, solar_dev
            )

            period_deviations.append(
                PeriodDeviation(
                    period=period_idx,
                    predicted_battery_action=predicted_battery_action,
                    predicted_consumption=predicted_consumption,
                    predicted_solar=predicted_solar,
                    predicted_grid_import=predicted_grid_import,
                    predicted_grid_export=predicted_grid_export,
                    predicted_savings=predicted_savings,
                    actual_battery_action=actual_battery_action,
                    actual_consumption=actual_consumption,
                    actual_solar=actual_solar,
                    actual_grid_import=actual_grid_import,
                    actual_grid_export=actual_grid_export,
                    actual_savings=actual_savings,
                    battery_action_deviation=battery_dev,
                    consumption_deviation=consumption_dev,
                    solar_deviation=solar_dev,
                    grid_import_deviation=grid_import_dev,
                    grid_export_deviation=grid_export_dev,
                    savings_deviation=savings_dev,
                    deviation_type=deviation_type,
                )
            )

            # Accumulate totals
            total_predicted_savings += predicted_savings
            total_actual_savings += actual_savings

            # Track absolute deviations for primary cause
            total_battery_dev += abs(battery_dev)
            total_consumption_dev += abs(consumption_dev)
            total_solar_dev += abs(solar_dev)

        # Determine primary deviation cause
        primary_cause = self._determine_primary_cause(
            total_battery_dev, total_consumption_dev, total_solar_dev
        )

        savings_deviation = total_actual_savings - total_predicted_savings

        # Full-day savings breakdown at snapshot time
        # Use grid_only_cost - hourly_cost to match dashboard total savings definition
        snapshot_actual_savings = sum(
            p.economic.grid_only_cost - p.economic.hourly_cost
            for p in snapshot.daily_view.periods
            if p.data_source == "actual" and p.economic is not None
        )
        snapshot_predicted_savings = sum(
            p.economic.grid_only_cost - p.economic.hourly_cost
            for p in snapshot.daily_view.periods
            if p.data_source == "predicted" and p.economic is not None
        )

        # Full-day savings breakdown now
        current_actual_savings = sum(
            p.economic.grid_only_cost - p.economic.hourly_cost
            for p in current_daily_view.periods
            if p.data_source == "actual" and p.economic is not None
        )
        current_predicted_savings = sum(
            p.economic.grid_only_cost - p.economic.hourly_cost
            for p in current_daily_view.periods
            if p.data_source == "predicted" and p.economic is not None
        )

        logger.info(
            "Snapshot comparison: predicted %.2f, actual %.2f, deviation %.2f (%s)",
            total_predicted_savings,
            total_actual_savings,
            savings_deviation,
            primary_cause,
        )

        return SnapshotComparison(
            reference_snapshot=snapshot,
            current_daily_view=current_daily_view,
            period_deviations=period_deviations,
            total_predicted_savings=total_predicted_savings,
            total_actual_savings=total_actual_savings,
            savings_deviation=savings_deviation,
            primary_deviation_cause=primary_cause,
            snapshot_total_savings=snapshot_actual_savings + snapshot_predicted_savings,
            snapshot_actual_savings=snapshot_actual_savings,
            snapshot_predicted_savings=snapshot_predicted_savings,
            current_total_savings=current_actual_savings + current_predicted_savings,
            current_actual_savings=current_actual_savings,
            current_predicted_savings=current_predicted_savings,
            predicted_growatt_schedule=snapshot.growatt_schedule,
            current_growatt_schedule=current_growatt_schedule,
        )

    def _calculate_battery_action(self, period_data) -> float:
        """Calculate net battery action (positive = charge, negative = discharge).

        Args:
            period_data: PeriodData object

        Returns:
            float: Net battery action in kWh
        """
        if not period_data or not period_data.energy:
            return 0.0

        # Battery action = charged - discharged
        charged = period_data.energy.battery_charged or 0.0
        discharged = period_data.energy.battery_discharged or 0.0

        return charged - discharged

    def _classify_deviation(
        self, battery_dev: float, consumption_dev: float, solar_dev: float
    ) -> str:
        """Classify deviation type based on which factor changed most.

        Args:
            battery_dev: Battery action deviation (kWh)
            consumption_dev: Consumption deviation (kWh)
            solar_dev: Solar production deviation (kWh)

        Returns:
            str: Classification like "CONSUMPTION_HIGHER", "SOLAR_LOWER", etc.
        """
        # Thresholds for significant deviation
        THRESHOLD = 0.3  # kWh

        max_abs_dev = max(abs(battery_dev), abs(consumption_dev), abs(solar_dev))

        if max_abs_dev < THRESHOLD:
            return "MINIMAL"

        # Identify which factor had the largest deviation
        if abs(consumption_dev) == max_abs_dev:
            return "CONSUMPTION_HIGHER" if consumption_dev > 0 else "CONSUMPTION_LOWER"
        elif abs(solar_dev) == max_abs_dev:
            return "SOLAR_LOWER" if solar_dev < 0 else "SOLAR_HIGHER"
        else:  # battery_dev is largest
            return "BATTERY_MISMATCH"

    def _determine_primary_cause(
        self,
        total_battery_dev: float,
        total_consumption_dev: float,
        total_solar_dev: float,
    ) -> str:
        """Determine primary cause of deviation across all periods.

        Args:
            total_battery_dev: Sum of absolute battery deviations
            total_consumption_dev: Sum of absolute consumption deviations
            total_solar_dev: Sum of absolute solar deviations

        Returns:
            str: Primary cause ("consumption", "solar", "battery_control", "multiple")
        """
        total_dev = total_battery_dev + total_consumption_dev + total_solar_dev

        if total_dev == 0:
            return "none"

        # Calculate contribution percentages
        battery_pct = total_battery_dev / total_dev
        consumption_pct = total_consumption_dev / total_dev
        solar_pct = total_solar_dev / total_dev

        # If one factor dominates (>50%), it's the primary cause
        if consumption_pct > 0.5:
            return "consumption"
        elif solar_pct > 0.5:
            return "solar"
        elif battery_pct > 0.5:
            return "battery_control"
        else:
            return "multiple"
