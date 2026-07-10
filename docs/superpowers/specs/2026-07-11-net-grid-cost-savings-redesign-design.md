# Net Grid Cost / Battery Wear Split — Savings & Insights Redesign

## Origin

GitHub issue #249, following on from #126 (Frank-Leysen). Frank tracks a manual
daily log of net supplier result (import EUR − export EUR) against his
Growatt/Luminus meter and wants BESS Manager's dashboard to show that same
number natively — currently "Today's Costs" bundles it with modeled battery
wear (`battery_cycle_cost`), which makes profitable high-solar-throughput days
look only marginally worthwhile. His framing: wear is an investment/TCO cost,
not a line on the electricity bill — "we do not amortise our kitchen into
tonight's dinner cost either."

Builds directly on the week/month/year aggregation work in
`2026-07-09-daily-savings-history-design.md` (`savings_aggregator.py`,
`DailyViewStore`, `SavingsAggregateView.tsx`) — that work already computes
`grid_cost`/`battery_cycle_cost` separately per bucket; this design extends it
to cover "today" and restructures where each number is shown.

## Goal

1. **`grid_cost` (relabeled "Net Grid Cost") becomes the headline cost figure**
   everywhere savings are shown — dashboard card and Savings page — replacing
   the bundled `hourly_cost` ("Today's Costs"/"Optimized Cost").
2. **Battery wear (`battery_cycle_cost`) is removed from every savings/cost
   headline and summary.** It is not hidden behind a toggle — it simply isn't
   part of that view. It surfaces only in the per-period "Battery Actions"
   table, where it explains *why* the optimizer acted, not what something
   costs on the bill.
3. **The Savings page is simplified to a pure financial-outcome view** (no
   SOC, no per-period battery-action detail) and, because it no longer needs
   per-period battery-action data, can share one calculation with the
   week/month/year history view — adding a **Today / Week / Month / Year**
   period selector backed by the existing aggregator instead of a separate
   "today" code path.
4. **The per-period battery-action table** (currently `SavingsOverview.tsx`'s
   "Hourly Battery Actions & Savings" section: SOC, battery action, per-period
   actual cost) **moves to the Insights page**, renamed "Battery Actions" —
   grouped with the other decision-diagnostic views (`PredictionAccuracyView`,
   `ConsumptionForecastComparison`) rather than the financial-outcome page.

## Explicitly out of scope

- **Changing the optimizer.** `cycle_cost_per_kwh` continues to be used
  exactly as today to discourage pointless cycling. Nothing here touches
  `core/bess/algorithms/`.
- **Changing the savings/percentage-saved formula.** "Today's Savings" /
  "Total Savings" stay `grid_only_cost − hourly_cost` (wear-inclusive),
  unchanged. This was raised and explicitly rejected during design — see
  Rationale.
- **A display toggle for battery wear.** Considered and rejected — see
  Rationale.
- Payback/investment/ROI calculator.
- Backfilling "day"-granularity history before this ships (inherits the
  existing `DailyViewStore` limitation from the prior spec).
- Any change to `DetailedSavingsAnalysis.tsx` ("Scenario Comparison": Grid-only
  vs Solar-only vs Solar+Battery) — it has no SOC and no wear-bundling problem,
  stays as-is on the Savings page.

## Rationale (from design discussion)

- **No toggle.** A "show battery wear" toggle was the starting proposal but
  was dropped: it multiplies UI states (wear shown/hidden × wear
  counted/not-counted in savings) without resolving the actual tension, since
  the savings formula stays wear-inclusive either way — a shown-but-not-netted
  wear figure next to a wear-inclusive savings number is more confusing than
  either extreme. Recommended and agreed: no toggle, wear just lives somewhere
  else entirely.
- **No formula change.** Frank's kitchen/breakfast argument ("we don't
  amortise the kitchen into tonight's dinner") applies equally to *not*
  netting wear out of savings either — the counter-argument is that BESS
  doesn't account for the PV/battery capital investment at all today, so
  partially adjusting the savings formula for wear-TCO without also
  addressing capex would be an inconsistent half-measure. Decision: leave the
  algorithm-facing formula untouched; solve this as an information-design
  problem instead.
