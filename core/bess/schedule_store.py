"""
ScheduleStore - Storage for all optimization results throughout the day.

"""

import logging
from dataclasses import dataclass
from datetime import date, datetime

from core.bess.models import HourlyData, OptimizationResult

logger = logging.getLogger(__name__)


@dataclass
class StoredSchedule:
    """Container for a stored optimization result with metadata.

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

    def get_hourly_data(self) -> list[HourlyData]:
        """Get unified hourly data directly."""
        return self.optimization_result.hourly_data

    def get_total_savings(self) -> float:
        """Get total savings from optimization results."""
        return self.optimization_result.economic_summary.grid_to_battery_solar_savings


class ScheduleStore:
    """Storage for all optimization results throughout the day.

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


