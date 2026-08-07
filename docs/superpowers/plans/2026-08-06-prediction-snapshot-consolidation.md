# PredictionSnapshotStore Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold `PredictionSnapshotStore`'s persistence into `DailyViewStore`'s existing per-day file (`/data/daily_views/{date}.json`) instead of its own bespoke `/data/bess_prediction_snapshots.json`, with zero call-site changes and no data-loss regression.

**Architecture:** The per-day file's top-level shape becomes `{"view": <DailyView|null>, "snapshots": [<PredictionSnapshot>, ...]}`. `DailyViewStore` only ever touches `"view"`; `PredictionSnapshotStore` only ever touches `"snapshots"`. Both go through new shared `_load_container`/`_write_container` helpers in `daily_view_store.py` that do an atomic (temp-file + `os.replace`) read-modify-write, so the two independent writers never clobber each other's key. `PredictionSnapshotStore`'s midnight-based invalidation is removed — a new calendar day is naturally a new file.

**Tech Stack:** Python 3.13, dataclasses, `pytest` (`.venv/bin/pytest`), existing `core/bess/tests/unit/` suite.

## Global Constraints

- Public API of `PredictionSnapshotStore` (`store_snapshot`, `get_all_snapshots_today`, `get_snapshot_at_period`, `clear`, `get_snapshot_count`) does not change — no call-site edits in `battery_system_manager.py`, `debug_data_exporter.py`, or `backend/api.py`.
- `ScheduleStore` is explicitly out of scope for this plan (separate design/PR per the spec).
- No new UI/endpoint, no change to what triggers a snapshot or what it contains.
- Disk I/O stays best-effort: write/read failures log a warning and never raise out of the store's public methods.
- Spec: `docs/superpowers/specs/2026-08-06-prediction-snapshot-consolidation-design.md`.

---

### Task 1: Shared container helpers + atomic write + relocate deserialization in `daily_view_store.py`/`daily_view_builder.py`

**Files:**
- Modify: `core/bess/daily_view_store.py`
- Modify: `core/bess/daily_view_builder.py`
- Test: `core/bess/tests/unit/test_daily_view_store.py`

**Interfaces:**
- Consumes: nothing new from other tasks (this is the foundation task).
- Produces (for Task 2 to consume):
  - `daily_view_store._load_container(path: Path) -> dict` — returns `{}` on missing file, corrupt JSON, or `OSError` (logs a warning on the latter two).
  - `daily_view_store._write_container(path: Path, container: dict) -> None` — atomic write (`.tmp` sibling + `os.replace`); raises `OSError` on failure (caller catches).
  - `daily_view_builder._daily_view_from_dict(d: dict) -> DailyView` — moved here from `prediction_snapshot.py`, same signature/behavior.
  - `daily_view_builder._period_data_from_dict(d: dict) -> PeriodData` — moved here from `prediction_snapshot.py`, same signature/behavior.

- [ ] **Step 1: Write the failing test for the new wrapped container shape**

Add to `core/bess/tests/unit/test_daily_view_store.py`, in a new class at the end of the file:

```python
class TestSharedContainerShape:
    def test_save_day_writes_view_key_wrapper(self, tmp_path):
        import json

        store = DailyViewStore(persist_dir=tmp_path)
        store.save_day(_make_view(date(2026, 7, 8)))

        raw = json.loads((tmp_path / "2026-07-08.json").read_text())
        assert "view" in raw
        assert raw["view"]["total_savings"] == 3.5

    def test_save_day_preserves_existing_snapshots_key(self, tmp_path):
        import json

        path = tmp_path / "2026-07-08.json"
        path.write_text(json.dumps({"snapshots": [{"foo": "bar"}]}))

        store = DailyViewStore(persist_dir=tmp_path)
        store.save_day(_make_view(date(2026, 7, 8)))

        raw = json.loads(path.read_text())
        assert raw["snapshots"] == [{"foo": "bar"}]
        assert raw["view"]["total_savings"] == 3.5


class TestLegacyFlatFormatFallback:
    def test_load_day_parses_pre_consolidation_flat_file(self, tmp_path):
        """Files written before this change have no "view"/"snapshots"
        wrapper - the whole file IS the DailyView dict."""
        import json
        from dataclasses import asdict

        path = tmp_path / "2026-07-08.json"
        path.write_text(json.dumps(asdict(_make_view(date(2026, 7, 8))), default=str))

        store = DailyViewStore(persist_dir=tmp_path)
        loaded = store.load_day(date(2026, 7, 8))

        assert loaded is not None
        assert loaded.total_savings == 3.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest core/bess/tests/unit/test_daily_view_store.py -v`
