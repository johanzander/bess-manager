# Savings Day-Resolution Hourly Drill-Down Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the Savings page's Tibber-style drill-down pattern — Year already shows its months, Month already shows its days — by making Day resolution's History section show the hour-by-hour (or quarter-hourly) breakdown of the selected day, instead of its current rolling-14-day trend.

**Architecture:** No new backend endpoint needed. `/api/dashboard` (already used elsewhere via `useDashboardData`) already returns per-period `importCost`, `exportRevenue`, `gridCost`, `gridOnlyCost`, `solarOnlyCost`, `solarSavings` for either a live "today" or a historical `date`. It is missing two fields the History table needs: `netSavings` and `batterySavings`. **These are computed backend-side** (Task 1), exactly like `APISavingsBucket.from_internal` already does for daily buckets (`backend/api_dataclasses.py:110-111`) — the wear-free savings formula lives in exactly one place, Python, not duplicated into TypeScript. The frontend (Task 4) then only maps/renames fields into the shape the existing History chart/table already render; it does no economic computation of its own.

**Tech Stack:** Python (FastAPI dataclasses), React + TypeScript, Vitest + Testing Library, pytest.

## Global Constraints

- No new backend endpoint or route — only two new fields on the existing `APIDashboardHourlyData` dataclass (`/api/dashboard`'s hourly items).
- The wear-free savings formula is computed once, backend-side: `netSavings = gridOnlyCost - gridCost`, `batterySavings = solarOnlyCost - gridCost` — identical to `backend/api_dataclasses.py:110-111`'s `solar_savings`/`battery_savings` on `APISavingsBucket`. The frontend must not re-derive these from raw values; it only reads the fields the API already provides.
- Both new frontend hooks (`useDashboardData`, `useSavingsAggregate`) must stay 100% backward compatible for every existing call site — the new `enabled` param is appended last, defaults to `true`, and changes no existing behavior when omitted.
- Backend: run `.venv/bin/pytest -m "not slow"` after Task 1; must be green, no regressions.
- Frontend: run `cd frontend && npx vitest run && npx tsc --noEmit -p . && npm run lint:fix` after every frontend task; all must be clean before moving on.

---

### Task 1: Backend — expose `netSavings` and `batterySavings` per hour on `/api/dashboard`

**Files:**
- Modify: `backend/api_dataclasses.py`
- Test: `backend/tests/test_dashboard_api.py`

**Interfaces:**
- Consumes: `hourly.economic.grid_only_cost`, `hourly.economic.solar_only_cost`, `hourly.economic.grid_cost` (all already exist on `core.bess.models.EconomicData`, already read elsewhere in `APIDashboardHourlyData.from_internal`).
- Produces: `APIDashboardHourlyData` gains two new required fields, `netSavings: FormattedValue` and `batterySavings: FormattedValue`, populated by `from_internal` on every call (live and historical, hourly and quarter-hourly — the same method already handles both).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_dashboard_api.py`, in the "APIDashboardHourlyData unit tests" section (after `test_hourly_data_exposes_grid_cost_and_battery_cycle_cost`, following the exact same fixture style):

```python
def test_hourly_data_exposes_wear_free_net_and_battery_savings():
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
            grid_only_cost=10.0,
            solar_only_cost=6.0,
            battery_cycle_cost=0.1,
            hourly_cost=2.1,
        ),
        decision=DecisionData(strategic_intent="IDLE"),
    )

    api_hourly = APIDashboardHourlyData.from_internal(
        hourly, battery_capacity=10.0, currency="EUR"
    )

    # netSavings = gridOnlyCost - gridCost = 10.0 - 2.0
    assert api_hourly.netSavings.value == 8.0
    # batterySavings = solarOnlyCost - gridCost = 6.0 - 2.0 = 4.0 (wear-free:
    # subtracts grid_cost, NOT hourly_cost, which folds in
    # battery_cycle_cost=0.1 — if wear were included this would instead be
    # solar_only_cost - hourly_cost = 6.0 - 2.1 = 3.9).
    assert api_hourly.batterySavings.value == 4.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest backend/tests/test_dashboard_api.py -k wear_free_net_and_battery_savings -v`
Expected: FAIL — `APIDashboardHourlyData` has no `netSavings`/`batterySavings` attributes yet (`AttributeError`).

- [ ] **Step 3: Implement**

In `backend/api_dataclasses.py`, in the `APIDashboardHourlyData` dataclass field list, find:

```python
    solarSavings: FormattedValue  # Savings from solar vs grid-only
