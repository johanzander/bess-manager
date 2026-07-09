"""Persistent per-day savings history.

Stores the full DailyView (all periods: energy, economic, decision data) for
each calendar day, so week/month/year aggregates can be computed later and
full daily detail isn't thrown away. Unlike HistoricalDataStore/
PredictionSnapshotStore, this store is never cleared at day rollover — one
file accumulates per day, kept forever until a user clears it.

Reuses PredictionSnapshotStore's DailyView (de)serialization helpers rather
than duplicating that logic — see _daily_view_from_dict in prediction_snapshot.py.
"""

import json
import logging
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .daily_view_builder import DailyView
from .prediction_snapshot import _daily_view_from_dict

logger = logging.getLogger(__name__)

PERSIST_DIR = Path("/data/daily_views")


class DailyViewStore:
    """Persists one full DailyView per day as an individual JSON file."""

    def __init__(self, persist_dir: Path = PERSIST_DIR):
        self._persist_dir = persist_dir

    def save_day(self, view: DailyView) -> None:
        """Persist the given day's full view, overwriting any existing file for that date."""
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        path = self._persist_dir / f"{view.date.isoformat()}.json"
        with open(path, "w") as f:
            json.dump(asdict(view), f, default=str)

    def load_day(self, day: date) -> DailyView | None:
        """Load the persisted view for a specific day, or None if not saved."""
        path = self._persist_dir / f"{day.isoformat()}.json"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not load %s: %s", path, e)
            return None
        return _daily_view_from_dict(data)

    def list_available_dates(self) -> list[str]:
        """Return ISO dates that have a saved snapshot, sorted ascending."""
        if not self._persist_dir.exists():
            return []
        return sorted(p.stem for p in self._persist_dir.glob("*.json"))

    def get_disk_usage(self) -> dict:
        """Return {"day_count": int, "total_bytes": int} for the saved snapshots."""
        if not self._persist_dir.exists():
            return {"day_count": 0, "total_bytes": 0}
        files = list(self._persist_dir.glob("*.json"))
        return {
            "day_count": len(files),
            "total_bytes": sum(f.stat().st_size for f in files),
        }

    def clear_all(self) -> None:
        """Delete every saved snapshot."""
        if not self._persist_dir.exists():
            return
        for f in self._persist_dir.glob("*.json"):
            f.unlink()
