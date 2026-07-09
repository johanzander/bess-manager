# Daily Savings History — Design

## Origin

GitHub issue #126, comment #4 (https://github.com/johanzander/bess-manager/issues/126). Frank-Leysen keeps a manual daily log of net supplier result (import EUR − export EUR) to compare against his own meter. Discussing the shape of a fix surfaced a broader, more useful goal: let a user pick any past day on the Savings page and see the exact same Overview/Detailed savings views they'd see for today, just backed by that day's frozen data.

## Goal

Persist each day's full period-level data (the same `PeriodData` objects — energy flows, prices, decisions — that the live Savings page already renders from `DailyView`) so a user can browse back to any past day and see identical Overview/Detailed views, not just a summary number.

## Explicitly out of scope

- Backfilling data from before this feature ships — history starts the day it's deployed.
- Archiving historical electricity prices separately — prices are already captured per-period inside each day's snapshot.
- Weekly/monthly/yearly aggregation views.
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
        ├─ date picker (new) — only past dates with a saved snapshot are selectable
        │
        └─ useDashboardData(date, resolution)      [existing hook, extended]
                │
                ├─ date is today/undefined → GET /api/dashboard              [existing, unchanged]
                └─ date is a past date     → GET /api/savings/history/{date} [new]
                                                    │
                                                    builds the same APIDashboardResponse
                                                    shape, fed from the persisted DailyView
```

## Store: `DailyViewStore` (`core/bess/daily_view_store.py`)

One JSON file per day at `/data/daily_views/YYYY-MM-DD.json` (not one growing file — avoids re-parsing/rewriting the whole history on every write, and each day is naturally an independent unit).

Public interface:

- `save_day(view: DailyView) -> None` — serializes the full `DailyView` (date + all periods with energy/economic/decision data) to that day's file. Called once, at rollover.
- `load_day(day: date) -> DailyView | None` — returns `None` if no file exists for that date (never guessed/interpolated).
- `list_available_dates() -> list[str]` — ISO dates with a saved file, sorted ascending. Backs the date-picker's enabled set.
- `get_disk_usage() -> dict` — e.g. `{"day_count": int, "total_bytes": int}`, for the Settings page display.
- `clear_all() -> None` — deletes every saved file. Backs the Settings page "Clear History" button.

Follows the existing `core/bess/` store convention: plain dataclasses, direct `json.dump`/`json.load` (no atomic temp-file+rename — matches `PredictionSnapshotStore`/`ScheduleStore`, verified neither of those is atomic either).

## Backend API

- `GET /api/savings/history/dates` → `{"dates": ["2026-07-01", "2026-07-02", ...]}` (camelCase via `convert_keys_to_camel_case`, consistent with existing routes).
- `GET /api/savings/history/{date}` → same shape as `APIDashboardResponse` (the existing `/api/dashboard` response type), built from the persisted `DailyView` for that date instead of a live one:
  - `summary`, `hourlyData` — computed exactly as `/api/dashboard` computes them today, just fed the historical `DailyView`.
  - `tomorrowData: []` — no next-day schedule was persisted alongside a historical day; this field is simply empty. `SavingsOverview` already guards on `tomorrowData.length > 0` before rendering that section, so this degrades cleanly with no component change.
  - `currentPeriod: -1` — there is no "now" on a past day; existing "is this the current period" highlighting logic in both components naturally matches nothing.
  - 404 if no snapshot exists for that date (the date-picker won't offer such a date, but the route still needs to fail explicitly rather than guess, per project rules on no silent fallbacks).
- `DELETE /api/savings/history` → calls `DailyViewStore.clear_all()`, returns the new (zeroed) disk-usage dict. Used by the Settings page "Clear History" button.

All new routes follow the existing pattern in `backend/api.py`: `_require_configured_system`, try/except → `HTTPException(500)`, `convert_keys_to_camel_case` on the response dict.

## Frontend

**`useDashboardData(date, resolution)`** (existing hook, `frontend/src/hooks/useDashboardData.ts`): today it always calls `fetchDashboardData` (→ `/api/dashboard`). Extend it to branch: if `date` is provided and is not today's date, call a new `fetchDailySavingsHistory(date)` (→ `/api/savings/history/{date}`) instead. `SavingsOverview` and `DetailedSavingsAnalysis` need no changes — verified they only read `summary`, `hourlyData`, `currentPeriod`, `tomorrowData` from the response, all of which the historical endpoint supplies in the same shape.

**Date picker** (new, on `frontend/src/pages/SavingsPage.tsx`): a calendar/date-input control. On mount, fetch `/api/savings/history/dates` and disable every date not in that list (plus disable future dates). Selecting a date sets state that flows into `SavingsOverview`/`DetailedSavingsAnalysis` as a `date` prop (both already accept and forward one to `useDashboardData`, currently hardcoded to `undefined`). Selecting "today" (or a reset control) returns to the live view.

**Settings page** (`frontend/src/pages/SettingsPage.tsx`, existing "Diagnostics" card, ~line 741): add a "Savings History" row showing `"{day_count} days recorded, {size}"` (from `GET /api/savings/history/dates` + a disk-usage call, or a single combined endpoint — implementation detail for the plan) and a "Clear History" button with a confirm step before calling `DELETE /api/savings/history`.

## Testing

- `core/bess/tests/unit/test_daily_view_store.py` — save/load round-trip, missing-date returns `None`, `list_available_dates` ordering, disk usage counts, `clear_all` behavior.
- `battery_system_manager.py` rollover test (extends existing `TestHandleSpecialCases`) — `_handle_special_cases(prepare_next_day=True)` calls `DailyViewStore.save_day` with the current daily view before the historical store is cleared.
- `backend/tests/test_dashboard_api.py`-style tests for the three new routes: 200/empty list, 200 with a saved day producing the expected shape, 404 for a missing date, 200 for clear.
- Frontend: a test for the date-picker's disabled-dates behavior, and a test that `useDashboardData` calls the history endpoint (not `/api/dashboard`) when given a past date.

## Open implementation detail (left for the plan)

Whether disk usage and the date list are served by one combined endpoint or two separate ones is a small enough call to make during planning rather than here.
