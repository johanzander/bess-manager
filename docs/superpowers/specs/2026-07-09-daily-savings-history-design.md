# Daily Savings History — Design

## Origin

GitHub issue #126, comment #4 (https://github.com/johanzander/bess-manager/issues/126). Frank-Leysen keeps a manual daily log of net supplier result (import EUR − export EUR) to compare against his own meter. Discussing the shape of a fix surfaced a broader, more useful goal: show savings trends over time — week/month/year — not just today, in a way that's intuitive to browse.

## Goal

Today the Savings page only shows a single day at a time, live, lost at midnight. The primary goal is an **aggregated view: week / month / year, browsable with a simple toggle**, so a user can see trends over time — not just today. Financial totals (net grid cost, savings, battery wear) are the headline numbers; energy-flow totals (solar/import/export/battery kWh) are a nice-to-have alongside them as long as they don't clutter the view.

To make that possible, each day's full period-level data (the same `PeriodData` objects — energy flows, prices, decisions — that the live Savings page already renders from `DailyView`) is persisted once per day. This is deliberately more than the aggregate view strictly needs today, so that "show all historical data" stays possible later without a second migration — but the *only* UI built now is the aggregate rollup.

The exact visual shape of the aggregate view (bar chart vs. table vs. both with a toggle) is intentionally not fully pinned down here — build a first cut and iterate on it directly rather than speccing pixel layout up front.

## Explicitly out of scope

- A per-day drill-down that replicates today's Overview/Detailed views for an arbitrary past day — dropped for now. (This was the original framing of this spec; superseded — see note above. May return later as a secondary view once the aggregate view exists.)
- Backfilling data from before this feature ships — history starts the day it's deployed.
- Archiving historical electricity prices separately — prices are already captured per-period inside each day's snapshot.
- A payback/investment prediction calculator.
- Any change to `/api/dashboard`'s live behavior or response shape.
- Any change to `HistoricalDataStore`/`PredictionSnapshotStore`'s existing daily-clear behavior. (Noted for later: the user wants these three stores eventually consolidated/simplified — this design keeps the new store's schema close to `DailyView`/`PeriodData` rather than inventing a divergent shape, so that future consolidation isn't made harder than necessary. No action beyond that is taken now.)

## Architecture

```
23:55 rollover (existing trigger, battery_system_manager.py:_handle_special_cases)
        │
        ├─ DailyViewStore.save_day(view)         [new]
        ├─ historical_store.clear()               [existing, unchanged]
        └─ prediction_snapshot_store.clear()       [existing, unchanged]

Savings page
        │
        ├─ period-type toggle: week / month / year (new)
        │
        └─ GET /api/savings/aggregate?period=week|month|year&count=N   [new]
                │
                loads the relevant days from DailyViewStore, sums financials
                (+ energy-flow totals) per bucket, returns one row per bucket
```

No change to `/api/dashboard` or its live behavior. No per-day drill-down endpoint in this pass (see Explicitly out of scope) — `DailyViewStore` still persists full per-day detail so that door isn't closed, it's just not exposed yet.

## Store: `DailyViewStore` (`core/bess/daily_view_store.py`)

One JSON file per day at `/data/daily_views/YYYY-MM-DD.json` (not one growing file — avoids re-parsing/rewriting the whole history on every write, and each day is naturally an independent unit).

Public interface:

- `save_day(view: DailyView) -> None` — serializes the full `DailyView` (date + all periods with energy/economic/decision data) to that day's file. Called once, at rollover.
- `load_day(day: date) -> DailyView | None` — returns `None` if no file exists for that date (never guessed/interpolated).
- `list_available_dates() -> list[str]` — ISO dates with a saved file, sorted ascending. Used by the aggregation logic to know which days exist in a given bucket.
- `get_disk_usage() -> dict` — e.g. `{"day_count": int, "total_bytes": int}`, for the Settings page display.
- `clear_all() -> None` — deletes every saved file. Backs the Settings page "Clear History" button.

Follows the existing `core/bess/` store convention: plain dataclasses, direct `json.dump`/`json.load` (no atomic temp-file+rename — matches `PredictionSnapshotStore`/`ScheduleStore`, verified neither of those is atomic either).

## Backend API