Expected: `TestSharedContainerShape` and `TestLegacyFlatFormatFallback` tests FAIL — `save_day` currently writes the flat `asdict(view)` shape directly (no `"view"` wrapper key), so `raw["view"]` raises `KeyError`.

- [ ] **Step 3: Move deserialization helpers into `daily_view_builder.py`**

In `core/bess/daily_view_builder.py`, add `import dataclasses` to the imports and, immediately after the `DailyView` dataclass definition, add:

```python
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
```

(`EnergyData`, `EconomicData`, `DecisionData`, `PeriodData` are already imported at the top of this file; `date`/`datetime` are already imported too.)

Remove the equivalent `_period_data_from_dict` and `_daily_view_from_dict` function bodies from `core/bess/prediction_snapshot.py` (they stay defined only in `daily_view_builder.py` now). In `prediction_snapshot.py`, change the import line to pull them in instead:

```python
from core.bess.daily_view_builder import DailyView, _daily_view_from_dict, _period_data_from_dict
```

`prediction_snapshot.py` keeps its own `_snapshot_from_dict` (still snapshot-specific), which now calls the imported `_daily_view_from_dict`.

- [ ] **Step 4: Add shared container helpers and rewrite `save_day`/`load_day` in `daily_view_store.py`**

In `core/bess/daily_view_store.py`, add `import os` to imports, remove the now-stale `from .prediction_snapshot import _daily_view_from_dict` line, and change the `DailyView` import to `from .daily_view_builder import DailyView, _daily_view_from_dict`.

Add module-level helpers (above the `DailyViewStore` class):

```python
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
```

Replace `save_day`'s body:

```python
    def save_day(self, view: DailyView) -> None:
        """Persist the given day's full view, overwriting any existing file for that date."""
        path = self._persist_dir / f"{view.date.isoformat()}.json"
        try:
            container = _load_container(path)
            container["view"] = asdict(view)
            _write_container(path, container)
        except OSError as e:
            logger.warning("Failed to persist daily view for %s: %s", view.date, e)
```

Replace `load_day`'s body:

```python
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
```