```

Replace it with:

```python
    solarSavings: FormattedValue  # Savings from solar vs grid-only
    # Wear-free savings, matching APISavingsBucket.from_internal's formula
    # (this file, above): battery's own contribution on top of solar, and
    # total savings vs a grid-only baseline. Neither includes battery
    # wear — that's the pre-existing `hourlySavings` field's job.
    batterySavings: FormattedValue
    netSavings: FormattedValue
```

Then, in `from_internal`, find:

```python
            solarSavings=safe_format(
                hourly.economic.solar_savings,
                "currency",
            ),
            # Raw values for logic
```

Replace it with:

```python
            solarSavings=safe_format(
                hourly.economic.solar_savings,
                "currency",
            ),
            batterySavings=safe_format(
                hourly.economic.solar_only_cost - hourly.economic.grid_cost,
                "currency",
            ),
            netSavings=safe_format(
                hourly.economic.grid_only_cost - hourly.economic.grid_cost,
                "currency",
            ),
            # Raw values for logic
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest backend/tests/test_dashboard_api.py -k wear_free_net_and_battery_savings -v`
Expected: PASS.

- [ ] **Step 5: Run the full fast backend suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS, no regressions. (`backend/tests/test_api_conversion.py`'s `test_api_conversion_required_fields` lists specific required fields and does not iterate all dataclass fields, so adding two new required ones does not break it — confirm this remains true; if it does break, add `"batterySavings"` and `"netSavings"` to that test's `required_fields` list too.)

- [ ] **Step 6: Commit**

```bash
git add backend/api_dataclasses.py backend/tests/test_dashboard_api.py
git commit -m "feat: expose wear-free netSavings and batterySavings per hour on /api/dashboard"
```

---

### Task 2: Frontend — `useDashboardData` gains an `enabled` flag to skip fetching

**Files:**
- Modify: `frontend/src/hooks/useDashboardData.ts`
- Test: `frontend/src/hooks/__tests__/useDashboardData.test.ts`

**Interfaces:**
- Consumes: nothing new.
- Produces: `useDashboardData(date?, resolution?, refreshInterval?, enabled: boolean = true)` — when `enabled` is `false`, the hook does not call `fetchDashboardData` at all and `loading` is `false` (not stuck `true`). Existing call sites (`EnergyFlowCards.tsx`, `BatteryActionsTable.tsx`, `DetailedSavingsAnalysis.tsx`, `SystemStatusCard.tsx`, `TableBatteryDecisionExplorer.tsx`) all omit the 4th arg and are unaffected.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/hooks/__tests__/useDashboardData.test.ts`, inside the `describe('useDashboardData', ...)` block (after the existing `'passes date and resolution params'` test):

```ts
  it('does not fetch when enabled is false', async () => {
    const { result } = renderHook(() => useDashboardData(undefined, 'quarter-hourly', 0, false))

    expect(result.current.loading).toBe(false)
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('fetches once enabled flips from false to true', async () => {
    mockFetch.mockResolvedValueOnce(fakeDashboard)

    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useDashboardData(undefined, 'quarter-hourly', 0, enabled),
      { initialProps: { enabled: false } }
    )

    expect(mockFetch).not.toHaveBeenCalled()

    rerender({ enabled: true })

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })
    expect(mockFetch).toHaveBeenCalledWith(undefined, 'quarter-hourly')
  })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useDashboardData.test.ts`
Expected: FAIL — `enabled` isn't a recognized 4th param yet, so the hook always fetches regardless.

- [ ] **Step 3: Implement**

Replace the full contents of `frontend/src/hooks/useDashboardData.ts`:

