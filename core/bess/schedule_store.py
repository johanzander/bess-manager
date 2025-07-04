"""
ScheduleStore - Storage for all optimization results throughout the day.

CLEAN ARCHITECTURE: Now works directly with OptimizationResult objects.
No conversions needed - unified data flow throughout the system.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from core.bess.dp_battery_algorithm import OptimizationResult
from core.bess.models import NewHourlyData

logger = logging.getLogger(__name__)


@dataclass
class StoredSchedule:
    """Container for a stored optimization result with metadata.

    UPDATED: Can store either OptimizationResult (new) or dict (legacy).
    """

    timestamp: datetime
    optimization_hour: int  # Hour optimization started from (0-23)
    optimization_result: OptimizationResult  # Direct storage of OptimizationResult
    created_for_scenario: str  # "tomorrow", "hourly", "restart"

    def get_optimization_range(self) -> tuple[int, int]:
        """Get the hour range that was optimized."""
        if (
            "next_day" in self.created_for_scenario
            or "tomorrow" in self.created_for_scenario
        ):
            return (0, 23)  # Full day optimization
        else:
            return (self.optimization_hour, 23)  # Partial day optimization

    def get_hourly_data(self) -> list[NewHourlyData]:
        """Get unified hourly data directly."""
        return self.optimization_result.hourly_data

    def get_total_savings(self) -> float:
        """Get total savings from optimization results."""
        return self.optimization_result.economic_summary.base_to_battery_solar_savings

    def get_hourly_actions(self) -> list[float]:
        """Get battery actions from unified data.

        Returns:
            list[float]: Battery actions for optimized hours
        """
        hourly_data = self.get_hourly_data()
        return [h.battery_action or 0.0 for h in hourly_data]

    def get_hourly_soe(self) -> list[float]:
        """Get state of energy values from unified data.

        Returns:
            list[float]: SOE values for optimized hours
        """
        hourly_data = self.get_hourly_data()
        return [h.battery_soc_end for h in hourly_data]

    def get_summary_info(self) -> str:
        """Get a summary string for logging.

        Returns:
            str: Human-readable summary of this schedule
        """
        start_hour, end_hour = self.get_optimization_range()
        savings = self.get_total_savings()

        return (
            f"{self.created_for_scenario} schedule from {start_hour:02d}:00-{end_hour:02d}:00, "
            f"savings: {savings:.2f} SEK"
        )


class ScheduleStore:
    """Storage for all optimization results throughout the day.

    CLEAN ARCHITECTURE: Now works directly with OptimizationResult objects.
    No conversions needed - unified data flow throughout the system.
    """

    def __init__(self):
        """Initialize the schedule store."""
        self._schedules: list[StoredSchedule] = []
        self._current_date: date | None = None

        logger.info("Initialized ScheduleStore with unified data structures")

    def store_schedule(
        self,
        optimization_result: OptimizationResult,
        optimization_hour: int,
        scenario: str,
    ) -> StoredSchedule:
        """Store a new optimization result.

        Args:
            optimization_result: OptimizationResult from optimize_battery_schedule()
            optimization_hour: Hour optimization started from (0-23)
            scenario: Why this optimization was performed (any string)

        Returns:
            StoredSchedule: The stored schedule object

        Raises:
            ValueError: If parameters are invalid
        """
        # Validate inputs
        if not isinstance(optimization_result, OptimizationResult):
            raise ValueError("optimization_result must be an OptimizationResult object")

        if not 0 <= optimization_hour <= 23:
            raise ValueError(f"optimization_hour must be 0-23, got {optimization_hour}")

        # Create the stored schedule - no scenario validation or mapping
        stored_schedule = StoredSchedule(
            timestamp=datetime.now(),
            optimization_hour=optimization_hour,
            optimization_result=optimization_result,
            created_for_scenario=scenario,
        )

        # Add to our list
        self._schedules.append(stored_schedule)
        self._current_date = stored_schedule.timestamp.date()

        logger.info("Stored new schedule: %s", stored_schedule.get_summary_info())

        return stored_schedule

    def store_optimization_result(
        self,
        optimization_hour: int,
        optimization_result: OptimizationResult,
        scenario: str,
    ) -> StoredSchedule:
        """Store optimization result directly - just calls store_schedule with parameter order."""
        return self.store_schedule(optimization_result, optimization_hour, scenario)

    def get_latest_schedule(self) -> StoredSchedule | None:
        """Get the most recently created schedule.

        Returns:
            StoredSchedule | None: Latest schedule, or None if no schedules stored
        """
        if not self._schedules:
            return None

        return max(self._schedules, key=lambda s: s.timestamp)

    def get_schedule_at_time(self, target_time: datetime) -> StoredSchedule | None:
        """Get schedule that was active at a specific time.

        Args:
            target_time: Time to query

        Returns:
            StoredSchedule | None: Schedule active at that time, or None
        """
        # Find the most recent schedule before or at the target time
        valid_schedules = [s for s in self._schedules if s.timestamp <= target_time]

        if not valid_schedules:
            return None

        return max(valid_schedules, key=lambda s: s.timestamp)

    def get_all_schedules_today(self) -> list[StoredSchedule]:
        """Get all schedules created today.

        Returns:
            list[StoredSchedule]: All schedules for today, ordered by timestamp
        """
        today = datetime.now().date()
        today_schedules = [s for s in self._schedules if s.timestamp.date() == today]

        return sorted(today_schedules, key=lambda s: s.timestamp)

    def get_schedule_count(self) -> int:
        """Get total number of stored schedules.

        Returns:
            int: Number of stored schedules
        """
        return len(self._schedules)

    def clear_old_schedules(self, days_to_keep: int = 7) -> int:
        """Clear schedules older than specified days.

        Args:
            days_to_keep: Number of days to keep (default: 7)

        Returns:
            int: Number of schedules cleared
        """
        cutoff_date = datetime.now().date()
        cutoff_date = cutoff_date.replace(day=cutoff_date.day - days_to_keep)

        original_count = len(self._schedules)
        self._schedules = [
            s for s in self._schedules if s.timestamp.date() >= cutoff_date
        ]

        cleared_count = original_count - len(self._schedules)
        if cleared_count > 0:
            logger.info(
                f"Cleared {cleared_count} old schedules (keeping {days_to_keep} days)"
            )

        return cleared_count

    def clear_all_schedules(self) -> int:
        """Clear all stored schedules.

        Returns:
            int: Number of schedules cleared
        """
        count = len(self._schedules)
        self._schedules.clear()
        self._current_date = None

        logger.info(f"Cleared all {count} schedules")
        return count

    def get_current_date(self) -> date | None:
        """Get the current date for stored schedules.

        Returns:
            date | None: Current date, or None if no schedules stored
        """
        return self._current_date

    def get_summary_stats(self) -> dict[str, Any]:
        """Get summary statistics for stored schedules.

        Returns:
            dict[str, Any]: Summary statistics
        """
        if not self._schedules:
            return {}

        total_schedules = len(self._schedules)
        scenarios = [s.created_for_scenario for s in self._schedules]
        scenario_counts = {
            scenario: scenarios.count(scenario)
            for scenario in ["tomorrow", "hourly", "restart"]
        }

        latest_schedule = self.get_latest_schedule()
        total_savings = sum(s.get_total_savings() for s in self._schedules)

        return {
            "total_schedules": total_schedules,
            "scenario_counts": scenario_counts,
            "latest_schedule_time": (
                latest_schedule.timestamp if latest_schedule else None
            ),
            "total_savings_all_schedules": total_savings,
            "current_date": self._current_date,
        }
