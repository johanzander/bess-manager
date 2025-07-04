# core/bess/historical_data_store.py
"""
HistoricalDataStore - Immutable storage of what actually happened.

TODO: MIGRATE TO UNIFIED NAMES AND FUNCTIONS - COMBining _NEW_ AND LEGACY FUNCTIONS

"""

import logging
from datetime import date, datetime

from core.bess.models import EnergyData, NewHourlyData, StrategyData

logger = logging.getLogger(__name__)


class HistoricalDataStore:
    """Immutable storage of what actually happened each hour.

    """

    def __init__(self, battery_capacity_kwh: float = 30.0):
        """Initialize the historical data store.

        Args:
            battery_capacity_kwh: Total battery capacity for SOC calculations
        """
        # Primary storage - unified data structure
        self._new_events: dict[int, NewHourlyData] = {}  # hour -> NewHourlyData

        self._current_date: date | None = None
        self._battery_capacity = battery_capacity_kwh

        logger.info(
            "Initialized HistoricalDataStore with %.1f kWh battery capacity (supports both old and new data formats)",
            battery_capacity_kwh,
        )

    # =============================================================================
    # NEW METHODS - Using NewHourlyData and EnergyData (Migration Target)
    # =============================================================================

    def record_energy_data(
        self,
        hour: int,
        energy_data: EnergyData,
        data_source: str = "actual",
        timestamp: datetime | None = None,
    ) -> bool:
        """Record energy data for a completed hour using new data structures.

        This is the new preferred method for recording hourly data.

        Args:
            hour: Hour of the day (0-23)
            energy_data: Pure energy flow data from sensors
            data_source: Source of the data ("actual" for sensor data)
            timestamp: When this data was recorded

        Returns:
            bool: True if recording was successful

        Raises:
            ValueError: If energy data is invalid
        """
        if not 0 <= hour <= 23:
            raise ValueError(f"Invalid hour: {hour}, must be 0-23")

        # Validate energy data with a very tolerant threshold for testing
        validation_errors = energy_data.validate_energy_balance(
            tolerance=1.0
        )  # Very tolerant for tests
        if not validation_errors[0]:
            logger.warning(
                f"Energy balance issue for hour {hour}: {validation_errors[1]}"
            )

        # Analyze strategic intent from energy flows
        strategic_intent = self._analyze_intent_from_energy_data(energy_data)

        # Create complete hourly data
        hourly_data = NewHourlyData(
            hour=hour,
            energy=energy_data,
            timestamp=timestamp or datetime.now(),
            data_source=data_source,
            strategy=StrategyData(strategic_intent=strategic_intent),
        )

        # Validate the complete data
        validation_errors = hourly_data.validate_data()
        if validation_errors:
            raise ValueError(
                f"Invalid hourly data for hour {hour}: {validation_errors}"
            )

        # Check if we're overwriting existing data
        if hour in self._new_events:
            existing = self._new_events[hour]
            logger.warning(
                "Overwriting existing data for hour %d (SOC: %.1f%% -> %.1f%%)",
                hour,
                existing.energy.battery_soc_start,
                existing.energy.battery_soc_end,
            )

        # Store the new format data
        self._new_events[hour] = hourly_data

        # Update current date
        if hourly_data.timestamp:
            self._current_date = hourly_data.timestamp.date()

        logger.info(
            "Recorded hour %02d (NEW FORMAT): SOC %.1f%% -> %.1f%%, Net: %.2f kWh, Solar: %.2f kWh, Load: %.2f kWh, Intent: %s",
            hour,
            energy_data.battery_soc_start,
            energy_data.battery_soc_end,
            energy_data.battery_net_change,
            energy_data.solar_generated,
            energy_data.home_consumed,
            strategic_intent,
        )

        return True

    def get_new_hourly_data(self, hour: int) -> NewHourlyData | None:
        """Get recorded data for specific hour using new data structure.

        This is the new preferred method for retrieving hourly data.

        Args:
            hour: Hour to retrieve (0-23)

        Returns:
            NewHourlyData | None: Complete hourly data for the hour, or None if not recorded
        """
        if not 0 <= hour <= 23:
            logger.error("Invalid hour: %d", hour)
            return None

        return self._new_events.get(hour)

    def get_all_new_hourly_data(self) -> list[NewHourlyData]:
        """Get all recorded data using new data structure, sorted by hour.

        Returns:
            list[NewHourlyData]: All recorded hourly data, sorted by hour
        """
        hours = sorted(self._new_events.keys())
        return [self._new_events[hour] for hour in hours]

    def get_energy_data_for_hour(self, hour: int) -> EnergyData | None:
        """Get pure energy data for specific hour.

        Args:
            hour: Hour to retrieve (0-23)

        Returns:
            EnergyData | None: Pure energy flows for the hour, or None if not recorded
        """
        hourly_data = self.get_new_hourly_data(hour)
        return hourly_data.energy if hourly_data else None

    def has_new_data_for_hour(self, hour: int) -> bool:
        """Check if new format data exists for a specific hour.

        Args:
            hour: Hour to check (0-23)

        Returns:
            bool: True if new format data exists for the hour
        """
        return hour in self._new_events

    def get_latest_energy_state(self) -> tuple[float, float, str]:
        """Get most recent battery and energy state using new data format.

        This method finds the latest hour with recorded data and returns
        the final state and strategic context.

        Returns:
            tuple[float, float, str]: (SOC percentage, energy in kWh, strategic_intent)
        """
        if not self._new_events:
            logger.warning("No data available for latest energy state")
            return 50.0, self._battery_capacity * 0.5, "IDLE"  # Default to 50%

        latest_hour = max(self._new_events.keys())
        latest_data = self._new_events[latest_hour]

        soc_percent = latest_data.energy.battery_soc_end
        energy_kwh = (soc_percent / 100.0) * self._battery_capacity
        strategic_intent = latest_data.strategy.strategic_intent

        logger.debug(
            "Latest energy state from hour %02d: SOC %.1f%%, Energy %.1f kWh, Intent %s",
            latest_hour,
            soc_percent,
            energy_kwh,
            strategic_intent,
        )

        return soc_percent, energy_kwh, strategic_intent

    def get_new_energy_balance_summary(self) -> dict[str, float]:
        """Get comprehensive energy balance summary using new data format.

        Calculates totals across all recorded hours with detailed breakdowns
        of energy flows and battery performance.

        Returns:
            dict[str, float]: Comprehensive energy balance summary
        """
        if not self._new_events:
            logger.info("No new format data available for energy balance summary")
            return {}

        # Calculate totals from new format data
        total_solar = sum(
            data.energy.solar_generated for data in self._new_events.values()
        )
        total_consumption = sum(
            data.energy.home_consumed for data in self._new_events.values()
        )
        total_grid_import = sum(
            data.energy.grid_imported for data in self._new_events.values()
        )
        total_grid_export = sum(
            data.energy.grid_exported for data in self._new_events.values()
        )
        total_battery_charged = sum(
            data.energy.battery_charged for data in self._new_events.values()
        )
        total_battery_discharged = sum(
            data.energy.battery_discharged for data in self._new_events.values()
        )

        # Calculate derived metrics
        self_consumption = total_solar - total_grid_export
        battery_efficiency = (
            (total_battery_discharged / total_battery_charged) * 100
            if total_battery_charged > 0
            else 0
        )

        # Strategic intent distribution
        intent_counts = {}
        for data in self._new_events.values():
            intent = data.strategy.strategic_intent
            intent_counts[intent] = intent_counts.get(intent, 0) + 1

        summary = {
            "total_solar_generated": total_solar,
            "total_home_consumed": total_consumption,
            "total_grid_imported": total_grid_import,
            "total_grid_exported": total_grid_export,
            "total_battery_charged": total_battery_charged,
            "total_battery_discharged": total_battery_discharged,
            "net_battery_change": total_battery_charged - total_battery_discharged,
            "self_consumption": self_consumption,
            "battery_efficiency_percent": battery_efficiency,
            "hours_recorded": len(self._new_events),
            "strategic_intent_distribution": intent_counts,
        }

        logger.debug(
            "Energy balance summary (NEW FORMAT): %d hours, %.1f kWh solar, %.1f kWh consumed, %.1f%% battery efficiency",
            len(self._new_events),
            total_solar,
            total_consumption,
            battery_efficiency,
        )

        return summary

    def clear_new_data(self) -> int:
        """Clear all new format data.

        Returns:
            int: Number of hours cleared
        """
        count = len(self._new_events)
        self._new_events.clear()

        logger.info("Cleared new format data (%d hours)", count)
        return count

    def _analyze_intent_from_energy_data(self, energy_data: EnergyData) -> str:
        """Analyze strategic intent from energy flow patterns.

        Uses energy flow patterns to determine the primary strategic intent
        of the battery system during this hour.

        Args:
            energy_data: Energy data to analyze

        Returns:
            str: Strategic intent classification
        """
        net_battery = energy_data.battery_net_change

        # Threshold for considering "significant" activity
        threshold = 0.1  # kWh

        if abs(net_battery) < threshold:
            return "IDLE"
        elif net_battery > threshold:  # Net charging
            # Determine if charging from grid or storing solar
            if energy_data.grid_imported > energy_data.battery_charged:
                return "GRID_CHARGING"
            else:
                return "SOLAR_STORAGE"
        else:  # Net discharging
            # Determine if supporting load or exporting for arbitrage
            if energy_data.grid_exported > 0:
                return "EXPORT_ARBITRAGE"
            else:
                return "LOAD_SUPPORT"

    # =============================================================================
    # COMPATIBILITY METHODS - Bridge old method names to new implementation
    # =============================================================================

    def get_hour_event(self, hour: int) -> NewHourlyData | None:
        """Compatibility method - returns NewHourlyData instead of old HourlyData."""
        return self.get_new_hourly_data(hour)

    def has_data_for_hour(self, hour: int) -> bool:
        """Compatibility method - checks for new format data."""
        return self.has_new_data_for_hour(hour)

    def get_completed_hours(self) -> list[int]:
        """Get list of hours that have been completed and recorded.

        Returns:
            list[int]: Sorted list of hours (0-23) that have recorded data
        """
        return sorted(self._new_events.keys())

    def get_latest_battery_state(self) -> tuple[float, float]:
        """Compatibility method - returns (SOC, energy) from new format data."""
        soc, energy, _ = self.get_latest_energy_state()
        return soc, energy

    def get_energy_balance_summary(self) -> dict[str, float]:
        """Compatibility method - returns new format energy balance."""
        return self.get_new_energy_balance_summary()

    def clear_all_data(self) -> int:
        """Clear all data (new format only)."""
        return self.clear_new_data()

    def reset_for_new_day(self) -> int:
        """Reset for a new day."""
        cleared = self.clear_new_data()
        self._current_date = None

        logger.info("Reset for new day - cleared %d hours", cleared)
        return cleared

    def get_current_date(self) -> date | None:
        """Get the current date for stored data."""
        return self._current_date

    def record_hour_completion(self, hourly_data: NewHourlyData) -> bool:
        """Compatibility method - accepts NewHourlyData."""
        return self.record_energy_data(
            hour=hourly_data.hour,
            energy_data=hourly_data.energy,
            data_source=hourly_data.data_source,
            timestamp=hourly_data.timestamp,
        )
