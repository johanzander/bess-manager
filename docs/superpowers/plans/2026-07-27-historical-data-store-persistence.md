# HistoricalDataStore Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make today's `HistoricalDataStore` actuals survive a mid-day process restart by folding it into `DailyViewStore`'s existing per-day file, instead of it being purely in-memory.

**Architecture:** `HistoricalDataStore` becomes a write-through cache: `BatterySystemManager` persists the merged `DailyView` (via the existing `DailyViewBuilder`/`DailyViewStore`) on every tick that records new actuals, and on startup seeds `HistoricalDataStore` from today's file before falling back to InfluxDB for anything still missing. "Clear Savings History" is changed to leave today's file alone.

**Tech Stack:** Python (backend), pytest, existing `DailyViewStore`/`DailyViewBuilder`/`ScheduleStore` classes — no new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-27-historical-data-store-persistence-design.md` — every task below implements a specific section of it.
- Scope is `HistoricalDataStore` only. Do not touch `PredictionSnapshotStore` or `ScheduleStore`'s persistence formats.
- Disk writes must never raise out of the calling code path — mirror `DailyViewStore.save_day()`'s existing best-effort `OSError` handling; do not add new exception types.
- Run `.venv/bin/pytest -m "not slow"` after every task; it must stay green before moving to the next task.

---

### Task 1: Exclude today's file from `DailyViewStore`'s history-wide operations

**Files:**
- Modify: `core/bess/daily_view_store.py`
- Test: `core/bess/tests/unit/test_daily_view_store.py`

**Interfaces:**
- Consumes: `core.bess.time_utils.today() -> date` (existing).
- Produces: `DailyViewStore.list_available_dates()`, `DailyViewStore.get_disk_usage()`, `DailyViewStore.clear_all()` — same signatures as today, but all three now skip `{today}.json`. No change to `save_day()`/`load_day()` signatures (today's file must still be writable/readable by those).

- [ ] **Step 1: Write the failing tests**

Add to `core/bess/tests/unit/test_daily_view_store.py`:

```python
class TestTodayExcludedFromHistoryWideOperations:
    def test_list_available_dates_excludes_today(self, tmp_path, monkeypatch):
        from core.bess import time_utils

        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 27))
        store = DailyViewStore(persist_dir=tmp_path)
        store.save_day(_make_view(date(2026, 7, 26)))
        store.save_day(_make_view(date(2026, 7, 27)))

        assert store.list_available_dates() == ["2026-07-26"]

    def test_disk_usage_excludes_today(self, tmp_path, monkeypatch):
        from core.bess import time_utils

        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 27))
        store = DailyViewStore(persist_dir=tmp_path)
        store.save_day(_make_view(date(2026, 7, 26)))
        store.save_day(_make_view(date(2026, 7, 27)))

        usage = store.get_disk_usage()

        assert usage["day_count"] == 1

    def test_clear_all_leaves_todays_file_in_place(self, tmp_path, monkeypatch):
        from core.bess import time_utils

        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 27))
        store = DailyViewStore(persist_dir=tmp_path)
        store.save_day(_make_view(date(2026, 7, 26)))
        store.save_day(_make_view(date(2026, 7, 27)))

        store.clear_all()

        assert store.load_day(date(2026, 7, 26)) is None
        assert store.load_day(date(2026, 7, 27)) is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest core/bess/tests/unit/test_daily_view_store.py -v`
Expected: the three new tests FAIL (today's file is currently included/deleted like any other).

- [ ] **Step 3: Implement the exclusion**

In `core/bess/daily_view_store.py`, add the import and a private helper, then use it in the three methods:

```python
from . import time_utils
```

```python
    def _is_today(self, path: Path) -> bool:
        return path.stem == time_utils.today().isoformat()

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_daily_view_store.py -v`
Expected: all tests PASS, including the pre-existing ones (`test_clear_all_removes_every_saved_day` etc. use dates that aren't "today" in real time, so they're unaffected).

- [ ] **Step 5: Commit**

```bash
git add core/bess/daily_view_store.py core/bess/tests/unit/test_daily_view_store.py
git commit -m "feat: exclude today's file from DailyViewStore history-wide operations"
```

---

### Task 2: Write-through persistence from `BatterySystemManager`

**Files:**
- Modify: `core/bess/battery_system_manager.py`
- Test: `core/bess/tests/unit/test_bsm_settings_and_lifecycle.py`

**Interfaces:**
- Consumes: `self.schedule_store.get_latest_schedule() -> StoredSchedule | None` (existing), `self.get_current_daily_view() -> DailyView` (existing, line ~3065), `self.daily_view_store.save_day(view: DailyView) -> None` (existing).
- Produces: `BatterySystemManager._persist_today_view() -> None` — new private method. No schedule exists yet → no-op (silent). Schedule exists → best-effort `save_day()` call (`save_day` itself never raises).

- [ ] **Step 1: Write the failing test**

Add to `core/bess/tests/unit/test_bsm_settings_and_lifecycle.py`, near `TestHandleSpecialCases`:

```python
class TestPersistTodayView:
    def test_no_op_when_no_schedule_exists_yet(self, system):
        with patch.object(system, "get_current_daily_view") as mock_get_view:
            system._persist_today_view()
        mock_get_view.assert_not_called()

    def test_saves_current_view_when_schedule_exists(self, system, tmp_path):
        from core.bess.daily_view_builder import DailyView
        from core.bess.daily_view_store import DailyViewStore
        from datetime import date as date_cls

        system.daily_view_store = DailyViewStore(persist_dir=tmp_path)
        fake_view = DailyView(
            date=date_cls(2026, 7, 27),
            periods=[],
            total_savings=4.0,
            actual_count=0,
            predicted_count=0,
        )

        with (
            patch.object(
                system.schedule_store, "get_latest_schedule", return_value=MagicMock()
            ),
            patch.object(system, "get_current_daily_view", return_value=fake_view),
        ):
            system._persist_today_view()

        saved = system.daily_view_store.load_day(date_cls(2026, 7, 27))
        assert saved is not None
        assert saved.total_savings == 4.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_bsm_settings_and_lifecycle.py::TestPersistTodayView -v`
Expected: FAIL with `AttributeError: 'BatterySystemManager' object has no attribute '_persist_today_view'`

- [ ] **Step 3: Implement `_persist_today_view()` and wire it into `_update_energy_data`**

In `core/bess/battery_system_manager.py`, add a new method directly after `get_current_daily_view` (which ends at line 3092):

```python
    def _persist_today_view(self) -> None:
        """Best-effort snapshot of today's merged view to disk.

        Write-through cache for HistoricalDataStore: called on every tick
        that may have recorded new actuals, so a mid-day restart can seed
        from disk instead of relying solely on InfluxDB backfill. No-op
        until the first schedule of the day exists (build_daily_view raises
        ValueError otherwise) — this mirrors the is_first_run skip that used
        to gate the old 23:55-only save call.
        """
        if self.schedule_store.get_latest_schedule() is None:
            return
        self.daily_view_store.save_day(self.get_current_daily_view())
