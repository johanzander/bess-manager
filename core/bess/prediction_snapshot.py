"""PredictionSnapshotStore - Storage for prediction vs actual tracking.

Stores snapshots of predictions and actuals throughout the day for deviation
analysis. Leverages DailyView for consistent data representation.
Persists to disk in the shared per-day file owned by DailyViewStore (under the
"snapshots" key), so snapshots survive restarts within the day.

Retention is one day, on disk as well as in memory — the same lifecycle this
store had before #409, which consolidated the storage *format* only. Each
snapshot embeds a full DailyView and one is captured per optimization (~96/day),
so a day's file holds ~96x more snapshot data than view data; keeping that for
every day would take a year of /data from ~30 MB to ~2.9 GB. Yesterday's
snapshots are therefore pruned (see daily_view_store.prune_snapshots_before)
while the day's view — the actual history — is kept forever.
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
from core.bess.daily_view_store import (
    container_transaction,
    prune_snapshots_before,
    prune_snapshots_for_day,
    read_container,
)

logger = logging.getLogger(__name__)

PERSIST_DIR = Path("/data/daily_views")

# Pre-#409 location. Superseded by the shared per-day file; removed on startup
# so it does not linger on /data forever with nothing left to reference it.
LEGACY_PERSIST_PATH = Path("/data/bess_prediction_snapshots.json")


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
    add-on restarts. Retention is a single calendar day, in memory and on
    disk — the store is long-lived (constructed once per process), so it
    re-checks the current date on every public access and rolls over itself
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
        self._remove_legacy_persist_file()
        # A restart across midnight never runs the in-process rollover below,
        # so sweep on startup too — otherwise a crash or upgrade leaves an
        # earlier day's snapshots on disk permanently.
        prune_snapshots_before(self._persist_dir, self._current_date)
        self._load_from_disk()
        logger.debug("Initialized PredictionSnapshotStore")

    def _remove_legacy_persist_file(self) -> None:
        """Delete the pre-#409 standalone snapshot file if it is still around.

        Its contents are deliberately not migrated: it holds at most the
        current day's display/diagnostic snapshots, which the next optimization
        regenerates within 15 minutes.
        """
        if self._persist_dir != PERSIST_DIR:
            # The legacy file is an absolute /data path. A store pointed at a
            # different root (tests, an alternate data dir) does not own /data
            # and must not delete anything there.
            return
        try:
            if LEGACY_PERSIST_PATH.exists():
                LEGACY_PERSIST_PATH.unlink()
                logger.info(
                    "Removed superseded snapshot file %s (now stored per-day)",
                    LEGACY_PERSIST_PATH,
                )
        except OSError as e:
            logger.warning("Could not remove %s: %s", LEGACY_PERSIST_PATH, e)

    def _today_path(self) -> Path:
        return self._persist_dir / f"{self._current_date.isoformat()}.json"

    def _ensure_current_day(self, as_of: date | None = None) -> None:
        """Roll the in-memory snapshot list over when the calendar day changes.

        This store outlives any single day (it is created once at process
        start), so every public read/write re-anchors it before touching
        self._snapshots.

        `as_of` anchors to the day a snapshot describes rather than to the wall
        clock. A snapshot stamped at 23:59:5x can reach the write a moment after
        midnight (slow optimization, contended lock); it belongs in its own
        day's file, not the new day's.
        """
        target = as_of or time_utils.today()
        if target == self._current_date:
            return

        logger.info(
            "Prediction snapshot day rollover: %s -> %s (discarding %d in-memory snapshots)",
            self._current_date,
            target,
            len(self._snapshots),
        )
        previous_date = self._current_date
        self._current_date = target
        # The day just ended has served its purpose; keep only its view. Scoped
        # to that one file — the startup sweep is what handles missed days.
        if target > previous_date:
            prune_snapshots_for_day(self._persist_dir, previous_date)
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
            # Anchored to the snapshot's own timestamp, not the wall clock:
            # see _ensure_current_day().
            self._ensure_current_day(as_of=snapshot_timestamp.date())
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
        except Exception as e:
            # Best-effort by contract: snapshots are display/diagnostic data,
            # and this runs on the optimization tick. A disk problem must not
            # abort the tick's hardware write.
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
        except Exception as e:
            # Best-effort by contract. This runs from __init__ *and* from
            # _ensure_current_day() inside every public accessor, so a single
            # schema-shifted entry must not abort BatterySystemManager
            # construction or 500 the prediction-analysis endpoints.
            logger.warning("Failed to load persisted prediction snapshots: %s", e)
            self._snapshots = []
