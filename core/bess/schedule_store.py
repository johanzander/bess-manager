"""
ScheduleStore - Storage for all optimization results throughout the day.

This module provides the ScheduleStore class that stores every optimization
result created during the day. Each stored schedule contains the raw algorithm
output with metadata about when and why it was created.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StoredSchedule:
    """Container for a stored optimization result with metadata.

    This stores the raw output from optimize_battery_schedule() along with
    context about when and why the optimization was performed.
    """

    timestamp: datetime
    optimization_hour: int  # Hour optimization started from (0-23)
    algorithm_result: dict[str, Any]  # Raw result from optimize_battery_schedule()
    created_for_scenario: str  # "tomorrow", "hourly", "restart"

    def get_optimization_range(self) -> tuple[int, int]:
        """Get the hour range that was optimized.

        Returns:
            tuple[int, int]: (start_hour, end_hour) inclusive
        """
        if self.created_for_scenario == "tomorrow":
            return (0, 23)  # Full day optimization
        else:
            return (self.optimization_hour, 23)  # Partial day optimization

    def get_hourly_actions(self) -> list[float]:
        """Get battery actions from the algorithm result.

        Returns:
            list[float]: Battery actions for optimized hours only
        """
        try:
            return self.algorithm_result["hourly_data"]["battery_action"]
        except KeyError:
            logger.warning("No battery_action found in algorithm result")
            return []

    def get_hourly_soe(self) -> list[float]:
        """Get state of energy values from the algorithm result.

        Returns:
            list[float]: SOE values for optimized hours only
        """
        try:
            return self.algorithm_result["hourly_data"]["state_of_charge"]
        except KeyError:
            logger.warning("No state_of_charge found in algorithm result")
            return []

    def get_total_savings(self) -> float:
        """Get total savings from the algorithm result.

        Returns:
            float: Total savings in SEK for the optimized period
        """
        try:
            return self.algorithm_result["economic_results"][
                "solar_to_battery_solar_savings"
            ]
        except KeyError:
            logger.warning("No savings data found in algorithm result")
            return 0.0

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
    """Storage for all optimization results created during the day.

    This class maintains a chronological record of every schedule optimization
    performed. Each schedule contains the raw algorithm output plus metadata
    about when and why it was created.
    """

    def __init__(self):
        """Initialize the schedule store."""
        self._schedules: list[StoredSchedule] = []
        self._current_date: date | None = None

        logger.info("Initialized ScheduleStore")

    def store_schedule(
        self, algorithm_result: dict[str, Any], optimization_hour: int, scenario: str
    ) -> StoredSchedule:
        """Store a new optimization result.

        Args:
            algorithm_result: Raw output from optimize_battery_schedule()
            optimization_hour: Hour optimization started from (0-23)
            scenario: Why this optimization was performed ("tomorrow", "hourly", "restart")

        Returns:
            StoredSchedule: The stored schedule object

        Raises:
            ValueError: If parameters are invalid
        """
        # Validate inputs
        if not isinstance(algorithm_result, dict):
            raise ValueError("algorithm_result must be a dictionary")

        if not 0 <= optimization_hour <= 23:
            raise ValueError(f"optimization_hour must be 0-23, got {optimization_hour}")

        valid_scenarios = ["tomorrow", "hourly", "restart"]
        if scenario not in valid_scenarios:
            raise ValueError(
                f"scenario must be one of {valid_scenarios}, got {scenario}"
            )

        # Validate that algorithm_result has expected structure
        if "hourly_data" not in algorithm_result:
            raise ValueError("algorithm_result missing 'hourly_data' key")

        if "economic_results" not in algorithm_result:
            raise ValueError("algorithm_result missing 'economic_results' key")

        # Create the stored schedule
        stored_schedule = StoredSchedule(
            timestamp=datetime.now(),
            optimization_hour=optimization_hour,
            algorithm_result=algorithm_result,
            created_for_scenario=scenario,
        )

        # Add to our list
        self._schedules.append(stored_schedule)
        self._current_date = stored_schedule.timestamp.date()

        logger.info("Stored new schedule: %s", stored_schedule.get_summary_info())

        return stored_schedule

    def get_latest_schedule(self) -> StoredSchedule | None:
        """Get the most recently created schedule.

        Returns:
            Optional[StoredSchedule]: Latest schedule, or None if no schedules stored
        """
        if not self._schedules:
            return None

        return self._schedules[-1]

    def get_schedule_at_time(self, target_time: datetime) -> StoredSchedule | None:
        """Get the schedule that was active at a specific time.

        This returns the most recent schedule created before or at the target time.

        Args:
            target_time: Time to look up schedule for

        Returns:
            Optional[StoredSchedule]: Schedule active at target time, or None
        """
        if not self._schedules:
            return None

        # Find the most recent schedule before or at the target time
        valid_schedules = [s for s in self._schedules if s.timestamp <= target_time]

        if not valid_schedules:
            return None

        return max(valid_schedules, key=lambda s: s.timestamp)

    def get_all_schedules_today(self) -> list[StoredSchedule]:
        """Get all schedules created today in chronological order.

        Returns:
            list[StoredSchedule]: All schedules for today, ordered by creation time
        """
        return self._schedules.copy()  # Return a copy to prevent external modification

    def get_schedules_by_scenario(self, scenario: str) -> list[StoredSchedule]:
        """Get all schedules created for a specific scenario.

        Args:
            scenario: Scenario to filter by ("tomorrow", "hourly", "restart")

        Returns:
            list[StoredSchedule]: Schedules matching the scenario
        """
        return [s for s in self._schedules if s.created_for_scenario == scenario]

    def get_schedule_count(self) -> int:
        """Get the total number of schedules stored.

        Returns:
            int: Number of schedules stored
        """
        return len(self._schedules)

    def reset_for_new_day(self) -> None:
        """Clear all schedules for a new day.

        This should be called at midnight to start fresh for the new day.
        """
        schedules_cleared = len(self._schedules)
        self._schedules.clear()
        self._current_date = None

        logger.info(
            "Schedule store reset for new day (%d schedules cleared)", schedules_cleared
        )

    def get_current_date(self) -> date | None:
        """Get the date for which schedules are currently stored.

        Returns:
            Optional[date]: Current date, or None if no schedules stored
        """
        return self._current_date

    def log_daily_summary(self) -> None:
        """Log a summary of all stored schedules for the day."""
        if not self._schedules:
            logger.info("No schedules stored for today")
            return

        # Count schedules by scenario
        scenario_counts = {}
        for schedule in self._schedules:
            scenario = schedule.created_for_scenario
            scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1

        # Get latest schedule info
        latest = self.get_latest_schedule()
        latest_summary = latest.get_summary_info() if latest else "None"

        logger.info(
            "\n%s\n"
            "Schedule Store Summary for %s\n"
            "%s\n"
            "Total schedules created: %d\n"
            "Breakdown by scenario: %s\n"
            "Latest schedule: %s\n"
            "%s",
            "=" * 60,
            self._current_date or "Unknown",
            "=" * 60,
            len(self._schedules),
            ", ".join(
                [f"{scenario}: {count}" for scenario, count in scenario_counts.items()]
            ),
            latest_summary,
            "=" * 60,
        )

        # Log each schedule briefly
        logger.info("Schedule chronology:")
        for i, schedule in enumerate(self._schedules):
            logger.info(
                "  %d. %s at %s",
                i + 1,
                schedule.get_summary_info(),
                schedule.timestamp.strftime("%H:%M:%S"),
            )
