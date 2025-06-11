"""
HistoricalDataStore - Immutable storage of what actually happened.

This module provides the HistoricalDataStore class that stores immutable records
of completed hours. Once an hour is recorded, its data never changes.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HourlyEvent:
    """Immutable record of what actually happened in one hour.

    UPDATED: Stores only facts - energy flows, state, and context.
    Costs are calculated on-demand using shared calculation functions.
    """

    hour: int
    timestamp: datetime

    # Battery state (facts)
    battery_soc_start: float  # %
    battery_soc_end: float  # %

    # Energy flows (facts) - all in kWh
    solar_generated: float
    home_consumed: float
    grid_imported: float
    grid_exported: float
    battery_charged: float
    battery_discharged: float

    # Context (facts)
    buy_price: float = 0.0  # Price for this hour (SEK/kWh)
    sell_price: float = 0.0  # Price for selling to grid (SEK/kWh)
    strategic_intent: str = "IDLE"

    # Derived values (calculated automatically)
    battery_net_change: float = field(init=False)
    soc_change: float = field(init=False)

    def __post_init__(self):
        """Calculate derived values after initialization."""
        object.__setattr__(
            self, "battery_net_change", self.battery_charged - self.battery_discharged
        )
        object.__setattr__(
            self, "soc_change", self.battery_soc_end - self.battery_soc_start
        )

    def to_energy_flows(self):
        """Convert to EnergyFlows format for cost calculations."""
        from core.bess.dp_battery_algorithm import EnergyFlows

        return EnergyFlows(
            home_consumption=self.home_consumed,
            solar_production=self.solar_generated,
            grid_import=self.grid_imported,
            grid_export=self.grid_exported,
            battery_charged=self.battery_charged,
            battery_discharged=self.battery_discharged,
        )

    def validate(self) -> bool:
        """Validate that the event data is physically reasonable.

        Returns:
            bool: True if data passes basic validation checks
        """
        # Hour must be valid
        if not 0 <= self.hour <= 23:
            logger.warning(f"Invalid hour: {self.hour}")
            return False

        # SOC must be in valid range
        if not 0 <= self.battery_soc_start <= 100:
            logger.warning(f"Invalid start SOC: {self.battery_soc_start}%")
            return False

        if not 0 <= self.battery_soc_end <= 100:
            logger.warning(f"Invalid end SOC: {self.battery_soc_end}%")
            return False

        # Energy values should be non-negative
        energy_fields = [
            self.solar_generated,
            self.home_consumed,
            self.grid_imported,
            self.grid_exported,
            self.battery_charged,
            self.battery_discharged,
        ]

        for i, value in enumerate(energy_fields):
            if value < 0:
                field_names = [
                    "solar_generated",
                    "home_consumed",
                    "grid_imported",
                    "grid_exported",
                    "battery_charged",
                    "battery_discharged",
                ]
                logger.warning(f"Negative energy value for {field_names[i]}: {value}")
                return False

        # Check for unreasonably large values (> 50 kWh in one hour)
        for i, value in enumerate(energy_fields):
            if value > 50.0:
                field_names = [
                    "solar_generated",
                    "home_consumed",
                    "grid_imported",
                    "grid_exported",
                    "battery_charged",
                    "battery_discharged",
                ]
                logger.warning(
                    f"Unusually large energy value for {field_names[i]}: {value} kWh"
                )

        return True


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
        self._events: dict[int, HourlyEvent] = {}  # hour -> event
        self._current_date: date | None = None
        self._battery_capacity = battery_capacity_kwh

        logger.info(
            "Initialized HistoricalDataStore with %.1f kWh battery capacity",
            battery_capacity_kwh,
        )

    def record_hour_completion(self, event: HourlyEvent) -> bool:
        """Record what happened in a completed hour.

        Args:
            event: HourlyEvent containing all measured data for the hour

        Returns:
            bool: True if recording was successful

        Raises:
            ValueError: If event data is invalid
        """
        # Validate the event data
        if not event.validate():
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
        self._current_date = event.timestamp.date()

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

    def get_hour_event(self, hour: int) -> HourlyEvent | None:
        """Get recorded event for specific hour.

        Args:
            hour: Hour to retrieve (0-23)

        Returns:
            Optional[HourlyEvent]: Event for the hour, or None if not recorded
        """
        if not 0 <= hour <= 23:
            logger.error("Invalid hour: %d", hour)
            return None

        return self._events.get(hour)

    def get_latest_battery_state(self) -> tuple[float, float]:
        """Get most recent battery SOC and energy content.

        Returns:
            Tuple[float, float]: (SOC percentage, energy in kWh)
        """
        if not self._events:
            # No historical data - return default minimum values
            default_soc = 10.0  # 10% SOC
            default_energy = (default_soc / 100.0) * self._battery_capacity
            logger.debug(
                "No historical data, returning default: %.1f%%, %.1f kWh",
                default_soc,
                default_energy,
            )
            return default_soc, default_energy

        # Get the latest completed hour
        latest_hour = max(self._events.keys())
        latest_event = self._events[latest_hour]

        # Calculate energy from SOC
        latest_energy = (latest_event.battery_soc_end / 100.0) * self._battery_capacity

        logger.debug(
            "Latest battery state from hour %d: %.1f%%, %.1f kWh",
            latest_hour,
            latest_event.battery_soc_end,
            latest_energy,
        )

        return latest_event.battery_soc_end, latest_energy

    def get_energy_balance_summary(self) -> dict[str, float]:
        """Get summary of energy flows for all completed hours.

        Returns:
            Dict[str, float]: Summary of total energy flows
        """
        if not self._events:
            return {}

        totals = {
            "total_solar": 0.0,
            "total_consumption": 0.0,
            "total_grid_import": 0.0,
            "total_grid_export": 0.0,
            "total_battery_charge": 0.0,
            "total_battery_discharge": 0.0,
            "battery_net_change": 0.0,
            "hours_recorded": len(self._events),
        }

        for event in self._events.values():
            totals["total_solar"] += event.solar_generated
            totals["total_consumption"] += event.home_consumed
            totals["total_grid_import"] += event.grid_imported
            totals["total_grid_export"] += event.grid_exported
            totals["total_battery_charge"] += event.battery_charged
            totals["total_battery_discharge"] += event.battery_discharged

        # Calculate net battery change
        totals["battery_net_change"] = (
            totals["total_battery_charge"] - totals["total_battery_discharge"]
        )

        return totals

    def reset_for_new_day(self) -> None:
        """Clear all data for a new day.

        This should be called at midnight to start fresh for the new day.
        """
        hours_cleared = len(self._events)
        self._events.clear()
        self._current_date = None

        logger.info(
            "Historical data reset for new day (%d hours cleared)", hours_cleared
        )

    def get_current_date(self) -> date | None:
        """Get the date for which data is currently stored.

        Returns:
            Optional[date]: Current date, or None if no data stored
        """
        return self._current_date

    def has_data_for_hour(self, hour: int) -> bool:
        """Check if data exists for a specific hour.

        Args:
            hour: Hour to check (0-23)

        Returns:
            bool: True if data exists for the hour
        """
        return hour in self._events

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


__all__ = ["HistoricalDataStore", "HourlyEvent"]
