"""Persistent per-day savings history.

Stores the full DailyView (all periods: energy, economic, decision data) for
each calendar day, so week/month/year aggregates can be computed later and
full daily detail isn't thrown away. Unlike HistoricalDataStore/
PredictionSnapshotStore, this store is never cleared at day rollover — one
file accumulates per day, kept forever until a user clears it.

Reuses DailyViewBuilder's DailyView (de)serialization helpers rather
than duplicating that logic — see _daily_view_from_dict in daily_view_builder.py.
"""

import json
import logging
import os
from dataclasses import asdict
from datetime import date
from pathlib import Path

from . import time_utils
from .daily_view_builder import DailyView, _daily_view_from_dict

logger = logging.getLogger(__name__)

PERSIST_DIR = Path("/data/daily_views")


def _load_container(path: Path) -> dict:
    """Read a per-day file's JSON container, or {} if missing/corrupt."""
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not load %s: %s", path, e)
        return {}


def _write_container(path: Path, container: dict) -> None:
    """Atomically write a per-day file's JSON container (temp file + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(container, f, default=str)
    os.replace(tmp_path, path)


class DailyViewStore:
    """Persists one full DailyView per day as an individual JSON file."""

    def __init__(self, persist_dir: Path = PERSIST_DIR):
        self._persist_dir = persist_dir

    def _is_today(self, path: Path) -> bool:
        return path.stem == time_utils.today().isoformat()

    def save_day(self, view: DailyView) -> None:
        """Persist the given day's full view, overwriting any existing file for that date."""
        path = self._persist_dir / f"{view.date.isoformat()}.json"
        try:
            container = _load_container(path)
            container["view"] = asdict(view)
            _write_container(path, container)
        except OSError as e:
            logger.warning("Failed to persist daily view for %s: %s", view.date, e)

    def load_day(self, day: date) -> DailyView | None:
        """Load the persisted view for a specific day, or None if not saved."""
        path = self._persist_dir / f"{day.isoformat()}.json"
        container = _load_container(path)
        if not container:
            return None

        view_dict = container.get("view")
        if view_dict is None:
            # Legacy pre-consolidation flat file: the whole container IS the
            # view dict (written before "view"/"snapshots" wrapper existed).
            if "date" in container and "periods" in container:
                view_dict = container
            else:
                return None

        try:
            return _daily_view_from_dict(view_dict)
        except (KeyError, ValueError) as e:
            logger.warning("Could not parse daily view %s: %s", path, e)
            return None

    def list_available_dates(self) -> list[str]:
        """Return ISO dates that have a saved snapshot, sorted ascending.

        Excludes today — today's file is a live write-through cache, not a
        completed day's history entry.
        """
        if not self._persist_dir.exists():
            return []
        return sorted(
            p.stem for p in self._persist_dir.glob("*.json") if not self._is_today(p)
        )

    def get_disk_usage(self) -> dict:
        """Return {"day_count": int, "total_bytes": int} for saved snapshots, excluding today."""
        if not self._persist_dir.exists():
            return {"day_count": 0, "total_bytes": 0}
        files = [f for f in self._persist_dir.glob("*.json") if not self._is_today(f)]
        return {
            "day_count": len(files),
            "total_bytes": sum(f.stat().st_size for f in files),
        }

    def clear_all(self) -> None:
        """Delete every saved snapshot except today's."""
        if not self._persist_dir.exists():
            return
        for f in self._persist_dir.glob("*.json"):
            if not self._is_today(f):
                f.unlink()
