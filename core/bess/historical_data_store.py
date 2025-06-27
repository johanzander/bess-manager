"""
HistoricalDataStore - Immutable storage of what actually happened.

This module provides the HistoricalDataStore class that stores immutable records
of completed hours. Once an hour is recorded, its data never changes.
"""

import logging
from datetime import date, datetime

from core.bess.dp_battery_algorithm import HourlyData

logger = logging.getLogger(__name__)


class HistoricalDataStore:
    """Immutable storage of what actually happened each hour.

    This class maintains a record of completed hours as immutable events.
    Once an hour is recorded, its data never changes. This provides a
    reliable foundation for state calculation and reporting.
    """

    def __init__(self, battery_capacity_kwh: float = 30.0):
        """Initialize the historical data store.

        Args:
            battery_capacity_kwh: Total battery capacity for SOC calculations
        """
        self._events: dict[int, HourlyData] = {}  # hour -> event
        self._current_date: date | None = None
        self._battery_capacity = battery_capacity_kwh

        logger.info(
            "Initialized HistoricalDataStore with %.1f kWh battery capacity",
            battery_capacity_kwh,
        )

    def record_hour_completion(self, event: HourlyData) -> bool:
        """Record what happened in a completed hour.

        Args:
            event: HourlyData containing all measured data for the hour

        Returns:
            bool: True if recording was successful

        Raises:
            ValueError: If event data is invalid
        """
        # Validate the event data
        if not self._validate_event_data(event):
            raise ValueError(f"Invalid event data for hour {event.hour}")

        # Check if we're overwriting existing data
        if event.hour in self._events:
            existing = self._events[event.hour]
            logger.warning(
                "Overwriting existing data for hour %d (SOC: %.1f%% -> %.1f%%)",
                event.hour,
                existing.battery_soc_end,
                event.battery_soc_end,
            )

        # Store the event
        self._events[event.hour] = event
        if event.timestamp:
            self._current_date = event.timestamp.date()
        else:
            self._current_date = datetime.now().date()

        logger.info(
            "Recorded hour %02d: SOC %.1f%% -> %.1f%%, Net: %.2f kWh, Solar: %.2f kWh, Load: %.2f kWh",
            event.hour,
            event.battery_soc_start,
            event.battery_soc_end,
            event.battery_net_change,
            event.solar_generated,
            event.home_consumed,
        )

        return True

    def get_completed_hours(self) -> list[int]:
        """Get list of hours with recorded data.

        Returns:
            List[int]: Sorted list of completed hours (0-23)
        """
        return sorted(self._events.keys())

    def get_hour_event(self, hour: int) -> HourlyData | None:
        """Get recorded event for specific hour.

        Args:
            hour: Hour to retrieve (0-23)

        Returns:
            HourlyData | None: Event for the hour, or None if not recorded
        """
        if not 0 <= hour <= 23:
            logger.error("Invalid hour: %d", hour)
            return None

        return self._events.get(hour)

    def get_latest_battery_state(self) -> tuple[float, float]:
        """Get most recent battery SOC and energy content.

        Returns:
            Tuple[float, float]: (soc_percentage, energy_kwh)
        """
        if not self._events:
            return 20.0, 20.0 * self._battery_capacity / 100.0

        # Get the latest hour with data
        latest_hour = max(self._events.keys())
        latest_event = self._events[latest_hour]

        soc_percentage = latest_event.battery_soc_end
        energy_kwh = soc_percentage * self._battery_capacity / 100.0

        return soc_percentage, energy_kwh

    def has_data_for_hour(self, hour: int) -> bool:
        """Check if data exists for a specific hour.

        Args:
            hour: Hour to check (0-23)

        Returns:
            bool: True if data exists for the hour
        """
        return hour in self._events

    def get_current_date(self) -> date | None:
        """Get the date for which data is currently stored.

        Returns:
            date | None: Current date, or None if no data stored
        """
        return self._current_date

    def get_energy_balance_summary(self) -> dict[str, float]:
        """Get energy balance summary for all stored events.

        Returns:
            Dict[str, float]: Energy balance summary
        """
        if not self._events:
            return {}

        events = list(self._events.values())

        total_solar = sum(e.solar_generated for e in events)
        total_consumption = sum(e.home_consumed for e in events)
        total_grid_import = sum(e.grid_imported for e in events)
        total_grid_export = sum(e.grid_exported for e in events)
        total_battery_charge = sum(e.battery_charged for e in events)
        total_battery_discharge = sum(e.battery_discharged for e in events)

        return {
            "hours_recorded": len(events),
            "total_solar": total_solar,
            "total_consumption": total_consumption,
            "total_grid_import": total_grid_import,
            "total_grid_export": total_grid_export,
            "total_battery_charge": total_battery_charge,
            "total_battery_discharge": total_battery_discharge,
            "battery_net_change": total_battery_charge - total_battery_discharge,
        }

    def reset_for_new_day(self) -> None:
        """Reset all stored data for a new day.

        This should be called at midnight to start fresh for the new day.
        """
        hours_cleared = len(self._events)
        self._events.clear()
        self._current_date = None

        logger.info(
            "Historical data reset for new day (%d hours cleared)", hours_cleared
        )

    def log_daily_summary(self) -> None:
        """Log a summary of all recorded data for the day."""
        if not self._events:
            logger.info("No historical data recorded for today")
            return

        summary = self.get_energy_balance_summary()
        completed_hours = self.get_completed_hours()

        logger.info(
            "\n%s\n"
            "Historical Data Summary for %s\n"
            "%s\n"
            "Hours recorded: %d (%s)\n"
            "Total solar generation: %.2f kWh\n"
            "Total home consumption: %.2f kWh\n"
            "Total grid import: %.2f kWh\n"
            "Total grid export: %.2f kWh\n"
            "Total battery charge: %.2f kWh\n"
            "Total battery discharge: %.2f kWh\n"
            "Net battery change: %.2f kWh\n"
            "%s",
            "=" * 60,
            self._current_date or "Unknown",
            "=" * 60,
            summary["hours_recorded"],
            ", ".join([f"{h:02d}" for h in completed_hours]),
            summary["total_solar"],
            summary["total_consumption"],
            summary["total_grid_import"],
            summary["total_grid_export"],
            summary["total_battery_charge"],
            summary["total_battery_discharge"],
            summary["battery_net_change"],
            "=" * 60,
        )

    def _validate_event_data(self, event: HourlyData) -> bool:
        """Validate that the event data is physically reasonable.

        Args:
            event: HourlyData to validate

        Returns:
            bool: True if data passes basic validation checks
        """
        # Hour must be valid
        if not 0 <= event.hour <= 23:
            logger.warning(f"Invalid hour: {event.hour}")
            return False

        # SOC must be in valid range
        if not 0 <= event.battery_soc_start <= 100:
            logger.warning(f"Invalid start SOC: {event.battery_soc_start}%")
            return False

        if not 0 <= event.battery_soc_end <= 100:
            logger.warning(f"Invalid end SOC: {event.battery_soc_end}%")
            return False

        # Energy values should be non-negative
        energy_fields = [
            ("solar_generated", event.solar_generated),
            ("home_consumed", event.home_consumed),
            ("grid_imported", event.grid_imported),
            ("grid_exported", event.grid_exported),
            ("battery_charged", event.battery_charged),
            ("battery_discharged", event.battery_discharged),
        ]

        for field_name, value in energy_fields:
            if value < 0:
                logger.warning(f"Negative energy value for {field_name}: {value}")
                return False

        # Check for unreasonably large values (> 50 kWh in one hour)
        for field_name, value in energy_fields:
            if value > 50.0:
                logger.warning(
                    f"Unusually large energy value for {field_name}: {value} kWh"
                )

        return True


__all__ = ["HistoricalDataStore"]