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
import os
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from . import time_utils
from .daily_view_builder import DailyView
from .models import PeriodData
from .prediction_snapshot import _daily_view_from_dict

logger = logging.getLogger(__name__)

PERSIST_DIR = Path("/data/daily_views")


class DailyViewStore:
    """Persists one full DailyView per day as an individual JSON file."""

    def __init__(self, persist_dir: Path = PERSIST_DIR):
        self._persist_dir = persist_dir

    def _is_today(self, path: Path) -> bool:
        return path.stem == time_utils.today().isoformat()

    def save_day(self, view: DailyView) -> bool:
        """Persist the given day's full view, overwriting any existing file for that date."""
        temporary: Path | None = None
        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            path = self._persist_dir / f"{view.date.isoformat()}.json"
            # A crash or failed write must not destroy the previous snapshot.
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._persist_dir,
                suffix=".tmp",
                delete=False,
            ) as f:
                temporary = Path(f.name)
                json.dump(asdict(view), f, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
            return True
        except OSError as e:
            logger.warning("Failed to persist daily view for %s: %s", view.date, e)
            return False
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def finalize_period(self, day: date, period: PeriodData) -> bool:
        """Atomically replace a completed day's closing prediction with actuals."""
        if (
            day >= time_utils.today()
            or period.period != time_utils.get_period_count(day) - 1
            or period.data_source != "actual"
        ):
            raise ValueError(
                "Finalization requires an actual closing quarter of a completed day"
            )
        view = self.load_day(day)
        if view is None:
            return False
        if sum(p.period == period.period for p in view.periods) != 1:
            return False
        rows = [period if p.period == period.period else p for p in view.periods]
        return self.save_day(
            replace(
                view,
                periods=rows,
                actual_count=sum(p.data_source == "actual" for p in rows),
                predicted_count=sum(p.data_source == "predicted" for p in rows),
                missing_count=sum(p.data_source == "missing" for p in rows),
                total_savings=sum(p.economic.hourly_savings for p in rows),
                finalization_pending=False,
            )
        )

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
        try:
            return _daily_view_from_dict(data)
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
