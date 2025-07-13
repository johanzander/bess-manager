# core/bess/historical_data_store.py
"""
HistoricalDataStore - Immutable storage of what actually happened.

"""

import logging
from datetime import date, datetime

from core.bess.models import DecisionData, EnergyData, HourlyData

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
        self._records: dict[int, HourlyData] = {} 

        self._current_date: date | None = None

        logger.info(
            "Initialized HistoricalDataStore",
        )

    def record_energy_data(
        self,
        hour: int,
        energy_data: EnergyData,
        data_source: str = "actual",
        timestamp: datetime | None = None,
    ) -> bool:
        """Record energy data for a completed hour.

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

        # Analyze strategic intent from energy flows
        strategic_intent = self._analyze_intent_from_energy_data(energy_data)

        # Create complete hourly data
        hourly_data = HourlyData(
            hour=hour,
            energy=energy_data,
            timestamp=timestamp or datetime.now(),
            data_source=data_source,
            decision=DecisionData(strategic_intent=strategic_intent),
        )

        # Validate the complete data
        validation_errors = hourly_data.validate_data()
        if validation_errors:
            raise ValueError(
                f"Invalid hourly data for hour {hour}: {validation_errors}"
            )

        # Store the new format data
        self._records[hour] = hourly_data

        # Update current date
        if hourly_data.timestamp:
            self._current_date = hourly_data.timestamp.date()

        logger.info(
            "Recorded hour %02d: SOC %.1f%% -> %.1f%%, Net: %.2f kWh, Solar: %.2f kWh, Load: %.2f kWh, Intent: %s",
            hour,
            energy_data.battery_soe_start,
            energy_data.battery_soe_end,
            energy_data.battery_net_change,
            energy_data.solar_production,
            energy_data.home_consumption,
            strategic_intent,
        )

        return True

    def get_hour_record(self, hour: int) -> HourlyData | None:
        """Get recorded data for specific hour using new data structure.

        This is the new preferred method for retrieving hourly data.

        Args:
            hour: Hour to retrieve (0-23)

        Returns:
            HourlyData | None: Complete hourly data for the hour, or None if not recorded
        """
        if not 0 <= hour <= 23:
            logger.error("Invalid hour: %d", hour)
            return None

        return self._records.get(hour)

    def get_latest_battery_state(self) -> tuple[float, float]:
        """Get the latest battery SOC and SOE state.
        
        Returns:
            tuple[float, float]: (soc_percent, soe_kwh)
        """
        if not self._records:
            # No records, return default state
            return 20.0, 6.0  # 20% SOC, 6 kWh SOE
        
        # Get the most recent hour
        latest_hour = max(self._records.keys())
        latest_record = self._records[latest_hour]
        
        # Return end state from the latest record
        soc_percent = (latest_record.energy.battery_soe_end / self.total_capacity) * 100.0
        soe_kwh = latest_record.energy.battery_soe_end
        
        return soc_percent, soe_kwh

    def has_data_for_hour(self, hour: int) -> bool:
        """Check if historical data exists for the given hour.
        
        Args:
            hour: Hour to check (0-23)
            
        Returns:
            bool: True if data exists for the hour
        """
        return hour in self._records

    def _analyze_intent_from_energy_data(self, energy_data: EnergyData) -> str: # TODO move out of data store
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


    def get_completed_hours(self) -> list[int]:
        """Get list of hours that have been completed and recorded.

        Returns:
            list[int]: Sorted list of hours (0-23) that have recorded data
        """
        return sorted(self._records.keys())