- **Industry precedent** (Tesla Powerwall app, Home Assistant Energy
  dashboard, Sonnen): none of them net degradation into a daily operational
  savings number. Tesla explicitly keeps "Energy Value" (operational,
  meter-based) separate from investment/ROI, which it pushes to external
  calculators entirely. This validates the two-tier split (operational vs.
  wear-as-decision-context) over a toggle.
- **Wear belongs with the actions it explains.** The per-period battery-action
  table already exists to justify each period's charge/discharge decision;
  wear is naturally a breakdown of that period's actual cost, not a
  savings-page concern. This is also why that table is moving to Insights
  (decision diagnostics) rather than staying on Savings (financial outcome).
- **This satisfies issue #249's debug requirement by construction.** The
  issue asks that setting `cycle_cost_per_kwh` to 0 make the headline match
  `grid_cost` exactly. Since the headline *is* `grid_cost` regardless of the
  cycle-cost setting, this holds unconditionally rather than needing a
  specific settings state to verify.

## Architecture

```
Dashboard card (SystemStatusCard.tsx, "Today's Cost & Savings")
        │
        └─ keyMetric: Net Grid Cost (grid_cost)      [was: bundled hourly_cost]
           sub-metrics unchanged: Grid-Only Cost, Today's Savings, % Saved
           (still wear-inclusive — see Rationale)

Savings page (SavingsPage.tsx)
        │
        ├─ period selector: Today / Week / Month / Year   [new — Today is new]
        │
        └─ GET /api/savings/aggregate?period=day|week|month|year&count=N
                │
                period=day, requested date has no persisted snapshot yet
                (i.e. today, pre-rollover) → build_buckets() falls back to
                live DailyView via daily_view_builder.build_daily_view()
                │
                period=week|month|year → unchanged, reads DailyViewStore
                (as in the prior spec)
                │
                one shared rendering (bar/table, from SavingsAggregateView)
                across all four period types: Grid-Only Cost, Net Grid Cost,
                Total Savings — no wear column, no SOC

        └─ DetailedSavingsAnalysis (Scenario Comparison) — unchanged tab

Insights page (InsightsPage.tsx)
        │
        └─ new "Battery Actions" section (moved from SavingsOverview.tsx)
           per-period: time, price, solar, consumption, battery action,
           SOC, grid import/export, Actual Cost (hourly_cost) with a
           wear breakdown ("of which ~X wear"), Savings
           — this is where battery_cycle_cost is visible, in context
```

`SavingsOverview.tsx` is retired: its summary cards are replaced by the new
Savings-page period-selector component, and its per-period table becomes the
Insights-page "Battery Actions" table.

## Backend changes

**`core/bess/savings_aggregator.py`**
- Add `"day"` to `VALID_PERIODS`.
- `_BOUNDS_FN["day"]` → `(d, d)`. `_bucket_label("day", start)` → ISO date
  string. `_step_back("day", d)` → `d - timedelta(days=1)`.
- `build_buckets()`: when `period == "day"` and a bucket's single date has no
  entry in `store.list_available_dates()` *and* that date is today, source its
  `DailyView` from the live builder instead of `store.load_day()` (returns
  `None` today pre-rollover, same as any other missing day, unless the caller
  substitutes the live view). Exact injection mechanism (optional `today_view`
  param on `build_buckets`, vs. a wrapper the API layer calls) is a
  planning-time detail — either works, but the aggregator itself must not
  reach into `BatteryController`/`daily_view_builder` directly to keep it
  testable with a plain store double, matching its current design.
- Add `grid_only_cost: float = 0.0` to `DailyTotals` (sum of
  `p.economic.grid_only_cost` across periods, same pattern as the existing
  fields) — needed as the baseline for every granularity in the simplified
  Savings page, not just today.

**`backend/api_dataclasses.py`**
- `APISavingsBucket` gains `gridOnlyCost: FormattedValue`, sourced from the
  new `DailyTotals.grid_only_cost`.
- The per-period hourly dataclass backing the Battery Actions table (currently
  only exposes bundled `hourlyCost`, ~line 361) gains `gridCost` and
  `batteryCycleCost` fields, sourced from `hourly.economic.grid_cost` /
  `hourly.economic.battery_cycle_cost` (already present in
  `core/bess/models.py`, just not threaded through to this dataclass yet).
- `APIDashboardSummary`/`APICostAndSavings`: add a `netGridCost` field (sum of
  `h.gridCost.value` across today's hours, mirroring how `total_optimized_cost`
  is currently summed in `backend/api.py:692-706`). The existing bundled total
  stays available internally (still needed to compute Today's
  Savings/percentage, unchanged) but is no longer the field the dashboard
  headline reads.