Leave `list_available_dates`, `get_disk_usage`, and `clear_all` unchanged — they operate on file existence/paths, not container contents.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_daily_view_store.py -v`
Expected: PASS, all tests including the new ones. Also run `.venv/bin/pytest core/bess/tests/unit/test_daily_view_store.py::TestLoadDayResilience -v` specifically — confirm `test_load_day_returns_none_for_schema_invalid_json` still passes (a `{"foo": "bar"}` file has neither `"view"` nor `"date"`/`"periods"`, so `load_day` still correctly returns `None`).

- [ ] **Step 6: Run the full fast suite to catch any other `prediction_snapshot` import break**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS. `core/bess/prediction_snapshot.py` still exports `_snapshot_from_dict`, `PredictionSnapshot`, `PredictionSnapshotStore` unchanged at this point (Task 2 changes its persistence internals) — only its deserialization-helper imports moved, so nothing importing from it directly should break yet.

- [ ] **Step 7: Commit**

```bash
git add core/bess/daily_view_store.py core/bess/daily_view_builder.py core/bess/prediction_snapshot.py core/bess/tests/unit/test_daily_view_store.py
git commit -m "refactor: shared atomic container helpers + relocate DailyView deserialization (#409)"
```

---

### Task 2: Swap `PredictionSnapshotStore` persistence to the shared per-day file

**Files:**
- Modify: `core/bess/prediction_snapshot.py`
- Test: `core/bess/tests/unit/test_prediction_snapshot_store.py` (new)

**Interfaces:**
- Consumes: `daily_view_store._load_container`, `daily_view_store._write_container` (from Task 1); `daily_view_builder._daily_view_from_dict`, `daily_view_builder._period_data_from_dict` (relocated in Task 1).
- Produces: `PredictionSnapshotStore(persist_dir: Path = Path("/data/daily_views"))` — same class name and public methods as before, only the constructor parameter changes from `persist_path` to `persist_dir`. Later tasks (Task 3) construct it the same way as `DailyViewStore`.

- [ ] **Step 1: Write the failing test for round-trip via the shared file**

Create `core/bess/tests/unit/test_prediction_snapshot_store.py`:

```python
"""Unit tests for PredictionSnapshotStore."""

from datetime import date, datetime

from core.bess import time_utils
from core.bess.daily_view_builder import DailyView
from core.bess.daily_view_store import DailyViewStore
from core.bess.models import EconomicData, EnergyData, PeriodData
from core.bess.prediction_snapshot import PredictionSnapshotStore


def _make_period(period: int) -> PeriodData:
    energy = EnergyData(
        solar_production=1.0,
        home_consumption=1.0,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=1.0,
        grid_exported=0.0,
        battery_soe_start=10.0,
        battery_soe_end=10.0,
    )
    economic = EconomicData(buy_price=2.0, sell_price=1.0, battery_cycle_cost=0.05)
    return PeriodData(
        period=period,
        energy=energy,
        timestamp=datetime(2026, 7, 8, period // 4, (period % 4) * 15),
        data_source="predicted",
        economic=economic,
    )


def _make_view(day: date) -> DailyView:
    return DailyView(
        date=day,
        periods=[_make_period(0), _make_period(1)],
        total_savings=3.5,
        actual_count=0,
        predicted_count=2,
    )


class TestStoreAndRetrieve:
    def test_store_snapshot_round_trips_through_disk(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        store = PredictionSnapshotStore(persist_dir=tmp_path)

        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[{"start": "00:00", "end": "06:00"}],
            predicted_daily_savings=12.5,
        )

        reloaded = PredictionSnapshotStore(persist_dir=tmp_path)
        snapshots = reloaded.get_all_snapshots_today()

        assert len(snapshots) == 1
        assert snapshots[0].optimization_period == 24
        assert snapshots[0].predicted_daily_savings == 12.5
        assert snapshots[0].daily_view.total_savings == 3.5
        assert snapshots[0].growatt_schedule == [{"start": "00:00", "end": "06:00"}]

    def test_get_all_snapshots_today_orders_chronologically(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        store = PredictionSnapshotStore(persist_dir=tmp_path)

        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 12, 0),
            optimization_period=48,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=5.0,
        )
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )

        ordered = store.get_all_snapshots_today()
        assert [s.optimization_period for s in ordered] == [24, 48]

    def test_get_snapshot_at_period_returns_closest_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        store = PredictionSnapshotStore(persist_dir=tmp_path)
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 12, 0),
            optimization_period=48,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=5.0,
        )

        closest = store.get_snapshot_at_period(50)
        assert closest.optimization_period == 48

    def test_get_snapshot_at_period_returns_none_when_empty(self, tmp_path):
        store = PredictionSnapshotStore(persist_dir=tmp_path)
        assert store.get_snapshot_at_period(10) is None