```ts
import { useState, useEffect, useCallback } from 'react';
import { fetchDashboardData, DashboardResponse } from '../api/scheduleApi';
import { DataResolution } from './useUserPreferences';

interface UseDashboardDataResult {
  data: DashboardResponse | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * Shared hook for dashboard data fetching.
 * Centralizes all /api/dashboard calls to prevent duplicate requests.
 *
 * @param date - Optional date filter
 * @param resolution - Data resolution: 'hourly' (24 periods) or 'quarter-hourly' (96 periods). Defaults to 'quarter-hourly'.
 * @param refreshInterval - Auto-refresh interval in ms. 0 = no auto-refresh (default).
 * @param enabled - When false, skips fetching entirely (loading stays false). Defaults to true.
 */
export const useDashboardData = (
  date?: string,
  resolution: DataResolution = 'quarter-hourly',
  refreshInterval: number = 0,
  enabled: boolean = true
): UseDashboardDataResult => {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(enabled);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await fetchDashboardData(date, resolution);
      setData(result);
    } catch (err) {
      console.error('Failed to fetch dashboard data:', err);
      const errorMessage = err instanceof Error ? err.message : 'Failed to load dashboard data';
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [date, resolution]);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    fetchData();
    if (refreshInterval > 0) {
      const interval = setInterval(fetchData, refreshInterval);
      return () => clearInterval(interval);
    }
  }, [fetchData, refreshInterval, enabled]);

  const refetch = useCallback(() => {
    fetchData();
  }, [fetchData]);

  return {
    data,
    loading,
    error,
    refetch
  };
};

export default useDashboardData;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useDashboardData.test.ts`
Expected: PASS, all tests (existing + 2 new).

- [ ] **Step 5: Run the full frontend suite**

Run: `cd frontend && npx vitest run && npx tsc --noEmit -p .`
Expected: PASS, no regressions in the 5 existing consumers.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useDashboardData.ts frontend/src/hooks/__tests__/useDashboardData.test.ts
git commit -m "feat: add enabled flag to useDashboardData to skip fetching"
```

---

### Task 3: Frontend — `useSavingsAggregate` gains an `enabled` flag to skip fetching

**Files:**
- Modify: `frontend/src/hooks/useSavingsAggregate.ts`
- Test: `frontend/src/hooks/__tests__/useSavingsAggregate.test.ts`

**Interfaces:**
- Consumes: nothing new.
- Produces: `useSavingsAggregate(period, count?, date?, enabled: boolean = true)` — same skip-fetch contract as Task 2's `useDashboardData`. Every existing call site (`SavingsAggregateView.tsx`'s hero and history calls) omits the 4th arg today and is unaffected until Task 4 passes it explicitly.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/hooks/__tests__/useSavingsAggregate.test.ts`, inside the `describe('useSavingsAggregate', ...)` block (after the `'passes the date param through to fetchSavingsAggregate'` test):

```ts
  it('does not fetch when enabled is false', async () => {
    const fetchSpy = vi.spyOn(scheduleApi, 'fetchSavingsAggregate');

    const { result } = renderHook(() => useSavingsAggregate('day', 1, undefined, false));

    expect(result.current.loading).toBe(false);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useSavingsAggregate.test.ts`
Expected: FAIL — `enabled` isn't a recognized 4th param yet, so the hook always fetches.

- [ ] **Step 3: Implement**

Replace the full contents of `frontend/src/hooks/useSavingsAggregate.ts`:

```ts
import { useState, useEffect, useCallback } from 'react';
import { fetchSavingsAggregate, SavingsBucket, SavingsAggregatePeriod } from '../api/scheduleApi';

interface UseSavingsAggregateResult {
  data: SavingsBucket[] | null;
  loading: boolean;
  error: string | null;
}

export const useSavingsAggregate = (
  period: SavingsAggregatePeriod,
  count?: number,
  date?: string,
  enabled: boolean = true
): UseSavingsAggregateResult => {
  const [data, setData] = useState<SavingsBucket[] | null>(null);
  const [loading, setLoading] = useState<boolean>(enabled);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await fetchSavingsAggregate(period, count, date);
      setData(result.buckets);
    } catch (err) {
      console.error('Failed to fetch savings aggregate:', err);
      const errorMessage = err instanceof Error ? err.message : 'Failed to load savings history';
      setError(errorMessage);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [period, count, date]);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    fetchData();
  }, [fetchData, enabled]);

  return { data, loading, error };
};

export default useSavingsAggregate;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useSavingsAggregate.test.ts`
Expected: PASS, all tests (existing + 1 new).

- [ ] **Step 5: Run the full frontend suite**

