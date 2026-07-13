# Design: Dashboard Net Cost/Savings should reflect the full optimization horizon

**Date**: 2026-07-13
**Issue**: [#287](https://github.com/johanzander/bess-manager/issues/287)
**Related**: #126, #275, #276, #285,
`docs/superpowers/specs/2026-07-12-issue-275-root-cause-investigation.md`
(the investigation that identified this as a display gap, not an algorithm
bug — see that doc's "Recommendation" section for the original framing)

## Problem

When `prices_tomorrow` is available, the DP optimizer plans a full 2-day
(192-period) schedule. When that plan correctly defers value to tomorrow
(e.g. holding an overnight reserve because tomorrow's evening peak pays
more, or to avoid overnight grid import), today's slice of the plan
necessarily looks worse in isolation — with no visibility anywhere in the
UI into the larger gain landing the next day. This produced the "Net Cost
dropped from -0.80 to -0.15" observation reported in #126 and investigated
in #275/#276/#285.

## Root cause

`backend/api.py`'s `/api/dashboard` endpoint sums `gridCost`/`gridOnlyCost`
only over `daily_view.periods`, which `DailyViewBuilder.build_daily_view()`
hard-caps at today's ~96 periods (`core/bess/daily_view_builder.py:118`)
even when the DP's `period_data` holds up to 192. The endpoint already
extracts a `tomorrow_data` list (`backend/api.py:670-730`) for the
tomorrow-schedule-preview table, but never folds it into the cost totals.

## Scope

**In scope:** the Dashboard page's "Today's Cost & Savings" glance card
(`frontend/src/components/SystemStatusCard.tsx`) — the Net Grid Cost and
Net Savings figures specifically.

**Out of scope:** the Savings view (`SavingsAggregateView.tsx`). That view
is framed as a historical ledger with a day/month/year date picker, so
folding a forecast into "today"'s bucket there is a different, murkier
product question — it also raises the pre-existing, unresolved question of
how actual-vs-predicted data should be visually distinguished at all in
that view (today's own numbers already blend both), and whether "tomorrow"
should become its own selectable day once its prices are known. Not
deciding that here; noted as an open question for a future design pass.

## Design

### Backend

1. **`backend/api.py`** (`get_dashboard_data`): the tomorrow-period
   extraction logic (currently inline, `backend/api.py:670-730`) computes
   `tomorrow_data: list[APIDashboardHourlyData]`. When it's non-empty,
   additionally sum `gridCost.value` and `gridOnlyCost.value` over it to get
   `tomorrow_net_grid_cost` / `tomorrow_grid_only_cost`. Add to the `costs`
   dict:
   - `netGridFullHorizon` = today's `netGrid` + `tomorrow_net_grid_cost`
   - `gridOnlyFullHorizon` = today's `gridOnly` + `tomorrow_grid_only_cost`
   - `horizonDays` = 2 if `tomorrow_data` is non-empty, else 1

2. **`backend/api_dataclasses.py`** (`APIDashboardSummary`): add three
   fields — `netGridCostFullHorizon: FormattedValue | None`,
   `netSavingsFullHorizon: FormattedValue | None` (computed as
   `gridOnlyFullHorizon - netGridFullHorizon`, mirroring how `netSavings`
   is derived today), `horizonDays: int`. `None`/`1` when there's no 2-day
   plan — never a guessed fallback value.

No changes to the DP, `DailyViewBuilder`, or the today-only truncation
itself — both are still correct for what they're for (today's actual
merge-with-sensors view). This only adds a second, parallel total.

### Frontend

3. **`frontend/src/api/scheduleApi.ts`**: add the three optional fields to
   the `DashboardSummary` type.

4. **`frontend/src/components/SystemStatusCard.tsx`**:
   - Extend `StatusCardProps` with optional `keyAnnotation?: string`
     (small text rendered under the big key value) and an optional
     `subLabel?: string` per metric row (generalizing the existing
     `systemMode === 'demo'` "theoretical" annotation pattern at
     `SystemStatusCard.tsx:124-128` into a reusable prop instead of a
     one-off conditional).
   - Read the new optional summary fields (no throw — legitimately absent
     on a single-day horizon).
   - **Net Grid Cost** (`keyValue`): when `horizonDays === 2`, becomes the
     full-horizon total, with `keyAnnotation` = `"Today: {todaysCost.text}"`.
     When `horizonDays === 1`, unchanged — pixel-identical to today's
     rendering.
   - **Net Savings** (metric row): same treatment — full-horizon value
     becomes primary, `subLabel` = `"Today: {todaysSavings.text}"`, only
     when `horizonDays === 2`.
   - **Grid-Only Cost** and **Percentage Saved** rows: unchanged, today-only
     — these are baseline/comparison figures, not the ones the issue is
     about.

This matches the previously-approved UX direction (stacked primary value +
small annotation, no auto-rotation, no manual toggle) — nothing is ever
hidden, and the card's layout doesn't change at all on a single-day horizon.

## Testing

- Backend: extend `backend/tests/test_dashboard_api.py` with a case
  asserting `horizonDays`/`netGridCostFullHorizon`/`netSavingsFullHorizon`
  are correct when a 2-day schedule is stored (values equal today-only sum
  + tomorrow-slice sum), and are absent/`horizonDays == 1` otherwise.
- Frontend: extend
  `frontend/src/components/__tests__/SystemStatusCard.test.tsx` to assert
  the annotation renders only when `horizonDays === 2`, and that
  single-day rendering is byte-identical to current snapshots.

## Open questions (not resolved by this design)

- How should the Savings view represent actual-vs-predicted data more
  clearly (affects today's numbers there even without this issue)?
- Should "tomorrow" become its own selectable day in the Savings view once
  its prices are published, rather than being folded into "today"?

These are left for a separate future design pass, not blocking this fix.
