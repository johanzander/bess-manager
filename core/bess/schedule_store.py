"""
ScheduleStore - Storage for all optimization results throughout the day.

"""

import logging
from dataclasses import dataclass
from datetime import date, datetime

from core.bess.models import OptimizationResult

logger = logging.getLogger(__name__)


@dataclass
class StoredSchedule:
    """Container for a stored optimization result with metadata."""

    timestamp: datetime
    optimization_period: int  # Period optimization started from
    optimization_result: OptimizationResult  # Direct storage of OptimizationResult


    def get_total_savings(self) -> float:
        """Get total savings from optimization results."""
        if self.optimization_result.economic_summary is None:
            raise ValueError("OptimizationResult missing economic_summary")
        return self.optimization_result.economic_summary.grid_to_battery_solar_savings


class ScheduleStore:
    """Storage for all optimization results throughout the day."""

    def __init__(self):
        """Initialize the schedule store."""
        self._schedules: list[StoredSchedule] = []
        self._current_date: date | None = None

        logger.debug("Initialized ScheduleStore")

    def store_schedule(
        self,
        optimization_result: OptimizationResult,
        optimization_period: int
    ) -> StoredSchedule:
        """Store a new optimization result.

        Args:
            optimization_result: OptimizationResult from optimize_battery_schedule()
            optimization_period: Period optimization started from (0-95)

        Returns:
            StoredSchedule: The stored schedule object

        Raises:
            ValueError: If parameters are invalid
        """
        # Validate inputs
        if not isinstance(optimization_result, OptimizationResult):
            raise ValueError("optimization_result must be an OptimizationResult object")

        if optimization_period < 0:
            raise ValueError(f"optimization_period must be non-negative, got {optimization_period}")

        # Create the stored schedule
        stored_schedule = StoredSchedule(
            timestamp=datetime.now(),
            optimization_period=optimization_period,
            optimization_result=optimization_result
        )

        # Add to our list
        self._schedules.append(stored_schedule)
        self._current_date = stored_schedule.timestamp.date()

        return stored_schedule

    def get_latest_schedule(self) -> StoredSchedule | None:
        """Get the most recently created schedule.

        Returns:
            StoredSchedule | None: Latest schedule, or None if no schedules stored
        """
        if not self._schedules:
            return None

        return max(self._schedules, key=lambda s: s.timestamp)

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