Run: `cd frontend && npx vitest run && npx tsc --noEmit -p .`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useSavingsAggregate.ts frontend/src/hooks/__tests__/useSavingsAggregate.test.ts
git commit -m "feat: add enabled flag to useSavingsAggregate to skip fetching"
```

---

### Task 4: Frontend — `SavingsAggregateView` hourly History drill-down for Day resolution

**Files:**
- Modify: `frontend/src/api/scheduleApi.ts`
- Modify: `frontend/src/components/SavingsAggregateView.tsx`
- Test: `frontend/src/components/__tests__/SavingsAggregateView.test.tsx`

**Interfaces:**
- Consumes: `useDashboardData(date?, resolution?, refreshInterval?, enabled?)` from Task 2; `useSavingsAggregate(period, count?, date?, enabled?)` from Task 3; `useUserPreferences()` (existing, `frontend/src/hooks/useUserPreferences.ts` — returns `{ dataResolution: 'hourly' | 'quarter-hourly', ... }`); `DashboardHourlyData.netSavings`/`.batterySavings` from Task 1 (now backend-populated, no longer optional/derived).
- Produces: no new exports — this is the final consumer in this plan.

- [ ] **Step 1: Update the `DashboardHourlyData` TypeScript interface to match Task 1's backend fields**

In `frontend/src/api/scheduleApi.ts`, find:

```typescript
  // Additional economic fields - FormattedValue
  gridOnlyCost: FormattedValue;
  solarOnlyCost: FormattedValue;
  solarSavings: FormattedValue;
  batterySavings?: FormattedValue;
```

Replace it with:

```typescript
  // Additional economic fields - FormattedValue
  gridOnlyCost: FormattedValue;
  solarOnlyCost: FormattedValue;
  solarSavings: FormattedValue;
  // Wear-free savings, computed backend-side (see backend/api_dataclasses.py
  // APIDashboardHourlyData.from_internal) — do not re-derive these from
  // other fields on the frontend.
  batterySavings: FormattedValue;
  netSavings: FormattedValue;
