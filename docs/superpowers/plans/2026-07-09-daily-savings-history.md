# Daily Savings History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist each day's full period-level savings data forever, and expose it as a week/month/year aggregate view (financial totals + energy-flow totals) on the Savings page, plus disk-usage visibility and a clear-history control in Settings.

**Architecture:** A new `DailyViewStore` (`core/bess/`) writes one JSON file per day at the existing 23:55 rollover point, reusing `PredictionSnapshotStore`'s already-proven `DailyView`/`PeriodData` (de)serialization helpers. A new pure `savings_aggregator` module sums those persisted days into week/month/year buckets. A new `GET /api/savings/aggregate` route (plus disk-usage/clear routes) exposes this to a new frontend hook and a new bar-chart/table component with a period toggle.

**Tech Stack:** Python (dataclasses, `core/bess/`), FastAPI (`backend/`), React/TypeScript + recharts (`frontend/`).

## Global Constraints

- Source of truth: `docs/superpowers/specs/2026-07-09-daily-savings-history-design.md` — read it if any ambiguity arises; this plan implements it exactly.
- Origin: GitHub issue #126, comment #4 (https://github.com/johanzander/bess-manager/issues/126).
- Explicitly OUT OF SCOPE (per spec — do not implement any of these): a per-day drill-down view, backfilling data from before this ships, archiving historical electricity prices separately, a payback/investment calculator, any change to `/api/dashboard`, `SavingsOverview`, `DetailedSavingsAnalysis`, or `useDashboardData`. Do not attempt to consolidate `DailyViewStore` with `HistoricalDataStore`/`PredictionSnapshotStore` — that is tracked separately in `TODO.md` under Technical Debt.
- `DailyViewStore` is never cleared automatically — no retention cap, no auto-pruning (per spec).
- Follow `docs/agents/patterns.md`: no new `api_models.py` (extend `backend/api_dataclasses.py`); wrap new dict API responses in `convert_keys_to_camel_case`.
- Follow `docs/agents/testing.md`: test behavior, not internal field counts; unit tests in `core/bess/tests/unit/` and `backend/tests/`.
- No new dependencies. JSON only (no SQLite, no changes to HA's Recorder DB).

---

### Task 1: `DailyViewStore` (core/bess)

**Files:**
- Create: `core/bess/daily_view_store.py`
- Test: `core/bess/tests/unit/test_daily_view_store.py`

**Interfaces:**
- Consumes: `DailyView` (`core.bess.daily_view_builder`, fields: `date: date`, `periods: list[PeriodData]`, `total_savings: float`, `actual_count: int`, `predicted_count: int`, `missing_count: int = 0`); `_daily_view_from_dict(d: dict) -> DailyView` (existing private helper, `core/bess/prediction_snapshot.py:75-85`, already proven to round-trip `DailyView`/`PeriodData` through `dataclasses.asdict()` + `json.dump(..., default=str)`).
- Produces: `DailyViewStore` class with `__init__(self, persist_dir: Path = PERSIST_DIR)`, `save_day(self, view: DailyView) -> None`, `load_day(self, day: date) -> DailyView | None`, `list_available_dates(self) -> list[str]`, `get_disk_usage(self) -> dict` (keys `"day_count"`, `"total_bytes"`), `clear_all(self) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# core/bess/tests/unit/test_daily_view_store.py
"""Unit tests for DailyViewStore."""

from datetime import date, datetime

from core.bess.daily_view_builder import DailyView
from core.bess.daily_view_store import DailyViewStore
from core.bess.models import EconomicData, EnergyData, PeriodData


def _make_period(period: int, grid_imported: float, grid_exported: float) -> PeriodData:
    energy = EnergyData(
        solar_production=1.0,
        home_consumption=grid_imported,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=grid_imported,
        grid_exported=grid_exported,
        battery_soe_start=10.0,
        battery_soe_end=10.0,
    )
    economic = EconomicData(buy_price=2.0, sell_price=1.0, battery_cycle_cost=0.05)
    return PeriodData(
        period=period,
        energy=energy,
        timestamp=datetime(2026, 7, 8, period // 4, (period % 4) * 15),
        data_source="actual",
        economic=economic,
    )


def _make_view(day: date) -> DailyView:
    return DailyView(
        date=day,
        periods=[_make_period(0, 1.0, 0.0), _make_period(1, 0.0, 2.0)],
        total_savings=3.5,
        actual_count=2,
        predicted_count=0,
    )


class TestSaveAndLoad:
    def test_load_day_returns_none_when_nothing_saved(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        assert store.load_day(date(2026, 7, 8)) is None

    def test_save_then_load_round_trips_the_view(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        view = _make_view(date(2026, 7, 8))

        store.save_day(view)
        loaded = store.load_day(date(2026, 7, 8))

        assert loaded is not None
        assert loaded.date == date(2026, 7, 8)
        assert loaded.total_savings == 3.5
        assert len(loaded.periods) == 2
        assert loaded.periods[0].energy.grid_imported == 1.0
        assert loaded.periods[1].economic.sell_price == 1.0

    def test_save_day_overwrites_existing_file_for_same_date(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        store.save_day(_make_view(date(2026, 7, 8)))
        second_view = DailyView(
            date=date(2026, 7, 8),
            periods=[_make_period(0, 5.0, 0.0)],
            total_savings=9.0,
            actual_count=1,
            predicted_count=0,
        )

        store.save_day(second_view)
        loaded = store.load_day(date(2026, 7, 8))

        assert loaded.total_savings == 9.0
        assert len(loaded.periods) == 1


class TestListAvailableDates:
    def test_empty_store_returns_empty_list(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        assert store.list_available_dates() == []

    def test_returns_sorted_iso_dates(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        store.save_day(_make_view(date(2026, 7, 9)))
        store.save_day(_make_view(date(2026, 7, 7)))
        store.save_day(_make_view(date(2026, 7, 8)))

        assert store.list_available_dates() == ["2026-07-07", "2026-07-08", "2026-07-09"]


class TestDiskUsageAndClear:
    def test_disk_usage_zero_when_empty(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        assert store.get_disk_usage() == {"day_count": 0, "total_bytes": 0}

    def test_disk_usage_counts_saved_days(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        store.save_day(_make_view(date(2026, 7, 7)))
        store.save_day(_make_view(date(2026, 7, 8)))

        usage = store.get_disk_usage()

        assert usage["day_count"] == 2
        assert usage["total_bytes"] > 0

    def test_clear_all_removes_every_saved_day(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        store.save_day(_make_view(date(2026, 7, 7)))
        store.save_day(_make_view(date(2026, 7, 8)))

        store.clear_all()

        assert store.list_available_dates() == []
        assert store.get_disk_usage() == {"day_count": 0, "total_bytes": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest core/bess/tests/unit/test_daily_view_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.bess.daily_view_store'`

- [ ] **Step 3: Write the implementation**

```python
# core/bess/daily_view_store.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_daily_view_store.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Format, lint, commit**

```bash
.venv/bin/black core/bess/daily_view_store.py core/bess/tests/unit/test_daily_view_store.py
.venv/bin/ruff check --fix core/bess/daily_view_store.py core/bess/tests/unit/test_daily_view_store.py
git add core/bess/daily_view_store.py core/bess/tests/unit/test_daily_view_store.py
git commit -m "feat: add DailyViewStore for persistent per-day savings history"
```

---

### Task 2: Wire `save_day()` into day rollover

**Files:**
- Modify: `core/bess/battery_system_manager.py:15` (import), `~127` (`__init__`), `1284-1291` (`_handle_special_cases`)
- Test: `core/bess/tests/unit/test_bsm_settings_and_lifecycle.py`

**Interfaces:**
- Consumes: `DailyViewStore` (Task 1, `core.bess.daily_view_store`); `self.get_current_daily_view()` (existing, `battery_system_manager.py:2854`, returns `DailyView`).
- Produces: `self.daily_view_store: DailyViewStore` attribute on `BatterySystemManager`.

- [ ] **Step 1: Write the failing test**

Add to `core/bess/tests/unit/test_bsm_settings_and_lifecycle.py`, inside the existing `class TestHandleSpecialCases:` (after the existing `test_prepare_next_day_clears_stores_and_refetches`):

```python
    def test_prepare_next_day_saves_daily_view_before_clearing(self, system):
        from datetime import date as date_cls
        from unittest.mock import patch

        from core.bess.daily_view_builder import DailyView

        fake_view = DailyView(
            date=date_cls(2026, 7, 9),
            periods=[],
            total_savings=1.5,
            actual_count=0,
            predicted_count=0,
        )

        with patch.object(system, "get_current_daily_view", return_value=fake_view):
            with patch.object(system, "_fetch_predictions"):
                system._handle_special_cases(period=0, prepare_next_day=True)

        saved = system.daily_view_store.load_day(date_cls(2026, 7, 9))
        assert saved is not None
        assert saved.total_savings == 1.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_bsm_settings_and_lifecycle.py -k test_prepare_next_day_saves_daily_view_before_clearing -v`
Expected: FAIL with `AttributeError: 'BatterySystemManager' object has no attribute 'daily_view_store'`

- [ ] **Step 3: Add the import and store attribute**

In `core/bess/battery_system_manager.py`, add the import directly after the existing `from .daily_view_builder import DailyView, DailyViewBuilder` line (line 15):

```python
from .daily_view_store import DailyViewStore
```

Near line 127 (where `self.prediction_snapshot_store = PredictionSnapshotStore()` is set), add:

```python
        self.daily_view_store = DailyViewStore()
```

- [ ] **Step 4: Call `save_day()` from `_handle_special_cases`**

Update the `prepare_next_day` branch in `_handle_special_cases` (currently lines 1284-1291):

```python
        if prepare_next_day:
            logger.info(
                "Preparing for next day - clearing historical store and refreshing predictions"
            )
            self.daily_view_store.save_day(self.get_current_daily_view())
            # Clear historical store to prevent yesterday's data from appearing as today's future data
            self.historical_store.clear()
            self.prediction_snapshot_store.clear()
            self._fetch_predictions()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_bsm_settings_and_lifecycle.py -k TestHandleSpecialCases -v`
Expected: PASS (3 tests, including the two pre-existing ones — confirms no regression)

- [ ] **Step 6: Run the full fast suite, format, lint, commit**

```bash
.venv/bin/pytest -m "not slow"
.venv/bin/black core/bess/battery_system_manager.py core/bess/tests/unit/test_bsm_settings_and_lifecycle.py
.venv/bin/ruff check --fix core/bess/battery_system_manager.py core/bess/tests/unit/test_bsm_settings_and_lifecycle.py
git add core/bess/battery_system_manager.py core/bess/tests/unit/test_bsm_settings_and_lifecycle.py
git commit -m "feat: persist daily view to DailyViewStore at day rollover"
```

---

### Task 3: `savings_aggregator` — week/month/year bucketing

**Files:**
- Create: `core/bess/savings_aggregator.py`
- Test: `core/bess/tests/unit/test_savings_aggregator.py`

**Interfaces:**
- Consumes: `DailyViewStore` (Task 1) — specifically its `list_available_dates() -> list[str]` and `load_day(day: date) -> DailyView | None` methods (duck-typed; any object with these two methods works, which is what the test fixture relies on — a real `DailyViewStore` backed by `tmp_path`).
- Produces: `DailyTotals` dataclass (fields: `import_kwh`, `import_eur`, `export_kwh`, `export_eur`, `grid_cost`, `battery_cycle_cost`, `savings_vs_grid_only`, `solar_kwh`, `battery_charged_kwh`, `battery_discharged_kwh`, all `float`), `SavingsBucket` dataclass (fields: `label: str`, `start_date: str`, `end_date: str`, `day_count: int`, `totals: DailyTotals`), `DEFAULT_COUNTS: dict[str, int]` (`{"week": 12, "month": 12, "year": 5}`), `build_buckets(period: str, count: int, store, today: date | None = None) -> list[SavingsBucket]` (oldest bucket first; raises `ValueError` for an unknown `period`).

- [ ] **Step 1: Write the failing tests**

```python
# core/bess/tests/unit/test_savings_aggregator.py
"""Unit tests for savings_aggregator bucketing."""

from datetime import date

import pytest

from core.bess.daily_view_builder import DailyView
from core.bess.daily_view_store import DailyViewStore
from core.bess.models import EconomicData, EnergyData, PeriodData
from core.bess.savings_aggregator import DEFAULT_COUNTS, build_buckets


def _period(grid_imported: float, grid_exported: float) -> PeriodData:
    energy = EnergyData(
        solar_production=2.0,
        home_consumption=grid_imported,
        battery_charged=0.5,
        battery_discharged=0.3,
        grid_imported=grid_imported,
        grid_exported=grid_exported,
        battery_soe_start=10.0,
        battery_soe_end=10.0,
    )
    economic = EconomicData(buy_price=2.0, sell_price=1.0, battery_cycle_cost=0.1)
    return PeriodData(period=0, energy=energy, economic=economic)


def _seed_day(store: DailyViewStore, day: date, grid_imported: float, grid_exported: float, savings: float) -> None:
    view = DailyView(
        date=day,
        periods=[_period(grid_imported, grid_exported)],
        total_savings=savings,
        actual_count=1,
        predicted_count=0,
    )
    store.save_day(view)


class TestWeekBuckets:
    def test_sums_the_single_saved_day_into_its_week(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        # Wednesday 2026-07-08 is in ISO week 2026-W28 (Mon 2026-07-06 .. Sun 2026-07-12)
        _seed_day(store, date(2026, 7, 8), grid_imported=1.0, grid_exported=2.0, savings=3.0)

        buckets = build_buckets("week", count=1, store=store, today=date(2026, 7, 9))

        assert len(buckets) == 1
        bucket = buckets[0]
        assert bucket.label == "2026-W28"
        assert bucket.start_date == "2026-07-06"
        assert bucket.end_date == "2026-07-12"
        assert bucket.day_count == 1
        assert bucket.totals.import_kwh == 1.0
        assert bucket.totals.export_kwh == 2.0
        assert bucket.totals.import_eur == 2.0  # 1.0 * buy_price 2.0
        assert bucket.totals.export_eur == 2.0  # 2.0 * sell_price 1.0
        assert bucket.totals.grid_cost == 0.0
        assert bucket.totals.savings_vs_grid_only == 3.0

    def test_two_days_in_the_same_week_are_summed(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        _seed_day(store, date(2026, 7, 6), grid_imported=1.0, grid_exported=0.0, savings=1.0)
        _seed_day(store, date(2026, 7, 8), grid_imported=1.0, grid_exported=0.0, savings=1.0)

        buckets = build_buckets("week", count=1, store=store, today=date(2026, 7, 9))

        assert buckets[0].day_count == 2
        assert buckets[0].totals.import_kwh == 2.0
        assert buckets[0].totals.savings_vs_grid_only == 2.0

    def test_multiple_weeks_returned_oldest_first(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        _seed_day(store, date(2026, 6, 29), grid_imported=1.0, grid_exported=0.0, savings=1.0)  # W27
        _seed_day(store, date(2026, 7, 8), grid_imported=1.0, grid_exported=0.0, savings=1.0)  # W28

        buckets = build_buckets("week", count=2, store=store, today=date(2026, 7, 9))

        assert [b.label for b in buckets] == ["2026-W27", "2026-W28"]

    def test_day_with_no_snapshot_is_not_counted(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)

        buckets = build_buckets("week", count=1, store=store, today=date(2026, 7, 9))

        assert buckets[0].day_count == 0
        assert buckets[0].totals.import_kwh == 0.0


class TestMonthBuckets:
    def test_bucket_spans_the_whole_calendar_month(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        _seed_day(store, date(2026, 7, 15), grid_imported=1.0, grid_exported=0.0, savings=1.0)

        buckets = build_buckets("month", count=1, store=store, today=date(2026, 7, 20))

        assert buckets[0].label == "2026-07"
        assert buckets[0].start_date == "2026-07-01"
        assert buckets[0].end_date == "2026-07-31"
        assert buckets[0].day_count == 1

    def test_february_end_date_respects_leap_year(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)

        buckets = build_buckets("month", count=1, store=store, today=date(2028, 2, 10))

        assert buckets[0].end_date == "2028-02-29"


class TestYearBuckets:
    def test_bucket_spans_the_whole_calendar_year(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        _seed_day(store, date(2026, 3, 1), grid_imported=1.0, grid_exported=0.0, savings=1.0)

        buckets = build_buckets("year", count=1, store=store, today=date(2026, 12, 1))

        assert buckets[0].label == "2026"
        assert buckets[0].start_date == "2026-01-01"
        assert buckets[0].end_date == "2026-12-31"
        assert buckets[0].day_count == 1


class TestInvalidPeriod:
    def test_unknown_period_raises(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        with pytest.raises(ValueError):
            build_buckets("fortnight", count=1, store=store)


class TestDefaultCounts:
    def test_has_an_entry_for_every_valid_period(self):
        assert set(DEFAULT_COUNTS.keys()) == {"week", "month", "year"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest core/bess/tests/unit/test_savings_aggregator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.bess.savings_aggregator'`

- [ ] **Step 3: Write the implementation**

```python
# core/bess/savings_aggregator.py
"""Aggregates persisted DailyView snapshots (DailyViewStore) into week/month/year buckets."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from .daily_view_builder import DailyView

VALID_PERIODS = ("week", "month", "year")

DEFAULT_COUNTS: dict[str, int] = {"week": 12, "month": 12, "year": 5}


@dataclass
class DailyTotals:
    """Sums of one or more days' energy/economic fields."""

    import_kwh: float = 0.0
    import_eur: float = 0.0
    export_kwh: float = 0.0
    export_eur: float = 0.0
    grid_cost: float = 0.0
    battery_cycle_cost: float = 0.0
    savings_vs_grid_only: float = 0.0
    solar_kwh: float = 0.0
    battery_charged_kwh: float = 0.0
    battery_discharged_kwh: float = 0.0

    @classmethod
    def from_daily_view(cls, view: DailyView) -> DailyTotals:
        import_kwh = sum(p.energy.grid_imported for p in view.periods)
        export_kwh = sum(p.energy.grid_exported for p in view.periods)
        import_eur = sum(p.energy.grid_imported * p.economic.buy_price for p in view.periods)
        export_eur = sum(p.energy.grid_exported * p.economic.sell_price for p in view.periods)
        return cls(
            import_kwh=import_kwh,
            import_eur=import_eur,
            export_kwh=export_kwh,
            export_eur=export_eur,
            grid_cost=import_eur - export_eur,
            battery_cycle_cost=sum(p.economic.battery_cycle_cost for p in view.periods),
            savings_vs_grid_only=view.total_savings,
            solar_kwh=sum(p.energy.solar_production for p in view.periods),
            battery_charged_kwh=sum(p.energy.battery_charged for p in view.periods),
            battery_discharged_kwh=sum(p.energy.battery_discharged for p in view.periods),
        )

    def __add__(self, other: DailyTotals) -> DailyTotals:
        return DailyTotals(
            import_kwh=self.import_kwh + other.import_kwh,
            import_eur=self.import_eur + other.import_eur,
            export_kwh=self.export_kwh + other.export_kwh,
            export_eur=self.export_eur + other.export_eur,
            grid_cost=self.grid_cost + other.grid_cost,
            battery_cycle_cost=self.battery_cycle_cost + other.battery_cycle_cost,
            savings_vs_grid_only=self.savings_vs_grid_only + other.savings_vs_grid_only,
            solar_kwh=self.solar_kwh + other.solar_kwh,
            battery_charged_kwh=self.battery_charged_kwh + other.battery_charged_kwh,
            battery_discharged_kwh=self.battery_discharged_kwh + other.battery_discharged_kwh,
        )


@dataclass
class SavingsBucket:
    """One week/month/year of aggregated savings."""

    label: str
    start_date: str
    end_date: str
    day_count: int
    totals: DailyTotals = field(default_factory=DailyTotals)


def _week_bounds(d: date) -> tuple[date, date]:
    start = d - timedelta(days=d.weekday())  # Monday
    return start, start + timedelta(days=6)


def _month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    last_day = calendar.monthrange(d.year, d.month)[1]
    return start, d.replace(day=last_day)


def _year_bounds(d: date) -> tuple[date, date]:
    return date(d.year, 1, 1), date(d.year, 12, 31)


_BOUNDS_FN = {"week": _week_bounds, "month": _month_bounds, "year": _year_bounds}


def _bucket_label(period: str, start: date) -> str:
    if period == "week":
        iso_year, iso_week, _ = start.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if period == "month":
        return f"{start.year}-{start.month:02d}"
    return str(start.year)


def _step_back(period: str, bucket_start: date) -> date:
    """Return a reference date inside the previous bucket."""
    if period == "week":
        return bucket_start - timedelta(days=7)
    if period == "month":
        return bucket_start - timedelta(days=1)  # last day of the previous month
    return date(bucket_start.year - 1, 6, 15)


def build_buckets(
    period: str,
    count: int,
    store,
    today: date | None = None,
) -> list[SavingsBucket]:
    """Build the last `count` buckets of the given period type, oldest first.

    `store` needs only `list_available_dates() -> list[str]` and
    `load_day(day: date) -> DailyView | None` (duck-typed to DailyViewStore).
    """
    if period not in VALID_PERIODS:
        raise ValueError(f"Unknown period type: {period!r}")

    bounds_fn = _BOUNDS_FN[period]
    available_dates = {date.fromisoformat(d) for d in store.list_available_dates()}

    buckets: list[SavingsBucket] = []
    cursor = today or date.today()
    for _ in range(count):
        start, end = bounds_fn(cursor)
        days_in_bucket = sorted(d for d in available_dates if start <= d <= end)

        totals = DailyTotals()
        for day in days_in_bucket:
            view = store.load_day(day)
            if view is not None:
                totals = totals + DailyTotals.from_daily_view(view)

        buckets.append(
            SavingsBucket(
                label=_bucket_label(period, start),
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                day_count=len(days_in_bucket),
                totals=totals,
            )
        )
        cursor = _step_back(period, start)

    buckets.reverse()
    return buckets
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_savings_aggregator.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Format, lint, commit**

```bash
.venv/bin/black core/bess/savings_aggregator.py core/bess/tests/unit/test_savings_aggregator.py
.venv/bin/ruff check --fix core/bess/savings_aggregator.py core/bess/tests/unit/test_savings_aggregator.py
git add core/bess/savings_aggregator.py core/bess/tests/unit/test_savings_aggregator.py
git commit -m "feat: add week/month/year savings bucketing over DailyViewStore"
```

---

### Task 4: Backend API — `/api/savings/aggregate`, disk-usage, clear

**Files:**
- Modify: `backend/api_dataclasses.py` (add `APISavingsBucket`)
- Modify: `backend/api.py` (add three routes + import + wire `daily_view_store` where needed)
- Test: `backend/tests/test_savings_aggregate_api.py`

**Interfaces:**
- Consumes: `SavingsBucket`, `DailyTotals`, `DEFAULT_COUNTS`, `build_buckets` (Task 3, `core.bess.savings_aggregator`); `bess_controller.system.daily_view_store` (Task 2 attribute, `DailyViewStore`); `create_formatted_value(value, unit_type, currency, precision=None) -> FormattedValue` (existing, `backend/api_dataclasses.py:27-77`); `_require_configured_system(bess_controller)` (existing, `backend/api.py:112`); `convert_keys_to_camel_case` (existing, already imported in `backend/api.py`).
- Produces: `APISavingsBucket` dataclass; three routes.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_savings_aggregate_api.py
"""Tests for GET /api/savings/aggregate, disk-usage, and clear routes."""

import sys
from datetime import date
from unittest.mock import MagicMock

from api import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.bess.daily_view_builder import DailyView
from core.bess.daily_view_store import DailyViewStore
from core.bess.models import EconomicData, EnergyData, PeriodData

_test_app = FastAPI()
_test_app.include_router(router)
_client = TestClient(_test_app, raise_server_exceptions=False)


def _period(grid_imported: float, grid_exported: float) -> PeriodData:
    energy = EnergyData(
        solar_production=1.0,
        home_consumption=grid_imported,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=grid_imported,
        grid_exported=grid_exported,
        battery_soe_start=10.0,
        battery_soe_end=10.0,
    )
    economic = EconomicData(buy_price=2.0, sell_price=1.0, battery_cycle_cost=0.1)
    return PeriodData(period=0, energy=energy, economic=economic)


def _seeded_store(tmp_path) -> DailyViewStore:
    store = DailyViewStore(persist_dir=tmp_path)
    store.save_day(
        DailyView(
            date=date(2026, 7, 8),
            periods=[_period(1.0, 2.0)],
            total_savings=3.0,
            actual_count=1,
            predicted_count=0,
        )
    )
    return store


def _make_started_controller(daily_view_store) -> MagicMock:
    ctrl = MagicMock()
    ctrl.system.is_configured = True
    ctrl.startup_complete = True
    ctrl.system.daily_view_store = daily_view_store
    ctrl.system.home_settings.currency = "EUR"
    return ctrl


def _unconfigured_controller() -> MagicMock:
    ctrl = MagicMock()
    ctrl.system.is_configured = False
    ctrl.startup_complete = True
    return ctrl


class TestSavingsAggregate:
    def test_returns_200_with_expected_bucket_fields(self, tmp_path):
        sys.modules["app"].bess_controller = _make_started_controller(_seeded_store(tmp_path))

        resp = _client.get("/api/savings/aggregate?period=week&count=1")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        bucket = body["buckets"][0]
        assert bucket["dayCount"] == 1
        assert bucket["gridCost"]["value"] == 0.0  # 2.0 import_eur - 2.0 export_eur
        assert bucket["savingsVsGridOnly"]["value"] == 3.0

    def test_empty_store_returns_empty_buckets_list_not_error(self, tmp_path):
        empty_store = DailyViewStore(persist_dir=tmp_path)
        sys.modules["app"].bess_controller = _make_started_controller(empty_store)

        resp = _client.get("/api/savings/aggregate?period=month&count=1")

        assert resp.status_code == 200
        assert resp.json()["buckets"][0]["dayCount"] == 0

    def test_omitted_count_uses_period_default(self, tmp_path):
        sys.modules["app"].bess_controller = _make_started_controller(_seeded_store(tmp_path))

        resp = _client.get("/api/savings/aggregate?period=week")

        assert resp.status_code == 200
        assert resp.json()["count"] == 12  # DEFAULT_COUNTS["week"]

    def test_invalid_period_returns_422(self, tmp_path):
        sys.modules["app"].bess_controller = _make_started_controller(_seeded_store(tmp_path))

        resp = _client.get("/api/savings/aggregate?period=fortnight")

        assert resp.status_code == 422

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()

        resp = _client.get("/api/savings/aggregate?period=week")

        assert resp.status_code == 503


class TestDiskUsage:
    def test_returns_day_count_and_bytes(self, tmp_path):
        sys.modules["app"].bess_controller = _make_started_controller(_seeded_store(tmp_path))

        resp = _client.get("/api/savings/history/disk-usage")

        assert resp.status_code == 200
        body = resp.json()
        assert body["dayCount"] == 1
        assert body["totalBytes"] > 0


class TestClearHistory:
    def test_clears_and_returns_zeroed_usage(self, tmp_path):
        store = _seeded_store(tmp_path)
        sys.modules["app"].bess_controller = _make_started_controller(store)

        resp = _client.delete("/api/savings/history")

        assert resp.status_code == 200
        assert resp.json()["dayCount"] == 0
        assert store.list_available_dates() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest backend/tests/test_savings_aggregate_api.py -v`
Expected: FAIL with 404 (routes don't exist yet)

- [ ] **Step 3: Add `APISavingsBucket` to `backend/api_dataclasses.py`**

Add near `APIPredictionSnapshot`:

```python
@dataclass
class APISavingsBucket:
    """API representation of a savings_aggregator.SavingsBucket."""

    label: str
    startDate: str
    endDate: str
    dayCount: int
    importKwh: FormattedValue
    importEur: FormattedValue
    exportKwh: FormattedValue
    exportEur: FormattedValue
    gridCost: FormattedValue
    batteryCycleCost: FormattedValue
    savingsVsGridOnly: FormattedValue
    solarKwh: FormattedValue
    batteryChargedKwh: FormattedValue
    batteryDischargedKwh: FormattedValue

    @classmethod
    def from_internal(cls, bucket, currency: str) -> "APISavingsBucket":
        t = bucket.totals
        return cls(
            label=bucket.label,
            startDate=bucket.start_date,
            endDate=bucket.end_date,
            dayCount=bucket.day_count,
            importKwh=create_formatted_value(t.import_kwh, "energy_kwh_only", currency),
            importEur=create_formatted_value(t.import_eur, "currency", currency),
            exportKwh=create_formatted_value(t.export_kwh, "energy_kwh_only", currency),
            exportEur=create_formatted_value(t.export_eur, "currency", currency),
            gridCost=create_formatted_value(t.grid_cost, "currency", currency),
            batteryCycleCost=create_formatted_value(t.battery_cycle_cost, "currency", currency),
            savingsVsGridOnly=create_formatted_value(t.savings_vs_grid_only, "currency", currency),
            solarKwh=create_formatted_value(t.solar_kwh, "energy_kwh_only", currency),
            batteryChargedKwh=create_formatted_value(t.battery_charged_kwh, "energy_kwh_only", currency),
            batteryDischargedKwh=create_formatted_value(t.battery_discharged_kwh, "energy_kwh_only", currency),
        )
```

- [ ] **Step 4: Add the routes to `backend/api.py`**

Add `APISavingsBucket` to the existing `from api_dataclasses import (...)` block (~line 20), and add near the top-level imports:

```python
from core.bess.savings_aggregator import DEFAULT_COUNTS, build_buckets
```

Add the routes after the `/api/prediction-analysis/timeline` route:

```python
@router.get("/api/savings/aggregate")
async def get_savings_aggregate(
    period: str = Query(..., pattern="^(week|month|year)$"),
    count: int | None = Query(None, ge=1, le=520),
):
    """Get week/month/year savings aggregates from the persisted daily history."""
    from app import bess_controller

    _require_configured_system(bess_controller)

    try:
        resolved_count = count or DEFAULT_COUNTS[period]
        buckets = build_buckets(period, resolved_count, bess_controller.system.daily_view_store)
        currency = bess_controller.system.home_settings.currency

        api_buckets = [APISavingsBucket.from_internal(b, currency) for b in buckets]

        response = {
            "buckets": [b.__dict__ for b in api_buckets],
            "count": len(api_buckets),
        }

        return convert_keys_to_camel_case(response)

    except Exception as e:
        logger.error(f"Error building savings aggregate: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/savings/history/disk-usage")
async def get_savings_history_disk_usage():
    """Get disk usage of the persisted daily savings history."""
    from app import bess_controller

    _require_configured_system(bess_controller)

    try:
        usage = bess_controller.system.daily_view_store.get_disk_usage()
        return convert_keys_to_camel_case(usage)
    except Exception as e:
        logger.error(f"Error getting savings history disk usage: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/api/savings/history")
async def delete_savings_history():
    """Clear all persisted daily savings history."""
    from app import bess_controller

    _require_configured_system(bess_controller)

    try:
        bess_controller.system.daily_view_store.clear_all()
        usage = bess_controller.system.daily_view_store.get_disk_usage()
        return convert_keys_to_camel_case(usage)
    except Exception as e:
        logger.error(f"Error clearing savings history: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest backend/tests/test_savings_aggregate_api.py -v`
Expected: PASS (9 tests)

- [ ] **Step 6: Run full fast suite, format, lint, commit**

```bash
.venv/bin/pytest -m "not slow"
.venv/bin/black backend/api.py backend/api_dataclasses.py backend/tests/test_savings_aggregate_api.py
.venv/bin/ruff check --fix backend/api.py backend/api_dataclasses.py backend/tests/test_savings_aggregate_api.py
git add backend/api.py backend/api_dataclasses.py backend/tests/test_savings_aggregate_api.py
git commit -m "feat: add GET /api/savings/aggregate, disk-usage, and clear routes"
```

---

### Task 5: Frontend fetch functions + `useSavingsAggregate` hook

**Files:**
- Modify: `frontend/src/api/scheduleApi.ts` (append fetch functions + types)
- Create: `frontend/src/hooks/useSavingsAggregate.ts`
- Test: `frontend/src/hooks/__tests__/useSavingsAggregate.test.ts`

**Interfaces:**
- Consumes: `GET /api/savings/aggregate`, `GET /api/savings/history/disk-usage`, `DELETE /api/savings/history` (Task 4).
- Produces: `SavingsBucket`, `SavingsAggregateResponse`, `SavingsAggregatePeriod`, `SavingsHistoryDiskUsage` types; `fetchSavingsAggregate(period, count?)`, `fetchSavingsHistoryDiskUsage()`, `clearSavingsHistory()` functions (`frontend/src/api/scheduleApi.ts`); `useSavingsAggregate(period, count?): { data: SavingsBucket[] | null; loading: boolean; error: string | null }` hook.

- [ ] **Step 1: Append fetch functions and types to `frontend/src/api/scheduleApi.ts`**

```typescript
export type SavingsAggregatePeriod = 'week' | 'month' | 'year';

export interface SavingsBucket {
  label: string;
  startDate: string;
  endDate: string;
  dayCount: number;
  importKwh: FormattedValue;
  importEur: FormattedValue;
  exportKwh: FormattedValue;
  exportEur: FormattedValue;
  gridCost: FormattedValue;
  batteryCycleCost: FormattedValue;
  savingsVsGridOnly: FormattedValue;
  solarKwh: FormattedValue;
  batteryChargedKwh: FormattedValue;
  batteryDischargedKwh: FormattedValue;
}

export interface SavingsAggregateResponse {
  buckets: SavingsBucket[];
  count: number;
}

export const fetchSavingsAggregate = async (
  period: SavingsAggregatePeriod,
  count?: number
): Promise<SavingsAggregateResponse> => {
  const params: Record<string, string | number> = { period };
  if (count) params.count = count;
  const response = await api.get('/api/savings/aggregate', { params });
  return response.data;
};

export interface SavingsHistoryDiskUsage {
  dayCount: number;
  totalBytes: number;
}

export const fetchSavingsHistoryDiskUsage = async (): Promise<SavingsHistoryDiskUsage> => {
  const response = await api.get('/api/savings/history/disk-usage');
  return response.data;
};

export const clearSavingsHistory = async (): Promise<SavingsHistoryDiskUsage> => {
  const response = await api.delete('/api/savings/history');
  return response.data;
};
```

- [ ] **Step 2: Write the failing hook test**

```typescript
// frontend/src/hooks/__tests__/useSavingsAggregate.test.ts
import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useSavingsAggregate } from '../useSavingsAggregate';
import * as scheduleApi from '../../api/scheduleApi';

describe('useSavingsAggregate', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('fetches buckets for the given period and exposes them as data', async () => {
    const fetchSpy = vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [
        {
          label: '2026-W28',
          startDate: '2026-07-06',
          endDate: '2026-07-12',
          dayCount: 1,
          importKwh: { value: 1, display: '1.0', unit: 'kWh', text: '1.0 kWh' },
          importEur: { value: 2, display: '2.00', unit: 'EUR', text: '2.00 EUR' },
          exportKwh: { value: 2, display: '2.0', unit: 'kWh', text: '2.0 kWh' },
          exportEur: { value: 2, display: '2.00', unit: 'EUR', text: '2.00 EUR' },
          gridCost: { value: 0, display: '0.00', unit: 'EUR', text: '0.00 EUR' },
          batteryCycleCost: { value: 0.1, display: '0.10', unit: 'EUR', text: '0.10 EUR' },
          savingsVsGridOnly: { value: 3, display: '3.00', unit: 'EUR', text: '3.00 EUR' },
          solarKwh: { value: 1, display: '1.0', unit: 'kWh', text: '1.0 kWh' },
          batteryChargedKwh: { value: 0, display: '0.0', unit: 'kWh', text: '0.0 kWh' },
          batteryDischargedKwh: { value: 0, display: '0.0', unit: 'kWh', text: '0.0 kWh' },
        },
      ],
      count: 1,
    });

    const { result } = renderHook(() => useSavingsAggregate('week', 1));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(fetchSpy).toHaveBeenCalledWith('week', 1);
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].label).toBe('2026-W28');
    expect(result.current.error).toBeNull();
  });

  it('surfaces an error message when the fetch rejects', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockRejectedValue(new Error('boom'));

    const { result } = renderHook(() => useSavingsAggregate('month'));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe('boom');
    expect(result.current.data).toBeNull();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npm run test -- useSavingsAggregate`
Expected: FAIL — cannot find module `../useSavingsAggregate`

- [ ] **Step 4: Write the hook**

```typescript
// frontend/src/hooks/useSavingsAggregate.ts
import { useState, useEffect, useCallback } from 'react';
import { fetchSavingsAggregate, SavingsBucket, SavingsAggregatePeriod } from '../api/scheduleApi';

interface UseSavingsAggregateResult {
  data: SavingsBucket[] | null;
  loading: boolean;
  error: string | null;
}

export const useSavingsAggregate = (
  period: SavingsAggregatePeriod,
  count?: number
): UseSavingsAggregateResult => {
  const [data, setData] = useState<SavingsBucket[] | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await fetchSavingsAggregate(period, count);
      setData(result.buckets);
    } catch (err) {
      console.error('Failed to fetch savings aggregate:', err);
      const errorMessage = err instanceof Error ? err.message : 'Failed to load savings history';
      setError(errorMessage);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [period, count]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, loading, error };
};

export default useSavingsAggregate;
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm run test -- useSavingsAggregate`
Expected: PASS (2 tests)

- [ ] **Step 6: Lint, commit**

```bash
cd frontend
npm run lint:fix
cd ..
git add frontend/src/api/scheduleApi.ts frontend/src/hooks/useSavingsAggregate.ts frontend/src/hooks/__tests__/useSavingsAggregate.test.ts
git commit -m "feat: add fetch functions and useSavingsAggregate hook"
```

---

### Task 6: Frontend — `SavingsAggregateView` (chart + table, period toggle)

**Files:**
- Create: `frontend/src/components/SavingsAggregateView.tsx`
- Modify: `frontend/src/pages/SavingsPage.tsx`
- Test: `frontend/src/components/__tests__/SavingsAggregateView.test.tsx`

**Interfaces:**
- Consumes: `useSavingsAggregate` (Task 5); `SavingsBucket` type (Task 5).
- Produces: `SavingsAggregateView` component (no required props, self-fetching, matches `SavingsOverview`'s pattern).

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/components/__tests__/SavingsAggregateView.test.tsx
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SavingsAggregateView } from '../SavingsAggregateView';
import * as scheduleApi from '../../api/scheduleApi';

const bucket = (label: string, dayCount: number) => ({
  label,
  startDate: '2026-07-06',
  endDate: '2026-07-12',
  dayCount,
  importKwh: { value: 1, display: '1.0', unit: 'kWh', text: '1.0 kWh' },
  importEur: { value: 2, display: '2.00', unit: 'EUR', text: '2.00 EUR' },
  exportKwh: { value: 2, display: '2.0', unit: 'kWh', text: '2.0 kWh' },
  exportEur: { value: 2, display: '2.00', unit: 'EUR', text: '2.00 EUR' },
  gridCost: { value: 0, display: '0.00', unit: 'EUR', text: '0.00 EUR' },
  batteryCycleCost: { value: 0.1, display: '0.10', unit: 'EUR', text: '0.10 EUR' },
  savingsVsGridOnly: { value: 3, display: '3.00', unit: 'EUR', text: '3.00 EUR' },
  solarKwh: { value: 1, display: '1.0', unit: 'kWh', text: '1.0 kWh' },
  batteryChargedKwh: { value: 0, display: '0.0', unit: 'kWh', text: '0.0 kWh' },
  batteryDischargedKwh: { value: 0, display: '0.0', unit: 'kWh', text: '0.0 kWh' },
});

describe('SavingsAggregateView', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders a row per bucket for the default period', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-W28', 1)],
      count: 1,
    });

    render(<SavingsAggregateView />);

    await waitFor(() => {
      expect(screen.getByText('2026-W28')).toBeInTheDocument();
    });
    expect(screen.getByText('3.00 EUR')).toBeInTheDocument();
  });

  it('refetches with the new period when the toggle is changed', async () => {
    const fetchSpy = vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-07', 5)],
      count: 1,
    });

    render(<SavingsAggregateView />);

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith('week', undefined));

    fireEvent.click(screen.getByRole('button', { name: /month/i }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith('month', undefined));
  });

  it('shows an empty state when there are no buckets with data', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({ buckets: [], count: 0 });

    render(<SavingsAggregateView />);

    await waitFor(() => {
      expect(screen.getByText(/no savings history yet/i)).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- SavingsAggregateView`
Expected: FAIL — cannot find module `../SavingsAggregateView`

- [ ] **Step 3: Write the component**

```typescript
// frontend/src/components/SavingsAggregateView.tsx
import React, { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { useSavingsAggregate } from '../hooks/useSavingsAggregate';
import { SavingsAggregatePeriod } from '../api/scheduleApi';

const PERIODS: SavingsAggregatePeriod[] = ['week', 'month', 'year'];

export const SavingsAggregateView: React.FC = () => {
  const [period, setPeriod] = useState<SavingsAggregatePeriod>('week');
  const [viewMode, setViewMode] = useState<'chart' | 'table'>('chart');
  const { data, loading, error } = useSavingsAggregate(period);
  const [isDarkMode, setIsDarkMode] = useState(
    document.documentElement.classList.contains('dark')
  );

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.classList.contains('dark'));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  const colors = {
    text: isDarkMode ? '#9CA3AF' : '#374151',
    gridLines: isDarkMode ? '#374151' : '#e5e7eb',
    savings: '#10b981',
    cost: '#3b82f6',
  };

  const hasData = !!data && data.some((b) => b.dayCount > 0);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-4 gap-3">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Savings History</h2>
        <div className="flex gap-2">
          <div className="flex bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
            {PERIODS.map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-3 py-1 rounded-md text-sm font-medium capitalize transition-colors ${
                  period === p
                    ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                    : 'text-gray-600 dark:text-gray-300'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
          <div className="flex bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
            <button
              onClick={() => setViewMode('chart')}
              className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
                viewMode === 'chart'
                  ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-600 dark:text-gray-300'
              }`}
            >
              Chart
            </button>
            <button
              onClick={() => setViewMode('table')}
              className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
                viewMode === 'table'
                  ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-600 dark:text-gray-300'
              }`}
            >
              Table
            </button>
          </div>
        </div>
      </div>

      {loading && <p className="text-sm text-gray-500 dark:text-gray-400">Loading...</p>}

      {!loading && error && (
        <p className="text-sm text-red-600 dark:text-red-400">Could not load savings history: {error}</p>
      )}

      {!loading && !error && !hasData && (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          No savings history yet. A record is captured once per day.
        </p>
      )}

      {!loading && !error && hasData && viewMode === 'chart' && (
        <div style={{ width: '100%', height: '300px' }}>
          <ResponsiveContainer>
            <BarChart
              data={data!.map((b) => ({
                label: b.label,
                gridCost: b.gridCost.value,
                savings: b.savingsVsGridOnly.value,
              }))}
              margin={{ top: 10, right: 10, left: 0, bottom: 10 }}
            >
              <CartesianGrid stroke={colors.gridLines} strokeOpacity={isDarkMode ? 0.12 : 0.3} strokeWidth={0.5} />
              <XAxis dataKey="label" stroke={colors.text} tick={{ fill: colors.text, fontSize: 11 }} />
              <YAxis stroke={colors.text} tick={{ fill: colors.text, fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="gridCost" name="Net Grid Cost" fill={colors.cost} fillOpacity={0.8} isAnimationActive={false} />
              <Bar dataKey="savings" name="Savings" fill={colors.savings} fillOpacity={0.8} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {!loading && !error && hasData && viewMode === 'table' && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 dark:text-gray-400">
                <th className="pr-4 py-1">Period</th>
                <th className="pr-4 py-1">Days</th>
                <th className="pr-4 py-1">Import</th>
                <th className="pr-4 py-1">Export</th>
                <th className="pr-4 py-1">Net Grid Cost</th>
                <th className="pr-4 py-1">Battery Wear</th>
                <th className="pr-4 py-1">Savings</th>
              </tr>
            </thead>
            <tbody>
              {[...data!].reverse().map((b) => (
                <tr key={b.label} className="border-t border-gray-100 dark:border-gray-700">
                  <td className="pr-4 py-1 text-gray-900 dark:text-white">{b.label}</td>
                  <td className="pr-4 py-1 text-gray-500 dark:text-gray-400">{b.dayCount}</td>
                  <td className="pr-4 py-1 text-gray-600 dark:text-gray-300">{b.importEur.text}</td>
                  <td className="pr-4 py-1 text-gray-600 dark:text-gray-300">{b.exportEur.text}</td>
                  <td className="pr-4 py-1 font-medium text-gray-900 dark:text-white">{b.gridCost.text}</td>
                  <td className="pr-4 py-1 text-gray-500 dark:text-gray-400">{b.batteryCycleCost.text}</td>
                  <td className="pr-4 py-1 text-gray-600 dark:text-gray-300">{b.savingsVsGridOnly.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default SavingsAggregateView;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- SavingsAggregateView`
Expected: PASS (3 tests)

- [ ] **Step 5: Wire it into the Savings page**

In `frontend/src/pages/SavingsPage.tsx`, add the import (near line 3):

```typescript
import { SavingsAggregateView } from '../components/SavingsAggregateView';
```

And render it below the existing view switch (after the `viewMode === 'overview' ? ... : ...` block, still inside the outer `<div className="space-y-6">`):

```typescript
      {viewMode === 'overview' ? (
        <SavingsOverview resolution={dataResolution} />
      ) : (
        <DetailedSavingsAnalysis settings={mergedSettings} resolution={dataResolution} />
      )}

      <SavingsAggregateView />
```

- [ ] **Step 6: Lint, build, commit**

```bash
cd frontend
npm run lint:fix
npm run build
cd ..
git add frontend/src/components/SavingsAggregateView.tsx frontend/src/components/__tests__/SavingsAggregateView.test.tsx frontend/src/pages/SavingsPage.tsx
git commit -m "feat: add SavingsAggregateView with week/month/year toggle to Savings page"
```

---

### Task 7: Settings page — disk usage + clear history

**Files:**
- Create: `frontend/src/components/settings/SavingsHistorySection.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx` (Diagnostics card, ~line 741)
- Test: `frontend/src/components/settings/__tests__/SavingsHistorySection.test.tsx`

**Interfaces:**
- Consumes: `fetchSavingsHistoryDiskUsage`, `clearSavingsHistory` (Task 5, `frontend/src/api/scheduleApi.ts`).
- Produces: `SavingsHistorySection: React.FC` (no props, self-fetching — same convention as the existing no-props `SystemHealthComponent` already used in this Diagnostics card), rendered inside it with a two-step "Clear History" / "Confirm Clear" button (no new modal component — a local `confirmingClear` boolean toggles the button label/action).

This follows the existing `frontend/src/components/settings/` convention (`HomeFormSection.tsx`, `PricingFormSection.tsx`, `AIAnalystSettings.tsx`, etc. — `SettingsPage` is already composed of small section components, so this is a new sibling, not a special case), which also makes it independently testable without mounting the entire `SettingsPage` (that page has many other API-backed sections with no existing test harness — testing this section in isolation avoids depending on that).

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/components/settings/__tests__/SavingsHistorySection.test.tsx
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SavingsHistorySection } from '../SavingsHistorySection';
import * as scheduleApi from '../../../api/scheduleApi';

describe('SavingsHistorySection', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(scheduleApi, 'fetchSavingsHistoryDiskUsage').mockResolvedValue({
      dayCount: 12,
      totalBytes: 45000,
    });
  });

  it('shows the recorded day count and requires a second click to clear', async () => {
    const clearSpy = vi.spyOn(scheduleApi, 'clearSavingsHistory').mockResolvedValue({
      dayCount: 0,
      totalBytes: 0,
    });

    render(<SavingsHistorySection />);

    await waitFor(() => {
      expect(screen.getByText(/12 days recorded/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /clear history/i }));
    expect(clearSpy).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /confirm clear/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /confirm clear/i }));

    await waitFor(() => expect(clearSpy).toHaveBeenCalled());
    await waitFor(() => {
      expect(screen.getByText(/0 days recorded/i)).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- SavingsHistorySection`
Expected: FAIL — cannot find module `../SavingsHistorySection`

- [ ] **Step 3: Write the component**

```typescript
// frontend/src/components/settings/SavingsHistorySection.tsx
import React, { useState, useEffect } from 'react';
import { fetchSavingsHistoryDiskUsage, clearSavingsHistory, SavingsHistoryDiskUsage } from '../../api/scheduleApi';

const formatBytes = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export const SavingsHistorySection: React.FC = () => {
  const [usage, setUsage] = useState<SavingsHistoryDiskUsage | null>(null);
  const [confirmingClear, setConfirmingClear] = useState(false);

  useEffect(() => {
    fetchSavingsHistoryDiskUsage()
      .then(setUsage)
      .catch(() => {});
  }, []);

  const handleClearHistory = async () => {
    if (!confirmingClear) {
      setConfirmingClear(true);
      return;
    }
    try {
      const result = await clearSavingsHistory();
      setUsage(result);
    } finally {
      setConfirmingClear(false);
    }
  };

  return (
    <div className="flex items-center justify-between">
      <p className="text-sm text-gray-700 dark:text-gray-300">
        Savings History: {usage?.dayCount ?? 0} days recorded
        {usage ? ` (${formatBytes(usage.totalBytes)})` : ''}
      </p>
      <button
        onClick={handleClearHistory}
        className="px-3 py-1.5 text-xs font-medium text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/30"
      >
        {confirmingClear ? 'Confirm Clear' : 'Clear History'}
      </button>
    </div>
  );
};

export default SavingsHistorySection;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- SavingsHistorySection`
Expected: PASS (1 test)

- [ ] **Step 5: Wire it into the Diagnostics card in `SettingsPage.tsx`**

Add the import near the other settings-section imports (after the `AIAnalystSettings` import, ~line 16):

```typescript
import { SavingsHistorySection } from '../components/settings/SavingsHistorySection';
```

In the Diagnostics card (currently ~lines 741-760), add the section above `<SystemHealthComponent />`:

```typescript
                <SavingsHistorySection />
                <SystemHealthComponent />
```

- [ ] **Step 6: Lint, build, commit**

```bash
cd frontend
npm run lint:fix
npm run build
cd ..
git add frontend/src/components/settings/SavingsHistorySection.tsx frontend/src/components/settings/__tests__/SavingsHistorySection.test.tsx frontend/src/pages/SettingsPage.tsx
git commit -m "feat: show savings history disk usage and clear control in Settings"
```

---

### Task 8: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full fast backend suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS, no regressions

- [ ] **Step 2: Run the full quality gate**

Run: `./scripts/quality-check.sh`
Expected: PASS

- [ ] **Step 3: Run frontend tests**

Run: `cd frontend && npm run test`
Expected: PASS, no regressions

- [ ] **Step 4: Manual verification via the `verify` skill**

Stand up the real mock-HA + backend E2E stack (per the `verify` skill) and confirm:
- On a fresh install, the Savings page's "Savings History" section shows "No savings history yet."
- Settings' Diagnostics card shows "0 days recorded."
- Triggering (or waiting through, in a running mock scenario) the day-rollover path produces a bucket with a sensible `Net Grid Cost`/`Savings` bar in the chart, and the same numbers in the table view.
- The week/month/year toggle refetches and changes the labels shown.
- Clicking "Clear History" requires a second confirming click, then the day count returns to 0.

- [ ] **Step 5: Commit any fixups from verification, then stop — do not open a PR without the user's go-ahead**

---

## Deferred (explicitly out of scope for this plan)

- A per-day drill-down view replicating today's Overview/Detailed charts for an arbitrary past day.
- Backfilling data from before this feature ships.
- Archiving historical electricity prices separately.
- A payback/investment prediction calculator.
- Consolidating `DailyViewStore` with `HistoricalDataStore`/`PredictionSnapshotStore` (tracked in `TODO.md` under Technical Debt).
- Automatic retention capping/pruning of `DailyViewStore` — it keeps everything until manually cleared.
- Refining the chart/table visual design further than a first functional cut — iterate after seeing it running, per the spec.