class TestClearAndCount:
    def test_clear_empties_snapshots_and_persists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        store = PredictionSnapshotStore(persist_dir=tmp_path)
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )

        store.clear()

        assert store.get_snapshot_count() == 0
        reloaded = PredictionSnapshotStore(persist_dir=tmp_path)
        assert reloaded.get_snapshot_count() == 0

    def test_get_snapshot_count_starts_at_zero(self, tmp_path):
        store = PredictionSnapshotStore(persist_dir=tmp_path)
        assert store.get_snapshot_count() == 0


class TestSharedFileWithDailyViewStore:
    def test_snapshot_write_does_not_clobber_daily_view(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        view_store = DailyViewStore(persist_dir=tmp_path)
        snapshot_store = PredictionSnapshotStore(persist_dir=tmp_path)

        view_store.save_day(_make_view(date(2026, 7, 8)))
        snapshot_store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )

        assert view_store.load_day(date(2026, 7, 8)) is not None
        assert len(
            PredictionSnapshotStore(persist_dir=tmp_path).get_all_snapshots_today()
        ) == 1

    def test_daily_view_save_after_snapshot_write_preserves_snapshots(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        view_store = DailyViewStore(persist_dir=tmp_path)
        snapshot_store = PredictionSnapshotStore(persist_dir=tmp_path)

        snapshot_store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )
        view_store.save_day(_make_view(date(2026, 7, 8)))

        assert len(
            PredictionSnapshotStore(persist_dir=tmp_path).get_all_snapshots_today()
        ) == 1


class TestLegacyFlatFormatFallback:
    def test_snapshots_start_empty_for_pre_consolidation_flat_file(
        self, tmp_path, monkeypatch
    ):
        """A DailyViewStore file written before this change has no
        "snapshots" key at all - should load as zero snapshots, not error."""
        import json
        from dataclasses import asdict

        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        path = tmp_path / "2026-07-08.json"
        path.write_text(json.dumps(asdict(_make_view(date(2026, 7, 8))), default=str))

        store = PredictionSnapshotStore(persist_dir=tmp_path)

        assert store.get_all_snapshots_today() == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_prediction_snapshot_store.py -v`
Expected: FAIL — `PredictionSnapshotStore.__init__` currently takes `persist_path`, not `persist_dir` (`TypeError: unexpected keyword argument`).

- [ ] **Step 3: Rewrite `PredictionSnapshotStore`'s persistence internals**

In `core/bess/prediction_snapshot.py`:

Remove `PERSIST_PATH = Path("/data/bess_prediction_snapshots.json")`; add `PERSIST_DIR = Path("/data/daily_views")` (matches `daily_view_store.PERSIST_DIR`).

Add the import: `from core.bess.daily_view_store import _load_container, _write_container`.

Change the constructor:

```python
    def __init__(self, persist_dir: Path = PERSIST_DIR):
        """Initialize the prediction snapshot store and load any persisted data."""
        self._snapshots: list[PredictionSnapshot] = []
        self._persist_dir = persist_dir
        self._load_from_disk()
        logger.debug("Initialized PredictionSnapshotStore")

    def _today_path(self) -> Path:
        return self._persist_dir / f"{time_utils.today().isoformat()}.json"
```

Replace `_save_to_disk`:

```python
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
```

Replace `_load_from_disk`:

```python
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
```

`store_snapshot` and `clear` are unchanged (both already just call `self._save_to_disk()`).

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_prediction_snapshot_store.py -v`
Expected: PASS, all classes.

- [ ] **Step 5: Commit**

```bash
git add core/bess/prediction_snapshot.py core/bess/tests/unit/test_prediction_snapshot_store.py
git commit -m "feat: persist PredictionSnapshotStore in the shared DailyView per-day file (#409)"
```

---

### Task 3: Remove the now-redundant midnight `clear()` call in `battery_system_manager.py`

