"""PredictionSnapshotStore - Storage for prediction vs actual tracking.

Stores snapshots of predictions and actuals throughout the day for deviation
analysis. Leverages DailyView for consistent data representation.
Persists to disk so snapshots survive restarts within the same day.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from core.bess import time_utils
from core.bess.daily_view_builder import (
    DailyView,
    _daily_view_from_dict,
)
from core.bess.daily_view_store import _load_container, _write_container

logger = logging.getLogger(__name__)

PERSIST_DIR = Path("/data/daily_views")


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


def _snapshot_from_dict(d: dict) -> PredictionSnapshot:
    """Deserialize a PredictionSnapshot from a dict produced by asdict()."""
    return PredictionSnapshot(
        snapshot_timestamp=datetime.fromisoformat(d["snapshot_timestamp"]),
        optimization_period=d["optimization_period"],
        daily_view=_daily_view_from_dict(d["daily_view"]),
        growatt_schedule=d["growatt_schedule"],
        predicted_daily_savings=d["predicted_daily_savings"],
    )


class PredictionSnapshotStore:
    """Persistent storage for prediction snapshots throughout the day.

    Stores snapshots captured during each optimization to enable comparison
    of predicted vs actual outcomes. Persisted to disk so snapshots survive
    add-on restarts. Cleared at midnight like HistoricalDataStore.
    """

    def __init__(self, persist_dir: Path = PERSIST_DIR):
        """Initialize the prediction snapshot store and load any persisted data."""
        self._snapshots: list[PredictionSnapshot] = []
        self._persist_dir = persist_dir
        self._load_from_disk()
        logger.debug("Initialized PredictionSnapshotStore")

    def _today_path(self) -> Path:
        return self._persist_dir / f"{time_utils.today().isoformat()}.json"

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
        self._save_to_disk()

        logger.debug(
            "Stored snapshot at period %d: predicted savings %.2f, %d periods, %d TOU intervals",
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
        self._save_to_disk()
        logger.info("Cleared all prediction snapshots")

    def get_snapshot_count(self) -> int:
        """Get count of stored snapshots.

        Returns:
            int: Number of snapshots stored
        """
        return len(self._snapshots)

    def _save_to_disk(self) -> None:
        """Persist snapshots to today's shared per-day file."""
        path = self._today_path()
        try:
            container = _load_container(path)
            container["snapshots"] = [asdict(s) for s in self._snapshots]
            _write_container(path, container)
            logger.debug(
                "Persisted %d prediction snapshots to %s",
                len(self._snapshots),
                path,
            )
        except OSError as e:
            logger.warning("Failed to persist prediction snapshots: %s", e)

    def _load_from_disk(self) -> None:
        """Load today's persisted snapshots from the shared per-day file."""
        path = self._today_path()
        container = _load_container(path)
        raw_snapshots = container.get("snapshots", [])
        try:
            self._snapshots = [_snapshot_from_dict(s) for s in raw_snapshots]
            if self._snapshots:
                logger.info(
                    "Loaded %d persisted prediction snapshots from disk",
                    len(self._snapshots),
                )
        except (KeyError, ValueError) as e:
            logger.warning("Failed to load persisted prediction snapshots: %s", e)
            self._snapshots = []
