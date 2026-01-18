"""
ScheduleStore - Storage for all optimization results throughout the day.

Includes JSON persistence to survive restarts.
"""

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from core.bess.models import OptimizationResult

logger = logging.getLogger(__name__)

# Persistence path for strategic intents (survives restart)
PERSIST_PATH = Path("/config/bess_strategic_intents.json")


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
    """Storage for all optimization results throughout the day.

    Also persists strategic intents to JSON file for restart recovery.
    """

    def __init__(self, persist_path: Path | None = None):
        """Initialize the schedule store.

        Args:
            persist_path: Optional custom path for persistence file (for testing)
        """
        self._schedules: list[StoredSchedule] = []
        self._current_date: date | None = None
        self._persist_path = persist_path or PERSIST_PATH
        self._persisted_intents: dict[int, str] = {}  # period -> intent

        # Load persisted intents on startup
        self._load_from_disk()

        logger.debug("Initialized ScheduleStore")

    def store_schedule(
        self, optimization_result: OptimizationResult, optimization_period: int
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
            raise ValueError(
                f"optimization_period must be non-negative, got {optimization_period}"
            )

        # Create the stored schedule
        stored_schedule = StoredSchedule(
            timestamp=datetime.now(),
            optimization_period=optimization_period,
            optimization_result=optimization_result,
        )

        # Add to our list
        self._schedules.append(stored_schedule)
        self._current_date = stored_schedule.timestamp.date()

        # Persist to disk for restart recovery
        self._save_to_disk()

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

    def get_persisted_intent(self, period: int) -> str | None:
        """Get a persisted strategic intent for a period.

        Use this on startup to recover DP-planned intents before new optimization runs.

        Args:
            period: Period index (0-95)

        Returns:
            Strategic intent string if available, None otherwise
        """
        return self._persisted_intents.get(period)

    def _save_to_disk(self) -> None:
        """Persist today's strategic intents to survive restart.

        Stores minimal data: date and period->intent mapping.
        """
        if not self._schedules:
            return

        # Build intent map from all stored schedules
        period_intents: dict[int, str] = {}
        for stored in self._schedules:
            result = stored.optimization_result
            if not result.period_data:
                continue

            opt_period = stored.optimization_period
            for i, period_data in enumerate(result.period_data):
                target_period = opt_period + i
                if target_period < 96:
                    period_intents[target_period] = (
                        period_data.decision.strategic_intent
                    )

        # Store with date for validation on load
        data = {
            "date": datetime.now().date().isoformat(),
            "period_intents": {str(k): v for k, v in period_intents.items()},
        }

        try:
            # Ensure parent directory exists
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._persist_path, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(
                f"Persisted {len(period_intents)} strategic intents to {self._persist_path}"
            )
        except Exception as e:
            logger.warning(f"Failed to persist strategic intents: {e}")

    def _load_from_disk(self) -> None:
        """Load persisted intents on startup.

        Only loads if the persisted file is from today.
        """
        self._persisted_intents = {}

        if not self._persist_path.exists():
            logger.debug("No persisted intents file found")
            return

        try:
            with open(self._persist_path) as f:
                data = json.load(f)

            # Validate date - only use if from today
            stored_date = data.get("date")
            today = datetime.now().date().isoformat()
            if stored_date != today:
                logger.info(
                    f"Persisted intents from {stored_date} (not today {today}), discarding"
                )
                return

            # Load period intents
            period_intents = data.get("period_intents", {})
            self._persisted_intents = {int(k): v for k, v in period_intents.items()}
            logger.info(
                f"Loaded {len(self._persisted_intents)} persisted strategic intents from disk"
            )

        except Exception as e:
            logger.warning(f"Failed to load persisted intents: {e}")