```

- [ ] **Step 2: Write the failing tests**

Add to `frontend/src/components/__tests__/SavingsAggregateView.test.tsx`, as a new `describe` block appended at the end of the file:

```ts
describe('SavingsAggregateView Day-resolution hourly drill-down', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  const hourlyItem = (
    period: number,
    overrides: Partial<{
      importCost: number;
      exportRevenue: number;
      gridCost: number;
      gridOnlyCost: number;
      solarSavings: number;
      batterySavings: number;
      netSavings: number;
    }> = {}
  ) => {
    const v = (value: number) => ({ value, display: value.toFixed(2), unit: 'EUR', text: `${value.toFixed(2)} EUR` });
    return {
      hour: Math.floor(period / 4),
      period,
      dataSource: 'actual' as const,
      solarProduction: v(0),
      homeConsumption: v(0),
      gridImported: v(0),
      gridExported: v(0),
      batteryCharged: v(0),
      batteryDischarged: v(0),
      batterySocStart: v(0),
      batterySocEnd: v(0),
      batterySoeEnd: v(0),
      buyPrice: v(0),
      sellPrice: v(0),
      importCost: v(overrides.importCost ?? 0),
      exportRevenue: v(overrides.exportRevenue ?? 0),
      hourlyCost: v(0),
      hourlySavings: v(0),
      batteryCycleCost: v(0),
      gridOnlyCost: v(overrides.gridOnlyCost ?? 10),
      solarOnlyCost: v(6),
      solarSavings: v(overrides.solarSavings ?? 4),
      batterySavings: v(overrides.batterySavings ?? 4),
      netSavings: v(overrides.netSavings ?? 8),
      gridCost: v(overrides.gridCost ?? 2),
      gridImportNeeded: v(0),
      solarExcess: v(0),
      batteryAction: null,
    };
  };

  it('fetches dashboard hourly data (not a savings-aggregate day history) when period is day', async () => {
    const savingsSpy = vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-07-11', 1)],
      count: 1,
    });
    const dashboardSpy = vi.spyOn(scheduleApi, 'fetchDashboardData').mockResolvedValue({
      hourlyData: [hourlyItem(0), hourlyItem(4)],
    });

    render(<SavingsAggregateView period="day" date="2026-07-11" />);

    await waitFor(() => expect(dashboardSpy).toHaveBeenCalledWith('2026-07-11', 'quarter-hourly'));
    // The hero still requests exactly one day-level bucket for its own
    // totals; History no longer requests a rolling window of days.
    expect(savingsSpy).toHaveBeenCalledWith('day', 1, '2026-07-11');
    expect(savingsSpy).not.toHaveBeenCalledWith('day', 14, expect.anything());
  });

  it('labels the History section "Hours in <day>" and shows HH:MM rows', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [{ ...bucket('2026-07-11', 1), startDate: '2026-07-11', endDate: '2026-07-11' }],
      count: 1,
    });
    vi.spyOn(scheduleApi, 'fetchDashboardData').mockResolvedValue({
      hourlyData: [hourlyItem(0), hourlyItem(4)], // 00:00 and 01:00
    });

    render(<SavingsAggregateView period="day" date="2026-07-11" />);

    await waitFor(() => {
      expect(screen.getByText(/^Hours in /)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /table/i }));

    await waitFor(() => {
      expect(screen.getByText('00:00')).toBeInTheDocument();
    });
    expect(screen.getByText('01:00')).toBeInTheDocument();
  });

  it('renders the API-provided Net Savings and Battery Contribution for hourly rows, not a re-derived value', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [{ ...bucket('2026-07-11', 1), startDate: '2026-07-11', endDate: '2026-07-11' }],
      count: 1,
    });
    vi.spyOn(scheduleApi, 'fetchDashboardData').mockResolvedValue({
      // netSavings/batterySavings are deliberately set to values that do
      // NOT match gridOnlyCost/solarOnlyCost/gridCost arithmetic, so this
      // test fails if the component re-derives them instead of reading
      // the API's own fields.
      hourlyData: [hourlyItem(0, { netSavings: 99, batterySavings: 77 })],
    });

    render(<SavingsAggregateView period="day" date="2026-07-11" />);

    fireEvent.click(screen.getByRole('button', { name: /table/i }));

    await waitFor(() => {
      expect(screen.getByText('00:00')).toBeInTheDocument();
    });
    expect(screen.getByText('99.00 EUR')).toBeInTheDocument();
    expect(screen.getByText('77.00 EUR')).toBeInTheDocument();
  });

  it('does not affect the History drill-down for month/year resolutions', async () => {
    const dashboardSpy = vi.spyOn(scheduleApi, 'fetchDashboardData');
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [{ ...bucket('2026-07', 1), startDate: '2026-07-01', endDate: '2026-07-31' }],
      count: 1,
    });

    render(<SavingsAggregateView period="month" date="2026-07-15" />);

    await waitFor(() => {
      expect(screen.getByText('Net Cost')).toBeInTheDocument();
    });
    expect(dashboardSpy).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/__tests__/SavingsAggregateView.test.tsx`
Expected: FAIL — `fetchDashboardData` is never called yet for `period="day"`, and the History section still shows the old rolling-day-window behavior.

- [ ] **Step 4: Implement**

In `frontend/src/components/SavingsAggregateView.tsx`:

1. Replace the existing import block at the top of the file (currently):

```typescript
import React, { useState, useEffect } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { DollarSign, TrendingUp, Sun, Battery } from 'lucide-react';
import { useSavingsAggregate } from '../hooks/useSavingsAggregate';
import { StatusCard } from './SystemStatusCard';
import { SavingsAggregatePeriod, SavingsBucket } from '../api/scheduleApi';
import { toISODate } from '../utils/timeUtils';
```

with:

```typescript
import React, { useState, useEffect } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { DollarSign, TrendingUp, Sun, Battery } from 'lucide-react';
import { useSavingsAggregate } from '../hooks/useSavingsAggregate';
import { useDashboardData } from '../hooks/useDashboardData';
import { useUserPreferences } from '../hooks/useUserPreferences';
import { StatusCard } from './SystemStatusCard';
import { SavingsAggregatePeriod, SavingsBucket, DashboardHourlyData } from '../api/scheduleApi';
import { FormattedValue } from '../types';
import { toISODate } from '../utils/timeUtils';
```

2. Insert a shared row type and the hourly-mapping helper right after the `SAVINGS_PERIOD_LABELS` constant (before `interface SavingsAggregateViewProps`):

```typescript
// Both History data sources (savings-aggregate buckets for month/year,
// dashboard hourly data for day) are shaped into this common row type so
// the chart/table below don't need to know which source they came from.
interface HistoryRow {
  label: string;
  importEur: FormattedValue;
  exportEur: FormattedValue;
  gridCost: FormattedValue;
  gridOnlyCost: FormattedValue;
  solarSavings: FormattedValue;
  batterySavings: FormattedValue;
  netSavings: FormattedValue;
  dayCount: number;
}

