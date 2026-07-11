# Net Grid Cost / Battery Wear Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "Net Grid Cost" (`grid_cost`, import EUR − export EUR) the headline cost figure everywhere savings are shown, remove battery wear (`battery_cycle_cost`) from every cost/savings headline, and restructure the Savings and Insights pages so wear only appears where it explains a battery decision.

**Architecture:** Extend the existing `savings_aggregator.py`/`DailyViewStore` machinery (built for week/month/year history) with a `day` period backed by today's live `DailyView`, so "Today" becomes just another bucket instead of a separate calculation path. Move the per-period SOC/battery-action table from the Savings page to the Insights page (renamed "Battery Actions"), and replace the Savings page's summary cards with a Today/Week/Month/Year selector built on the aggregator.

**Tech Stack:** Python/FastAPI backend (`core/bess/`, `backend/`), React/TypeScript frontend (`frontend/src/`), pytest, vitest.

## Global Constraints

- Do not change the optimizer or `cycle_cost_per_kwh` usage — `core/bess/algorithms/` is untouched.
- Do not change the savings/percentage-saved formula — `grid_only_cost − hourly_cost` (wear-inclusive) stays exactly as today.
- No display toggle of any kind for battery wear — it lives in the Battery Actions table only, not gated by a setting.
- `DetailedSavingsAnalysis.tsx` ("Scenario Comparison") is unchanged.
- Follow the design spec: `docs/superpowers/specs/2026-07-11-net-grid-cost-savings-redesign-design.md`.
- Run `.venv/bin/black . && .venv/bin/ruff check --fix .` and `cd frontend && npm run lint:fix` before each commit that touches those trees; run `./scripts/quality-check.sh` before the final commit of the plan.

---

## Task 1: `DailyTotals.grid_only_cost` field

**Files:**
- Modify: `core/bess/savings_aggregator.py:16-69`
- Test: `core/bess/tests/unit/test_savings_aggregator.py`

**Interfaces:**
- Produces: `DailyTotals.grid_only_cost: float` — sum of `p.economic.grid_only_cost` across a day's periods, additive via `__add__` like the other fields.

- [ ] **Step 1: Write the failing test**

Add to `core/bess/tests/unit/test_savings_aggregator.py`, inside `TestWeekBuckets`:

```python
    def test_grid_only_cost_is_summed(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        _seed_day(
            store, date(2026, 7, 8), grid_imported=1.0, grid_exported=2.0, savings=3.0
        )

        buckets = build_buckets("week", count=1, store=store, today=date(2026, 7, 9))

        # _period() sets home_consumption == grid_imported and buy_price 2.0
        assert buckets[0].totals.grid_only_cost == 2.0  # 1.0 * 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_savings_aggregator.py -k grid_only_cost_is_summed -v`
Expected: FAIL — `AttributeError: 'DailyTotals' object has no attribute 'grid_only_cost'`

- [ ] **Step 3: Add the field**

In `core/bess/savings_aggregator.py`, add `grid_only_cost` to `DailyTotals`:

```python
@dataclass
class DailyTotals:
    """Sums of one or more days' energy/economic fields."""

    import_kwh: float = 0.0
    import_eur: float = 0.0
    export_kwh: float = 0.0
    export_eur: float = 0.0
    grid_cost: float = 0.0
    grid_only_cost: float = 0.0
    battery_cycle_cost: float = 0.0
    savings_vs_grid_only: float = 0.0
    solar_kwh: float = 0.0
    battery_charged_kwh: float = 0.0
    battery_discharged_kwh: float = 0.0

    @classmethod
    def from_daily_view(cls, view: DailyView) -> DailyTotals:
        import_kwh = sum(p.energy.grid_imported for p in view.periods)
        export_kwh = sum(p.energy.grid_exported for p in view.periods)
        import_eur = sum(
            p.energy.grid_imported * p.economic.buy_price for p in view.periods
        )
        export_eur = sum(
            p.energy.grid_exported * p.economic.sell_price for p in view.periods
        )
        return cls(
            import_kwh=import_kwh,
            import_eur=import_eur,
            export_kwh=export_kwh,
            export_eur=export_eur,
            grid_cost=import_eur - export_eur,
            grid_only_cost=sum(p.economic.grid_only_cost for p in view.periods),
            battery_cycle_cost=sum(p.economic.battery_cycle_cost for p in view.periods),
            savings_vs_grid_only=view.total_savings,
            solar_kwh=sum(p.energy.solar_production for p in view.periods),
            battery_charged_kwh=sum(p.energy.battery_charged for p in view.periods),
            battery_discharged_kwh=sum(
                p.energy.battery_discharged for p in view.periods
            ),
        )

    def __add__(self, other: DailyTotals) -> DailyTotals:
        return DailyTotals(
            import_kwh=self.import_kwh + other.import_kwh,
            import_eur=self.import_eur + other.import_eur,
            export_kwh=self.export_kwh + other.export_kwh,
            export_eur=self.export_eur + other.export_eur,
            grid_cost=self.grid_cost + other.grid_cost,
            grid_only_cost=self.grid_only_cost + other.grid_only_cost,
            battery_cycle_cost=self.battery_cycle_cost + other.battery_cycle_cost,
            savings_vs_grid_only=self.savings_vs_grid_only + other.savings_vs_grid_only,
            solar_kwh=self.solar_kwh + other.solar_kwh,
            battery_charged_kwh=self.battery_charged_kwh + other.battery_charged_kwh,
            battery_discharged_kwh=self.battery_discharged_kwh
            + other.battery_discharged_kwh,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_savings_aggregator.py -v`
Expected: all PASS (including the new test and every pre-existing one — `__add__`/`from_daily_view` signatures are unchanged for callers).

- [ ] **Step 5: Commit**

```bash
git add core/bess/savings_aggregator.py core/bess/tests/unit/test_savings_aggregator.py
git commit -m "feat: add grid_only_cost to DailyTotals aggregation"
```

---

## Task 2: `day` period support in `build_buckets`

**Files:**
- Modify: `core/bess/savings_aggregator.py:1-13,83-162`
- Test: `core/bess/tests/unit/test_savings_aggregator.py`

