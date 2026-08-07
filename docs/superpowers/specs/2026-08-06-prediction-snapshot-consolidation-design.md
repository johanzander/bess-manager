# Consolidate `PredictionSnapshotStore` into the `DailyView` per-day file

## Problem

Per #409 (follow-up to #408), the "today" store landscape is still
fragmented across three persistence formats:

| Store | Persists? | Where |
|---|---|---|
| `DailyViewStore` | ✅ (forever, until user clears) | `/data/daily_views/{date}.json`, one file/day |
| `PredictionSnapshotStore` | ✅ (discarded at midnight) | `/data/bess_prediction_snapshots.json`, single flat file |
| `ScheduleStore` (strategic intents) | ✅ (discarded at midnight) | `/config/bess_strategic_intents.json`, single flat file |

`#408`'s design explicitly deferred folding `PredictionSnapshotStore` and
`ScheduleStore` into the `DailyView` format. #409 splits that remaining work
into two PRs given the risk asymmetry between the two stores:
`PredictionSnapshotStore` is purely display/diagnostic (dashboards, debug
export, AI-chat "predicted vs actual" comparisons — no hardware write path),
while `ScheduleStore.get_period_data_at()` sits on the hot path for actual
inverter writes (discharge-rate gating, export curtailment). This design
covers **`PredictionSnapshotStore` only** — the lower-risk, currently
untested store — as the first step. `ScheduleStore` gets its own follow-up
design.

## Scope

In scope: replacing `PredictionSnapshotStore`'s bespoke
`/data/bess_prediction_snapshots.json` file with storage inside
`DailyViewStore`'s existing per-day file, keeping the class's public API
unchanged so no call site in `battery_system_manager.py`,
`debug_data_exporter.py`, or `backend/api.py` needs to change.

Out of scope: `ScheduleStore` consolidation (separate design/PR); any UI or
endpoint changes; changing snapshot semantics (what triggers a snapshot,
what it contains).

## Design

### Architecture

`PredictionSnapshotStore` keeps its current public API exactly as-is:
`store_snapshot()`, `get_all_snapshots_today()`, `get_snapshot_at_period()`,
`clear()`, `get_snapshot_count()`. Only its persistence internals change.

- Drop `PERSIST_PATH = Path("/data/bess_prediction_snapshots.json")`.
  Constructor takes the same `persist_dir` as `DailyViewStore`
  (`/data/daily_views`), so both stores read/write `{date}.json` for the
  current day.
- The per-day file's top-level shape becomes:
  ```json
  {"view": <DailyView-or-null>, "snapshots": [<PredictionSnapshot>, ...]}
  ```
  `DailyViewStore.save_day()`/`load_day()` only ever touch `"view"`;
  `PredictionSnapshotStore.store_snapshot()`/`get_all_snapshots_today()`/
  `get_snapshot_at_period()` only ever touch `"snapshots"`. Each does a
  read-modify-write of the whole file so it never clobbers the other's key.
- The existing midnight-based invalidation in `PredictionSnapshotStore`
  (`data["date"] != today` → discard) is removed entirely. A new calendar
  day is naturally a new file (`{new_date}.json`), so snapshots persist
  per-day forever, matching `DailyViewStore`'s existing retention
  (`list_available_dates`/`clear_all` already exclude "today"). The explicit
  `prediction_snapshot_store.clear()` call at `prepare_next_day`
  (`battery_system_manager.py:1471`) becomes redundant and is removed.

### Shared read-modify-write + atomic write

Two independent writers (`DailyViewStore.save_day()`, called every tick, and
`PredictionSnapshotStore.store_snapshot()`, called once per optimization
run) now share one file. Two changes reduce the corruption risk this
introduces:

- `daily_view_store.py` gains `_load_container(path) -> dict` (read+parse,
  return `{}` on missing/corrupt file) and `_write_container(path,
  container)` (atomic write: serialize to a `.tmp` sibling, then
  `os.replace()` over the target). `prediction_snapshot.py` imports and
  reuses both rather than duplicating the read-modify-write logic.