**Files:**
- Modify: `core/bess/battery_system_manager.py:1466-1472` (`_handle_special_cases`)
- Test: `core/bess/tests/unit/test_bsm_settings_and_lifecycle.py`

**Interfaces:**
- Consumes: `PredictionSnapshotStore` (unchanged public API from Task 2) — `battery_system_manager.py`'s existing `self.prediction_snapshot_store = PredictionSnapshotStore()` construction needs no change, since its default `persist_dir` (`/data/daily_views`) now already matches `self.daily_view_store`'s default `persist_dir`.
- Produces: nothing consumed by later tasks — this is the last task.

- [ ] **Step 1: Write the failing regression test**

Add to `core/bess/tests/unit/test_bsm_settings_and_lifecycle.py`, in the same test class as `test_prepare_next_day_does_not_clear_historical_store` (search for that method to find the class):

```python
    def test_prepare_next_day_does_not_clear_prediction_snapshot_store(self, system):
        """Day rollover now happens via a new per-day file (folded into the
        DailyView format, #409) instead of an explicit clear() call - a new
        calendar day naturally starts a new, empty file."""
        with (
            patch.object(system, "_fetch_predictions"),
            patch.object(system.prediction_snapshot_store, "clear") as mock_clear,
        ):
            system._handle_special_cases(
                period=95, prepare_next_day=True, is_first_run=False
            )
            mock_clear.assert_not_called()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_bsm_settings_and_lifecycle.py -v -k test_prepare_next_day_does_not_clear_prediction_snapshot_store`
Expected: FAIL — `mock_clear.assert_not_called()` fails because `_handle_special_cases` still calls `self.prediction_snapshot_store.clear()`.

- [ ] **Step 3: Remove the call**

In `core/bess/battery_system_manager.py`, in `_handle_special_cases`, delete the line `self.prediction_snapshot_store.clear()` (currently line 1471), leaving:

```python
        if prepare_next_day:
            # Today's file is already current — _persist_today_view() (called
            # from _update_energy_data on every tick, including this one) has
            # been keeping it up to date all day. Nothing to save here.
            # prediction_snapshot_store's file similarly rolls over
            # automatically at midnight (a new date is a new file) - no
            # explicit clear() needed here (#409).
            logger.info("Preparing for next day - refreshing predictions")
            self._fetch_predictions()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_bsm_settings_and_lifecycle.py -v -k test_prepare_next_day_does_not_clear_prediction_snapshot_store`
Expected: PASS.

- [ ] **Step 5: Run the full fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS. `test_prepare_next_day_clears_stores_and_refetches` (the pre-existing test, name notwithstanding) only asserts `mock_fetch.assert_called_once()` — no assertion on `prediction_snapshot_store.clear()` — so it is unaffected by removing that call.

- [ ] **Step 6: Commit**

```bash
git add core/bess/battery_system_manager.py core/bess/tests/unit/test_bsm_settings_and_lifecycle.py
git commit -m "fix: drop redundant PredictionSnapshotStore.clear() at day rollover (#409)"
```

---

## Post-plan steps (owned by `implement-issue`, not this plan)

- Run `.venv/bin/pytest -m slow` (slow suite).
- Run `code-review` on the diff.
- `verify` skill: exercise a real optimization tick against mock-HA, confirm a snapshot is written into `/data/daily_views/{date}.json` under `"snapshots"` alongside `"view"`, and confirm `GET /api/prediction-analysis/snapshots` / `.../timeline` still return the expected shape.
- `CHANGELOG.md` entry under `## [Unreleased]` / `### Changed`.
- Check `docs/agents/bess-knowledge.md` / `docs/SOFTWARE_DESIGN.md` for any mention of `/data/bess_prediction_snapshots.json` or `PredictionSnapshotStore`'s persistence path that needs updating.
- Delete this plan file and the design spec's plan reference before the final commit per `implement-issue`'s Step 10 (keep the spec, drop the plan) — do not delete the spec.
