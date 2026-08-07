"""Persistent per-day savings history.

Stores the full DailyView (all periods: energy, economic, decision data) for
each calendar day, so week/month/year aggregates can be computed later and
full daily detail isn't thrown away. Unlike HistoricalDataStore, this store is
never cleared at day rollover — one file accumulates per day, kept forever
until a user clears it. PredictionSnapshotStore shares the same per-day file
(under the "snapshots" key) and the same forever-retention on disk; only its
in-memory cache resets on date change.

Reuses DailyViewBuilder's DailyView (de)serialization helpers rather
than duplicating that logic — see _daily_view_from_dict in daily_view_builder.py.
"""

import json
import logging
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path

from . import time_utils
from .daily_view_builder import DailyView, _daily_view_from_dict

logger = logging.getLogger(__name__)

PERSIST_DIR = Path("/data/daily_views")

# Process-wide lock serializing the load -> mutate -> write cycle on the shared
# per-day container files. DailyViewStore and PredictionSnapshotStore both write
# into the same {date}.json from different threads (scheduler jobs vs FastAPI
# request handlers), so an unguarded read-modify-write would lose updates.
# A single lock (rather than one per file) is fine: writes happen roughly every
# 15 minutes, plus one per stored snapshot.
container_lock = threading.RLock()


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


def _cleanup_stale_temp_files(path: Path) -> None:
    """Best-effort removal of orphaned temp files left by a crashed write.

    Temp files use a unique per-call name, so a failed write leaves a sibling
    that no *.json glob (housekeeping, disk usage, clear_all) will ever see.
    """
    try:
        for stale in path.parent.glob(f"{path.stem}.*.tmp"):
            stale.unlink()
    except OSError as e:
        logger.debug("Could not clean up stale temp files for %s: %s", path, e)


def _write_container(path: Path, container: dict) -> None:
    """Atomically write a per-day file's JSON container (temp file + replace).

    The temp file name is unique per call (pid + uuid) so two concurrent
    writers can never open/truncate the same temp path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _cleanup_stale_temp_files(path)
    tmp_path = path.parent / f"{path.stem}.{os.getpid()}-{uuid.uuid4().hex}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(container, f, default=str)
    os.replace(tmp_path, path)


@contextmanager
def container_transaction(path: Path) -> Iterator[dict]:
    """Load a per-day container, let the caller mutate it, then write it back.

    The whole read-modify-write cycle is held under `container_lock` so that
    concurrent writers to the same file cannot lose each other's keys.
    """
    with container_lock:
        container = _load_container(path)
        yield container
        _write_container(path, container)


def read_container(path: Path) -> dict:
    """Read a per-day container under the shared lock."""
    with container_lock:
        return _load_container(path)


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
            with container_transaction(path) as container:
                container["view"] = asdict(view)
        except OSError as e:
            logger.warning("Failed to persist daily view for %s: %s", view.date, e)

    def load_day(self, day: date) -> DailyView | None:
        """Load the persisted view for a specific day, or None if not saved."""
        path = self._persist_dir / f"{day.isoformat()}.json"
        container = read_container(path)
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