**Interfaces:**
- Consumes: `DailyView` (from Task 1's `from_daily_view`), `DailyViewStore.list_available_dates()`/`load_day()` (unchanged, from `core/bess/daily_view_store.py`).
- Produces: `build_buckets(period, count, store, today=None, today_view: DailyView | None = None) -> list[SavingsBucket]` — `period="day"` now valid; a `today_view` param lets the caller supply today's live (not-yet-persisted) `DailyView` so today counts even with no `DailyViewStore` snapshot yet. `DEFAULT_COUNTS["day"] == 1`.

- [ ] **Step 1: Write the failing tests**

Add a new test class to `core/bess/tests/unit/test_savings_aggregator.py`:

```python
class TestDayBuckets:
    def test_single_day_bucket_bounds_and_label(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        _seed_day(
            store, date(2026, 7, 8), grid_imported=1.0, grid_exported=2.0, savings=3.0
        )

        buckets = build_buckets("day", count=1, store=store, today=date(2026, 7, 8))

        assert len(buckets) == 1
        bucket = buckets[0]
        assert bucket.label == "2026-07-08"
        assert bucket.start_date == "2026-07-08"
        assert bucket.end_date == "2026-07-08"
        assert bucket.day_count == 1
        assert bucket.totals.grid_cost == 0.0  # 2.0 import_eur - 2.0 export_eur

    def test_multi_day_sequence_returned_oldest_first(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        _seed_day(
            store, date(2026, 7, 7), grid_imported=1.0, grid_exported=0.0, savings=1.0
        )
        _seed_day(
            store, date(2026, 7, 8), grid_imported=1.0, grid_exported=0.0, savings=1.0
        )

        buckets = build_buckets("day", count=2, store=store, today=date(2026, 7, 8))

        assert [b.label for b in buckets] == ["2026-07-07", "2026-07-08"]

    def test_today_with_no_snapshot_uses_live_today_view(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)  # nothing persisted yet
        live_view = DailyView(
            date=date(2026, 7, 9),
            periods=[_period(grid_imported=0.5, grid_exported=1.5)],
            total_savings=2.0,
            actual_count=1,
            predicted_count=0,
        )

        buckets = build_buckets(
            "day", count=1, store=store, today=date(2026, 7, 9), today_view=live_view
        )

        assert buckets[0].day_count == 1
        assert buckets[0].totals.import_eur == 1.0  # 0.5 * buy_price 2.0
        assert buckets[0].totals.export_eur == 1.5  # 1.5 * sell_price 1.0

    def test_today_view_ignored_for_a_day_that_is_already_persisted(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        _seed_day(
            store, date(2026, 7, 9), grid_imported=9.0, grid_exported=0.0, savings=1.0
        )
        live_view = DailyView(
            date=date(2026, 7, 9),
            periods=[_period(grid_imported=0.5, grid_exported=0.0)],
            total_savings=2.0,
            actual_count=1,
            predicted_count=0,
        )

        buckets = build_buckets(
            "day", count=1, store=store, today=date(2026, 7, 9), today_view=live_view
        )

        # persisted snapshot wins; live_view is only a fallback for missing days
        assert buckets[0].totals.import_kwh == 9.0
        assert buckets[0].day_count == 1

    def test_today_view_only_applies_to_the_bucket_matching_today(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        live_view = DailyView(
            date=date(2026, 7, 9),
            periods=[_period(grid_imported=0.5, grid_exported=0.0)],
            total_savings=2.0,
            actual_count=1,
            predicted_count=0,
        )

        buckets = build_buckets(
            "day", count=2, store=store, today=date(2026, 7, 9), today_view=live_view
        )

        assert buckets[0].label == "2026-07-08"
        assert buckets[0].day_count == 0  # yesterday: no snapshot, no live view
        assert buckets[1].label == "2026-07-09"
        assert buckets[1].day_count == 1  # today: live view used


class TestDefaultCountsDay:
    def test_day_default_count_is_one(self):
        assert DEFAULT_COUNTS["day"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest core/bess/tests/unit/test_savings_aggregator.py -k "TestDayBuckets or DefaultCountsDay" -v`
Expected: FAIL — `ValueError: Unknown period type: 'day'` and `KeyError: 'day'`.

- [ ] **Step 3: Implement `day` period support**

In `core/bess/savings_aggregator.py`, update the module-level constants and `build_buckets`:

```python
VALID_PERIODS = ("day", "week", "month", "year")

DEFAULT_COUNTS: dict[str, int] = {"day": 1, "week": 12, "month": 12, "year": 5}
```

Add a day bounds function next to the existing ones:

```python
def _day_bounds(d: date) -> tuple[date, date]:
    return d, d
```

Update `_BOUNDS_FN`:

```python
_BOUNDS_FN = {
    "day": _day_bounds,
    "week": _week_bounds,
    "month": _month_bounds,
    "year": _year_bounds,
}
```

Update `_bucket_label`:

```python
def _bucket_label(period: str, start: date) -> str:
    if period == "day":
        return start.isoformat()
    if period == "week":
        iso_year, iso_week, _ = start.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if period == "month":
        return f"{start.year}-{start.month:02d}"
    return str(start.year)
```

Update `_step_back`:

```python
def _step_back(period: str, bucket_start: date) -> date:
    """Return a reference date inside the previous bucket."""
    if period == "day":
        return bucket_start - timedelta(days=1)
    if period == "week":
        return bucket_start - timedelta(days=7)
    if period == "month":
        return bucket_start - timedelta(days=1)  # last day of the previous month
    return date(
        bucket_start.year - 1, 6, 15
    )  # any date in the prior year works since _year_bounds only reads .year
```

Update `build_buckets` to accept and use `today_view`:

```python
def build_buckets(
    period: str,
    count: int,
    store,
    today: date | None = None,
    today_view: DailyView | None = None,
) -> list[SavingsBucket]:
    """Build the last `count` buckets of the given period type, oldest first.

    `store` needs only `list_available_dates() -> list[str]` and
    `load_day(day: date) -> DailyView | None` (duck-typed to DailyViewStore).

    `today_view`, if given, is used only for `period="day"` and only for the
    bucket whose single date equals `today` and has no persisted snapshot yet
    (i.e. today, before the 23:55 rollover writes it to the store). It never
    overrides a persisted snapshot.
    """
    if period not in VALID_PERIODS:
        raise ValueError(f"Unknown period type: {period!r}")

    bounds_fn = _BOUNDS_FN[period]
    available_dates = {date.fromisoformat(d) for d in store.list_available_dates()}

    reference_today = today or date.today()
    buckets: list[SavingsBucket] = []
    cursor = reference_today
    for _ in range(count):
        start, end = bounds_fn(cursor)
        days_in_bucket = sorted(d for d in available_dates if start <= d <= end)

        totals = DailyTotals()
        for day in days_in_bucket:
            view = store.load_day(day)
            if view is not None:
                totals = totals + DailyTotals.from_daily_view(view)
        day_count = len(days_in_bucket)

        if (
            period == "day"
            and today_view is not None
            and start == reference_today
            and reference_today not in available_dates
        ):
            totals = totals + DailyTotals.from_daily_view(today_view)
            day_count += 1

        buckets.append(
            SavingsBucket(
                label=_bucket_label(period, start),
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                day_count=day_count,
                totals=totals,
            )
        )
        cursor = _step_back(period, start)

    buckets.reverse()
    return buckets
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_savings_aggregator.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/bess/savings_aggregator.py core/bess/tests/unit/test_savings_aggregator.py
git commit -m "feat: add day period to savings_aggregator with live-today fallback"
```

---

## Task 3: `/api/savings/aggregate?period=day` route + `gridOnlyCost` on `APISavingsBucket`

**Files:**
- Modify: `backend/api_dataclasses.py:80-125`
- Modify: `backend/api.py:2224-2252`
- Test: `backend/tests/test_savings_aggregate_api.py`

**Interfaces:**
- Consumes: `build_buckets(period, count, store, today_view=...)` (Task 2), `bess_controller.system.daily_view_builder.build_daily_view(current_period)` (existing, `core/bess/daily_view_builder.py:89`).
- Produces: `APISavingsBucket.gridOnlyCost: FormattedValue`. Route accepts `period=day|week|month|year`.

- [ ] **Step 1: Write the failing tests**

Add inside `TestSavingsAggregate` in `backend/tests/test_savings_aggregate_api.py`:

```python
    def test_grid_only_cost_present_on_bucket(self, tmp_path):
        sys.modules["app"].bess_controller = _make_started_controller(
            _seeded_store(tmp_path)
        )

        resp = _client.get("/api/savings/aggregate?period=week&count=1")

        assert resp.status_code == 200
        bucket = resp.json()["buckets"][0]
        assert bucket["gridOnlyCost"]["value"] == 2.0  # 1.0 import_kwh * buy_price 2.0

    def test_day_period_uses_live_daily_view_for_today(self, tmp_path):
        controller = _make_started_controller(DailyViewStore(persist_dir=tmp_path))
        controller.system.daily_view_builder.build_daily_view.return_value = DailyView(
            date=date(2026, 7, 9),
            periods=[_period(1.0, 0.0)],
            total_savings=1.0,
            actual_count=1,
            predicted_count=0,
        )
        sys.modules["app"].bess_controller = controller

        resp = _client.get("/api/savings/aggregate?period=day&count=1")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["buckets"][0]["dayCount"] == 1

    def test_day_period_default_count_is_one(self, tmp_path):
        controller = _make_started_controller(_seeded_store(tmp_path))
        controller.system.daily_view_builder.build_daily_view.return_value = DailyView(
            date=date(2026, 7, 9),
            periods=[_period(1.0, 0.0)],
            total_savings=1.0,
            actual_count=1,
            predicted_count=0,
        )
        sys.modules["app"].bess_controller = controller

        resp = _client.get("/api/savings/aggregate?period=day")

        assert resp.status_code == 200
        assert resp.json()["count"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest backend/tests/test_savings_aggregate_api.py -v`
Expected: FAIL — `gridOnlyCost` KeyError, and `period=day` returns 422 (route pattern doesn't allow it yet).

- [ ] **Step 3: Implement**

In `backend/api_dataclasses.py`, add `gridOnlyCost` to `APISavingsBucket` (`80-125` area):

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
    gridOnlyCost: FormattedValue
    batteryCycleCost: FormattedValue
    savingsVsGridOnly: FormattedValue
    solarKwh: FormattedValue
    batteryChargedKwh: FormattedValue
    batteryDischargedKwh: FormattedValue

    @classmethod
    def from_internal(cls, bucket, currency: str) -> APISavingsBucket:
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
            gridOnlyCost=create_formatted_value(t.grid_only_cost, "currency", currency),
            batteryCycleCost=create_formatted_value(
                t.battery_cycle_cost, "currency", currency
            ),
            savingsVsGridOnly=create_formatted_value(
                t.savings_vs_grid_only, "currency", currency
            ),
            solarKwh=create_formatted_value(t.solar_kwh, "energy_kwh_only", currency),
            batteryChargedKwh=create_formatted_value(
                t.battery_charged_kwh, "energy_kwh_only", currency
            ),
            batteryDischargedKwh=create_formatted_value(
                t.battery_discharged_kwh, "energy_kwh_only", currency
            ),
        )
```

In `backend/api.py`, update the route (`2224-2252`):

```python
@router.get("/api/savings/aggregate")
async def get_savings_aggregate(
    period: str = Query(..., pattern="^(day|week|month|year)$"),
    count: int | None = Query(None, ge=1, le=520),  # 520 weeks is roughly 10 years
):
    """Get day/week/month/year savings aggregates.

    `day` is today's live (in-progress) view when no snapshot has been
    persisted for it yet; week/month/year read the persisted daily history.
    """
    from app import bess_controller

    _require_configured_system(bess_controller)

    try:
        resolved_count = count or DEFAULT_COUNTS[period]

        today_view = None
        if period == "day":
            now = time_utils.now()
            current_period = now.hour * 4 + now.minute // 15
            today_view = bess_controller.system.daily_view_builder.build_daily_view(
                current_period
            )

        buckets = build_buckets(
            period,
            resolved_count,
            bess_controller.system.daily_view_store,
            today_view=today_view,
        )
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
```

`time_utils` is already imported at module level in `backend/api.py` (used at line ~2314 for the same `now.hour * 4 + now.minute // 15` pattern) — no new import needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest backend/tests/test_savings_aggregate_api.py core/bess/tests/unit/test_savings_aggregator.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/api_dataclasses.py backend/api.py backend/tests/test_savings_aggregate_api.py
git commit -m "feat: expose day period and gridOnlyCost on /api/savings/aggregate"
```

---

## Task 4: `gridCost`/`batteryCycleCost` on the per-period hourly dataclass

**Files:**
- Modify: `backend/api_dataclasses.py:344-440`
- Test: `backend/tests/test_dashboard_api.py` (existing file — extend whichever test covers `APIDashboardHourlyData.from_internal`; if none exists yet, add one alongside it)

**Interfaces:**
- Produces: `APIDashboardHourlyData.gridCost: FormattedValue`, `APIDashboardHourlyData.batteryCycleCost: FormattedValue`, sourced from `hourly.economic.grid_cost` / `hourly.economic.battery_cycle_cost` (`core/bess/models.py:175-176`, already populated on every `PeriodData`).

- [ ] **Step 1: Write the failing test**

```bash
grep -n "APIDashboardHourlyData\|from_internal" backend/tests/test_dashboard_api.py
```

If a test builds an `APIDashboardHourlyData` via `from_internal` and asserts on fields, add these two assertions there. Otherwise add a new focused test to `backend/tests/test_dashboard_api.py`:

```python
def test_hourly_data_exposes_grid_cost_and_battery_cycle_cost():
    from api_dataclasses import APIDashboardHourlyData
    from core.bess.models import DecisionData, EconomicData, EnergyData, PeriodData

    hourly = PeriodData(
        period=0,
        energy=EnergyData(
            solar_production=1.0,
            home_consumption=1.0,
            battery_charged=0.0,
            battery_discharged=0.0,
            grid_imported=1.0,
            grid_exported=0.0,
            battery_soe_start=5.0,
            battery_soe_end=5.0,
        ),
        economic=EconomicData(
            buy_price=2.0,
            sell_price=1.0,
            grid_cost=2.0,
            battery_cycle_cost=0.1,
            hourly_cost=2.1,
        ),
        decision=DecisionData(strategic_intent="IDLE"),
    )

    api_hourly = APIDashboardHourlyData.from_internal(
        hourly, battery_capacity=10.0, currency="EUR"
    )

    assert api_hourly.gridCost.value == 2.0
    assert api_hourly.batteryCycleCost.value == 0.1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest backend/tests/test_dashboard_api.py -k grid_cost_and_battery_cycle_cost -v`
Expected: FAIL — `AttributeError: 'APIDashboardHourlyData' object has no attribute 'gridCost'`

- [ ] **Step 3: Implement**

In `backend/api_dataclasses.py`, add the two fields to `APIDashboardHourlyData` and set them in `from_internal`:

```python
    hourlyCost: FormattedValue
    gridCost: FormattedValue
    batteryCycleCost: FormattedValue
    hourlySavings: FormattedValue
```

(insert `gridCost`/`batteryCycleCost` immediately after the existing `hourlyCost: FormattedValue` field declaration at line 361)

And in `from_internal` (line 437 area), add alongside the existing `hourlyCost=...`:

```python
            hourlyCost=safe_format(hourly.economic.hourly_cost, "currency"),
            gridCost=safe_format(hourly.economic.grid_cost, "currency"),
            batteryCycleCost=safe_format(hourly.economic.battery_cycle_cost, "currency"),
            hourlySavings=safe_format(hourly.economic.hourly_savings, "currency"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest backend/tests/test_dashboard_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/api_dataclasses.py backend/tests/test_dashboard_api.py
git commit -m "feat: expose gridCost and batteryCycleCost on per-period dashboard data"
```

---

## Task 5: `netGridCost` on the dashboard summary

**Files:**
- Modify: `backend/api.py:691-706`
- Modify: `backend/api_dataclasses.py:528-577` (`APIDashboardSummary` fields), `:579-614` (`from_totals`)
- Test: `backend/tests/test_dashboard_api.py`

**Interfaces:**
- Consumes: `APIDashboardHourlyData.gridCost` (Task 4).
- Produces: `APIDashboardSummary.netGridCost: FormattedValue` — sum of `h.gridCost.value` across today's hours, independent of `cycle_cost_per_kwh`. This lands on `APIDashboardSummary` (not `APICostAndSavings`) because `SystemStatusCard.tsx` reads `dashboardData.summary?.optimizedCost` today (`APIDashboardResponse.summary: APIDashboardSummary`, a separate struct from `APIDashboardResponse.costAndSavings: APICostAndSavings` — verified by reading `backend/api_dataclasses.py:781-782`), and Task 7 needs `dashboardData.summary?.netGridCost` to exist.

- [ ] **Step 1: Write the failing test**

Find the existing dashboard-summary test setup (search for how `costs` dict / `APICostAndSavings` construction is already exercised):

```bash
grep -n "APICostAndSavings\|costAndSavings\|total_optimized_cost" backend/tests/test_dashboard_api.py
```

Add a test asserting `netGridCost` equals the sum of per-hour `grid_cost`, and that it is unaffected by `battery_cycle_cost`:

```python
def test_net_grid_cost_excludes_battery_wear():
    from api_dataclasses import APIDashboardHourlyData
    from core.bess.models import DecisionData, EconomicData, EnergyData, PeriodData

    def _hour(grid_cost, cycle_cost):
        return APIDashboardHourlyData.from_internal(
            PeriodData(
                period=0,
                energy=EnergyData(
                    solar_production=0.0,
                    home_consumption=1.0,
                    battery_charged=0.0,
                    battery_discharged=0.0,
                    grid_imported=1.0,
                    grid_exported=0.0,
                    battery_soe_start=5.0,
                    battery_soe_end=5.0,
                ),
                economic=EconomicData(
                    buy_price=1.0,
                    sell_price=1.0,
                    grid_cost=grid_cost,
                    battery_cycle_cost=cycle_cost,
                    hourly_cost=grid_cost + cycle_cost,
                ),
                decision=DecisionData(strategic_intent="IDLE"),
            ),
            battery_capacity=10.0,
            currency="EUR",
        )

    hours = [_hour(1.0, 0.5), _hour(2.0, 0.5)]
    net_grid_cost = sum(h.gridCost.value for h in hours)

    assert net_grid_cost == 3.0  # 1.0 + 2.0, wear excluded
```

This test locks in the summation formula that Step 3 wires into the real route; it doesn't hit the route directly to keep it fast and independent of controller mocking. Also add a route-level assertion if `backend/tests/test_dashboard_api.py` already has a working `/api/dashboard` fixture — search for one:

```bash
grep -n "def test_.*dashboard\b\|_client.get(\"/api/dashboard\")" backend/tests/test_dashboard_api.py
```

If such a fixture exists, add:

```python
    assert resp.json()["summary"]["netGridCost"]["value"] == pytest.approx(
        expected_grid_cost_sum
    )
```

using whatever seeded hourly data that existing test already sets up (mirror how it currently asserts `optimizedCost`, which lives on the same `summary` object).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest backend/tests/test_dashboard_api.py -k net_grid_cost -v`
Expected: PASS for the pure-summation test (no dataclass field involved yet) is not possible — it references no new field, so it should already pass. Skip to asserting the *route* test fails instead:

Run: `.venv/bin/pytest backend/tests/test_dashboard_api.py -v`
Expected: the new route-level assertion (if added) FAILS with `KeyError: 'netGridCost'`.

- [ ] **Step 3: Implement**

In `backend/api_dataclasses.py`, add `netGridCost` to `APIDashboardSummary`'s field list (`528-577`), next to `optimizedCost`:

```python
    # Cost scenarios
    gridOnlyCost: FormattedValue
    solarOnlyCost: FormattedValue
    optimizedCost: FormattedValue
    netGridCost: FormattedValue
```

In `backend/api.py`, compute the new total alongside the existing ones (`691-706`):

```python
        # Calculate costs from dataclass fields directly - using ACTUAL backend calculations
        total_optimized_cost = sum(
            h.hourlyCost.value for h in hourly_dataclass_instances
        )
        total_grid_only_cost = sum(
            h.gridOnlyCost.value for h in hourly_dataclass_instances
        )
        total_solar_only_cost = sum(
            h.solarOnlyCost.value for h in hourly_dataclass_instances
        )
        total_net_grid_cost = sum(
            h.gridCost.value for h in hourly_dataclass_instances
        )

        costs = {
            "gridOnly": total_grid_only_cost,
            "solarOnly": total_solar_only_cost,
            "optimized": total_optimized_cost,
            "netGrid": total_net_grid_cost,
        }
```

In `APIDashboardSummary.from_totals` (`backend/api_dataclasses.py:579-614`), add the new field to the returned instance, next to `optimizedCost`:

```python
            optimizedCost=create_formatted_value(
                total_optimized_cost, "currency", currency
            ),
            netGridCost=create_formatted_value(
                costs["netGrid"], "currency", currency
            ),
```

`from_totals` already receives `costs` as a parameter (line 581) and is the sole place `APIDashboardSummary` is constructed (called from `backend/api_dataclasses.py:841`, inside `APIDashboardResponse.from_dashboard_data`) — no other call site to update.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest backend/tests/test_dashboard_api.py backend/tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/api.py backend/api_dataclasses.py backend/tests/test_dashboard_api.py
git commit -m "feat: add netGridCost to dashboard cost-and-savings summary"
```

---

## Task 6: Frontend types + API client for `day` period and `netGridCost`

**Files:**
- Modify: `frontend/src/api/scheduleApi.ts:191` (`SavingsAggregatePeriod`), `:63-93` (`DashboardSummary`)
- Test: `frontend/src/hooks/__tests__/useSavingsAggregate.test.ts`

**Interfaces:**
- Produces: `SavingsAggregatePeriod = 'day' | 'week' | 'month' | 'year'`; `useSavingsAggregate('day')` calls `GET /api/savings/aggregate?period=day`. `DashboardSummary.netGridCost: FormattedValue`.
- Note: `dashboardData.summary` (consumed by `SystemStatusCard.tsx`, Task 7) is typed as `DashboardSummary` in `frontend/src/api/scheduleApi.ts:63-93` — confirmed via `DashboardResponse.summary: DashboardSummary` at `scheduleApi.ts:153`. `frontend/src/types.ts` has a similarly-named but *different*, unused-by-this-flow `ScheduleSummary` interface (raw `number` fields, not `FormattedValue`) — do not edit that one for this task, it isn't what the dashboard actually returns.

- [ ] **Step 1: Write the failing test**

Read the existing hook test first:

```bash
cat frontend/src/hooks/__tests__/useSavingsAggregate.test.ts
```

Add a test mirroring the existing week/month/year cases but for `'day'` (follow the exact mocking pattern already used in that file for `fetchSavingsAggregate`):

```typescript
  it('fetches the day period', async () => {
    // mirror the existing 'week' test in this file, substituting period='day'
    // and asserting the request/query param is period=day
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- useSavingsAggregate`
Expected: FAIL — TypeScript error, `'day'` is not assignable to `SavingsAggregatePeriod`.

- [ ] **Step 3: Implement**

In `frontend/src/api/scheduleApi.ts:191`:

```typescript
export type SavingsAggregatePeriod = 'day' | 'week' | 'month' | 'year';
```

In the same file, add `netGridCost` to `DashboardSummary` (`63-93`), next to `optimizedCost`:

```typescript
export interface DashboardSummary {
  // Baseline costs (what scenarios would cost) - CANONICAL
  gridOnlyCost: FormattedValue;
  solarOnlyCost: FormattedValue;
  optimizedCost: FormattedValue;
  netGridCost: FormattedValue;

  // Savings calculations - CANONICAL
  totalSavings: FormattedValue;
  solarSavings: FormattedValue;
  batterySavings: FormattedValue;

  // ... remaining fields unchanged
```

(only add the one new line — the `// ... remaining fields unchanged` marker above is this plan's shorthand for "don't touch the rest of the interface," not code to paste in.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- useSavingsAggregate && npm run lint:fix`
Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/scheduleApi.ts frontend/src/hooks/__tests__/useSavingsAggregate.test.ts
git commit -m "feat: add day period type and netGridCost field to frontend"
```

---

## Task 7: `SystemStatusCard.tsx` headline switches to Net Grid Cost

**Files:**
- Modify: `frontend/src/components/SystemStatusCard.tsx:251-256,426-431`
- Test: `frontend/src/components/__tests__/SystemStatusCard.test.tsx` (find or create alongside existing component tests)

**Interfaces:**
- Consumes: `dashboardData.summary.netGridCost` (`DashboardSummary.netGridCost`, Task 6; backed by `APIDashboardSummary.netGridCost`, Task 5).

- [ ] **Step 1: Write the failing test**

```bash
find frontend/src -iname "*SystemStatusCard*test*"
```

If a test file exists, add a case asserting the "Today's Cost & Savings" card's `keyValue` reads `netGridCost.text`, not `optimizedCost.text`, when both are present and differ. If none exists, add `frontend/src/components/__tests__/SystemStatusCard.test.tsx` following the pattern of a sibling component test in the same directory (check `SavingsAggregateView.test.tsx` for the project's RTL conventions: mock the data hook, render, assert text content).

```typescript
it('shows Net Grid Cost as the headline, not the bundled optimized cost', () => {
  // render with mocked dashboardData where
  // summary.netGridCost.text === '1.50 EUR' and summary.optimizedCost.text === '1.90 EUR'
  // assert screen shows '1.50 EUR' as the card's key value and not '1.90 EUR'
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- SystemStatusCard`
Expected: FAIL — headline shows `optimizedCost.text`.

- [ ] **Step 3: Implement**

In `frontend/src/components/SystemStatusCard.tsx`, change the `todaysCost` derivation (`251-256`):

```typescript
        todaysCost: (() => {
          if (!dashboardData.summary?.netGridCost) {
            throw new Error('MISSING DATA: summary.netGridCost is required for cost display');
          }
          return dashboardData.summary.netGridCost;
        })(),
```

And update the card label (`426-431`):

```typescript
      keyMetric: "Net Grid Cost",
      keyValue: statusData.costAndSavings?.todaysCost?.text,
```

(the `costAndSavings.todaysCost` name in the component's internal `statusData` shape stays as-is — only its source flips from `optimizedCost` to `netGridCost` — no need to rename the internal prop, avoids touching every consumer of `statusData.costAndSavings.todaysCost`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- SystemStatusCard`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/api_dataclasses.py backend/tests/test_dashboard_api.py frontend/src/types.ts frontend/src/components/SystemStatusCard.tsx frontend/src/components/__tests__/SystemStatusCard.test.tsx
git commit -m "feat: dashboard headline shows Net Grid Cost instead of bundled cost"
```

---

## Task 8: "Today" tab + Grid-Only Cost baseline in `SavingsAggregateView.tsx`, remove Battery Wear

**Files:**
- Modify: `frontend/src/components/SavingsAggregateView.tsx`
- Test: `frontend/src/components/__tests__/SavingsAggregateView.test.tsx`

**Interfaces:**
- Consumes: `useSavingsAggregate('day' | 'week' | 'month' | 'year')` (Task 6), `SavingsBucket.gridOnlyCost` (Task 3, threaded through `frontend/src/api/scheduleApi.ts`'s `SavingsBucket` type — add `gridOnlyCost: FormattedValue` there if not already present; check first).

- [ ] **Step 1: Write the failing test**

```bash
cat frontend/src/components/__tests__/SavingsAggregateView.test.tsx
```

Add a test asserting a "Today" period button exists and, when clicked, calls `useSavingsAggregate` with `'day'`; a test asserting the table renders a "Grid-Only Cost" column populated from `bucket.gridOnlyCost.text`; and a test asserting "Battery Wear" is absent from the rendered output (table and chart legend) even when the mocked bucket data includes a non-zero `batteryCycleCost`. Follow this file's existing render/mock conventions exactly (it already mocks `useSavingsAggregate`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- SavingsAggregateView`
Expected: FAIL — no "Today" button, no Grid-Only Cost column, and "Battery Wear" is still present (that last assertion fails until Step 3's removal).

- [ ] **Step 3: Implement**

First confirm `SavingsBucket` in `frontend/src/api/scheduleApi.ts` has `gridOnlyCost: FormattedValue`; if not, add it (mirrors the backend `APISavingsBucket` field from Task 3).

In `frontend/src/components/SavingsAggregateView.tsx`, add `'day'` to the period list and relabel it "Today" in the button, and add the Grid-Only Cost column/bar:

```typescript
const PERIODS: SavingsAggregatePeriod[] = ['day', 'week', 'month', 'year'];

const PERIOD_LABELS: Record<SavingsAggregatePeriod, string> = {
  day: 'Today',
  week: 'Week',
  month: 'Month',
  year: 'Year',
};
```

Replace the button label (currently `{p}` at line 49) with `{PERIOD_LABELS[p]}`.

Update the bar chart data mapping (`94-98`) to include the baseline:

```typescript
              data={data!.map((b) => ({
                label: b.label,
                gridOnlyCost: b.gridOnlyCost.value,
                gridCost: b.gridCost.value,
                savings: b.savingsVsGridOnly.value,
              }))}
```

Add a third `<Bar>` (after the existing `gridCost`/`savings` bars, `105-106`):

```typescript
              <Bar dataKey="gridOnlyCost" name="Grid-Only Cost" fill={colors.text} fillOpacity={0.35} isAnimationActive={false} />
              <Bar dataKey="gridCost" name="Net Grid Cost" fill={colors.cost} fillOpacity={0.8} isAnimationActive={false} />
              <Bar dataKey="savings" name="Savings" fill={colors.savings} fillOpacity={0.8} isAnimationActive={false} />
```

Add a "Grid-Only Cost" table column (`116-135`), between "Export" and "Net Grid Cost":

```typescript
                <th className="pr-4 py-1">Grid-Only Cost</th>
```

and the matching `<td>`:

```typescript
                  <td className="pr-4 py-1 text-gray-500 dark:text-gray-400">{b.gridOnlyCost.text}</td>
```

Update the section title from "Savings History" to something covering all four periods, e.g. `Savings` (line 36):

```typescript
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Savings</h2>
```

**Remove the existing "Battery Wear" column** — per the design, wear does not appear anywhere on the Savings page anymore, only in the Insights page's Battery Actions table (Task 9). Delete the `<th className="pr-4 py-1">Battery Wear</th>` header cell and its matching `<td className="pr-4 py-1 text-gray-500 dark:text-gray-400">{b.batteryCycleCost.text}</td>` row cell (original lines 122 and 134).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- SavingsAggregateView`
Expected: PASS. Add/update a test asserting "Battery Wear" no longer appears anywhere in this component's rendered output, alongside the "Today" tab and "Grid-Only Cost" column tests from Step 1.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SavingsAggregateView.tsx frontend/src/components/__tests__/SavingsAggregateView.test.tsx frontend/src/api/scheduleApi.ts
git commit -m "feat: add Today tab and Grid-Only Cost baseline, drop wear from savings view"
```

---

## Task 9: Move the per-period table to Insights as `BatteryActionsTable.tsx`

**Files:**
- Create: `frontend/src/components/BatteryActionsTable.tsx`
- Modify: `frontend/src/pages/InsightsPage.tsx`
- Delete: `frontend/src/components/SavingsOverview.tsx`
- Modify: `frontend/src/pages/SavingsPage.tsx`
- Test: create `frontend/src/components/__tests__/BatteryActionsTable.test.tsx`; delete/replace any existing `SavingsOverview` test with the same coverage under the new name.

**Interfaces:**
- Consumes: `useDashboardData` (unchanged), `hour.gridCost`/`hour.batteryCycleCost` (Task 4) for the new wear breakdown.
- Produces: `BatteryActionsTable` component, default export, props `{ resolution: DataResolution }` (identical props to the old `SavingsOverview`).

- [ ] **Step 1: Write the failing test**

```bash
find frontend/src -iname "*SavingsOverview*test*"
```

Copy that test file to `frontend/src/components/__tests__/BatteryActionsTable.test.tsx`, updating the import/component name from `SavingsOverview` to `BatteryActionsTable`, and add one new assertion: given an hour with `hour.hourlyCost.text === '0.12 EUR'` and `hour.batteryCycleCost.text === '0.02 EUR'`, the rendered "Actual Cost" cell shows both the total and a wear sub-line containing `'0.02 EUR'`. Also delete the old summary-cards assertions (Grid-Only/Optimized/Total Savings cards) since those are removed in this task — they now live in `SavingsAggregateView.tsx` (Task 8).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- BatteryActionsTable`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create `frontend/src/components/BatteryActionsTable.tsx` as a copy of `frontend/src/components/SavingsOverview.tsx` (all 837 lines), then apply these edits to the copy:

1. Rename the component: `export const SavingsOverview: React.FC<SavingsOverviewProps>` → `export const BatteryActionsTable: React.FC<BatteryActionsTableProps>`, and `interface SavingsOverviewProps` → `interface BatteryActionsTableProps` (same single field: `resolution: DataResolution`). Update the trailing default export if one exists (check bottom of file; if none, none needed — this file currently has no default export, only the named one).

2. Delete the "Summary Cards" block entirely — original lines 106-150 (`{/* Summary Cards */}` through the closing `</div>` before `{/* Simplified Hourly Table */}`). This content now lives in `SavingsAggregateView.tsx` (Task 8).

3. Change the heading text (original line 100) from `Hourly Battery Actions & Savings` to `Battery Actions`.

4. Add the wear breakdown to the "Actual Cost" cell in the main table (original lines 408-416):

```typescript
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className={`font-medium ${
                    Math.abs(getNumericValue(hour.hourlyCost)) < 0.01 ? 'text-gray-900 dark:text-white' :
                    getNumericValue(hour.hourlyCost) > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
                  }`}>
                    {getDisplayValue(hour.hourlyCost)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.hourlyCost)}</div>
                  {getNumericValue(hour.batteryCycleCost) > 0.001 && (
                    <div className="text-xs text-gray-400 dark:text-gray-500">
                      of which {getDisplayValue(hour.batteryCycleCost)} wear
                    </div>
                  )}
                </td>
```

5. Apply the identical wear-breakdown addition to the "Tomorrow's Projected" table's Actual Cost cell (original lines 807-815), same snippet.

6. Remove the now-unused `FormattedValueComponent` import if the deleted Summary Cards block was its only usage in this file — check:

```bash
grep -n "FormattedValueComponent" frontend/src/components/SavingsOverview.tsx
```

If it appears only in the deleted block, remove the import line (`import FormattedValueComponent from './FormattedValue';`) from the new file.

In `frontend/src/pages/InsightsPage.tsx`, add the new section:

```typescript
// frontend/src/pages/InsightsPage.tsx

import React from 'react';
import ConsumptionForecastComparison from '../components/ConsumptionForecastComparison';
import PredictionAccuracyView from '../components/PredictionAccuracyView';
import { BatteryActionsTable } from '../components/BatteryActionsTable';
import { useUserPreferences } from '../hooks/useUserPreferences';

const InsightsPage: React.FC = () => {
  const { dataResolution } = useUserPreferences();

  return (
    <div className="p-6 space-y-6 bg-gray-50 dark:bg-gray-900 min-h-screen">
      <BatteryActionsTable resolution={dataResolution} />
      <PredictionAccuracyView />
      <ConsumptionForecastComparison />
    </div>
  );
};

export default InsightsPage;
```

(confirm `useUserPreferences` exports `dataResolution` with this exact name — it's already used the same way in `frontend/src/pages/SavingsPage.tsx:12`.)

Delete `frontend/src/components/SavingsOverview.tsx`.

In `frontend/src/pages/SavingsPage.tsx`, remove the `Overview`/`Scenario Comparison` view-mode toggle's Overview branch and the `SavingsOverview` import (this page's full restructure — including replacing the toggle and adding the period selector — happens in Task 10; for this task, just remove the dead import and leave a TODO-free stopgap: render `DetailedSavingsAnalysis` unconditionally and drop the `viewMode` state, since Task 10 will properly rebuild this page next):

```typescript
import React, { useState, useEffect } from 'react';
import { DetailedSavingsAnalysis } from '../components/DetailedSavingsAnalysis';
import { SavingsAggregateView } from '../components/SavingsAggregateView';
import { useSettings } from '../hooks/useSettings';
import { useUserPreferences } from '../hooks/useUserPreferences';
import api from '../lib/api';
```

Remove the `viewMode` state and the "View Mode Switcher" JSX block, and replace the conditional render at the bottom with:

```typescript
      <DetailedSavingsAnalysis settings={mergedSettings} resolution={dataResolution} />
      <SavingsAggregateView />
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- BatteryActionsTable && npm test -- InsightsPage && npm run lint:fix`
Expected: PASS. (`SavingsPage` tests, if any reference the removed `viewMode`/`Overview` UI, will need the same trim — check and fix in this step, not deferred, since Task 9 already breaks that UI.)

```bash
grep -rln "SavingsOverview\|viewMode.*overview" frontend/src --include="*.test.tsx"
```

Fix any hits.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BatteryActionsTable.tsx frontend/src/components/__tests__/BatteryActionsTable.test.tsx frontend/src/pages/InsightsPage.tsx frontend/src/pages/SavingsPage.tsx
git rm frontend/src/components/SavingsOverview.tsx
git add -u frontend/src/components/__tests__
git commit -m "feat: move per-period battery action table to Insights page"
```

---

## Task 10: Rebuild `SavingsPage.tsx` around the period selector

**Files:**
- Modify: `frontend/src/pages/SavingsPage.tsx`
- Test: `frontend/src/pages/__tests__/SavingsPage.test.tsx` (create if none exists, following the RTL conventions of `SavingsAggregateView.test.tsx`)

**Interfaces:**
- Consumes: `SavingsAggregateView` (Task 8, now the Today/Week/Month/Year summary+history renderer), `DetailedSavingsAnalysis` (unchanged).

- [ ] **Step 1: Write the failing test**

Add/extend `frontend/src/pages/__tests__/SavingsPage.test.tsx`:

```typescript
it('renders the Scenario Comparison view and the savings aggregate view, with no Overview toggle', () => {
  // render SavingsPage with mocked hooks/data
  // assert: no text 'Overview' button is present
  // assert: SavingsAggregateView content (mocked) is rendered
  // assert: DetailedSavingsAnalysis content (mocked) is rendered
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- SavingsPage`
Expected: FAIL if the page still references removed state/imports from Task 9's stopgap, or the assertions don't match the current markup.

- [ ] **Step 3: Implement**

Finish the `SavingsPage.tsx` rebuild (Task 9 already removed the view-mode toggle and `SavingsOverview`import as a stopgap). Final shape:

```typescript
import React, { useState, useEffect } from 'react';
import { DetailedSavingsAnalysis } from '../components/DetailedSavingsAnalysis';
import { SavingsAggregateView } from '../components/SavingsAggregateView';
import { useSettings } from '../hooks/useSettings';
import { useUserPreferences } from '../hooks/useUserPreferences';
import api from '../lib/api';

const SavingsPage: React.FC = () => {
  const { batterySettings } = useSettings();
  const { dataResolution, setDataResolution } = useUserPreferences();
  const [systemMode, setSystemMode] = useState<string>('normal');

  useEffect(() => {
    api.get('/api/settings')
      .then(({ data }) => {
        const dm = data.demoMode || data.demo_mode || {};
        setSystemMode(dm.enabled ? 'demo' : 'normal');
      })
      .catch(() => {});
  }, []);

  const mergedSettings = {
    totalCapacity: batterySettings?.totalCapacity || 10,
    reservedCapacity: batterySettings?.reservedCapacity || 2,
    estimatedConsumption: batterySettings?.estimatedConsumption || 1.5,
    maxChargePowerKw: batterySettings?.maxChargePowerKw || 6,
    maxDischargePowerKw: batterySettings?.maxDischargePowerKw || 6,
    cycleCostPerKwh: batterySettings?.cycleCostPerKwh || 10,
    chargingPowerRate: batterySettings?.chargingPowerRate || 90,
    minSoc: batterySettings?.minSoc || 20,
    maxSoc: batterySettings?.maxSoc || 95,
    efficiencyCharge: batterySettings?.efficiencyCharge || 95,
    efficiencyDischarge: batterySettings?.efficiencyDischarge || 95,
    useActualPrice: true,
    markupRate: 0.05,
    vatMultiplier: 1.25,
    additionalCosts: 0.45,
    taxReduction: 0.1,
    area: 'SE3'
  };

  return (
    <div className="space-y-6">
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
          <div className="mb-4 sm:mb-0">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Financial Analysis & Savings Report</h1>
            <p className="text-gray-600 dark:text-gray-300">
              Compare how your battery system optimizes energy costs and increases solar utilization.
            </p>
            {systemMode === 'demo' && (
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                All savings are theoretical estimates based on optimization plans
              </p>
            )}
          </div>
        </div>

        {/* Resolution Selector (applies to Scenario Comparison, which is period-of-day granular) */}
        <div className="mt-4 flex items-center justify-end">
          <div className="flex bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
            <button
              onClick={() => setDataResolution('hourly')}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                dataResolution === 'hourly'
                  ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              60 min
            </button>
            <button
              onClick={() => setDataResolution('quarter-hourly')}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                dataResolution === 'quarter-hourly'
                  ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              15 min
            </button>
          </div>
        </div>
      </div>

      <SavingsAggregateView />

      <DetailedSavingsAnalysis settings={mergedSettings} resolution={dataResolution} />
    </div>
  );
};

export default SavingsPage;
```

(`SavingsAggregateView` moved above `DetailedSavingsAnalysis` since it's now the primary financial-outcome view including "Today"; Scenario Comparison remains available below it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- SavingsPage && npm run build`
Expected: PASS, production build succeeds (catches any lingering type errors from the removed `viewMode`/`Eye`/`Table2`/`SavingsOverview` imports).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SavingsPage.tsx frontend/src/pages/__tests__/SavingsPage.test.tsx
git commit -m "feat: rebuild Savings page around Today/Week/Month/Year summary view"
```

---

## Task 11: Full verification pass

**Files:** none (verification only)

**Interfaces:** none

- [ ] **Step 1: Backend full suite**

Run: `.venv/bin/pytest -m "not slow" -v`
Expected: all PASS.

- [ ] **Step 2: Frontend full suite + typecheck + build**

Run: `cd frontend && npm run lint:fix && npm test && npm run build`
Expected: all PASS, clean build.

- [ ] **Step 3: Quality gate**

Run: `./scripts/quality-check.sh`
Expected: PASS.

- [ ] **Step 4: Manual check against issue #249 / Frank's ask**

Use the `verify` skill (mock-HA + backend E2E stack) to confirm: dashboard headline reads "Net Grid Cost" and equals `grid_cost` regardless of the `cycle_cost_per_kwh` setting; Savings page shows Today/Week/Month/Year with Grid-Only Cost / Net Grid Cost / Savings and no wear figure; Insights page's new "Battery Actions" section shows per-period wear breakdown under Actual Cost.

- [ ] **Step 5: Commit any fixes found during verification, then stop for review**

No auto-merge, no PR creation — this plan ends with local verification. Follow `docs/agents/workflow.md` for the PR/review step once the user confirms the UI looks right.

---

## Task 12: `netSavings` — wear-free companion to the wear-inclusive savings formula

Added after the final whole-branch review (see the design spec's Addendum section) found that `Net Grid Cost` (headline, wear-free) and `Today's Savings`/`Total Savings` (wear-inclusive) no longer reconcile on the same card. This task does not touch the savings formula — it adds a second, purely additive figure and swaps which one two specific UI surfaces display.

**Files:**
- Modify: `backend/api_dataclasses.py` (`APIDashboardSummary` field list + `from_totals`; `APISavingsBucket` field list + `from_internal`)
- Modify: `frontend/src/api/scheduleApi.ts` (`DashboardSummary`, `SavingsBucket`)
- Modify: `frontend/src/components/SystemStatusCard.tsx:257-262,440-445`
- Modify: `frontend/src/components/SavingsAggregateView.tsx:101-106,113-115,128,144`
- Test: `backend/tests/test_dashboard_api.py`, `backend/tests/test_savings_aggregate_api.py`, `frontend/src/components/__tests__/SystemStatusCard.test.tsx`, `frontend/src/components/__tests__/SavingsAggregateView.test.tsx`

**Interfaces:**
- Produces: `APIDashboardSummary.netSavings: FormattedValue` = `gridOnlyCost − netGridCost`. `APISavingsBucket.netSavings: FormattedValue` = `gridOnlyCost − gridCost`. Both purely additive/derived — no new internal model field, no change to `hourly_savings`/`total_savings`/`savings_vs_grid_only`.

- [ ] **Step 1: Write the failing backend tests**

Add to `backend/tests/test_dashboard_api.py`, near `test_from_totals_wires_net_grid_cost_from_costs_dict`:

```python
def test_from_totals_computes_net_savings_as_grid_only_minus_net_grid():
    from api_dataclasses import APIDashboardSummary

    totals = {
        "totalSolarProduction": 0.0,
        "totalHomeConsumption": 0.0,
        "totalBatteryCharged": 0.0,
        "totalBatteryDischarged": 0.0,
        "totalGridImport": 0.0,
        "totalGridExport": 0.0,
        "totalSolarToHome": 0.0,
        "totalSolarToBattery": 0.0,
        "totalSolarToGrid": 0.0,
        "totalGridToHome": 0.0,
        "totalGridToBattery": 0.0,
        "totalBatteryToHome": 0.0,
        "totalBatteryToGrid": 0.0,
    }
    costs = {"gridOnly": 10.0, "solarOnly": 8.0, "optimized": 5.0, "netGrid": 3.0}

    summary = APIDashboardSummary.from_totals(
        totals, costs, battery_capacity=10.0, currency="EUR"
    )

    assert summary.netSavings.value == 7.0  # gridOnly(10) - netGrid(3)
    # Unchanged: still wear-inclusive, still independent of the new field
    assert summary.totalSavings.value == 5.0  # gridOnly(10) - optimized(5)
```

(Check the real `totals` dict keys against `from_totals`'s current signature before running — copy the exact keys used by the neighboring `test_from_totals_wires_net_grid_cost_from_costs_dict` test rather than retyping them, they must match.)

Add to `backend/tests/test_savings_aggregate_api.py`, inside `TestSavingsAggregate`:

```python
    def test_net_savings_present_on_bucket(self, tmp_path):
        sys.modules["app"].bess_controller = _make_started_controller(
            _seeded_store(tmp_path)
        )

        resp = _client.get("/api/savings/aggregate?period=week&count=1")

        assert resp.status_code == 200
        bucket = resp.json()["buckets"][0]
        # _seeded_store's _period(1.0, 2.0): grid_only_cost = 1.0*2.0 = 2.0,
        # grid_cost = import_eur(2.0) - export_eur(2.0) = 0.0
        assert bucket["netSavings"]["value"] == 2.0  # gridOnly(2.0) - gridCost(0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest backend/tests/test_dashboard_api.py backend/tests/test_savings_aggregate_api.py -v`
Expected: FAIL — `AttributeError`/`KeyError` on `netSavings`.

- [ ] **Step 3: Implement**

In `backend/api_dataclasses.py`, add `netSavings` to `APIDashboardSummary`'s field list, next to `netGridCost`:

```python
    optimizedCost: FormattedValue
    netGridCost: FormattedValue
    netSavings: FormattedValue
```

In `from_totals`, compute and add it alongside `netGridCost`:

```python
            netGridCost=create_formatted_value(
                costs["netGrid"], "currency", currency
            ),
            netSavings=create_formatted_value(
                total_grid_only_cost - costs["netGrid"], "currency", currency
            ),
```

Add `netSavings` to `APISavingsBucket`'s field list. Current order (verify against the live file — it may have shifted since this plan was written) is `gridCost, gridOnlyCost, batteryCycleCost, savingsVsGridOnly`; insert `netSavings` after `gridOnlyCost`:

```python
    gridCost: FormattedValue
    gridOnlyCost: FormattedValue
    netSavings: FormattedValue
    batteryCycleCost: FormattedValue
    savingsVsGridOnly: FormattedValue
```

In `from_internal`, compute and add it in the same position, between the existing `gridOnlyCost=...` and `batteryCycleCost=...` lines:

```python
            gridOnlyCost=create_formatted_value(t.grid_only_cost, "currency", currency),
            netSavings=create_formatted_value(
                t.grid_only_cost - t.grid_cost, "currency", currency
            ),
            batteryCycleCost=create_formatted_value(
                t.battery_cycle_cost, "currency", currency
            ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest backend/tests/test_dashboard_api.py backend/tests/test_savings_aggregate_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit backend changes**

```bash
git add backend/api_dataclasses.py backend/tests/test_dashboard_api.py backend/tests/test_savings_aggregate_api.py
git commit -m "feat: add wear-free netSavings alongside existing savings formula"
```

- [ ] **Step 6: Write the failing frontend tests**

In `frontend/src/components/__tests__/SystemStatusCard.test.tsx`, extend the existing headline test (or add a new one) asserting the "Today's Cost & Savings" card's savings sub-metric reads `summary.netSavings.text` and the label is "Net Savings" — not the old `summary.totalSavings.text`/"Today's Savings" label. Mirror the existing test's mock-data shape, giving `netSavings` and `totalSavings` distinct values so a wrong-field regression would be caught.

In `frontend/src/components/__tests__/SavingsAggregateView.test.tsx`, extend the existing bucket-fixture-based tests (or add one) asserting the table's savings column reads `bucket.netSavings.text` and the chart's savings bar is keyed off `netSavings.value`, not `savingsVsGridOnly.value` — again with distinct fixture values for the two fields.

- [ ] **Step 7: Run tests to verify they fail**

Run: `cd frontend && npm test -- SystemStatusCard SavingsAggregateView`
Expected: FAIL — old field/label still in use.

- [ ] **Step 8: Implement**

In `frontend/src/api/scheduleApi.ts`, add `netSavings: FormattedValue` to `DashboardSummary` (next to `netGridCost`) and to `SavingsBucket` (next to `gridOnlyCost`).

In `frontend/src/components/SystemStatusCard.tsx`, change the `todaysSavings` derivation (`257-262`) to read `netSavings`:

```typescript
        todaysSavings: (() => {
          if (!dashboardData.summary?.netSavings) {
            throw new Error('MISSING DATA: summary.netSavings is required for savings display');
          }
          return dashboardData.summary.netSavings;
        })(),
```

Change the card's sub-metric label (`440-445` area) from `"Today's Savings"` to `"Net Savings"`:

```typescript
        {
          label: "Net Savings",
          value: statusData.costAndSavings?.todaysSavings?.text,
          unit: "",
          icon: DollarSign,
          color: (statusData.costAndSavings?.todaysSavings?.value || 0) >= 0 ? 'green' as const : 'red' as const
        },
```

(internal prop name `todaysSavings` stays as-is, same minimal-diff convention Task 7 used for `todaysCost`/`netGridCost`.)

In `frontend/src/components/SavingsAggregateView.tsx`, update the chart data mapping (`101-106`):

```typescript
              data={data!.map((b) => ({
                label: b.label,
                gridOnlyCost: b.gridOnlyCost.value,
                gridCost: b.gridCost.value,
                savings: b.netSavings.value,
              }))}
```

Update the `Savings` bar's name (`115`) to `"Net Savings"`:

```typescript
              <Bar dataKey="savings" name="Net Savings" fill={colors.savings} fillOpacity={0.8} isAnimationActive={false} />
```

Update the table header (`128`) from `"Savings"` to `"Net Savings"`, and the table cell (`144`) to read `b.netSavings.text`:

```typescript
                  <td className="pr-4 py-1 text-gray-600 dark:text-gray-300">{b.netSavings.text}</td>
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd frontend && npm test -- SystemStatusCard SavingsAggregateView && npm run lint:fix && npm run build`
Expected: all PASS, clean build.

- [ ] **Step 10: Commit frontend changes**

```bash
git add frontend/src/api/scheduleApi.ts frontend/src/components/SystemStatusCard.tsx frontend/src/components/SavingsAggregateView.tsx frontend/src/components/__tests__/SystemStatusCard.test.tsx frontend/src/components/__tests__/SavingsAggregateView.test.tsx
git commit -m "feat: dashboard card and Savings page show wear-free Net Savings"
```

- [ ] **Step 11: Full verification**

Run: `.venv/bin/pytest -m "not slow" -q && cd frontend && npm test -- --run && npm run build` and `./scripts/quality-check.sh`.
Expected: all green.