```

Then in `_update_energy_data`, call it unconditionally at the end of the method — replace the closing lines (currently ending at line 1634, `logger.info("Historical store: no periods stored yet")`) so the method ends with:

```python
        else:
            logger.info("Historical store: no periods stored yet")

        self._persist_today_view()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_bsm_settings_and_lifecycle.py -v`
Expected: all PASS, including the new `TestPersistTodayView` tests and every pre-existing test in the file (none of them assert `_update_energy_data` doesn't call anything extra at the end).

- [ ] **Step 5: Commit**

```bash
git add core/bess/battery_system_manager.py core/bess/tests/unit/test_bsm_settings_and_lifecycle.py
git commit -m "feat: persist today's DailyView to disk on every actuals-collecting tick"
```

---

### Task 3: Startup recovery — seed from today's file before InfluxDB

**Files:**
- Modify: `core/bess/battery_system_manager.py`
- Test: `core/bess/tests/unit/test_bsm_settings_and_lifecycle.py` (or a new focused test module if that file is getting unwieldy — check its line count first; if it's already large, create `core/bess/tests/unit/test_bsm_historical_recovery.py` instead, following the same `system` fixture pattern)

**Interfaces:**
- Consumes: `self.daily_view_store.load_day(day: date) -> DailyView | None` (existing), `self.historical_store.record_period(period_index: int, period_data: PeriodData) -> None` (existing, raises `ValueError` out of range), `self.historical_store.get_period(period_index: int) -> PeriodData | None` (existing).
- Produces: `BatterySystemManager._load_today_from_disk(current_period: int) -> None` — new private method, called from `_fetch_and_initialize_historical_data`.

- [ ] **Step 1: Write the failing test**

Add to `core/bess/tests/unit/test_bsm_settings_and_lifecycle.py`:

```python
class TestLoadTodayFromDisk:
    def test_seeds_only_actual_periods_within_range(self, system, tmp_path):
        from core.bess.daily_view_builder import DailyView
        from core.bess.daily_view_store import DailyViewStore
        from core.bess.models import DecisionData, EnergyData, PeriodData
        from datetime import date as date_cls, datetime

        system.daily_view_store = DailyViewStore(persist_dir=tmp_path)

        def _period(index, data_source):
            return PeriodData(
                period=index,
                energy=EnergyData(
                    solar_production=0.0,
                    home_consumption=0.5,
                    battery_charged=0.0,
                    battery_discharged=0.0,
                    grid_imported=0.5,
                    grid_exported=0.0,
                    battery_soe_start=10.0,
                    battery_soe_end=10.0,
                ),
                timestamp=datetime(2026, 7, 27, index // 4, (index % 4) * 15),
                data_source=data_source,
                decision=DecisionData(),
            )

        view = DailyView(
            date=date_cls(2026, 7, 27),
            periods=[
                _period(0, "actual"),
                _period(1, "actual"),
                _period(2, "missing"),
                _period(3, "actual"),  # out of range: current_period will be 2
            ],
            total_savings=0.0,
            actual_count=2,
            predicted_count=0,
        )
        system.daily_view_store.save_day(view)

        system._load_today_from_disk(current_period=2)

        assert system.historical_store.get_period(0) is not None
        assert system.historical_store.get_period(1) is not None
        assert system.historical_store.get_period(2) is None  # was "missing", not seeded
        assert system.historical_store.get_period(3) is None  # out of range, not seeded

    def test_no_op_when_no_file_saved(self, system, tmp_path):
        from core.bess.daily_view_store import DailyViewStore

        system.daily_view_store = DailyViewStore(persist_dir=tmp_path)
        system._load_today_from_disk(current_period=4)
        assert system.historical_store.get_stored_count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest core/bess/tests/unit/test_bsm_settings_and_lifecycle.py::TestLoadTodayFromDisk -v`
Expected: FAIL with `AttributeError: 'BatterySystemManager' object has no attribute '_load_today_from_disk'`

- [ ] **Step 3: Implement `_load_today_from_disk` and wire it into `_fetch_and_initialize_historical_data`**

In `core/bess/battery_system_manager.py`, add a new method right before `_fetch_and_initialize_historical_data` (currently starting at line 841):

```python
    def _load_today_from_disk(self, current_period: int) -> None:
        """Seed historical_store from today's persisted DailyView, if any.

        Only periods marked data_source == "actual" are trusted as real
        recovered data. Periods the file marked "predicted" or "missing"
        (e.g. a period a scheduler tick never got around to recording, see
        issue #403) are deliberately left unseeded so the InfluxDB backfill
        that runs after this can still attempt them.
        """
        view = self.daily_view_store.load_day(time_utils.today())
        if view is None:
            return

        seeded = 0
        for period_data in view.periods:
            if period_data.data_source != "actual":
                continue
            if not 0 <= period_data.period < current_period:
                continue
            try:
                self.historical_store.record_period(
                    period_data.period, period_data
                )
                seeded += 1
            except ValueError as e:
                logger.warning(
                    "Could not seed period %d from disk: %s", period_data.period, e
                )

        if seeded:
            logger.info("Seeded %d period(s) from today's persisted file", seeded)
```

Then modify `_fetch_and_initialize_historical_data` (existing method, current lines 841-963) in two places:

1. Call the new method right after the seed-file check, before the InfluxDB-configured check:

```python
            if current_period > 0 and self._load_historical_seed(current_period):
                self.sensor_collector.warm_readings_cache()
                return

            if current_period > 0:
                self._load_today_from_disk(current_period)

            if not is_influxdb_configured():
```

2. Skip already-seeded periods inside the existing backfill loop — insert this right after the `status_callback` block and before the `try:` that calls `collect_energy_data`:

```python
                for period in range(0, current_period):
                    # Report progress at each hour boundary (every 4th period)
                    if status_callback and period % 4 == 0:
                        hour = period // 4
                        total_hours = current_period // 4
                        status_callback(
                            f"Fetching historical data ({hour}/{total_hours}h)..."
                        )
                    if self.historical_store.get_period(period) is not None:
                        continue
                    try:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_bsm_settings_and_lifecycle.py -v`
Expected: all PASS.

- [ ] **Step 5: Add a test proving InfluxDB backfill skips already-seeded periods**

Add to `core/bess/tests/unit/test_bsm_settings_and_lifecycle.py`:

```python
class TestBackfillSkipsDiskSeededPeriods:
    def test_infludb_backfill_does_not_recollect_seeded_period(self, system, tmp_path):
        from core.bess.daily_view_store import DailyViewStore
        from core.bess.models import DecisionData, EnergyData, PeriodData
        from datetime import datetime

        system.daily_view_store = DailyViewStore(persist_dir=tmp_path)
        seeded_period = PeriodData(
            period=0,
            energy=EnergyData(
                solar_production=0.0,
                home_consumption=0.5,
                battery_charged=0.0,
                battery_discharged=0.0,
                grid_imported=0.5,
                grid_exported=0.0,
                battery_soe_start=10.0,
                battery_soe_end=10.0,
            ),
            timestamp=datetime(2026, 7, 27, 0, 0),
            data_source="actual",
            decision=DecisionData(),
        )
        system.historical_store.record_period(0, seeded_period)

        with (
            patch(
                "core.bess.battery_system_manager.is_influxdb_configured",
                return_value=True,
            ),
            patch.object(
                system.sensor_collector, "collect_energy_data"
            ) as mock_collect,
            patch.object(
                system.price_manager,
                "get_available_prices",
                return_value=([1.0] * 96, [0.5] * 96),
            ),
            patch("core.bess.battery_system_manager.time_utils.now") as mock_now,
        ):
            mock_now.return_value = datetime(2026, 7, 27, 0, 30)
            system._fetch_and_initialize_historical_data()

        # Period 0 was already seeded (from disk, in this test's setup) —
        # the backfill loop must not re-collect it.
        collected_periods = [call.args[0] for call in mock_collect.call_args_list]
        assert 0 not in collected_periods
        assert 1 in collected_periods
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_bsm_settings_and_lifecycle.py::TestBackfillSkipsDiskSeededPeriods -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add core/bess/battery_system_manager.py core/bess/tests/unit/test_bsm_settings_and_lifecycle.py
git commit -m "feat: seed HistoricalDataStore from today's persisted file before InfluxDB backfill"
```

---

### Task 4: Remove the now-redundant 23:55 save call

**Files:**
- Modify: `core/bess/battery_system_manager.py:1403-1442` (`_handle_special_cases`)
- Test: `core/bess/tests/unit/test_bsm_settings_and_lifecycle.py:248-351` (`TestHandleSpecialCases`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_handle_special_cases`'s `prepare_next_day` branch no longer calls `get_current_daily_view()`/`daily_view_store.save_day()` — that's now handled every tick by `_persist_today_view()` from Task 2, including the 23:55 tick itself (since `_update_energy_data` runs on every `update_battery_schedule()` call regardless of `prepare_next_day`).

- [ ] **Step 1: Update `_handle_special_cases`**

Replace the `prepare_next_day` branch (current lines 1429-1442):

```python
        if prepare_next_day:
            logger.info(
                "Preparing for next day - saving daily view and refreshing predictions"
            )
            if is_first_run:
                # No schedule has ever been created yet (fresh start/restart), so
                # there is no completed day's view to persist.
                logger.info(
                    "Skipping daily view save: no schedule exists yet for today"
                )
            else:
                self.daily_view_store.save_day(self.get_current_daily_view())
            self.prediction_snapshot_store.clear()
            self._fetch_predictions()
```

with:

```python
        if prepare_next_day:
            # Today's file is already current — _persist_today_view() (called
            # from _update_energy_data on every tick, including this one) has
            # been keeping it up to date all day. Nothing to save here.
            logger.info("Preparing for next day - refreshing predictions")
            self.prediction_snapshot_store.clear()
            self._fetch_predictions()
```

- [ ] **Step 2: Update the tests that asserted the old save behavior**

In `core/bess/tests/unit/test_bsm_settings_and_lifecycle.py`, replace
`test_prepare_next_day_saves_daily_view_before_clearing` and
`test_prepare_next_day_skips_save_on_first_run` (their premise — that
`_handle_special_cases` itself saves — no longer holds; that behavior is
now covered by Task 2's `TestPersistTodayView`) with a single test proving
`_handle_special_cases` does *not* touch `daily_view_store` at all:

```python
    def test_prepare_next_day_does_not_save_daily_view_itself(self, system, tmp_path):
        """Saving today's file is now _persist_today_view()'s job (called every
        tick from _update_energy_data), not _handle_special_cases's. Regression
        guard against reintroducing a second, now-redundant write path."""
        from core.bess.daily_view_store import DailyViewStore

        system.daily_view_store = DailyViewStore(persist_dir=tmp_path)

        with (
            patch.object(system, "get_current_daily_view") as mock_get_view,
            patch.object(system.daily_view_store, "save_day") as mock_save,
            patch.object(system, "_fetch_predictions"),
        ):
            system._handle_special_cases(
                period=95, prepare_next_day=True, is_first_run=False
            )

        mock_get_view.assert_not_called()
        mock_save.assert_not_called()
```

Also simplify `test_prepare_next_day_does_not_clear_historical_store` and
`test_prepare_next_day_clears_stores_and_refetches` by removing their now-
unnecessary `patch.object(system, "get_current_daily_view")` and
`patch.object(system.daily_view_store, "save_day")` context managers —
`_handle_special_cases` no longer calls either, so patching them adds
nothing:

```python
    def test_prepare_next_day_does_not_clear_historical_store(self, system):
        """prepare_next_day fires at 23:55, 5 minutes before midnight, while
        today's dashboard still needs today's actuals. Clearing here wiped
        today's real sensor data early and produced false "missing hours"
        and a broken chart (issue #380 follow-up)."""
        with (
            patch.object(system, "_fetch_predictions"),
            patch.object(system.historical_store, "clear") as mock_clear,
        ):
            system._handle_special_cases(
                period=95, prepare_next_day=True, is_first_run=False
            )
            mock_clear.assert_not_called()

    def test_prepare_next_day_clears_stores_and_refetches(self, system):
        system._consumption_predictions = [1.0] * 96
        system._solar_predictions = [0.0] * 96
        with patch.object(system, "_fetch_predictions") as mock_fetch:
            system._handle_special_cases(
                period=0, prepare_next_day=True, is_first_run=False
            )
            mock_fetch.assert_called_once()
```

- [ ] **Step 3: Run the full test file**

Run: `.venv/bin/pytest core/bess/tests/unit/test_bsm_settings_and_lifecycle.py -v`
Expected: all PASS. `TestHandleSpecialCases` should now have no reference
to `daily_view_store`/`get_current_daily_view` except in the new
`test_prepare_next_day_does_not_save_daily_view_itself` regression guard.

- [ ] **Step 4: Commit**

```bash
git add core/bess/battery_system_manager.py core/bess/tests/unit/test_bsm_settings_and_lifecycle.py
git commit -m "refactor: remove redundant 23:55 daily-view save now that persistence is incremental"
```

---

### Task 5: Full test suite and quality gate

**Files:** none (verification only)

- [ ] **Step 1: Run the fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: all PASS.

- [ ] **Step 2: Run the full quality gate**

Run: `./scripts/quality-check.sh`
Expected: black/ruff/mypy/tests all PASS. Fix any formatting/lint issues it surfaces and re-run.

- [ ] **Step 3: Run the slow suite**

Run: `.venv/bin/pytest -m slow`
Expected: all PASS (this suite includes algorithm/integration tests that exercise `update_battery_schedule` end-to-end and could be sensitive to `_persist_today_view()` being called on every tick).

- [ ] **Step 4: Commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: address quality-check.sh findings"
```

(Skip this commit if step 2/3 found nothing to fix.)

---

## Explicitly out of scope (per spec)

- `_load_historical_seed` (the `BESS_HISTORICAL_SEED_FILE` test/E2E-replay path) does **not** call `_persist_today_view()` or get touched by this plan — it's a fixture-injection mechanism for mock-HA scenarios, not real production data collection, and persisting replayed fixtures to `/data/daily_views` would conflate the two.
- No UI or endpoint for clearing today's in-progress data.
- No changes to `PredictionSnapshotStore` or `ScheduleStore`.
- No fix for issue #403 itself (the scheduler misfire) — this plan only makes its symptom recoverable via the InfluxDB-fills-remaining-gaps step in Task 3.