**`backend/api.py`**
- `/api/savings/aggregate`: accept `period=day` and wire in the live-view
  fallback described above.
- `/api/dashboard`: compute and expose `netGridCost` per above.

## Frontend changes

- **`SystemStatusCard.tsx`** — "Today's Cost & Savings" card: `keyValue`
  switches from `todaysCost` to the new `netGridCost`; label becomes "Net Grid
  Cost". Sub-metrics (Grid-Only Cost, Today's Savings, Percentage Saved)
  unchanged.
- **`SavingsPage.tsx`** — remove the Overview/Scenario Comparison viewMode
  toggle's Overview branch; replace with a new period-selector component
  (Today/Week/Month/Year) rendering Grid-Only Cost / Net Grid Cost / Total
  Savings via the extended `/api/savings/aggregate`. `SavingsAggregateView.tsx`
  becomes this shared renderer (bar chart + table) for all four periods rather
  than a separate section below a live-only Overview. Scenario Comparison tab
  unchanged.
- **`InsightsPage.tsx`** — new "Battery Actions" section: the per-period table
  moved from `SavingsOverview.tsx` (component likely renamed, e.g.
  `BatteryActionsTable.tsx`), unchanged in content except the Actual Cost
  column gains a wear breakdown sourced from the new per-hour `batteryCycleCost`
  field. Exact visual treatment of the breakdown (sub-line vs. separate column
  vs. tooltip) is left for implementation, not pinned down here.
- **`SavingsOverview.tsx`** — deleted; responsibilities split as above.
- **`useSavingsAggregate` hook** — extend accepted `period` type to include
  `'day'`.

## Testing

- `core/bess/tests/unit/test_savings_aggregator.py` (extends existing) —
  `day` period: single-day bounds, ISO-date label, live-view fallback for
  today when the store has no snapshot, `grid_only_cost` summed correctly for
  all period types.
- Backend API tests — `/api/savings/aggregate?period=day` returns today's live
  totals pre-rollover; `/api/dashboard` exposes `netGridCost` equal to
  `grid_cost` regardless of `cycle_cost_per_kwh` setting (covers the issue's
  debug requirement).
- Frontend — `SystemStatusCard` test asserts headline reads `netGridCost`, not
  the old bundled total. New test for the moved Battery Actions table
  (replaces whatever currently covers `SavingsOverview`'s table). Extended
  `useSavingsAggregate` test for `period: 'day'`.

## Open implementation details (left for the plan)

- Exact mechanism for injecting today's live `DailyView` into
  `build_buckets()` (param vs. wrapper) — aggregator must stay testable
  without a real controller.
- Whether `SavingsOverview.tsx`'s retirement is a delete-and-recreate or an
  in-place split/rename of its two responsibilities.
- Exact visual treatment of the wear breakdown in the Battery Actions table's
  Actual Cost column.
- Whether "today" via `/api/savings/aggregate` is recomputed live on every
  request (recommended, matches current dashboard behavior — no staleness
  until rollover) or opportunistically cached.

## Addendum (post-implementation): `netSavings`, a wear-free companion to the wear-inclusive savings formula

Found during the final whole-branch review, after all 11 tasks above shipped:
with `Net Grid Cost` as the headline and `Grid-Only Cost` as a sub-metric, the
existing wear-inclusive "Today's Savings" / "Total Savings" no longer
arithmetically reconciles with its own card — `Grid-Only Cost − Today's
Savings ≠ Net Grid Cost`, off by exactly the wear amount. The savings formula
itself is still deliberately unchanged (see Rationale above — this was
reconfirmed, not reopened).

Resolution: add a second, purely additive savings figure, `netSavings =
grid_only_cost − grid_cost` (wear-free by construction, so it always
reconciles with the wear-free headline), and **replace** the wear-inclusive
savings figure with it everywhere `Net Grid Cost` is the headline — the
dashboard card and the Savings page's Today/Week/Month/Year view. The
wear-inclusive formula keeps its existing internal role (percentage-saved
math, wherever else it's referenced) but is no longer displayed on either of
these two surfaces, consistent with this whole feature's principle that the
Savings page and dashboard card are wear-free financial-outcome views.