- `DailyViewStore.save_day()` becomes: load container, set `container["view"]
  = asdict(view)`, write container. `PredictionSnapshotStore.store_snapshot()`
  becomes: load container, append to `container.setdefault("snapshots", [])`,
  write container. Both keep the existing best-effort error handling (log +
  continue on `OSError`, never raise).

### Deserialization ownership

`daily_view_store.py` currently imports `_daily_view_from_dict`/
`_period_data_from_dict` *from* `prediction_snapshot.py`. Since
`prediction_snapshot.py`'s bespoke disk format is going away, these two
helpers move to `daily_view_builder.py` (which already owns the `DailyView`/
`PeriodData` dataclasses) as their new canonical home.
`daily_view_store.py` and `prediction_snapshot.py` both import them from
there. `prediction_snapshot.py` keeps `_snapshot_from_dict` (still
snapshot-specific).

### Backward compatibility

Files already on disk under `/data/daily_views/{date}.json` are the old flat
`asdict(view)` shape (no `"view"`/`"snapshots"` wrapper). `load_day()` and
`get_all_snapshots_today()` detect this: if the loaded dict has no `"view"`
key but does have `DailyView` fields (e.g. `"date"`, `"periods"`) at the top
level, treat the whole dict as the view with `snapshots: []`. This only
matters for "today"'s file immediately after a mid-day deploy — historical
(already-completed) days never had snapshots to lose, since
`PredictionSnapshotStore` discarded them at midnight before this change.

### Error handling

Unchanged pattern from both stores today — disk I/O is best-effort, never
fatal:

- Write failure (`OSError`, disk full, permissions): log a warning,
  continue operating (in-memory list is still correct), retry naturally on
  the next write. Never raises out of `store_snapshot()` or `save_day()`.
- Read failure: caught, logged, falls back to empty container (`{}`) —
  equivalent to today's `PredictionSnapshotStore._load_from_disk()` reset
  and `DailyViewStore.load_day()` returning `None`.
- No new exception types.

### Testing

- New `core/bess/tests/unit/test_prediction_snapshot_store.py` — the
  existing gap, currently zero dedicated unit coverage. Covers: round-trip
  save/load of a snapshot, `get_snapshot_at_period()`'s nearest-match
  behavior, `clear()`, `get_snapshot_count()`, and legacy-flat-file fallback
  parsing.
- Shared-file coexistence test: `DailyViewStore.save_day()` then
  `PredictionSnapshotStore.store_snapshot()` (and the reverse order) against
  the same date, asserting neither overwrites the other's top-level key.
- Extend `test_daily_view_store.py`'s existing resilience test classes
  (`TestSaveDayResilience`, `TestLoadDayResilience`) for the new wrapped
  shape, and add a legacy-format-fallback case.
- Update `test_bsm_settings_and_lifecycle.py`'s `prepare_next_day` coverage
  to reflect that `prediction_snapshot_store.clear()` is no longer called
  there (day rollover naturally starts a fresh file).
- No new integration/E2E coverage planned — backend persistence change only,
  no new UI surface; existing `backend/tests/test_dashboard_api.py`
  (`TestPredictionSnapshots` etc.) already covers the API layer against
  mocked store return values and needs no changes since the public API is
  unchanged.

## Out of scope

- `ScheduleStore` consolidation — separate design/PR, given its hot-path
  usage in inverter-write decisions (`get_period_data_at()` feeding
  discharge-rate gating and export curtailment in
  `battery_system_manager.py`) and its currently-lossy persisted shape
  (`period_intents: dict[int, str]` only, vs. the full `PeriodData` its
  in-memory `StoredSchedule.optimization_result` holds).
- Changing what triggers a snapshot or what data it contains.
- Any new UI/endpoint.

## Related

- #408 — `HistoricalDataStore` persistence (the first step toward this;
  explicitly deferred `PredictionSnapshotStore`/`ScheduleStore` folding).
- #409 — this issue; tracks both `PredictionSnapshotStore` (this design) and
  `ScheduleStore` (follow-up design) consolidation.
