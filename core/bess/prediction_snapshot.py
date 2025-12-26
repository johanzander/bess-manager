"""PredictionSnapshotStore - Storage for prediction vs actual tracking.

Stores snapshots of predictions and actuals throughout the day for deviation
analysis. Leverages DailyView for consistent data representation.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from core.bess.daily_view_builder import DailyView

logger = logging.getLogger(__name__)


@dataclass
class PredictionSnapshot:
    """Snapshot of predictions and actuals at a specific optimization time.

    Leverages existing DailyView which already merges actuals + predictions.
    This allows us to track how predictions evolved and compare them against
    actual outcomes to diagnose performance deviations.
    """

    snapshot_timestamp: datetime
    optimization_period: int  # Period when optimization ran (0-95)
    daily_view: DailyView  # Combined view of actuals + predictions
    growatt_schedule: list[dict]  # TOU intervals applied at snapshot time
    predicted_daily_savings: float  # From EconomicSummary


class PredictionSnapshotStore:
    """In-memory storage for prediction snapshots throughout the day.

    Stores snapshots captured during each optimization to enable comparison
    of predicted vs actual outcomes. Cleared at midnight like HistoricalDataStore.
    """

    def __init__(self):
        """Initialize the prediction snapshot store."""
        self._snapshots: list[PredictionSnapshot] = []
        logger.debug("Initialized PredictionSnapshotStore")

    def store_snapshot(
        self,
        snapshot_timestamp: datetime,
        optimization_period: int,
        daily_view: DailyView,
        growatt_schedule: list[dict],
        predicted_daily_savings: float,
    ) -> PredictionSnapshot:
        """Store a new prediction snapshot.

        Args:
            snapshot_timestamp: When this snapshot was captured
            optimization_period: Period optimization started from (0-95)
            daily_view: DailyView with merged actuals + predictions
            growatt_schedule: TOU intervals at snapshot time
            predicted_daily_savings: Total predicted savings from optimization

        Returns:
            PredictionSnapshot: The stored snapshot object
        """
        snapshot = PredictionSnapshot(
            snapshot_timestamp=snapshot_timestamp,
            optimization_period=optimization_period,
            daily_view=daily_view,
            growatt_schedule=growatt_schedule.copy(),  # Copy to avoid mutations
            predicted_daily_savings=predicted_daily_savings,
        )

        self._snapshots.append(snapshot)

        logger.debug(
            "Stored snapshot at period %d: predicted savings %.2f SEK, %d periods, %d TOU intervals",
            optimization_period,
            predicted_daily_savings,
            len(daily_view.periods),
            len(growatt_schedule),
        )

        return snapshot

    def get_all_snapshots_today(self) -> list[PredictionSnapshot]:
        """Get all snapshots for current day, ordered by time.

        Returns:
            list[PredictionSnapshot]: All snapshots, chronologically ordered
        """
        return sorted(self._snapshots, key=lambda s: s.snapshot_timestamp)

    def get_snapshot_at_period(self, period: int) -> PredictionSnapshot | None:
        """Get snapshot closest to specified period.

        Args:
            period: Period index (0-95) to find snapshot for

        Returns:
            PredictionSnapshot | None: Closest snapshot, or None if no snapshots
        """
        if not self._snapshots:
            return None

        # Find snapshot with optimization_period closest to target period
        closest_snapshot = min(
            self._snapshots,
            key=lambda s: abs(s.optimization_period - period),
        )

        return closest_snapshot

    def clear(self) -> None:
        """Clear all stored snapshots.

        Called at midnight transition to prepare for next day.
        """
        self._snapshots.clear()
        logger.info("Cleared all prediction snapshots")

    def get_snapshot_count(self) -> int:
        """Get count of stored snapshots.

        Returns:
            int: Number of snapshots stored
        """
        return len(self._snapshots)