- `GET /api/savings/aggregate?period=week|month|year&count=N` → `{"buckets": [...], "count": N}`. Each bucket:
  - `label` — human-readable, e.g. `"2026-W27"` (week), `"2026-07"` (month), `"2026"` (year).
  - `startDate` / `endDate` — ISO dates the bucket spans.
  - `dayCount` — how many days in this bucket actually have a saved snapshot (a partial current week/month/year, or a gap from downtime, just means a lower count — never guessed/interpolated).
  - Financials (headline): `importEur`, `exportEur`, `gridCost`, `batteryCycleCost`, `savingsVsGridOnly` — each a `FormattedValue`, summed across the bucket's saved days.
  - Energy flows (secondary, shown alongside if it doesn't clutter): `importKwh`, `exportKwh`, `solarKwh`, `batteryChargedKwh`, `batteryDischargedKwh` — same treatment.
  - Buckets are computed server-side from `DailyViewStore` snapshots (summing per-period `energy`/`economic` fields already in each day's persisted `DailyView` — the same fields the daily rollover capture already reads). `count` defaults to a sensible default per period type (e.g. 12 weeks, 12 months, 5 years) — exact default is a small planning-time detail.
  - No stored days at all → `buckets: []`; the frontend shows an empty state, not an error.
- `DELETE /api/savings/history` → calls `DailyViewStore.clear_all()`, returns the new (zeroed) disk-usage dict. Used by the Settings page "Clear History" button.
- `GET /api/savings/history/disk-usage` → `{"dayCount": int, "totalBytes": int}`, for the Settings page display.

All new routes follow the existing pattern in `backend/api.py`: `_require_configured_system`, try/except → `HTTPException(500)`, `convert_keys_to_camel_case` on the response dict.

## Frontend

**New `frontend/src/pages/SavingsHistoryPage.tsx` (or a new section on the existing Savings page — exact placement a planning-time detail)**: a period-type toggle (week/month/year) plus a combined bar-chart/table view (per the user's own preference — build both, toggle between them, and iterate visually once it's running rather than finalize the exact layout here). Fetches `GET /api/savings/aggregate` for the selected period type and renders `gridCost`/`savingsVsGridOnly` as the primary bars/columns, with energy-flow figures available but not competing for primary visual weight.

**New hook `useSavingsAggregate(period, count)`** (`frontend/src/hooks/useSavingsAggregate.ts`) — same loading/error/data shape as the existing `useDashboardData`, calling the new aggregate endpoint.

**Settings page** (`frontend/src/pages/SettingsPage.tsx`, existing "Diagnostics" card, ~line 741): add a "Savings History" row showing `"{day_count} days recorded, {size}"` (from `GET /api/savings/history/disk-usage`) and a "Clear History" button with a confirm step before calling `DELETE /api/savings/history`.

No date-picker, no per-day drill-down view, no changes to `SavingsOverview`/`DetailedSavingsAnalysis`/`useDashboardData` in this pass.

## Testing

- `core/bess/tests/unit/test_daily_view_store.py` — save/load round-trip, missing-date returns `None`, `list_available_dates` ordering, disk usage counts, `clear_all` behavior.
- `battery_system_manager.py` rollover test (extends existing `TestHandleSpecialCases`) — `_handle_special_cases(prepare_next_day=True)` calls `DailyViewStore.save_day` with the current daily view before the historical store is cleared.
- `core/bess/tests/unit/` — aggregation logic (whichever module computes week/month/year buckets from a list of `DailyView`s): correct bucket boundaries, correct sums, partial buckets when days are missing.
- `backend/tests/test_dashboard_api.py`-style tests for the new routes: empty-store → `buckets: []`; a few saved days → correct bucket sums; disk-usage and clear round-trip.
- Frontend: a test that `useSavingsAggregate` calls the endpoint with the right period/count and exposes loading/error/data; a smoke test that the aggregate view renders bars/rows for returned buckets and an empty state for none.

## Open implementation details (left for the plan)

- Default `count` per period type (e.g. 12/12/5), and where the aggregation-bucketing logic lives (a new pure module vs. a method on `DailyViewStore`).
- Exact placement of the aggregate view on the Savings page vs. a new page/tab.
- Exact bar-chart vs. table visual treatment — build a first cut, iterate directly rather than finalize here.
