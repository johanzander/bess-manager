"""PredictionSnapshotStore - Storage for prediction vs actual tracking.

Stores snapshots of predictions and actuals throughout the day for deviation
analysis. Leverages DailyView for consistent data representation.
Persists to disk so snapshots survive restarts within the same day.
"""

import dataclasses
import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from core.bess import time_utils
from core.bess.daily_view_builder import DailyView
from core.bess.models import (
    DecisionData,
    EconomicData,
    EnergyData,
    PeriodData,
)

logger = logging.getLogger(__name__)

PERSIST_PATH = Path("/data/bess_prediction_snapshots.json")


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


def _period_data_from_dict(d: dict) -> PeriodData:
    """Deserialize a PeriodData from a dict produced by dataclasses.asdict()."""
    energy_init_fields = {f.name for f in dataclasses.fields(EnergyData) if f.init}
    energy = EnergyData(
        **{k: v for k, v in d["energy"].items() if k in energy_init_fields}
    )

    economic_fields = {f.name for f in dataclasses.fields(EconomicData) if f.init}
    economic = EconomicData(
        **{k: v for k, v in d["economic"].items() if k in economic_fields}
    )

    decision_fields = {f.name for f in dataclasses.fields(DecisionData) if f.init}
    decision = DecisionData(
        **{k: v for k, v in d["decision"].items() if k in decision_fields}
    )

    ts_raw = d["timestamp"]
    ts = datetime.fromisoformat(ts_raw) if ts_raw else None

    return PeriodData(
        period=d["period"],
        energy=energy,
        timestamp=ts,
        data_source=d["data_source"],
        economic=economic,
        decision=decision,
    )


def _daily_view_from_dict(d: dict) -> DailyView:
    """Deserialize a DailyView from a dict produced by dataclasses.asdict()."""
    periods = [_period_data_from_dict(p) for p in d["periods"]]
    return DailyView(
        date=date.fromisoformat(d["date"]),
        periods=periods,
        total_savings=d["total_savings"],
        actual_count=d["actual_count"],
        predicted_count=d["predicted_count"],
        missing_count=d.get("missing_count", 0),
    )


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

    def __init__(self, persist_path: Path = PERSIST_PATH):
        """Initialize the prediction snapshot store and load any persisted data."""
        self._snapshots: list[PredictionSnapshot] = []
        self._persist_path = persist_path
        self._load_from_disk()
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
        """Persist snapshots to disk to survive restarts."""
        data = {
            "date": time_utils.today().isoformat(),
            "snapshots": [asdict(s) for s in self._snapshots],
        }

        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)

            # Serialize with default=str to handle datetime and date objects
            with open(self._persist_path, "w") as f:
                json.dump(data, f, default=str)

            logger.debug(
                "Persisted %d prediction snapshots to %s",
                len(self._snapshots),
                self._persist_path,
            )
        except Exception as e:
            logger.warning("Failed to persist prediction snapshots: %s", e)

    def _load_from_disk(self) -> None:
        """Load persisted snapshots on startup.

        Only loads if the persisted file is from today.
        """
        if not self._persist_path.exists():
            logger.debug("No persisted snapshots file found")
            return

        try:
            with open(self._persist_path) as f:
                data = json.load(f)

            # Validate date — only use if from today
            stored_date = data.get("date")
            today = time_utils.today().isoformat()
            if stored_date != today:
                logger.info(
                    "Persisted snapshots from %s (not today %s), discarding",
                    stored_date,
                    today,
                )
                return

            raw_snapshots = data.get("snapshots", [])
            self._snapshots = [_snapshot_from_dict(s) for s in raw_snapshots]
            logger.info(
                "Loaded %d persisted prediction snapshots from disk",
                len(self._snapshots),
            )
        except Exception as e:
            logger.warning("Failed to load persisted prediction snapshots: %s", e)
