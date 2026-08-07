"""PredictionSnapshotStore - Storage for prediction vs actual tracking.

Stores snapshots of predictions and actuals throughout the day for deviation
analysis. Leverages DailyView for consistent data representation.
Persists to disk in the shared per-day file owned by DailyViewStore, so
snapshots survive restarts and are kept per calendar day forever (same
retention as DailyViewStore) until a user clears the history. Only the
in-memory snapshot list is per-day: it rolls over on date change.
"""

import logging
import threading
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from core.bess import time_utils
from core.bess.daily_view_builder import (
    DailyView,
    _daily_view_from_dict,
)
from core.bess.daily_view_store import container_transaction, read_container

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
    add-on restarts. The in-memory list holds a single calendar day and rolls
    over automatically on date change — the store is long-lived (constructed
    once per process), so it re-checks the current date on every public access
    rather than relying on an external clear() at midnight.
    """

    def __init__(self, persist_dir: Path = PERSIST_DIR):
        """Initialize the prediction snapshot store and load any persisted data."""
        self._snapshots: list[PredictionSnapshot] = []
        self._persist_dir = persist_dir
        self._current_date: date = time_utils.today()
        # Guards self._current_date/self._snapshots across the day-rollover
        # check and the read/mutate/save that follows it in each public
        # method — container_lock (daily_view_store.py) only protects the
        # file, not this in-memory state, so scheduler-thread and
        # request-thread calls must not interleave here either.
        self._instance_lock = threading.Lock()
        self._load_from_disk()
        logger.debug("Initialized PredictionSnapshotStore")

    def _today_path(self) -> Path:
        return self._persist_dir / f"{self._current_date.isoformat()}.json"

    def _ensure_current_day(self) -> None:
        """Roll the in-memory snapshot list over when the calendar day changes.

        This store outlives any single day (it is created once at process
        start), so every public read/write re-anchors it to today before
        touching self._snapshots.
        """
        today = time_utils.today()
        if today == self._current_date:
            return

        logger.info(
            "Prediction snapshot day rollover: %s -> %s (discarding %d in-memory snapshots)",
            self._current_date,
            today,
            len(self._snapshots),
        )
        self._current_date = today
        # A new day's file normally has no snapshots yet; reloading also
        # recovers any written earlier today by a previous process.
        self._load_from_disk()

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

        with self._instance_lock:
            self._ensure_current_day()
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
        with self._instance_lock:
            self._ensure_current_day()
            return sorted(self._snapshots, key=lambda s: s.snapshot_timestamp)

    def get_snapshot_at_period(self, period: int) -> PredictionSnapshot | None:
        """Get snapshot closest to specified period.

        Args:
            period: Period index (0-95) to find snapshot for

        Returns:
            PredictionSnapshot | None: Closest snapshot, or None if no snapshots
        """
        with self._instance_lock:
            self._ensure_current_day()
            if not self._snapshots:
                return None

            # Find snapshot with optimization_period closest to target period
            closest_snapshot = min(
                self._snapshots,
                key=lambda s: abs(s.optimization_period - period),
            )

            return closest_snapshot

    def clear(self) -> None:
        """Clear all stored snapshots, in memory and in today's file.

        Optional manual reset (e.g. a user-triggered history wipe). Day
        rollover no longer depends on this: the store discards the previous
        day's in-memory snapshots automatically when the date changes.
        """
        with self._instance_lock:
            self._ensure_current_day()
            self._snapshots.clear()
            self._save_to_disk()
        logger.info("Cleared all prediction snapshots")

    def get_snapshot_count(self) -> int:
        """Get count of stored snapshots.

        Returns:
            int: Number of snapshots stored
        """
        with self._instance_lock:
            self._ensure_current_day()
            return len(self._snapshots)

    def _save_to_disk(self) -> None:
        """Persist snapshots to today's shared per-day file."""
        path = self._today_path()
        try:
            with container_transaction(path) as container:
                container["snapshots"] = [asdict(s) for s in self._snapshots]
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
        container = read_container(path)
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