const formatHourLabel = (item: DashboardHourlyData, resolution: 'hourly' | 'quarter-hourly'): string => {
  if (resolution === 'quarter-hourly') {
    const hour = Math.floor(item.period / 4);
    const minute = (item.period % 4) * 15;
    return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
  }
  return `${String(item.hour).padStart(2, '0')}:00`;
};

// netSavings/batterySavings are computed backend-side (see
// backend/api_dataclasses.py APIDashboardHourlyData.from_internal) using
// the same wear-free formula as the daily aggregator — this function only
// maps/renames fields, it does not compute anything.
const hourlyToHistoryRow = (
  item: DashboardHourlyData,
  resolution: 'hourly' | 'quarter-hourly'
): HistoryRow => ({
  label: formatHourLabel(item, resolution),
  importEur: item.importCost,
  exportEur: item.exportRevenue,
  gridCost: item.gridCost,
  gridOnlyCost: item.gridOnlyCost,
  solarSavings: item.solarSavings,
  batterySavings: item.batterySavings,
  netSavings: item.netSavings,
  dayCount: 1,
});
```

3. Replace the component body's data-fetching section. The current file (as of this plan's authoring) reads exactly:

```typescript
export const SavingsAggregateView: React.FC<SavingsAggregateViewProps> = ({ period, date }) => {
  const [viewMode, setViewMode] = useState<'chart' | 'table'>('chart');

  // The hero cards show exactly one bucket: the totals for the selected
  // period itself.
  const { data: heroData, loading: heroLoading, error: heroError } = useSavingsAggregate(
    period,
    1,
    date
  );
  const currentBucket = heroData?.[0];

  const historyConfig = getHistoryConfig(period, date);
  const {
    data: historyBuckets,
    loading: historyLoading,
    error: historyError,
  } = useSavingsAggregate(historyConfig.period, historyConfig.count, historyConfig.date);

  const [isDarkMode, setIsDarkMode] = useState(document.documentElement.classList.contains('dark'));

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

  // The History chart/table is a trend, so periods with no recorded day
  // are still excluded there — a "0.00" row for a day with no snapshot
  // yet is just noise in a trend view.
  const bucketsWithData = historyBuckets ? historyBuckets.filter(b => b.dayCount > 0) : [];
  const hasData = bucketsWithData.length > 0;
  const currencyUnit = bucketsWithData[0]?.gridOnlyCost.unit ?? currentBucket?.gridOnlyCost.unit ?? '';

  const historyTitle = currentBucket
    ? period === 'year'
      ? `Months in ${formatPeriodLabel(period, currentBucket)}`
      : period === 'month'
        ? `Days in ${formatPeriodLabel(period, currentBucket)}`
        : 'History'
    : 'History';
```

Replace it with:

```typescript
export const SavingsAggregateView: React.FC<SavingsAggregateViewProps> = ({ period, date }) => {
  const [viewMode, setViewMode] = useState<'chart' | 'table'>('chart');
  const { dataResolution } = useUserPreferences();
  const isHourlyDrillDown = period === 'day';

  // The hero cards show exactly one bucket: the totals for the selected
  // period itself.
  const { data: heroData, loading: heroLoading, error: heroError } = useSavingsAggregate(
    period,
    1,
    date
  );
  const currentBucket = heroData?.[0];

  // Month/Year drill-down: finer savings-aggregate buckets. Skipped
  // entirely for Day resolution, which uses the dashboard's hourly data
  // instead (below).
  const historyConfig = getHistoryConfig(period, date);
  const {
    data: historySavingsBuckets,
    loading: historySavingsLoading,
    error: historySavingsError,
  } = useSavingsAggregate(
    historyConfig.period,
    historyConfig.count,
    historyConfig.date,
    !isHourlyDrillDown
  );

  // Day drill-down: hour-by-hour (or quarter-hourly) breakdown of the
  // selected day, from the same endpoint the Dashboard page already uses.
  // Omitting `date` fetches today's live (in-progress) data, matching the
  // `date` prop's convention everywhere else on this page.
  const {
    data: dashboardData,
    loading: dashboardLoading,
    error: dashboardError,
  } = useDashboardData(date, dataResolution, 0, isHourlyDrillDown);

  const [isDarkMode, setIsDarkMode] = useState(document.documentElement.classList.contains('dark'));

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

  const historyLoading = isHourlyDrillDown ? dashboardLoading : historySavingsLoading;
  const historyError = isHourlyDrillDown ? dashboardError : historySavingsError;

  const historyRows: HistoryRow[] = isHourlyDrillDown
    ? (dashboardData?.hourlyData ?? []).map(item => hourlyToHistoryRow(item, dataResolution))
    : (historySavingsBuckets ?? []);

  // The History chart/table is a trend, so periods with no recorded day
  // are still excluded there — a "0.00" row for a day with no snapshot
  // yet is just noise in a trend view. Hourly rows always have
  // dayCount=1, so every returned hour is shown (including predicted
  // future hours of an in-progress "today", same as the rest of the app).
  const bucketsWithData = historyRows.filter(b => b.dayCount > 0);
  const hasData = bucketsWithData.length > 0;
  const currencyUnit = bucketsWithData[0]?.gridOnlyCost.unit ?? currentBucket?.gridOnlyCost.unit ?? '';

  const historyTitle = (() => {
    if (!currentBucket) return 'History';
    if (isHourlyDrillDown) return `Hours in ${formatPeriodLabel(period, currentBucket)}`;
    if (period === 'year') return `Months in ${formatPeriodLabel(period, currentBucket)}`;
    if (period === 'month') return `Days in ${formatPeriodLabel(period, currentBucket)}`;
    return 'History';
  })();
```

Note `historyLoading`/`historyError`/`bucketsWithData`/`historyTitle` keep the exact same names as before — every downstream reference in the JSX (the `{historyTitle}` heading, the `{historyLoading && ...}` / `{!historyLoading && historyError && ...}` / `{!historyLoading && !historyError && !hasData && ...}` / chart and table `{!historyLoading && !historyError && hasData && viewMode === ...}` conditionals, `bucketsWithData.map(...)` in the chart, and `[...bucketsWithData].reverse().map(...)` in the table) needs **no further edits** — it already compiles against the new values.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/__tests__/SavingsAggregateView.test.tsx`
Expected: PASS, all tests (21 existing + 4 new = 25).

- [ ] **Step 6: Run the full frontend suite, type-check, and lint**

Run: `cd frontend && npx vitest run && npx tsc --noEmit -p . && npm run lint:fix`
Expected: All tests pass; `tsc` clean; lint shows no new errors (pre-existing warnings elsewhere are fine).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/scheduleApi.ts frontend/src/components/SavingsAggregateView.tsx frontend/src/components/__tests__/SavingsAggregateView.test.tsx
git commit -m "feat: Day resolution's History section drills into hours, not a rolling day window"
```

---

### Task 5: Manual verification in the browser

**Files:** none (verification only).

- [ ] **Step 1: Start the dev stack**

`cd frontend && npm run dev`, alongside whichever backend dev process this checkout is already using.

- [ ] **Step 2: Walk the golden path**

On the Savings page:
1. Select **Day** — confirm the History section now says "Hours in Today" (or the picked day) and shows a bar chart / table of that day's hours (labelled "00:00", "00:15", ... if quarter-hourly, or "00:00".."23:00" if the hourly preference is set), not a multi-day trend.
2. Step the date picker back to a fully-elapsed historical day — confirm all 24/96 periods show, labelled correctly, with sensible cost/savings values.
3. Confirm **Month** and **Year** still behave as before (unaffected by this change).
4. Switch the `dataResolution` user preference (if there's a settings toggle) between hourly and quarter-hourly and confirm the Day History labels adjust accordingly.

- [ ] **Step 3: Report findings**

If everything matches, this task is done — no code change. If something looks wrong, note the specific mismatch so it becomes a follow-up fix before merging.
